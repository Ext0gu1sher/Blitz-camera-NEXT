"""Research: a no-op probe; both seek experiments are disabled after live failure.
Requires --execute for the no-op probe. Never retries or writes clock/camera
state. Retain the failed UI candidate and evidence for offline investigation.
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
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blitzcam.reader import CameraSession
from blitzcam.profile import CameraError
from blitzcam.project import atomic_json
from blitzcam.hook_layout import plain
from blitzcam.hook_transport import Remote, pe_exports, relocated_code
from blitzcam.profile import PROFILE_1121
from blitzcam.seek_trial import clock, settled
from blitzcam.seek_phase_trial import Config, Header, UiRepairState, prepare

# Third backward reconstruction reproduced a first-chance UIControl AV.
# Keep the evidence collector, but reject seek before service/process access.
LIVE_SEEK_ENABLED = False
# PID 49772 failed during continued rendering after two backward seeks and a
# forward seek. The resident UI repair did not make reconstruction safe.
LIVE_UI_REPAIR_ENABLED = False


def repair_state(value):
    return {n: (getattr(value, n).decode('ascii') if n == 'fault_path' else getattr(value, n))
            for n, _ in UiRepairState._fields_}


def verify_original_removal_code(session):
    """Full relocated function bodies, not just a matching first instruction."""
    if session.profile.sha256 != PROFILE_1121.sha256:
        raise RuntimeError('UI repair requires the exact 11.21.0.1235 image hash.')
    code = relocated_code(session.info.path, session.info.base)
    for va, size in ((0xcfab30, 0x15b), (0xcfaf90, 0x1de)):
        rva = va-0x400000
        matches = [data[rva-start:rva-start+size] for start, data in code.items()
                   if start <= rva and rva+size <= start+len(data)]
        if len(matches) != 1 or session.memory.read(session.live(va), size) != matches[0]:
            raise RuntimeError(f'Original UI removal code at {va:#x} differs; no patch installed.')


def rebuilt_chains(session, player):
    """Fresh discovery permits either tracked or free camera after native reset."""
    m, v, rows = session.memory, session.vft, []
    rx = re.compile(re.escape(struct.pack('<I', v['GameSceneController'])))
    for start, length in m.regions():
        for a in range(start, start+length, 1024*1024):
            try:
                data = m.read(a, min(1024*1024, start+length-a))
            except CameraError:
                continue
            for match in rx.finditer(data):
                owner = a+match.start()
                if owner % 4:
                    continue
                try:
                    u = m.u32
                    scene, context = u(owner+0x1c), u(owner+0x20)
                    game, free, controller = u(owner+0x8c), u(owner+0x94), u(owner+0x9c)
                    if (u(context) != v['AvatarContextReplay'] or u(context+0x1b0) != player or
                        u(scene) != v['GameScene'] or u(game) != v['GameCamera'] or
                        u(free) != v['FreeCamera'] or u(controller) != v['ReplayCameraController'] or
                        u(controller+0x28) != game or u(game+0x5b8) != controller):
                        continue
                    render = u(scene+0xa8)
                    active = u(scene+0x120)
                    if (u(render) != v['RenderSystem'] or active not in (free, game) or
                        u(scene+0x124) != active or u(render+0xb4) != active or u(render+0xb8) != active):
                        continue
                    rows.append(dict(scene_controller=hex(owner), scene=hex(scene), context=hex(context),
                                     game_camera=hex(game), free_camera=hex(free), replay_controller=hex(controller),
                                     render=hex(render), active_camera=hex(active),
                                     camera_mode='free' if active == free else 'tracked'))
                except CameraError:
                    continue
    return rows


def run(args):
    if args.mode == 'seek' and not LIVE_SEEK_ENABLED:
        raise RuntimeError('Live seek disabled after repeated reconstruction crash; no service or game access occurred.')
    if args.mode == 'repair-seek' and not LIVE_UI_REPAIR_ENABLED:
        raise RuntimeError('UI repair seek disabled after render AV in PID 49772; no service or game access occurred.')
    if not args.execute:
        raise RuntimeError('This is an explicit runtime experiment; pass --execute. No game access occurred.')
    repaired = args.mode == 'repair-seek'
    seeking = args.mode in ('seek', 'repair-seek')
    folder = ROOT/'output/replay-seek-phase-runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    report = dict(mode=args.mode, runtime_test=True, camera_writes=False, raw_clock_writes=False,
                  hypothesis='Defer native seek to verified native main-job pump; Replay tick must not be emitting.', passed=False)
    if repaired:
        report.update(hypothesis='UI component removal callbacks invalidate vector headers/slots; reacquire by identity and commit erase before Release.',
                      repair_candidate=True, full_validation_passed=False,
                      remaining_validation=['three backward reconstructions', 'continuous rendering',
                                            'pause/resume', 'free camera switching', 'replay exit'])
    session = None
    def api(path, payload=None):
        req = urllib.request.Request(args.url+path, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    def journal(row):
        with (folder/'operations.jsonl').open('a', encoding='utf8') as f:
            f.write(json.dumps(row)+'\n')
    try:
        ui = api('/api/state')
        if ui.get('playback', {}).get('active'):
            raise RuntimeError('Camera/speed playback must be stopped before research.')
        session = CameraSession.connect()
        sample = session.capture()
        target = args.target if args.target is not None else sample['replay']['time']-1
        cfg, link = prepare(session, sample, target, int(seeking), folder/'first-fault.bin', ui_repair=repaired)
        report.update(reference=sample, target=target, config={n:getattr(cfg,n) for n,_ in Config._fields_ if n!='fault_path'}, callback=link)
        atomic_json(folder/'reference.json', report)
        print(json.dumps(dict(run_path=str(folder), pid=session.info.pid, before=sample['replay']['time'],
                              target=target, delta=cfg.delta, mode=args.mode)), flush=True)
        native = ROOT/'blitzcam/native'
        manifest = json.loads((native/'replay_seek_phase_trial_1121.json').read_text(encoding='utf8'))
        expected = dict(config_size=C.sizeof(Config), header_size=C.sizeof(Header), header_offset=C.sizeof(Config),
                        shared_size=C.sizeof(Config)+C.sizeof(Header), ui_state_size=C.sizeof(UiRepairState), ui_event_size=48)
        if any(manifest.get(k) != v for k,v in expected.items()):
            raise RuntimeError('Native/Python ABI mismatch.')
        dll = native/manifest['dll']
        if (dll.parent.resolve() != native.resolve() or not dll.name.startswith('replay_seek_phase_trial_1121.') or
            dll.suffix != '.dll' or hashlib.sha256(dll.read_bytes()).hexdigest() != manifest['sha256']):
            raise RuntimeError('Unverified research DLL.')
        api('/api/disconnect', {})
        with Remote(session, journal) as driver:
            exports = pe_exports(dll)
            base = driver.load(dll)
            shared = base+exports['g_shared']
            hoff = C.sizeof(Config)
            driver.write_bounds = (shared, shared+manifest['shared_size'])
            read_h = lambda: Header.from_buffer_copy(session.memory.read(shared+hoff, C.sizeof(Header)))
            read_ui = lambda: UiRepairState.from_buffer_copy(session.memory.read(base+exports['g_ui_repair'], C.sizeof(UiRepairState)))
            h = read_h()
            state = read_ui()
            if state.installed and not repaired:
                raise RuntimeError('This process has the resident UI repair; use repair-seek or restart the game.')
            if h.active or h.queued or state.active or state.violations or h.faults or (h.observer and not (repaired and state.installed)) or h.status not in (0, 4, -1):
                raise RuntimeError('A previous request/observer is still active; no reuse.')
            if repaired and not state.installed:
                verify_original_removal_code(session)
            report['ui_before'] = repair_state(state)
            if session.memory.u32(cfg.functor+0x10) != cfg.tick_entry:
                raise RuntimeError('Original tick no longer owns the callback.')
            driver.write(shared, bytes(cfg), 'owned phase config')
            driver.write(shared+hoff, bytes(Header()), 'owned inactive phase header')
            beat = lambda: driver.write(shared+hoff+Header.heartbeat.offset,
                                         struct.pack('<I', driver.k.GetTickCount()&0xffffffff), 'owned phase watchdog')
            driver.detach_address = base+exports['HookDetach@4']
            driver.detach_probe = lambda: not (read_h().active or read_h().queued or
                (read_h().observer and not (repaired and read_ui().installed)))
            beat()
            report.update(module_base=hex(base), dll_sha256=manifest['sha256'])
            code = driver.call(base+exports['HookAttach@4'], 0, 'install queued phase experiment and first-fault observer')
            report['attach_result'] = code
            if code:
                raise RuntimeError(f'Native phase attachment rejected: {code}')
            start = time.monotonic()
            stable_at = None
            with (folder/'lifecycle.jsonl').open('w', encoding='utf8') as log:
                while time.monotonic()-start < 35:
                    h = read_h()
                    if h.status in (1, 2):
                        beat()
                    x = clock(session.memory, cfg.player, cfg.player_vft)
                    state = read_ui()
                    if state.installed:
                        report.update(resident_repair_until_process_exit=True,
                                      first_fault_path=state.fault_path.decode('ascii'),
                                      component_events_path=state.fault_path.decode('ascii')+'.ui.bin')
                    row = dict(elapsed=time.monotonic()-start, header=plain(h), clock=x, ui=repair_state(state))
                    log.write(json.dumps(row)+'\n');log.flush()
                    if h.faults or state.violations:
                        report['failure_header'] = plain(h)
                        report['ui_failure'] = repair_state(state)
                        raise RuntimeError('First-chance access violation recorded; experiment failed, no retry.')
                    if h.error or h.status == -1:
                        report['failure_header'] = plain(h)
                        raise RuntimeError(f'Native phase guard stopped the experiment: {h.error}')
                    if h.status == 4 and not h.active and not h.queued and settled(x, cfg.rate):
                        if stable_at is None:
                            stable_at = time.monotonic()
                            report['first_clock_settle'] = row['elapsed']
                        # Deliberately observe well beyond the old premature .6s acceptance.
                        if time.monotonic()-stable_at >= args.observe:
                            report.update(landing=x, observed_stable_seconds=time.monotonic()-stable_at)
                            break
                    else:
                        stable_at = None
                    time.sleep(.04)
                else:
                    raise RuntimeError('No sufficiently long stable landing; no second request submitted.')
            chains = rebuilt_chains(session, cfg.player)
            report['rebuilt_chains'] = chains
            if len(chains) != 1:
                raise RuntimeError('Rebuilt active camera/render chain is not unique.')
            final = plain(read_h())
            report['final_header'] = final
            if (final['faults'] or final['error'] or final['job_calls'] != 1 or final['emitting_nodes'] != 1 or
                final['emitting_vft'] != session.live(0x372ab00) or final['emitting_owner'] != cfg.job_manager or
                final['emitting_entry'] != session.live(0x92aec0)):
                raise RuntimeError('Phase execution/fault audit failed.')
            if final['requests'] != int(seeking) or final['thread'] != final['job_thread']:
                raise RuntimeError('Exactly-once or thread audit failed.')
            state = read_ui()
            if repaired and (not state.installed or state.violations):
                raise RuntimeError('UI repair was not installed cleanly.')
            report['ui_after'] = repair_state(state)
            report['resident_repair_until_process_exit'] = bool(state.installed)
            report['first_fault_path'] = state.fault_path.decode('ascii') if state.installed else str(folder/'first-fault.bin')
            report['component_events_path'] = report['first_fault_path']+'.ui.bin' if state.installed else None
            driver.call(driver.detach_address, 0, 'finish seek request; resident UI repair and observer stay through replay exit' if repaired else 'remove first-fault observer after observation')
            if not driver.detach_probe():
                raise RuntimeError('Research callback/observer did not detach.')
            driver.detach_address = None
            report['detached_header'] = plain(read_h())
            report['landing_error_seconds'] = report['landing']['time']-target if seeking else None
            report['landing_observed'] = True
            report['passed'] = not repaired
        print(json.dumps({k:report.get(k) for k in ('passed','landing_observed','full_validation_passed','landing','landing_error_seconds','rebuilt_chains','final_header','ui_after')}, ensure_ascii=False), flush=True)
    except BaseException as exc:
        report['error'] = str(exc)
        raise
    finally:
        if session:
            session.close()
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_json(folder/'report.json', report)
        print(str(folder/'report.json'), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', choices=['noop','seek','repair-seek'], required=True)
    ap.add_argument('--target', type=float)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--observe', type=float, default=15)
    ap.add_argument('--url', default='http://127.0.0.1:56592')
    args = ap.parse_args()
    if not 3 <= args.observe <= 20:
        ap.error('--observe must be 3–20 seconds')
    run(args)
