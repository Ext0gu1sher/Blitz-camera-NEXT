"""Experimental clock probe, independent of the production camera playback.

Importing this module does not access a process. --inspect is read-only;
the explicit runner in tools/verify_replay_speed.py owns runtime modifications.
"""
import ctypes as C
import math
import struct

from .profile import CameraError, PROFILE_1121

MAGIC = 0x31545242
CAP = 4096
POINTERS = ('magic size base context player scene_owner scene render shadow camera spectator '
            'context_vft player_vft secondary_vft scene_owner_vft scene_vft render_vft shadow_vft camera_vft spectator_vft '
            'engine head node functor functor_vft tick_entry scene_entry draw_entry notify_entry pause_entry').split()


class Config(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_uint32) for n in POINTERS] + [
        (n, C.c_float) for n in ('raw', 'origin', 'initial_rate', 'rate', 'duration')
    ] + [('mode', C.c_uint32)]


class Header(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_int32) for n in
                ('command', 'heartbeat', 'status', 'error', 'events', 'active', 'thread',
                 'detached', 'restored', 'writes', 'ticks', 'draws')] + [
                     ('frequency', C.c_int64), ('start_qpc', C.c_int64), ('sum_dt', C.c_double)]


class Event(C.Structure):
    _pack_ = 4
    _fields_ = [('commit', C.c_int32)] + [(n, C.c_uint32) for n in
                ('kind', 'thread', 'tick', 'stage', 'paused', 'scale_enabled', 'record_index')] + [
                    ('qpc', C.c_int64)] + [(n, C.c_float) for n in
                ('dt', 'raw', 'rate', 'scene_rate', 'fov')] + [
                    ('position', C.c_float * 3), ('shadow_width', C.c_float * 3), ('sum_dt', C.c_double)]


HEADER = C.sizeof(Config)
EVENTS = HEADER + C.sizeof(Header)


def signal_callback(session):
    """Walk the exact engine update signal; accept only its live replay functor."""
    s, m = session, session.memory
    if s.profile != PROFILE_1121:
        raise CameraError('回放时钟实验仅适配已核验的 11.21 构建。')
    engine = m.u32(s.live(0x46909a0))
    signal = engine + 0x70
    head, count = struct.unpack('<2I', m.read(signal + 4, 8))
    if not head or not 1 <= count <= 64:
        raise CameraError('主更新信号数量超出本次已分析范围。')
    sentinel = m.read(head, 8)
    node, tail = struct.unpack('<2I', sentinel)
    prev, seen, found = head, set(), []
    expected_vft, target = s.live(0x37c4674), s.live(0x140d100)
    while node != head:
        if node in seen or len(seen) >= count:
            raise CameraError('主更新信号链不稳定。')
        seen.add(node)
        data = m.read(node, 0x50)
        nxt, back = struct.unpack_from('<2I', data)
        if back != prev:
            raise CameraError('主更新信号反向链不匹配。')
        functor = node + 0x20
        vft, owner, code, adjust = (struct.unpack_from('<I', data, off)[0]
                                  for off in (0x20, 0x28, 0x30, 0x34))
        if vft == expected_vft and owner == s.objects.player and code == target and adjust == 0:
            found.append({'engine': engine, 'head': head, 'node': node, 'functor': functor,
                          'functor_vft': vft, 'tick_entry': code, 'node_hex': data.hex()})
        prev, node = node, nxt
    if len(seen) != count or tail != prev or m.read(head, 8) != sentinel:
        raise CameraError('主更新信号在读取过程中改变。')
    if len(found) != 1:
        raise CameraError('未找到唯一、未被其他工具接管的回放 tick 回调。')
    result = found[0]
    if m.u32(expected_vft + 8) != s.live(0x12f8310):
        raise CameraError('回放回调包装器与已分析代码不符。')
    return result


