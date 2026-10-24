"""Read the file owned by the active ReplayPlayer, without launch assumptions.

The NewReplayFile shared owner, ReplayFile type and their common reference are
verified for the exact 11.21 executable. No directory search or game writes.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import struct

from .profile import BuildProfile


@dataclass(frozen=True)
class ReplaySource:
    path: Path
    player: int
    source: int
    holder: int
    metadata: int
    version: str
    archive_key: str
    client_version: str = ''


def supports_runtime_source(session):
    profile = getattr(session, 'profile', None)
    return isinstance(profile, BuildProfile) and profile.replay_file_source_offset is not None


def _string(memory, address, limit):
    """Bounded MSVC x86 std::string; reject changing headers or unterminated data."""
    header = memory.read(address, 24)
    length, capacity = struct.unpack_from('<II', header, 16)
    if not 0 < length <= limit or length > capacity or capacity > 65535:
        raise ValueError('当前回放文件信息的字符串布局无效。')
    if capacity < 16:
        if capacity != 15:
            raise ValueError('当前回放文件信息的短字符串布局无效。')
        data = header[:length + 1]
    else:
        pointer = struct.unpack_from('<I', header)[0]
        if not 0x10000 <= pointer <= 0xFFFFFFFF - length:
            raise ValueError('当前回放文件信息的字符串地址无效。')
        data = memory.read(pointer, length + 1)
        if memory.read(pointer, length + 1) != data:
            raise ValueError('回放文件信息正在变化，请重新连接。')
    if data[-1:] != b'\0' or b'\0' in data[:-1] or memory.read(address, 24) != header:
        raise ValueError('回放文件信息读取不一致，请重新连接。')
    return data[:-1].decode('utf-8')


def runtime_replay_source(session):
    if not supports_runtime_source(session):
        raise ValueError('当前构建尚未适配游戏内回放文件读取。')
    session._guard()
    memory, player, profile = session.memory, session.objects.player, session.profile
    pair_address = player + profile.replay_file_source_offset
    pair = memory.read(pair_address, 8)
    source, holder = struct.unpack('<II', pair)
    if not 0x10000 <= holder <= 0xFFFFFFF0 or source != holder + 12:
        raise ValueError('当前回放文件的持有关系无效。')
    holder_type = session.live(profile.replay_file_holder_vft)
    if memory.u32(holder) != holder_type:
        raise ValueError('当前回放文件的对象类型未匹配。')
    header = memory.read(source, 0x50)
    metadata = struct.unpack_from('<I', header, 0x4C)[0]
    file_type = session.live(profile.replay_file_vft)
    if not metadata or memory.u32(player + 0xA0) != metadata or memory.u32(metadata) != file_type:
        raise ValueError('当前回放文件与播放对象的引用不一致。')
    path = Path(_string(memory, source, 32768))
    if not path.is_absolute() or path.suffix.lower() != '.wotbreplay' or any(ord(c) < 32 for c in str(path)):
        raise ValueError('游戏当前回放文件的路径无效。')
    # The embedded owner keeps the running client's build tag while the archive
    # object records the file's own version. Cross-region or older replays (for
    # example a "11.21.0_china" file on a 11.21.0 client) legitimately differ;
    # only the archive key must agree between the two objects.
    client_version = _string(memory, source + 0x1C, 64)
    key = _string(memory, source + 0x34, 32)
    version = _string(memory, metadata + 0xC, 64)
    if (not re.fullmatch(r'[0-9A-Fa-f]{32}', key) or
            _string(memory, metadata + 0x24, 32) != key):
        raise ValueError('当前回放文件的信息与播放对象不一致。')
    session._guard()
    if (memory.read(pair_address, 8) != pair or memory.read(source, 0x50) != header or
            memory.u32(holder) != holder_type or memory.u32(metadata) != file_type or
            memory.u32(player + 0xA0) != metadata):
        raise ValueError('游戏正在切换回放文件，请稳定后重新连接。')
    return ReplaySource(path.resolve(), player, source, holder, metadata, version, key, client_version)
