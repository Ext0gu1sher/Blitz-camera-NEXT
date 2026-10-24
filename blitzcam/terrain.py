"""Read locally built terrain caches. This module never writes or opens a process."""
import hashlib
import json
import math
import re
from pathlib import Path
import threading
from .paths import OUTPUT

ROOT = Path(__file__).resolve().parents[1]
MAPS = Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\Data\3d\Maps')


class TerrainStore:
    def __init__(self, cache=OUTPUT/'map-cache', maps=MAPS):
        self.cache, self.maps = Path(cache), Path(maps)
        self.lock = threading.Lock()

    def catalog(self):
        path = self.cache/'catalog.json'
        if not path.exists():
            from tools.map_preview_assets import catalog
            return catalog(self.maps, self.cache)
        data = json.loads(path.read_text(encoding='utf8'))
        source = self.maps.parents[1]/'maps.yaml.dvpl'
        if hashlib.sha256(source.read_bytes()).hexdigest() != data['source_sha256']:
            raise ValueError('地图目录已更新，请重新生成预览目录。')
        return data

    def load(self, map_id):
        if not re.fullmatch(r'[A-Za-z0-9_]{1,80}', map_id) or not (self.maps/map_id).is_dir():
            raise ValueError('地图 ID 无效或本地未安装该地图。')
        with self.lock:
            path = self.cache/(map_id+'.json')
            if not path.exists():
                try:
                    from tools.map_preview_assets import build
                    build(map_id, self.maps, self.cache)
                except (OSError, ValueError, ImportError) as exc:
                    raise ValueError('地图预览未生成：'+str(exc)) from exc
            if path.stat().st_size > 2*1024*1024:
                raise ValueError('地图预览缓存过大。')
            data = json.loads(path.read_text(encoding='utf8'))
            if data.get('schema') != 1 or data.get('map_id') != map_id or data.get('coordinate_space') != 'scene_world_z_up':
                raise ValueError('地形缓存格式不匹配。')
            size, rows = data.get('size'), data.get('rows')
            if type(size) is not int or not 2 <= size <= 129 or not isinstance(rows, list) or len(rows) != size:
                raise ValueError('地形网格大小无效。')
            bounds = data.get('bounds', {})
            lo, hi = bounds.get('min', []), bounds.get('max', [])
            finite = lambda v: type(v) in (int, float) and math.isfinite(v)
            if len(lo) != 3 or len(hi) != 3 or not all(finite(v) for v in lo+hi) or not all(a < b for a, b in zip(lo, hi)):
                raise ValueError('地形坐标范围无效。')
            if any(not isinstance(row, list) or len(row) != size or any(not finite(z) or not lo[2] <= z <= hi[2] for z in row) for row in rows):
                raise ValueError('地形高度数据无效。')
            sources = data.get('sources', [])
            if not isinstance(sources, list) or not 2 <= len(sources) <= 3 or not all(isinstance(s, dict) for s in sources):
                raise ValueError('地形来源不完整。')
            mandatory = [s.get('relative_path') for s in sources if s.get('scope','maps') == 'maps']
            if len(mandatory) != 2 or map_id+'.sc2.dvpl' not in mandatory or not any(re.fullmatch(r'landscape/[A-Za-z0-9_.]+\.heightmap\.dvpl',str(p)) for p in mandatory):
                raise ValueError('地形来源不完整。')
            for source in sources:
                name, scope = source['relative_path'], source.get('scope','maps')
                if scope == 'maps' and (name == map_id+'.sc2.dvpl' or re.fullmatch(r'landscape/[A-Za-z0-9_.]+\.heightmap\.dvpl',name)):
                    resource = self.maps/map_id/name
                elif scope == 'data' and re.fullmatch(r'Gfx/UI/BattleScreenHUD/minimap/[A-Za-z0-9_]+/MiniMapSmall@2x\.packed\.webp\.dvpl',name):
                    resource = self.maps.parents[1]/name
                else: raise ValueError('地图资源路径无效。')
                if not resource.exists() or resource.stat().st_size > 128*1024*1024 or hashlib.sha256(resource.read_bytes()).hexdigest() != source['sha256']:
                    raise ValueError('地图资源已更新或不存在，地形预览已停用；请重新核对并生成缓存。')
            return data
