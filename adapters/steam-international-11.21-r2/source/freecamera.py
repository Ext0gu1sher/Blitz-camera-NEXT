"""Restore native free camera after reconstruction, using only fresh roots.

The HUD action is a toggle, so it is dispatched at most once and only when
both context and scene/render agree that the current camera is tracked.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import struct
import time
from types import SimpleNamespace

from .hook_layout import plain
from .hook_transport import Remote, pe_exports, relocated_code
from .memory import confirmed_exit_code
from .profile import CameraError, PROFILE_1121
from .reader import CameraSession
from .replay_trial import signal_callback
from .seek_trial import clock, settled

NATIVE = Path(__file__).parent/'native'
UINTS = ('magic size base context player scene_owner scene render game_camera free_camera '
         'hud model engine head node functor job_manager tick_entry queue_entry '
         'any_entry action_entry destroy_entry initial_camera want_free execute').split()


class Config(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_uint32) for n in UINTS] + [(n, C.c_float) for n in ('raw', 'origin', 'rate')]


class Header(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_int32) for n in ('heartbeat status error active detached thread queued job_thread '
                                       'requests job_calls clones destroys before_mode after_mode').split()] + [('token', C.c_uint32)]


def discover(session, player, cancel):
    """One fresh scan; ignore all pre-reconstruction camera/HUD addresses."""
    m, v = session.memory, session.vft
    patterns = {struct.pack('<I', session.live(0x3853e68)): 'hud',
                struct.pack('<I', v['GameSceneController']): 'owner'}
    rx = re.compile(b'|'.join(re.escape(p) for p in patterns))
    candidates = {'hud': [], 'owner': []}
    for start, length in m.regions():
        for address in range(start, start+length, 1024*1024):
            if cancel.is_set():return []
            try:data = m.read(address, min(1024*1024, start+length-address))
            except CameraError:continue
            for match in rx.finditer(data):
                p = address+match.start()
                if p % 4 == 0:candidates[patterns[match.group()]].append(p)
    huds, chains = [], []
    u = m.u32
    for hud in candidates['hud']:
        try:
            context, model = u(hud+0x120), u(hud+0x148)
            if (u(context) == v['AvatarContextReplay'] and u(context+0x1b0) == player and
                    u(player) == v['ReplayPlayer'] and u(model) == session.live(0x385332c)):
                huds.append(dict(hud=hud, model=model, context=context, player=player))
        except CameraError:continue
    for owner in candidates['owner']:
        try:
            scene, context = u(owner+0x1c), u(owner+0x20)
            game, free, controller = u(owner+0x8c), u(owner+0x94), u(owner+0x9c)
            if (u(context) != v['AvatarContextReplay'] or u(context+0x1b0) != player or
                    u(scene) != v['GameScene'] or u(game) != v['GameCamera'] or
                    u(free) != v['FreeCamera'] or u(controller) != v['ReplayCameraController'] or
                    u(controller+0x28) != game or u(game+0x5b8) != controller):continue
            render, active = u(scene+0xa8), u(scene+0x120)
            if (u(render) != v['RenderSystem'] or active not in (free, game) or
                    u(scene+0x124) != active or u(render+0xb4) != active or u(render+0xb8) != active):continue
            mode = int(active == free)
            if m.read(context+0x190, 1)[0] != mode:continue
            chains.append(dict(scene_owner=owner, scene=scene, context=context, render=render,
                               game_camera=game, free_camera=free, initial_camera=active, mode=mode))
        except CameraError:continue
    # Ambiguous roots must not authorize a toggle, even if only one pair joins.
    if len(huds) != 1 or len(chains) != 1 or huds[0]['context'] != chains[0]['context']:return []
    return [{**huds[0], **chains[0]}]


def unchanged_clock(session, player, expected):
    value = clock(session.memory, player, session.vft['ReplayPlayer'])
    if not settled(value, expected['rate']) or any(value[n] != expected[n] for n in ('raw', 'origin', 'rate')):
        raise CameraError('恢复自由视角时回放时刻或暂停状态已改变，已停止。')
    return value


def wait_roots(session, player, expected, cancel, *, free=False):
    deadline = time.monotonic()+10
    while not cancel.is_set():
        unchanged_clock(session, player, expected)
        roots = discover(session, player, cancel)
        if cancel.is_set():return None
        unchanged_clock(session, player, expected)
        if len(roots) == 1 and (not free or roots[0]['mode'] == 1):return roots[0]
        if confirmed_exit_code(session.memory) is not None:raise CameraError('游戏已退出，停止恢复自由视角。')
        if time.monotonic() >= deadline:raise CameraError('未能确认重建后的相机与渲染引用一致，未重复切换视角。')
        cancel.wait(.1)
    return None


def configuration(session, root, expected):
    session.objects = SimpleNamespace(player=root['player'])
    link = signal_callback(session)
    cfg = Config(magic=0x31434642, size=C.sizeof(Config), base=session.info.base,
                 **{k:root[k] for k in ('context', 'player', 'scene_owner', 'scene', 'render',
                                        'game_camera', 'free_camera', 'hud', 'model', 'initial_camera')},
                 want_free=1, execute=1,
                 job_manager=session.memory.u32(session.memory.u32(session.live(0x4690a30))),
                 tick_entry=session.live(0x140d100), queue_entry=session.live(0x91d090),
                 any_entry=session.live(0x717250), action_entry=session.live(0x1e173e0), destroy_entry=session.live(0x6a4720),
                 **{k:expected[k] for k in ('raw', 'origin', 'rate')},
                 **{k:link[k] for k in ('engine', 'head', 'node', 'functor')})
    code = relocated_code(session.info.path, session.info.base)
    for va, size in ((0x717250, 0xe5), (0x1e173e0, 0x1b5), (0x6a4720, 0x5e)):
        rva = va-session.profile.preferred_base
        matches = [data[rva-start:rva-start+size] for start, data in code.items()
                   if start <= rva and rva+size <= start+len(data)]
        if len(matches) != 1 or session.memory.read(session.live(va), size) != matches[0]:
            raise CameraError('原生视角切换代码与适配版本不符，未提交动作。')
    unchanged_clock(session, cfg.player, expected)
    return cfg


def native_free_camera(session, cfg, folder, cancel, report):
    manifest = json.loads((NATIVE/'freecamera_switch_1121.json').read_text(encoding='utf8'))
    expected = dict(config_size=C.sizeof(Config), header_size=C.sizeof(Header), shared_size=C.sizeof(Config)+C.sizeof(Header))
    if any(manifest.get(k) != v for k, v in expected.items()):raise CameraError('视角切换组件布局不匹配。')
    dll = NATIVE/manifest['dll']
    if (dll.parent.resolve() != NATIVE.resolve() or not dll.name.startswith('freecamera_switch_1121.') or
            dll.suffix != '.dll' or hashlib.sha256(dll.read_bytes()).hexdigest() != manifest['sha256']):
        raise CameraError('视角切换组件校验失败。')
    def journal(row):
        with (folder/'freecamera-operations.jsonl').open('a', encoding='utf8') as f:f.write(json.dumps(row)+'\n')
    with Remote(session, journal) as driver:
        exports = pe_exports(dll);base = driver.load(dll);shared = base+exports['g_shared'];hoff = C.sizeof(Config)
        read = lambda: Header.from_buffer_copy(session.memory.read(shared+hoff, C.sizeof(Header)))
        h = read()
        if h.active or h.queued or h.status not in (0, 4, -1):raise CameraError('视角切换组件仍在执行。')
        if session.memory.u32(cfg.functor+0x10) != cfg.tick_entry:raise CameraError('回放回调已改变，未切换视角。')
        if cancel.is_set():return False
        driver.write_bounds = (shared, shared+manifest['shared_size'])
        driver.write(shared, bytes(cfg), 'owned free-camera config')
        driver.write(shared+hoff, bytes(Header()), 'owned free-camera header')
        beat = lambda: driver.write(shared+hoff, struct.pack('<I', driver.k.GetTickCount()&0xffffffff), 'owned free-camera watchdog')
        driver.detach_address = base+exports['HookDetach@4']
        def detached():
            value = read()
            return not (value.active or value.queued) and session.memory.u32(cfg.functor+0x10) == cfg.tick_entry
        driver.detach_probe = detached
        report['hooks_detached'] = False
        report['freecamera']['dll_sha256'] = manifest['sha256']
        try:
            beat()
            code = driver.call(base+exports['HookAttach@4'], 0, 'ensure native free camera once on main-job pump')
            if code:raise CameraError(f'游戏拒绝切换自由视角（{code}）。')
            deadline = time.monotonic()+8
            while time.monotonic() < deadline:
                if cancel.is_set():return False
                h = read()
                if h.status in (1, 2):beat()
                if h.error or h.status == -1:raise CameraError(f'原生自由视角切换失败（{h.error}），未重试。')
                if h.status == 4 and not h.active and not h.queued:break
                cancel.wait(.025)
            else:raise CameraError('自由视角切换超时，未重复提交。')
            report['freecamera']['header'] = plain(h)
            if h.job_calls != 1 or h.requests != 1 or h.thread != h.job_thread or not h.detached or h.before_mode != 0:
                raise CameraError('自由视角执行记录异常，已停止。')
            # after_mode may be -1 until the render roots catch up.
            return True
        finally:
            if confirmed_exit_code(session.memory) is not None:
                driver.detach_address = None
                report['hooks_detached'] = True
            else:
                driver.call(driver.detach_address, 0, 'detach native free-camera callback')
                if not detached():raise CameraError('自由视角切换回调尚未退出。')
                report['hooks_detached'] = True
                driver.detach_address = None


def ensure_free_camera(session, player, expected, folder, cancel, report):
    if session.profile != PROFILE_1121:raise CameraError('当前客户端不支持自动恢复自由视角。')
    # Reuse only the process handle/image identity, never the old object graph.
    reader = CameraSession(session.memory)
    report['freecamera'] = dict(requests=0)
    root = wait_roots(reader, player, expected, cancel)
    if root is None:return False
    report['freecamera']['before'] = root
    if root['mode'] == 0:
        cfg = configuration(reader, root, expected)
        if not native_free_camera(reader, cfg, folder, cancel, report):return False
        report['freecamera']['requests'] = 1
        root = wait_roots(reader, player, expected, cancel, free=True)
        if root is None:return False
    report['freecamera']['after'] = root
    return True
