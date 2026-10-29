"""Read replay ZIP metadata and corroborate its map with the active scene.

Never infer the running replay from the newest file in a directory.
No replay payload decoding, process writes, hooks, or game input.
"""
import json
from pathlib import Path
import re
import struct
import zipfile

from .profile import CameraError
from .replay_source import runtime_replay_source


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
            result['message'] = '回放文件与当前场景不同，已按当前场景选图。'
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
                try:
                    source = runtime_replay_source(session)
                    metadata = replay_metadata(source.path)
                    if runtime_replay_source(session) != source:
                        raise ValueError('读取期间当前回放文件已变化。')
                    self.metadata = metadata
                except (OSError, ValueError, AttributeError, CameraError, zipfile.BadZipFile): pass
            resource = scene_resource(session)
            if resource != self.previous:
                self.result = match_map(resource, self.metadata, self.terrain.catalog())
                self.previous = resource
            return self.result
        except (OSError, ValueError, AttributeError, CameraError, KeyError, TypeError) as exc:
            self.previous = None
            return {'state':'unavailable', 'message':str(exc)}
