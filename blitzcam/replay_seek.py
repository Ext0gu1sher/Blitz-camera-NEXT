"""User-requested experimental native seek. Importing performs no game access.

One native main-thread seek, followed by native free-camera restoration. Never
write the clock or retry a seek. A confirmed process exit permits one replay
launch. Backward reconstruction can still crash after the clock handshake.
"""
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import time

from .hook_layout import plain
from .hook_transport import Remote, pe_exports
from .freecamera import ensure_free_camera
from .memory import confirmed_exit_code
from .profile import CameraError, PROFILE_1121
from .project import atomic_json
from .reader import CameraSession
from .replay_preparation import stationary_project
from .replay_timeline import session_timeline, replay_matches
from .seek_phase_trial import Config, Header, UiRepairState, prepare
from .seek_trial import clock, settled

NATIVE = Path(__file__).parent/'native'


def native_seek(session, snapshot, target, folder, cancel, report):
    cfg, _ = prepare(session, snapshot, target, 1, folder/'first-fault.bin',
                     ui_repair=False, max_delta=3600)
    manifest = json.loads((NATIVE/'replay_seek_phase_trial_1121.json').read_text(encoding='utf8'))
    expected = dict(config_size=C.sizeof(Config), header_size=C.sizeof(Header),
                    header_offset=C.sizeof(Config), shared_size=C.sizeof(Config)+C.sizeof(Header),
                    ui_state_size=C.sizeof(UiRepairState), ui_event_size=48)
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise CameraError('跳转组件的数据布局不匹配，请重新构建。')
    dll = NATIVE/manifest['dll']
    if (dll.parent.resolve() != NATIVE.resolve() or not dll.name.startswith('replay_seek_phase_trial_1121.') or
            dll.suffix != '.dll' or hashlib.sha256(dll.read_bytes()).hexdigest() != manifest['sha256']):
        raise CameraError('跳转组件校验失败。')
    def journal(row):
        with (folder/'operations.jsonl').open('a', encoding='utf8') as f:
            f.write(json.dumps(row)+'\n')
    with Remote(session, journal) as driver:
        exports = pe_exports(dll)
        base = driver.load(dll)
        shared = base+exports['g_shared']
        hoff = C.sizeof(Config)
        read_h = lambda: Header.from_buffer_copy(session.memory.read(shared+hoff, C.sizeof(Header)))
        h = read_h()
        ui = UiRepairState.from_buffer_copy(session.memory.read(base+exports['g_ui_repair'], C.sizeof(UiRepairState)))
        if ui.installed or ui.active or ui.violations or h.active or h.queued or h.faults or h.observer or h.status not in (0, 4, -1):
            raise CameraError('进程中仍有跳转请求或旧修补状态，请重启游戏后再试。')
        if session.memory.u32(cfg.functor+0x10) != cfg.tick_entry:
            raise CameraError('回放更新入口已改变，未提交跳转。')
        if cancel.is_set():return None
        driver.write_bounds = (shared, shared+manifest['shared_size'])
        driver.write(shared, bytes(cfg), 'owned experimental seek config')
        driver.write(shared+hoff, bytes(Header()), 'owned inactive seek header')
        beat = lambda: driver.write(shared+hoff+Header.heartbeat.offset,
                                    struct.pack('<I', driver.k.GetTickCount()&0xffffffff), 'owned seek watchdog')
        driver.detach_address = base+exports['HookDetach@4']
        def detached():
            value = read_h()
            return not (value.active or value.queued or value.observer)
        driver.detach_probe = detached
        report.update(hooks_detached=False, dll_sha256=manifest['sha256'])
        try:
            beat()
            code = driver.call(base+exports['HookAttach@4'], 0, 'request one experimental native replay seek')
            if code:raise CameraError(f'游戏拒绝跳转请求（{code}）。')
            start = time.monotonic();stable = None
            with (folder/'lifecycle.jsonl').open('w', encoding='utf8') as f:
                while time.monotonic()-start < 35:
                    if cancel.is_set():return None
                    h = read_h()
                    if h.status in (1, 2):beat()
                    # Only ReplayPlayer survives reconstruction. Never capture
                    # through the old scene, callback node or camera references.
                    value = clock(session.memory, cfg.player, cfg.player_vft)
                    f.write(json.dumps(dict(header=plain(h), clock=value))+'\n');f.flush()
                    if h.faults or h.error or h.status == -1:
                        raise CameraError(f'实验性跳转未完成（{h.error}），未重试。')
                    if h.status == 4 and not h.active and not h.queued and settled(value, cfg.rate):
                        if stable is None:stable = time.monotonic()
                        if time.monotonic()-stable >= .6:break
                    else:stable = None
                    cancel.wait(.04)
                else:raise CameraError('实验性跳转超时，未提交第二次请求。')
            report.update(final_header=plain(h), landing=value)
            if (h.requests != 1 or h.job_calls != 1 or h.emitting_nodes != 1 or h.thread != h.job_thread or
                    h.emitting_vft != session.live(0x372ab00) or h.emitting_owner != cfg.job_manager or
                    h.emitting_entry != session.live(0x92aec0)):
                raise CameraError('跳转执行记录异常，已停止。')
            if abs(value['time']-target) > .12:
                raise CameraError(f'游戏实际停在 {value["time"]:.3f} 秒，未到达入点 {target:.3f} 秒。')
            return value
        finally:
            if confirmed_exit_code(session.memory) is not None:
                # The process no longer exists: skip all remaining remote calls.
                report['hooks_detached'] = True
                driver.detach_address = None
            else:
                driver.call(driver.detach_address, 0, 'detach experimental seek callback and observer')
                if not detached():raise CameraError('跳转组件尚未退出，请停止操作并重新打开回放。')
                report['hooks_detached'] = True
                driver.detach_address = None


