"""Read replay ZIP metadata and corroborate its map with the active scene.

Never infer the running replay from the newest file in a directory.
No replay payload decoding, process writes, hooks, or game input.
"""
import ctypes as C
import json
from pathlib import Path
import re
import struct
import zipfile

from .profile import CameraError


def replay_metadata(path):
    path = Path(path)
    if path.suffix.lower() != '.wotbreplay' or not path.is_file():
        raise ValueError('未取得有效的回放文件路径。')
    with zipfile.ZipFile(path) as archive:
        infos = [i for i in archive.infolist() if i.filename == 'meta.json']
        if len(infos) != 1 or infos[0].file_size > 65536 or infos[0].flag_bits & 1:
            raise ValueError('回放元数据不存在、重复或超过读取上限。')
        with archive.open(infos[0]) as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('回放元数据超过读取上限。')
        meta = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(meta, dict) or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', str(meta.get('mapName', ''))) or type(meta.get('mapId')) is not int:
        raise ValueError('回放地图元数据无效。')
    return {'map_name': meta['mapName'], 'map_number': meta['mapId'], 'replay_file': str(path),
            'replay_version': str(meta.get('version', '')), 'arena_id': str(meta.get('arenaUniqueId', ''))}


def launch_arguments(memory):
    """Observed Windows WOW64 PEB32 layout; bounded and independently validated.

    Uses the existing QUERY_INFORMATION|VM_READ handle. Unsupported OS layout
    simply disables this source. No WMI subprocess or elevated handle needed.
    """
    handle = getattr(memory, 'handle', None)
    if type(handle) is not int or not 0 < handle < 1 << (8 * C.sizeof(C.c_void_p)):
        raise ValueError('进程读取句柄不可用。')
    nt = C.WinDLL('ntdll')
    query = nt.NtQueryInformationProcess
    query.argtypes = [C.c_void_p, C.c_uint, C.c_void_p, C.c_ulong, C.c_void_p]
    query.restype = C.c_long
    peb = C.c_size_t()
    if query(handle, 26, C.byref(peb), C.sizeof(peb), None) != 0 or not 0x10000 < peb.value < 0x100000000:
        raise ValueError('无法读取启动回放路径。')
    params = memory.u32(peb.value+0x10)
    header = memory.read(params+0x40, 8)
    length, capacity, address = struct.unpack('<HHI', header)
    if not 2 <= length <= capacity <= 32768 or length % 2:
        raise ValueError('进程参数布局未匹配。')
    command = memory.read(address, length).decode('utf-16le')
    if memory.read(params+0x40, 8) != header:
        raise ValueError('进程参数读取不一致。')
    shell = C.WinDLL('shell32'); kernel = C.WinDLL('kernel32')
    shell.CommandLineToArgvW.argtypes = [C.c_wchar_p, C.POINTER(C.c_int)]
    shell.CommandLineToArgvW.restype = C.POINTER(C.c_wchar_p)
    kernel.LocalFree.argtypes = [C.c_void_p]
    argc = C.c_int(); argv = shell.CommandLineToArgvW(command, C.byref(argc))
    if not argv:
        raise ValueError('无法解析启动参数。')
    try:
        args = [argv[i] for i in range(argc.value)]
    finally:
        kernel.LocalFree(argv)
    if not args or Path(args[0]).resolve() != memory.info.path.resolve():
        raise ValueError('进程启动参数身份不一致。')
    return args


def replay_path_from_arguments(args):
    # Some launchers repeat the same file. Repetition is not a second replay;
    # distinct files must still fail rather than arbitrarily choosing one.
    candidates = list(dict.fromkeys(Path(a).resolve() for a in args[1:]
                                   if a.lower().endswith('.wotbreplay')))
    if len(candidates) != 1:
        if not candidates:
            raise ValueError('运行中的游戏启动参数未包含回放文件。')
        raise ValueError(f'游戏启动参数包含 {len(candidates)} 个不同的回放文件，无法确定当前文件。')
    return candidates[0]


def launch_replay_path(memory):
    return replay_path_from_arguments(launch_arguments(memory))


def scene_resource(session):
    offset = getattr(session.profile, 'scene_path_offset', None)
    if offset is None:
        raise ValueError('当前构建尚未适配场景地图读取。')
    memory, scene = session.memory, session.objects.scene
    header = memory.read(scene+offset, 24)
    length, capacity = struct.unpack_from('<II', header, 16)
    if not 1 <= length <= 240 or not length <= capacity < 4096:
        raise ValueError('场景路径字符串布局无效。')
    address = scene+offset if capacity < 16 else struct.unpack_from('<I', header)[0]
    raw = memory.read(address, length+1)
    if raw[-1:] != b'\0' or memory.read(scene+offset, 24) != header:
        raise ValueError('场景路径读取不一致。')
    path = raw[:-1].decode('ascii')
    match = re.fullmatch(r'~res:/3d/Maps/([A-Za-z0-9_]+)/\1\.sc2', path)
    if not match:
        raise ValueError('场景路径不是已识别的地图资源。')
    # Independent entity FastName confirms this is the scene file, not a texture path.
    name_address = memory.u32(scene+0x1c)
    expected = (match[1]+'.sc2').encode()+b'\0'
    if memory.read(name_address, len(expected)) != expected:
        raise ValueError('场景名称与资源路径不一致。')
    return path


def match_map(resource, metadata, catalog):
    entries = [e for e in catalog['maps'] if e['scene_resource'] == resource]
    if len(entries) != 1:
        return {'state':'unavailable', 'message':'当前场景未在地图目录中匹配，未载入其他地图。'}
    entry = entries[0]
    result = {'state':'scene_only', 'map_id':entry['map_id'], 'map_name':entry['map_name'],
              'scene_resource':resource, 'message':'已识别当前场景；未取得可对应的回放文件。'}
    if metadata:
        if metadata['map_name'] == entry['map_name'] and metadata['map_number'] == entry['map_number']:
            result.update(metadata, state='matched', message='回放文件地图与当前场景一致。')
        else:
            result['message'] = '启动回放文件与当前场景不同，已按当前场景选图。'
    return result


class ReplayMapResolver:
    def __init__(self, terrain):
        self.terrain = terrain
        self.reset()

    def reset(self):
        self.session = None; self.metadata = None; self.previous = None; self.result = None

    def identify(self, session):
        try:
            if session is not self.session:
                self.reset(); self.session = session
                try: self.metadata = replay_metadata(launch_replay_path(session.memory))
                except (OSError, ValueError, AttributeError, CameraError, zipfile.BadZipFile): pass
            resource = scene_resource(session)
            if resource != self.previous:
                self.result = match_map(resource, self.metadata, self.terrain.catalog())
                self.previous = resource
            return self.result
        except (OSError, ValueError, AttributeError, CameraError, KeyError, TypeError) as exc:
            self.previous = None
            return {'state':'unavailable', 'message':str(exc)}
