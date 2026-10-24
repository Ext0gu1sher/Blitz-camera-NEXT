"""Local conversion adapter around reviewed, pinned Agent exporters (MIT).

No downloaded geometry and no client modifications. NumPy/Pillow/imagecodecs
are isolated asset-conversion dependencies, included in the desktop package.
"""
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys

from .project import atomic_json
from .replay_preview import PIPELINE_VERSION, heightmap_corner_bytes, sha

VENDOR = Path(__file__).with_name('preview_vendor')
RUNTIME = Path(__file__).with_name('preview_runtime')


def dependencies():
    # Exporters use sibling imports; enter this path only when preparing assets.
    for p in (RUNTIME, VENDOR, VENDOR/'wotbtools'):
        if str(p) not in sys.path: sys.path.insert(0, str(p))
    import export_map_glb
    import export_tank_glb
    return export_map_glb, export_tank_glb


def fields(raw):
    """Bounded protobuf wire reader, schema from pinned blitzkit.rs."""
    pos = 0
    def varint():
        nonlocal pos
        value = 0
        for shift in range(0, 70, 7):
            if pos >= len(raw): raise ValueError('车辆元数据截断。')
            b = raw[pos]; pos += 1; value |= (b & 127) << shift
            if b < 128: return value
        raise ValueError('车辆元数据 varint 无效。')
    while pos < len(raw):
        tag = varint(); f, w = tag >> 3, tag & 7
        if w == 0: value = varint()
        elif w in (1, 2, 5):
            n = varint() if w == 2 else (8 if w == 1 else 4)
            if pos+n > len(raw): raise ValueError('车辆元数据字段越界。')
            value = raw[pos:pos+n]; pos += n
        else: raise ValueError('不支持的车辆元数据 wire。')
        yield f, w, value


def one(raw, f, w, default=None):
    return next((v for fn, wt, v in fields(raw) if (fn, wt) == (f, w)), default)


def vec(raw):
    if raw is None: return None
    v = [0., 0., 0.]
    for f, w, b in fields(raw):
        if w == 5 and 1 <= f <= 3: v[f-1] = struct.unpack('<f', b)[0]
    return [v[0], v[2], v[1]]  # same correctZY as tank_configs.rs


def pitch_range(raw):
    """GunModelDefinition.pitch -> Agent GunPitchRange (degrees, including sectors)."""
    if raw is None: return None
    number = lambda data, f: struct.unpack('<f', one(data, f, 5, b'\0'*4))[0]
    result = {'dep':number(raw, 2), 'ele':-number(raw, 1)}
    for field, name in ((3, 'front'), (4, 'back')):
        sector = one(raw, field, 2)
        if sector is not None:
            result[name] = {key:number(sector, i) for i,key in enumerate(('min','max','range'),1)}
    if one(raw, 5, 5) is not None: result['transition'] = number(raw, 5)
    values = [v for value in result.values() for v in (value.values() if isinstance(value,dict) else [value])]
    if not all(math.isfinite(v) for v in values): return None
    return result


def model_metadata(tank_id):
    content = None
    for f, w, b in fields((VENDOR/'data/models.pb').read_bytes()):
        if (f, w) == (1, 2) and one(b, 1, 0) == tank_id:
            content = one(b, 2, 2); break
    if content is None: return None
    track = None
    # Top track is the final tanks.pb TrackDefinition (field 22), not map order.
    tanks_content = None
    for f, w, b in fields((VENDOR/'data/tanks.pb').read_bytes()):
        if (f, w) == (1, 2) and one(b, 1, 0) == tank_id:
            tanks_content = one(b, 2, 2); break
    track_ids = [one(b, 1, 0) for f, w, b in fields(tanks_content or b'') if (f, w) == (22, 2)]
    tracks = {}
    for f, w, b in fields(content):
        if (f, w) == (5, 2):
            payload = one(b, 2, 2, b'')
            tracks[one(b, 1, 0)] = vec(one(payload, 2, 2, b''))
    if track_ids: track = tracks.get(track_ids[-1])
    turret_origin = vec(one(content, 2, 2))
    itr_raw = one(content, 3, 2)
    itr = None if itr_raw is None else {name:struct.unpack('<f', one(itr_raw, i, 5, b'\0'*4))[0] for i,name in enumerate(('yaw','pitch','roll'),1)}
    configs = []
    for f, w, b in fields(content):
        if (f, w) != (4, 2): continue
        turret_module, data = one(b, 1, 0), one(b, 2, 2, b'')
        for gf, gw, gb in fields(data):
            if (gf, gw) != (5, 2): continue
            gun_module, gun = one(gb, 1, 0), one(gb, 2, 2, b'')
            configs.append({'turret_local':turret_module >> 8, 'gun_local':gun_module >> 8,
                            'turret_node':one(data, 3, 0, 0), 'gun_node':one(gun, 3, 0, 0),
                            'gun_origin':vec(one(data, 4, 2, b'')),
                            'pitch_limits':pitch_range(one(gun, 4, 2))})
    return {'model_origins':{'track':track,'turret':turret_origin}, 'initial_turret_rotation':itr, 'configs':configs}


