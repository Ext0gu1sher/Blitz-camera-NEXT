"""Read the client replay origin from record 0x11, without decoding payloads.

11.21 ReplayPlayer initializes +0x64 from the first record of this type, then
exposes raw_time - origin. Vehicle playback facets retain the raw packet clock.
Framing matches the pinned Agent's replay/packets.rs (8dcec2c6).
"""
import math
import struct

MAX_DATA_BYTES=0x01E00000+8  # Client restLen cap, plus magic and length fields.


def replay_records(data):
    """Yield framed records only; never look for markers inside payload bytes."""
    if len(data)<14 or len(data)>MAX_DATA_BYTES or struct.unpack_from('<I',data)[0]!=0x12345678:
        raise ValueError('回放时钟头部未适配或已损坏，无法自动对齐预览。')
    if struct.unpack_from('<I',data,4)[0]>0x01E00000:
        raise ValueError('回放数据超过客户端格式上限。')
    offset=12
    for _ in range(2):  # Length-prefixed client hash and version, not payload.
        if offset>=len(data):raise ValueError('回放时钟头部不完整。')
        offset+=1+data[offset]
    offset+=1
    if offset>len(data):raise ValueError('回放时钟头部不完整。')
    while offset+12<=len(data):
        size,kind,clock=struct.unpack_from('<IIf',data,offset)
        offset+=12
        end=offset+size
        if end>len(data):raise ValueError('回放记录不完整，无法自动对齐预览。')
        if kind==0xFFFFFFFF:break
        yield kind, clock, memoryview(data)[offset:end]
        offset=end


def origin_from_data(data):
    for kind, clock, _ in replay_records(data):
        if kind == 0x11:
            if not math.isfinite(clock) or not 0 <= clock <= 3600:
                raise ValueError('回放时间原点无效，无法自动对齐预览。')
            return float(clock)
    raise ValueError('回放缺少时间原点标记，无法自动对齐预览。')


def replay_data(archive):
    """Bound ZIP input before scanning; do not search payload bytes for markers."""
    entries=[e for e in archive.infolist() if e.filename=='data.wotreplay']
    if len(entries)!=1 or entries[0].flag_bits&1 or not 14<=entries[0].file_size<=MAX_DATA_BYTES:
        raise ValueError('回放时钟数据不存在、重复或超过读取上限。')
    with archive.open(entries[0]) as stream:
        data=stream.read(MAX_DATA_BYTES+1)
    return data


def replay_origin(archive):
    return origin_from_data(replay_data(archive))
