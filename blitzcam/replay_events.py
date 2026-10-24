"""Read the explicit arena BATTLE event; never infer it from fixed countdowns.

Protocol: pinned Agent 8dcec2c6, combat/arena.rs::parse_arena_periods and
WotbTools docs/research/replay/entity-methods.md. EntityMethod 48 / wrapper 3
contains protobuf field 3 {1: period, 2: remaining f64, 3: duration varint}.
Only that narrow event is decoded, without executing pickle or parsing results.
"""
import math
import re
import struct

from .replay_clock import origin_from_data, replay_data, replay_records


def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError('截断的 protobuf 数值。')
        byte = data[offset]; offset += 1
        if shift == 63 and byte > 1:
            raise ValueError('protobuf 数值越界。')
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise ValueError('protobuf 数值过长。')


def _fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError('protobuf 字段编号无效。')
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, offset = _varint(data, offset)
            else:
                size = 8 if wire == 1 else 4
            end = offset + size
            if end > len(data):
                raise ValueError('截断的 protobuf 字段。')
            value = data[offset:end]; offset = end
        else:
            raise ValueError('不支持的 protobuf 字段类型。')
        yield field, wire, value


def _battle_period(payload):
    if len(payload) < 16 or struct.unpack_from('<I', payload, 4)[0] != 48:
        return False
    arg_length = struct.unpack_from('<I', payload, 8)[0]
    if arg_length < 4 or 12 + arg_length > len(payload) or payload[12] != 3:
        return False
    body = payload[14:12 + arg_length]
    # Phase messages are small. Reject an inconsistent envelope instead of
    # accidentally promoting arbitrary method data into a protected boundary.
    if payload[13] != len(body):
        return False
    try:
        blocks = [v for f, w, v in _fields(body) if f == 3 and w == 2]
        if len(blocks) != 1:
            return False
        fields = list(_fields(blocks[0]))
        periods = [v for f, w, v in fields if f == 1 and w == 0]
        remaining = [struct.unpack('<d', v)[0] for f, w, v in fields if f == 2 and w == 1]
        return (periods == [3] and len(remaining) == 1
                and math.isfinite(remaining[0]) and 0 <= remaining[0] <= 3600)
    except (ValueError, struct.error):
        return False


def battle_start_from_data(data, version):
    """Return raw and ReplayPlayer clocks, or an explicit unavailable status."""
    result = {'battle_start_status': 'unavailable', 'battle_start_sec': None,
              'battle_start_raw_sec': None, 'replay_origin_sec': None,
              'battle_start_reason': '未识别到比赛开始事件，请在设置中手动填写赛前片段长度。'}
    try:
        origin = origin_from_data(data)
        result['replay_origin_sec'] = origin
        match = re.match(r'^11\.(\d+)(?:\.|_|$)', str(version))
        # Method numbers change across versions. This mapping is supported by
        # the pinned parser/current client; unknown future layouts stay explicit.
        if not match or not 18 <= int(match.group(1)) <= 21:
            result['battle_start_reason'] = '该回放版本的比赛开始事件尚未适配，请在设置中手动填写赛前片段长度。'
            return result
        for kind, raw_clock, payload in replay_records(data):
            if kind == 8 and _battle_period(payload):
                if not math.isfinite(raw_clock) or not 0 <= raw_clock <= 3600:
                    continue
                result.update(battle_start_status='identified', battle_start_raw_sec=float(raw_clock),
                              battle_start_sec=max(0., float(raw_clock) - origin), battle_start_reason='')
                return result
    except (ValueError, struct.error) as exc:
        result['battle_start_reason'] = f'比赛开始事件无法读取：{exc} 请在设置中手动填写赛前片段长度。'
    return result


def replay_battle_start(archive, version):
    try:
        return battle_start_from_data(replay_data(archive), version)
    except ValueError as exc:
        return {'battle_start_status': 'unavailable', 'battle_start_sec': None,
                'battle_start_raw_sec': None, 'replay_origin_sec': None,
                'battle_start_reason': f'比赛开始事件无法读取：{exc} 请在设置中手动填写赛前片段长度。'}