def playback_pitch_limits(vehicles):
    """Resolve replay-mounted modules before the second WASM playback parse.

    Read pinned metadata directly, so existing GLB caches need no regeneration.
    Ambiguous/missing modules stay explicitly unanchored instead of using another
    gun's range. This is the same selection policy as the preview model rig.
    """
    if not isinstance(vehicles, list) or len(vehicles) > 64:
        raise ValueError('预览车辆名单无效。')
    limits, anchored, missing, metadata = {}, [], [], {}
    for vehicle in vehicles:
        if (not isinstance(vehicle, dict) or
                any(type(vehicle.get(key)) is not int or vehicle[key] < 0
                    for key in ('eid','tank_id')) or
                any(vehicle.get(key) is not None and (type(vehicle[key]) is not int or vehicle[key] < 0)
                    for key in ('turret_local','gun_local')) or
                not isinstance(vehicle.get('nickname'), str) or len(vehicle['nickname']) > 256):
            raise ValueError('预览车辆配置无效。')
        tid = vehicle['tank_id']
        if tid not in metadata: metadata[tid] = model_metadata(tid)
        configs = (metadata[tid] or {}).get('configs', [])
        matches = [c for c in configs if (c['turret_local'], c['gun_local']) ==
                   (vehicle.get('turret_local'), vehicle.get('gun_local'))]
        cfg = matches[-1] if matches else (configs[0] if len(configs) == 1 else None)
        limit = cfg.get('pitch_limits') if cfg else None
        if limit is not None and vehicle['nickname']:
            limits[vehicle['nickname']] = limit
            anchored.append(vehicle['eid'])
        else:
            missing.append(vehicle['eid'])
    return {'limits':limits, 'anchored':anchored, 'missing':missing}