def configuration(session, sample, rate, seconds, execute=False, curve=False):
    if isinstance(rate, bool) or not math.isfinite(rate) or not .0625 <= rate <= 1:
        raise ValueError('本轮只允许 1/16× 至 1× 的正倍率。')
    if isinstance(seconds, bool) or not math.isfinite(seconds) or not 1 <= seconds <= 12:
        raise ValueError('单次实验需要 1–12 秒。')
    if not sample['replay']['paused']:
        raise CameraError('实验必须从暂停的本地回放开始。')
    c = Config(magic=MAGIC, size=C.sizeof(Config), base=session.info.base,
               rate=rate, duration=seconds, mode=2 if curve and execute else int(execute))
    a, m = session.objects, session.memory
    for field, obj in [('context', 'context'), ('player', 'player'), ('scene_owner', 'scene_controller'),
                       ('scene', 'scene'), ('render', 'render'), ('camera', 'free_camera'),
                       ('spectator', 'spectator_controller')]:
        setattr(c, field, getattr(a, obj))
    for field, typ in [('context_vft', 'AvatarContextReplay'), ('player_vft', 'ReplayPlayer'),
                       ('scene_owner_vft', 'GameSceneController'), ('scene_vft', 'GameScene'),
                       ('render_vft', 'RenderSystem'), ('camera_vft', 'FreeCamera'),
                       ('spectator_vft', session.controller_kind)]:
        setattr(c, field, session.vft[typ])
    c.shadow = m.u32(a.render + 0x8c)
    c.shadow_vft = session.live(0x375b100)
    c.secondary_vft = session.live(PROFILE_1121.replay_secondary_vft)
    link = signal_callback(session)
    for key in ('engine', 'head', 'node', 'functor', 'functor_vft', 'tick_entry'):
        setattr(c, key, link[key])
    for key, va in [('scene_entry', 0x7c46f0), ('draw_entry', 0xc7b2c0),
                    ('notify_entry', 0x140ec00), ('pause_entry', 0x1402000)]:
        setattr(c, key, session.live(va))
    c.raw = sample['replay']['raw_time']
    c.origin = sample['replay']['origin']
    c.initial_rate = sample['replay']['rate']
    if m.u32(c.scene) != c.scene_vft or m.u32(c.shadow) != c.shadow_vft:
        raise CameraError('已有相机/绘制接管，先停止镜头轨迹。')
    if m.u32(c.scene_vft + 0x54) != c.scene_entry or m.u32(c.shadow_vft + 12) != c.draw_entry:
        raise CameraError('场景/绘制更新入口与分析不符。')
    enabled = m.read(c.scene + 0x2a4, 1)[0]
    scene_rate = struct.unpack('<f', m.read(c.scene + 0x2a8, 4))[0]
    if enabled != 1 or scene_rate != 0:
        raise CameraError('当前暂停场景的时间缩放状态不符。')
    if m.read(c.functor, 0x18).hex() != link['node_hex'][0x20*2:0x38*2]:
        raise CameraError('回放回调已改变。')
    return c, link


def summarize(events, header):
    """Numerical acceptance uses the same float operations as the client tick."""
    before, errors, advances, effective, frame_order = {}, [], [], [], []
    f32 = lambda x: C.c_float(x).value
    for e in events:
        kind = e['kind']
        frame_order.append(kind)
        if kind == 1:
            before[e['tick']] = e
        elif kind == 2:
            a = before.pop(e['tick'], None)
            if a is None:
                continue
            expected = a['raw'] if a['paused'] else f32(a['raw'] + f32(a['dt'] * a['rate']))
            errors.append(abs(e['raw'] - expected))
            advances.append(e['raw'] - a['raw'])
        if kind in (3, 4):
            effective.append({'kind': kind, 'stage': e['stage'], 'dt': e['dt'],
                              'effective_dt': e['dt'] * e['scene_rate'] if e['scale_enabled'] else e['dt'],
                              'rate': e['rate'], 'paused': e['paused'], 'scene_rate': e['scene_rate']})
    playing = [e for e in events if e['stage'] == 2]
    ticks = [e for e in events if e['kind'] == 1]
    intervals = [(b['qpc']-a['qpc'])/header['frequency'] for a,b in zip(ticks,ticks[1:])] if header.get('frequency') else []
    initial = events[0] if events else None
    return {'paired_ticks': len(errors), 'max_tick_float_error': max(errors, default=None),
            'raw_advance_sum': sum(advances), 'playing_events': len(playing),
            'threads': sorted({e['thread'] for e in events}),
            'first_kinds': frame_order[:35], 'scene_samples_first': effective[:8],
            'playing_scene_rate_values': sorted({e['scene_rate'] for e in playing if e['kind'] in (3,4)}),
            'input_dt_sum': header['sum_dt'], 'internal_rate_changes': header['writes'],
            'max_tick_interval_seconds': max(intervals, default=None),
            'max_position_delta': max((math.dist(e['position'], initial['position']) for e in events), default=None),
            'max_fov_delta': max((abs(e['fov']-initial['fov']) for e in events), default=None)}
