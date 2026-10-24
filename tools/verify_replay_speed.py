"""Bounded, explicit live replay-speed experiment. Never starts a game.

--mode inspect only reads. observe installs logging hooks without changing the
clock. slow changes native playback rate/pause for <=12 engine seconds and
restores the initially paused state. No camera transform is written.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blitzcam.reader import CameraSession
from blitzcam.project import atomic_json
from blitzcam.hook_layout import plain
from blitzcam.hook_transport import Remote, pe_exports
from blitzcam.replay_trial import Config, Header, Event, HEADER, EVENTS, CAP, configuration, summarize

NATIVE = ROOT/'blitzcam/native'
URL = 'http://127.0.0.1:56591'


def api(path, payload=None):
    req = urllib.request.Request(URL+path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def run(args):
    run_dir = ROOT/'output/replay-time-runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run_dir.mkdir(parents=True)
    report = {'mode': args.mode, 'rate': args.rate, 'seconds': args.seconds,
              'clock_modified': False, 'hooks_detached': True, 'state_restored': True,
              'camera_writes': False, 'runtime_test': args.mode != 'inspect'}
    event_rows = []
    s = driver = None
    cfg = shared = None
    disconnected_ui = False

    def journal(row):
        with (run_dir/'operations.jsonl').open('a', encoding='utf8') as f:
            f.write(json.dumps(row)+'\n')

    try:
        ui = api('/api/state')
        if ui.get('playback', {}).get('active'):
            raise RuntimeError('镜头轨迹仍在执行，请先停止。')
        s = CameraSession.connect()
        sample = s.capture()
        cfg, link = configuration(s, sample, args.rate, args.seconds, args.mode in ('slow', 'curve'), args.mode == 'curve')
        report.update(reference=sample, config=plain(cfg), callback=link)
        atomic_json(run_dir/'reference.json', report)
        if args.mode == 'inspect':
            print(json.dumps({'run_path': str(run_dir), 'callback': link,
                              'paused': sample['replay']['paused'], 'scene_scale_enabled': True}, ensure_ascii=False))
            return
        manifest = json.loads((NATIVE/'replay_time_trial_1121.json').read_text(encoding='utf8'))
        dll = NATIVE/manifest['dll']
        if dll.parent.resolve() != NATIVE.resolve() or not dll.name.startswith('replay_time_trial_1121.') or dll.suffix != '.dll':
            raise RuntimeError('实验 DLL 路径不匹配。')
        if hashlib.sha256(dll.read_bytes()).hexdigest() != manifest['sha256']:
            raise RuntimeError('实验 DLL 校验失败。')
        expected = {'config_size': C.sizeof(Config), 'header_size': C.sizeof(Header),
                    'event_size': C.sizeof(Event), 'events_offset': EVENTS,
                    'shared_size': EVENTS+CAP*C.sizeof(Event)}
        if any(manifest[k] != v for k, v in expected.items()):
            raise RuntimeError('实验数据布局不匹配。')
        # Scene's temporary per-instance table intentionally changes its type
        # pointer. Stop production polling first; reconnect only after detach.
        api('/api/disconnect', {})
        disconnected_ui = True
        exports = pe_exports(dll)
        with Remote(s, journal) as driver:
            module = driver.load(dll)
            shared = module+exports['g_shared']
            h = Header.from_buffer_copy(s.memory.read(shared+HEADER, C.sizeof(Header)))
            if h.active or h.status not in (0, -1, 4):
                raise RuntimeError('先前实验尚未退出。')
            # No current game pointer may still reference the prior instance.
            if (s.memory.u32(cfg.scene) != cfg.scene_vft or s.memory.u32(cfg.shadow) != cfg.shadow_vft
                    or s.memory.u32(cfg.functor+0x10) != cfg.tick_entry):
                raise RuntimeError('更新入口已有其他接管，未覆盖。')
            driver.write(shared, bytes(cfg), 'owned replay trial configuration')
            driver.write(shared+HEADER, bytes(Header()), 'owned inactive replay trial header')
            heartbeat = lambda: driver.write(shared+HEADER+Header.heartbeat.offset,
                                            struct.pack('<I', driver.k.GetTickCount() & 0xffffffff), 'owned watchdog')
            read_h = lambda: Header.from_buffer_copy(s.memory.read(shared+HEADER, C.sizeof(Header)))
            def detached():
                h = read_h()
                return (not h.active and h.detached == 7 and s.memory.u32(cfg.scene) == cfg.scene_vft
                        and s.memory.u32(cfg.shadow) == cfg.shadow_vft
                        and s.memory.u32(cfg.functor+0x10) == cfg.tick_entry)
            driver.detach_address = module+exports['HookDetach@4']
            driver.detach_probe = detached
            heartbeat()
            code = driver.call(module+exports['HookAttach@4'], 0, 'install bounded replay timing hooks')
            report.update(module_base=hex(module), dll_sha256=manifest['sha256'], hooks_detached=False)
            if code:
                raise RuntimeError(f'时钟实验拒绝安装（{code}）。')
            start, last, armed, stop_sent = time.monotonic(), 0, False, False
            with (run_dir/'events.jsonl').open('w', encoding='utf8') as f:
                while time.monotonic()-start < 25:
                    heartbeat()
                    h = read_h()
                    if h.events-last > CAP:
                        raise RuntimeError('时钟采样溢出，停止本轮。')
                    for i in range(last, h.events):
                        address = shared+EVENTS+(i % CAP)*C.sizeof(Event)
                        e = Event.from_buffer_copy(s.memory.read(address, C.sizeof(Event)))
                        if e.commit != i+1 or s.memory.u32(address) != i+1:
                            break
                        row = plain(e)
                        event_rows.append(row)
                        f.write(json.dumps(row)+'\n')
                        last = i+1
                    f.flush()
                    if h.status in (-1, 4):
                        break
                    if args.mode in ('slow', 'curve') and not armed and h.ticks >= 12 and h.draws >= 12:
                        if h.writes or len({e['thread'] for e in event_rows}) != 1:
                            raise RuntimeError('更新/渲染线程或观测阶段核对失败。')
                        driver.write(shared+HEADER+Header.command.offset, struct.pack('<i', 1),
                                     'start bounded native replay slow motion')
                        armed = True
                        report['clock_modified'] = True  # intent; final writes are recorded below
                    if args.mode == 'observe' and time.monotonic()-start >= args.seconds and not stop_sent:
                        driver.call(driver.detach_address, 0, 'finish observation')
                        stop_sent = True
                    time.sleep(.04)
            driver.call(driver.detach_address, 0, 'finish bounded replay experiment')
            deadline = time.monotonic()+3
            while not detached() and time.monotonic() < deadline:
                time.sleep(.02)
            h = read_h()
            report.update(final_header=plain(h), hooks_detached=detached(), state_restored=bool(h.restored),
                          clock_modified=bool(h.writes), numerical=summarize(event_rows, plain(h)))
            if not report['hooks_detached'] or not report['state_restored']:
                raise RuntimeError('未确认入口与原暂停/倍率已恢复；不要重试，请先检查回放状态。')
            if h.error:
                raise RuntimeError(f'原生时钟验证停止（{h.error}）。')
            if args.mode in ('slow', 'curve') and h.sum_dt < cfg.duration:
                raise RuntimeError('本轮未完成指定的慢放时长。')
            report['final_sample'] = s.capture()
        print(json.dumps({k: report[k] for k in ('hooks_detached', 'state_restored', 'clock_modified', 'numerical')},
                         ensure_ascii=False))
    except BaseException as exc:
        report['error'] = str(exc)
        raise
    finally:
        if s:
            if cfg is not None and shared:
                try:
                    h = Header.from_buffer_copy(s.memory.read(shared+HEADER, C.sizeof(Header)))
                    report.update(final_header=plain(h), state_restored=bool(h.restored), clock_modified=bool(h.writes),
                                  hooks_detached=not h.active and h.detached == 7
                                  and s.memory.u32(cfg.scene) == cfg.scene_vft
                                  and s.memory.u32(cfg.shadow) == cfg.shadow_vft
                                  and s.memory.u32(cfg.functor+0x10) == cfg.tick_entry)
                except Exception as exc:
                    report.update(hooks_detached=False, final_read_error=str(exc))
            s.close()
        if disconnected_ui and report['hooks_detached'] and report['state_restored']:
            try:
                api('/api/connect', {})
            except Exception as exc:
                report['ui_reconnect_error'] = str(exc)
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_json(run_dir/'report.json', report)
        print(str(run_dir/'report.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('inspect', 'observe', 'slow', 'curve'), default='inspect')
    parser.add_argument('--rate', type=float, default=.25)
    parser.add_argument('--seconds', type=float, default=8.)
    run(parser.parse_args())