class AssetBuilder:
    def __init__(self, executable, cache):
        self.executable, self.cache = Path(executable), Path(cache)
        self.data = self.executable.parent/'Data'
        if not self.data.is_dir(): raise ValueError('Steam 客户端 Data 目录不存在。')

    def build(self, map_id, expected_key, tank_ids, progress):
        maps, tanks = dependencies()
        entry = next((e for e in maps.load_registry(self.data) if e.map_id == map_id), None)
        if entry is None: raise ValueError(f'本机客户端未注册地图 {map_id}。')
        if not isinstance(expected_key, str) or entry.key.casefold() != expected_key.casefold():
            raise ValueError('回放地图代号与本机地图注册表不一致。')
        game_hash = sha(self.executable)
        progress('正在核对本机资源缓存…', .02)
        # Client updates and local resource replacements must not reuse a cache
        # solely because wotblitz.exe stayed the same. Inventory both resource
        # layers; no resource is modified. Hashing all geometry bytes on every
        # open is unnecessary, so this cache freshness key uses path/size/mtime.
        inventory = hashlib.sha256()
        for folder in (self.data, self.executable.parent/'packs'):
            if not folder.is_dir(): continue
            for p in sorted(folder.rglob('*')):
                if p.is_file():
                    stat=p.stat()
                    inventory.update(f'{p.relative_to(self.executable.parent).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}\n'.encode('utf-8'))
        identity = hashlib.sha256((PIPELINE_VERSION+game_hash+inventory.hexdigest()+sha(self.data/'maps.yaml.dvpl')+
                                   sha(VENDOR/'data/tanks.pb')+sha(VENDOR/'data/models.pb')).encode()).hexdigest()[:24]
        root = self.cache/identity
        directory = root/'maps'/entry.space
        marker = directory/'complete.json'
        if not marker.exists():
            directory.mkdir(parents=True, exist_ok=True)
            progress(f'正在转换地图 {entry.display}，首次载入需要一些时间…', .05)
            result = maps.export_map(self.data, entry, directory)
            meta = result['meta']
            height_path = self.data/'3d/Maps'/entry.space/(meta['heightmap']+'.dvpl')
            raw = maps.load_payload(height_path)
            binary = heightmap_corner_bytes(raw)
            (directory/'terrain.u16.bin').write_bytes(binary)
            bounds = meta['worldBounds']; lo, hi = bounds['min'], bounds['max']
            if abs(lo[0]+hi[0])+abs(lo[1]+hi[1])+abs((hi[0]-lo[0])-(hi[1]-lo[1])) > 1e-5:
                raise ValueError('当前预览需要居中的正方形地形边界。')
            terrain = {'size':512,'terrainLayout':2,'span':hi[0]-lo[0], 'zmin':lo[2], 'zmax':hi[2],
                       'worldBounds':bounds,'terrainBinSha256':hashlib.sha256(binary).hexdigest()}
            atomic_json(directory/'terrain.json', terrain)
            atomic_json(marker, {'map':meta, 'client_sha256':game_hash,
                         'source_scene_sha256':sha(maps.find_member(self.data/'3d/Maps'/entry.space,entry.space,'.sc2.dvpl')),
                         'heightmap_sha256':sha(height_path), 'pipeline':PIPELINE_VERSION})
        meta = json.loads(marker.read_text(encoding='utf-8'))['map']
        files = {'scenery':directory/(entry.space+'.glb'), 'terrain':directory/'terrain.u16.bin',
                 'terrainMeta':directory/'terrain.json', 'ground':directory/(entry.space+'.ground.webp')}
        layer_meta = directory/(entry.space+'.ground.layers.json')
        if layer_meta.exists():
            files['groundLayers'] = layer_meta
            for p in directory.glob(entry.space+'.ground.*.webp'):
                files['ground/'+p.name.split('.ground.',1)[1].removesuffix('.webp')] = p
        table = tanks.read_tank_table(VENDOR/'data/tanks.pb')
        vehicles, missing = {}, []
        for i, tid in enumerate(tank_ids):
            progress(f'正在准备车辆 {i+1}/{len(tank_ids)} · {tid}', .3+.65*i/max(1,len(tank_ids)))
            folder = root/'vehicles'/str(tid)
            if tid not in table:
                missing.append({'tank_id':tid,'reason':'车型不在当前元数据表中'}); continue
            tm = table[tid]
            if not (folder/'complete.json').exists():
                result = tanks.export_tank(self.data, tid, tm['nation'], tm['stem'], root/'vehicles', max_tex=1024)
                if 'error' in result:
                    missing.append({'tank_id':tid,'reason':result['error']}); continue
                atomic_json(folder/'rig.json', model_metadata(tid))
                atomic_json(folder/'complete.json', result)
            files[f'vehicle/{tid}'] = folder/'model.glb'
            files[f'rig/{tid}'] = folder/'rig.json'
            vehicles[str(tid)] = {'name':tm['stem']}
        manifest = {'pipeline':PIPELINE_VERSION, 'map':meta,'vehicles':vehicles, 'missing':missing,
                    'client_sha256':game_hash,'urls':{},
                    'limitations':['场景用于镜头设计；材质、植被、光照不等同于游戏画面。',
                                   '只显示回放中有位置记录的车辆，不补造隐藏车辆。',
                                   '炮火、命中及击毁效果按回放记录重建；缺少命中证据时不补造弹着结果。',
                                   '暂不重建悬挂和可破坏物状态。']}
        return manifest, files