def seek_replay(manager, project, reference, adopt_session, invalidate_session, reopen_replay=None):
    target = project.replay_timeline['work_start_sec']
    folder = (manager.output.parent/'replay-seek-phase-runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
    report = dict(experimental_seek=True, target_time=target, hooks_detached=True,
                  rendering_safety_validated=False, ui_repair=False)
    session = fresh = None
    restoring = False
    game_operation = False
    crashed = False
    bound = project.replay_timeline.get('replay_file')
    def phase(state, message):
        with manager.lock:
            manager.preparation = dict(state=state, message=message, target_time=target,
                                       current_time=reference['replay']['time'], replay_controlled=False)
    def complete(message, actual):
        manager.update(state='completed', active=False, progress=1., message=message,
                       experimental_seek=True, target_time=target, replay_time=actual,
                       run_path=str(folder), hooks_detached=True)
    try:
        folder.mkdir(parents=True)
        pid = int(reference['session_id'].split(':')[0])
        session = CameraSession.connect(pid)
        if session.profile != PROFILE_1121:raise CameraError('当前客户端构建不支持实验性跳转。')
        snapshot = session.capture(require_paused=True)
        player = session.objects.player
        if bound and not replay_matches(project.replay_timeline, session_timeline(session)):
            raise CameraError('当前回放与项目绑定不一致，未提交跳转。')
        if manager.cancel.is_set():return
        actual = snapshot['replay']['time']
        report['before'] = actual
        if abs(actual-target) >= .01:
            phase('seeking_replay', f'正在实验性跳转到入点 {target:.3f} 秒…')
            # Retire the workstation's reader before native reconstruction;
            # preparation also suspends its poller throughout this operation.
            if not invalidate_session():return
            game_operation = True
            manager.update(hooks_detached=False)
            value = native_seek(session, snapshot, target, folder, manager.cancel, report)
            manager.update(hooks_detached=report['hooks_detached'])
            if value is None:return
            actual = value['time']
            phase('reconnecting_replay', '跳转已执行，正在恢复自由视角并重新连接…')
            if not ensure_free_camera(session, player, value, folder, manager.cancel, report):return
            if manager.cancel.is_set():return
            fresh = CameraSession.connect(pid)
            snapshot = fresh.capture(require_paused=True)
            if snapshot['addresses']['player'] != hex(player):
                raise CameraError('重新连接到了不同的回放播放器，已停止。')
        else:
            fresh, session = session, None
        if manager.cancel.is_set():return
        if abs(snapshot['replay']['time']-actual) > .12:
            raise CameraError('重新连接时回放时刻已改变，请暂停后重试。')
        phase('positioning', f'正在恢复入点 {target:.3f} 秒的镜头构图…')
        pose = project.sample(target)
        camera = dict(position=pose.position, quaternion=pose.quaternion, horizontal_fov_deg=pose.horizontal_fov_deg)
        restoring = True
        game_operation = True
        manager._run(stationary_project(camera, .05), snapshot, False, True, True)
        if manager.cancel.is_set():return
        outcome = manager.state()
        if manager.value['state'] != 'completed' or not outcome.get('hooks_detached'):
            raise CameraError(manager.value.get('message') or '跳转已执行，镜头构图未恢复。')
        snapshot = fresh.capture(require_paused=True)
        if not adopt_session(fresh, snapshot):return
        fresh = None
        complete(f'已实验性跳转至 {snapshot["replay"]["time"]:.3f} 秒并暂停。', snapshot['replay']['time'])
    except Exception as exc:
        report['error'] = str(exc)
        reader = session if session is not None else fresh
        code = confirmed_exit_code(reader.memory) if reader is not None and game_operation else None
        crashed = code is not None
        if crashed:
            report.update(process_exit_code=code, hooks_detached=True)
        manager.update(state='error', message=str(exc), hooks_detached=report['hooks_detached'] and (not restoring or manager.value.get('hooks_detached', True)))
        if crashed:manager.update(hooks_detached=True)
    finally:
        for reader in (fresh, session):
            if reader is not None:reader.close()
        with manager.lock:
            manager.preparation = None
            manager.value['active'] = False
            if manager.cancel.is_set() and manager.value.get('state') != 'error':
                manager.value.update(state='stopped', message='已停止跳转；已执行的游戏跳转不会回退。')
        report['result'] = manager.state()
        if folder.exists():atomic_json(folder/'report.json', report)
    # Only a confirmed exit of the original handle permits one launch. Stop
    # all camera work first; do not seek again after opening the bound replay.
    if crashed and bound and reopen_replay is not None and not manager.cancel.is_set():
        report['relaunch_attempted'] = True
        try:
            requested = bool(reopen_replay())
            report['relaunch_requested'] = requested
            if requested:
                manager.update(state='stopped', active=False, hooks_detached=True, replay_relaunch_requested=True,
                               message='游戏已退出，已重新请求启动项目回放。载入后再连接；未继续跳转或恢复镜头。')
        except Exception as exc:
            report['relaunch_error'] = str(exc)
            manager.update(state='error', message=f'游戏已退出，重新启动回放失败：{exc}')
        report['result'] = manager.state()
        atomic_json(folder/'report.json', report)
