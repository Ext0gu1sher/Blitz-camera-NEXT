"""Isolated exact-build experiment; never seeks, never patches production code.

--inspect is read-only. --execute explicitly enables the native camera action.
The tracked option exists only to reproduce the post-reconstruction camera
state without invoking the crash-prone rewind path.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time
from types import SimpleNamespace
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam.hook_transport import Remote, pe_exports, relocated_code
from blitzcam.hook_layout import plain
from blitzcam.memory import ReadOnlyMemory, find_process
from blitzcam.profile import CameraError, PROFILE_1121
from blitzcam.reader import CameraSession
from blitzcam.replay_trial import signal_callback
from blitzcam.seek_trial import clock, settled
from tools.verify_replay_seek_phase import rebuilt_chains

UINTS = ('magic size base context player scene_owner scene render game_camera free_camera '
         'hud model engine head node functor job_manager tick_entry queue_entry '
         'any_entry action_entry destroy_entry initial_camera want_free execute').split()

class Config(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_uint32) for n in UINTS] + [(n, C.c_float) for n in ('raw','origin','rate')]

class Header(C.Structure):
    _pack_ = 4
    _fields_ = [(n,C.c_int32) for n in ('heartbeat status error active detached thread queued job_thread '
                                      'requests job_calls clones destroys before_mode after_mode').split()] + [('token',C.c_uint32)]

def hud_candidates(s):
    m=s.memory;rx=re.compile(re.escape(struct.pack('<I',s.live(0x3853e68))));rows=[]
    for start,n in m.regions():
        for a in range(start,start+n,1024*1024):
            try:data=m.read(a,min(1024*1024,start+n-a))
            except CameraError:continue
            for match in rx.finditer(data):
                hud=a+match.start()
                if hud%4:continue
                try:
                    context=m.u32(hud+0x120);model=m.u32(hud+0x148);player=m.u32(context+0x1b0)
                    if m.u32(context)!=s.vft['AvatarContextReplay'] or m.u32(player)!=s.vft['ReplayPlayer'] or m.u32(model)!=s.live(0x385332c):continue
                    rows.append(dict(hud=hud,model=model,context=context,player=player))
                except CameraError:continue
    return rows

def prepare(s,wanted,execute):
    if s.profile != PROFILE_1121:raise CameraError('Exact 11.21 build required.')
    rows=hud_candidates(s)
    if len(rows)!=1:raise CameraError('Replay HUD is not unique.')
    row=rows[0];chains=rebuilt_chains(s,row['player'])
    if len(chains)!=1:raise CameraError('Active camera/render chain is not unique.')
    chain=chains[0];s.objects=SimpleNamespace(player=row['player'])
    if s.memory.read(row['context']+0x190,1)[0]!=int(chain['camera_mode']=='free'):
        raise CameraError('Native context mode and active scene disagree; do not toggle.')
    link=signal_callback(s);x=clock(s.memory,row['player'],s.vft['ReplayPlayer'])
    if not settled(x,x['rate']):raise CameraError('Replay must be paused with no reconstruction pending.')
    c=Config(magic=0x31434642,size=C.sizeof(Config),base=s.info.base,**row,
             scene_owner=int(chain['scene_controller'],16),
             **{k:int(chain[k],16) for k in ('scene','render','game_camera','free_camera')},
             initial_camera=int(chain['active_camera'],16),want_free=wanted,execute=execute,
             job_manager=s.memory.u32(s.memory.u32(s.live(0x4690a30))),
             tick_entry=s.live(0x140d100),queue_entry=s.live(0x91d090),
             any_entry=s.live(0x717250),action_entry=s.live(0x1e173e0),destroy_entry=s.live(0x6a4720),
             **{k:x[k] for k in ('raw','origin','rate')},
             **{k:link[k] for k in ('engine','head','node','functor')})
    # Verify complete native callees against this image, with ASLR relocations.
    code=relocated_code(s.info.path,s.info.base)
    for va,n in ((0x717250,0xe5),(0x1e173e0,0x1b5),(0x6a4720,0x5e)):
        rva=va-0x400000
        expect=[data[rva-start:rva-start+n] for start,data in code.items() if start<=rva and rva+n<=start+len(data)]
        if len(expect)!=1 or s.memory.read(s.live(va),n)!=expect[0]:raise CameraError('Native action code differs from verified image.')
    return c,chain,x

def run(args):
    service=json.loads((ROOT/'output/workstation-service.json').read_text(encoding='utf8'))
    url=(args.url or service['url']).rstrip('/')
    def api(path,payload=None):
        req=urllib.request.Request(url+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
    ui=api('/api/state')
    if ui['playback']['active'] or not ui['playback'].get('hooks_detached',True):raise CameraError('Workstation playback must be stopped and detached.')
    s=CameraSession(ReadOnlyMemory(find_process(args.pid)))
    report=dict(passed=False,mode=args.mode,execute=args.execute,pid=s.info.pid,build_sha256=s.profile.sha256)
    folder=None
    try:
        c,chain,before=prepare(s,int(args.mode!='tracked'),int(args.execute and args.mode!='noop'))
        report.update(before=before,before_chain=chain,config=plain(c))
        if not args.execute:
            print(json.dumps(report,ensure_ascii=False,indent=2));return
        folder=ROOT/'output/free-camera-switch-research'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder.mkdir(parents=True)
        def journal(row):
            with (folder/'operations.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
        native=ROOT/'output/free-camera-switch-research';manifest=json.loads((native/'native.json').read_text())
        expected=dict(config_size=C.sizeof(Config),header_size=C.sizeof(Header),shared_size=C.sizeof(Config)+C.sizeof(Header))
        if any(manifest[k]!=v for k,v in expected.items()):raise CameraError('Native/Python ABI mismatch.')
        dll=native/manifest['dll']
        if dll.parent.resolve()!=native.resolve() or not dll.name.startswith('freecamera_switch_1121.') or dll.suffix!='.dll' or hashlib.sha256(dll.read_bytes()).hexdigest()!=manifest['sha256']:raise CameraError('Unverified experiment DLL.')
        # Only retire the poller while deliberately switching away from its
        # camera. The current project is never modified or saved by this test.
        fresh_ui=api('/api/state')
        if fresh_ui['playback']['active'] or fresh_ui['connection']['state']=='connecting':raise CameraError('Workstation became busy.')
        if c.execute and chain['camera_mode']!=args.mode and fresh_ui['connection']['state']=='connected':
            api('/api/disconnect',{})
        with Remote(s,journal) as d:
            ex=pe_exports(dll);base=d.load(dll);shared=base+ex['g_shared'];hoff=C.sizeof(Config)
            read=lambda:Header.from_buffer_copy(s.memory.read(shared+hoff,C.sizeof(Header)))
            h=read()
            if h.active or h.queued or h.status not in (0,4,-1):raise CameraError('Previous native request still active.')
            d.write_bounds=(shared,shared+manifest['shared_size'])
            d.write(shared,bytes(c),'owned experiment config');d.write(shared+hoff,bytes(Header()),'owned experiment header')
            beat=lambda:d.write(shared+hoff,struct.pack('<I',d.k.GetTickCount()&0xffffffff),'owned supervisor heartbeat')
            d.detach_address=base+ex['HookDetach@4']
            d.detach_probe=lambda:not(read().active or read().queued)
            beat();result=d.call(base+ex['HookAttach@4'],0,'arm one native camera action on main-job pump')
            report['attach_result']=result
            if result:raise CameraError(f'Native attachment rejected {result}.')
            start=time.monotonic()
            while time.monotonic()-start<8:
                h=read()
                if h.status in (1,2):beat()
                if h.error or h.status==-1:raise CameraError(f'Native guard rejected {h.error}.')
                if h.status==4 and not h.active and not h.queued:break
                time.sleep(.025)
            else:raise CameraError('Timed out; no resubmission.')
            report['header']=plain(h)
            requested=int(bool(c.execute) and chain['camera_mode']!=args.mode)
            if h.job_calls!=1 or h.requests!=requested or h.thread!=h.job_thread or not h.detached:raise CameraError('Exactly-once/thread audit failed.')
            d.call(d.detach_address,0,'finish isolated camera experiment')
            if not d.detach_probe() or s.memory.u32(c.functor+0x10)!=c.tick_entry:raise CameraError('Tick restoration incomplete.')
            d.detach_address=None
        # Observe fresh roots and the clock after dispatch. Never assume that
        # native return implies camera acquisition succeeded.
        deadline=time.monotonic()+8;wanted=chain['camera_mode'] if not c.execute else args.mode
        while True:
            chains=rebuilt_chains(s,c.player)
            after=clock(s.memory,c.player,s.vft['ReplayPlayer'])
            if len(chains)==1 and chains[0]['camera_mode']==wanted and settled(after,c.rate):break
            if time.monotonic()>=deadline:raise CameraError('Requested camera mode did not settle; no retry.')
            time.sleep(.1)
        report.update(after=after,after_chain=chains[0],clock_unchanged=after['raw']==before['raw'] and after['origin']==before['origin'])
        if not report['clock_unchanged']:raise CameraError('Replay clock changed during camera operation.')
        # Prove the same discovery used by the Bind button now succeeds.
        if wanted=='free':
            with_session=CameraSession.connect(s.info.pid)
            try:
                snap=with_session.capture(require_paused=True)
                if snap['addresses']['player']!=hex(c.player):raise CameraError('Reconnected different player.')
                report['camera_reconnected']=dict(session_id=snap['session_id'],addresses=snap['addresses'],time=snap['replay']['time'])
            finally:with_session.close()
            if args.reconnect:
                if api('/api/state')['playback']['active']:raise CameraError('Workstation became busy before rebind.')
                api('/api/connect',{});deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    state=api('/api/state')
                    if state['connection']['state']=='connected':
                        if state['sample']['addresses']['player']!=hex(c.player):raise CameraError('Workstation bound different replay.')
                        report['workstation_connection']=state['connection'];break
                    if state['connection']['state']=='error':raise CameraError(state['connection']['message'])
                    time.sleep(.15)
                else:raise CameraError('Workstation reconnect timeout.')
        report.update(passed=True,hooks_detached=True,dll_sha256=manifest['sha256'])
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except BaseException as exc:
        report['error']=str(exc);raise
    finally:
        s.close()
        if folder:
            report['finished_utc']=datetime.now(timezone.utc).isoformat()
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print('REPORT',folder/'report.json',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode',choices=['noop','free','tracked'],default='free')
    ap.add_argument('--inspect',action='store_true');ap.add_argument('--execute',action='store_true')
    ap.add_argument('--pid',type=int);ap.add_argument('--url');ap.add_argument('--reconnect',action='store_true')
    args=ap.parse_args()
    if args.inspect and args.execute:ap.error('Choose inspection or execution.')
    run(args)
