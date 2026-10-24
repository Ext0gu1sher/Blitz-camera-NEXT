"""Explicit one-request seek trial. --inspect reads only; --execute invokes
the verified native relative-seek method once on the replay update thread.
Never writes replay raw time, camera pose, or game files. No automatic retry.
"""
import argparse
import ctypes as C
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from blitzcam.reader import CameraSession
from blitzcam.project import atomic_json
from blitzcam.hook_layout import plain
from blitzcam.hook_transport import Remote,pe_exports
from blitzcam.seek_trial import Config,Header,prepare,clock,settled

# 2026-10-19: the 100.7 -> 35 s trial landed, then crashed during teardown.
# Clock stability alone is insufficient. Keep offline inspection available;
# runtime re-enablement requires a lifecycle fix and a new validation plan.
LIVE_SEEK_ENABLED=False

# 2026-10-19: the 100.7 -> 35 s trial landed, then crashed during teardown.
# Clock stability alone is insufficient. Keep offline inspection available;
# runtime re-enablement requires a lifecycle fix and a new validation plan.
LIVE_SEEK_ENABLED=False

def run(args):
    if args.execute and not LIVE_SEEK_ENABLED:
        raise RuntimeError('回放跳转实验因 2026-10-19 落点后闪退已停用；须先修复并验证生命周期。此命令未访问游戏。')
    if args.execute and not LIVE_SEEK_ENABLED:
        raise RuntimeError('回放跳转实验因 2026-10-19 落点后闪退已停用；须先修复并验证生命周期。此命令未访问游戏。')
    folder=ROOT/'output/replay-seek-runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    report={'runtime_test':args.execute,'camera_writes':False,'raw_clock_writes':False,'hooks_detached':True}
    s=None;disconnected=False
    def api(path,payload=None):
        req=urllib.request.Request(args.url+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
    def journal(row):
        with (folder/'operations.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
    try:
        ui=api('/api/state')
        if ui.get('playback',{}).get('active'):raise RuntimeError('请先停止正在执行的轨迹。')
        s=CameraSession.connect();sample=s.capture()
        target=args.target if args.target is not None else sample['replay']['time']+args.delta
        cfg,link=prepare(s,sample,target)
        report.update(reference=sample,requested_time=target,config=plain(cfg),callback=link)
        atomic_json(folder/'reference.json',report)
        print(json.dumps({'run_path':str(folder),'before':sample['replay']['time'],'target':target,'delta':cfg.delta,'execute':args.execute}),flush=True)
        if not args.execute:return
        native=ROOT/'blitzcam/native'
        manifest=json.loads((native/'replay_seek_trial_1121.json').read_text(encoding='utf8'))
        expected=dict(config_size=C.sizeof(Config),header_size=C.sizeof(Header),header_offset=C.sizeof(Config),shared_size=C.sizeof(Config)+C.sizeof(Header))
        if any(manifest.get(k)!=v for k,v in expected.items()):raise RuntimeError('实验布局不符。')
        dll=native/manifest['dll']
        if dll.parent.resolve()!=native.resolve() or not dll.name.startswith('replay_seek_trial_1121.') or dll.suffix!='.dll' or hashlib.sha256(dll.read_bytes()).hexdigest()!=manifest['sha256']:
            raise RuntimeError('实验 DLL 校验不符。')
        api('/api/disconnect',{});disconnected=True
        with Remote(s,journal) as driver:
            exports=pe_exports(dll);base=driver.load(dll);shared=base+exports['g_shared'];hoff=C.sizeof(Config)
            driver.write_bounds=(shared,shared+manifest['shared_size'])
            read_h=lambda:Header.from_buffer_copy(s.memory.read(shared+hoff,C.sizeof(Header)))
            h=read_h()
            if h.active or h.status not in (0,4,-1):raise RuntimeError('前一轮请求尚未退出。')
            if s.memory.u32(cfg.functor+0x10)!=cfg.tick_entry:raise RuntimeError('回放更新已被接管。')
            driver.write(shared,bytes(cfg),'owned bounded seek config')
            driver.write(shared+hoff,bytes(Header()),'owned inactive seek header')
            beat=lambda:driver.write(shared+hoff+Header.heartbeat.offset,struct.pack('<I',driver.k.GetTickCount()&0xffffffff),'owned seek watchdog')
            driver.detach_address=base+exports['HookDetach@4']
            driver.detach_probe=lambda:not read_h().active and read_h().detached==1
            beat();report.update(module_base=hex(base),dll_sha256=manifest['sha256'],hooks_detached=False)
            start=time.monotonic()
            code=driver.call(base+exports['HookAttach@4'],0,'install one-shot native replay seek request')
            report['attach_result']=code
            if code:
                report['hooks_detached']=s.memory.u32(cfg.functor+0x10)==cfg.tick_entry
                driver.detach_address=None
                raise RuntimeError(f'跳转请求安装被拒绝（{code}）。')
            stable_at=None;last=None;request_return=None
            with (folder/'lifecycle.jsonl').open('w',encoding='utf8') as log:
                while time.monotonic()-start<35:
                    h=read_h()
                    # After a claim, supervision is observation only. The request
                    # has detached itself before any native reconstruction.
                    if h.status==1:beat()
                    x=clock(s.memory,cfg.player,cfg.player_vft)
                    row={'elapsed':time.monotonic()-start,'header':plain(h),'clock':x}
                    log.write(json.dumps(row)+'\n');log.flush()
                    if h.status==-1:raise RuntimeError(f'跳转请求已停止（{h.error}）。')
                    if h.status==4 and not h.active:
                        if request_return is None:request_return=row['elapsed']
                        if settled(x,cfg.rate) and last==x:
                            if stable_at is None:stable_at=time.monotonic()
                            elif time.monotonic()-stable_at>=.6:
                                report.update(landing=x,request_return_seconds=request_return,settled_seconds=row['elapsed']);break
                        else:stable_at=None
                    last=x;time.sleep(.02)
                else:raise RuntimeError('跳转未在 35 秒内稳定；未提交第二次请求。')
            report.update(final_header=plain(read_h()),hooks_detached=driver.detach_probe())
            if not report['hooks_detached']:raise RuntimeError('未确认跳转 Hook 已退出。')
        # Discovery is deliberately fresh: never reuse pre-rewind camera roots.
        report['landing_error_seconds']=report['landing']['time']-target
        report['native_seek_completed']=True
        try:
            fresh=CameraSession.connect(s.info.pid)
            try:report['final_sample']=fresh.capture()
            finally:fresh.close()
            report['changed_objects']={k:[sample['addresses'][k],v] for k,v in report['final_sample']['addresses'].items() if sample['addresses'][k]!=v}
        except Exception as exc:
            # Native rewind switches back to the tracked tank camera. A stable
            # replay clock is distinct from a usable free-camera connection.
            report['free_camera_discovery_error']=str(exc)
        print(json.dumps({k:report.get(k) for k in ('landing','landing_error_seconds','settled_seconds','hooks_detached','changed_objects','free_camera_discovery_error')},ensure_ascii=False),flush=True)
    except BaseException as exc:
        report['error']=str(exc);raise
    finally:
        if s:s.close()
        if disconnected and report.get('hooks_detached'):
            try:report['ui_reconnect']=api('/api/connect',{})
            except Exception as exc:report['ui_reconnect_error']=str(exc)
        report['finished_utc']=datetime.now(timezone.utc).isoformat()
        atomic_json(folder/'report.json',report)
        print(str(folder/'report.json'),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--target',type=float);group.add_argument('--delta',type=float)
    ap.add_argument('--execute',action='store_true');ap.add_argument('--url',default='http://127.0.0.1:56592')
    run(ap.parse_args())
