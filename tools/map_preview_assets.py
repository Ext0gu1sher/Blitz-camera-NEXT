"""Local asset conversion; all writes go to the workstation cache, never the client."""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct

from research.scripts.inspect_map_assets import MAPS, decode, heights
from research.scripts.scene_archive import scene, walk

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/'output/map-cache'


def catalog(maps=MAPS, cache=CACHE):
    import yaml
    source = maps.parents[1]/'maps.yaml.dvpl'
    payload, evidence = decode(source)
    config = yaml.safe_load(payload)
    # Current file has a top-level maps dictionary; accept no guessed paths.
    entries = config.get('maps', config)
    result = []
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not re.fullmatch(r'[A-Za-z0-9_]+', name): continue
        local = entry.get('localName', '')
        match = re.fullmatch(r'([A-Za-z0-9_]+)/\1\.sc2', local)
        if not match or type(entry.get('id')) is not int: continue
        result.append({'map_name':name, 'map_number':entry['id'], 'map_id':match[1], 'scene_resource':'~res:/3d/Maps/'+local})
    if not result: raise ValueError('地图目录格式未适配。')
    output = {'maps': result, 'source_sha256': evidence['sha256']}
    cache.mkdir(parents=True, exist_ok=True)
    (cache/'catalog.json').write_text(json.dumps(output, ensure_ascii=False), encoding='utf8')
    return output


def build(map_id, maps=MAPS, cache=CACHE):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,80}', map_id): raise ValueError('无效地图 ID。')
    directory = catalog(maps, cache)
    entry, = [e for e in directory['maps'] if e['map_id'] == map_id]
    folder = maps/map_id
    data, scene_evidence = decode(folder/(map_id+'.sc2.dvpl'))
    root = scene(data)
    matches = [(p, a) for p, a in walk(root) if 'hmap' in a]
    if len(matches) != 1: raise ValueError('地图没有唯一地形，无法生成预览。')
    path, landscape = matches[0]
    if len(path) != 5 or path[0] != '#hierarchy': raise ValueError('嵌套地形变换尚未适配。')
    entity = root['#hierarchy'][path[1]]
    transform, = [c for c in entity['components'].values() if isinstance(c, dict) and c.get('comp.typename') == 'TransformComponent']
    for space in ('local', 'world'):
        for kind, value in {'Rotation':(0,0,0,1), 'Scale':(1,1,1), 'Translation':(0,0,0)}.items():
            if tuple(transform['tc.'+space+kind]) != value: raise ValueError('地形变换不是单位变换，停止预览转换。')
    bbox = list(struct.unpack('<6f', landscape['bbox']))
    if not all(math.isfinite(v) for v in bbox) or not all(bbox[i] < bbox[i+3] for i in range(3)): raise ValueError('地形范围无效。')
    relative = landscape['hmap']+'.dvpl'
    if not re.fullmatch(r'landscape/[A-Za-z0-9_.]+\.heightmap\.dvpl', relative): raise ValueError('高度图路径尚未适配。')
    raw, height_evidence = decode(folder/relative)
    size, tile, rows = heights(raw)
    if size < 64 or size%64: raise ValueError('高度图分辨率尚未适配。')
    grid = [min(i*size//64, size-1) for i in range(65)]
    z = lambda raw: bbox[2]+raw/65535*(bbox[5]-bbox[2])
    output = {'schema':1, 'map_id':map_id, 'map_name':entry['map_name'], 'label':entry['map_name'],
              'coordinate_space':'scene_world_z_up', 'bounds':{'min':bbox[:3], 'max':bbox[3:]},
              'size':65, 'rows':[[round(z(rows[y][x]),5) for x in grid] for y in grid],
              'source_resolution':size, 'sample_spacing':(bbox[3]-bbox[0])/64,
              'built_at_utc':datetime.now(timezone.utc).isoformat(),
              'sources':[{'relative_path':map_id+'.sc2.dvpl','sha256':scene_evidence['sha256']}, {'relative_path':relative,'sha256':height_evidence['sha256']}],
              'validation':{'asset_transform_verified':True, 'visual_alignment_verified':False, 'buildings_included':False},
              'evidence':{'landscape_archive_offset':landscape.offset, 'entity_root_index':path[1], 'local_and_world_transform':transform,
                          'height_tile':tile, 'map_catalog_sha256':directory['source_sha256']}}
    from PIL import Image
    texture_relative = 'Gfx/UI/BattleScreenHUD/minimap/'+entry['map_name']+'/MiniMapSmall@2x.packed.webp.dvpl'
    texture, image_evidence = decode(maps.parents[1]/texture_relative)
    image = Image.open(io.BytesIO(texture)).convert('RGB')
    if image.size != (512,512): raise ValueError('小地图尺寸尚未适配。')
    output['map_image'] = 'data:image/webp;base64,'+base64.b64encode(texture).decode('ascii')
    output['colors'] = [[list(image.getpixel((min(511,round(x/64*511)),min(511,round(y/64*511))))) for x in range(65)] for y in range(65)]
    output['sources'].append({'scope':'data','relative_path':texture_relative,'sha256':image_evidence['sha256']})
    output['evidence']['texture_mapping'] = 'image u=(worldX-minX)/extentX; v=(worldY-minY)/extentY; landmark visual validation pending'
    cache.mkdir(parents=True, exist_ok=True)
    (cache/(map_id+'.json')).write_text(json.dumps(output, ensure_ascii=False, separators=(',',':')), encoding='utf8')
    return output
