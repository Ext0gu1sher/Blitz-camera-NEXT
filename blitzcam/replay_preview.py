"""Offline-only replay source and local client asset cache. Never opens a process.

Packet payload decoding runs in the bundled, pinned Agent WASM in a Web Worker.
This module reads the client clock origin from record headers, registers exactly
one chosen file and prepares only its map/vehicles.
All generated content lives under OUTPUT, never inside the Steam installation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4
import zipfile

from .paths import OUTPUT
from .replay_timeline import file_timeline
from .replay_clock import replay_origin

PIPELINE_VERSION = 'preview-2-culling'
MAX_REPLAY_BYTES = 64 * 1024 * 1024


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay_metadata(path):
    info = file_timeline(path)
    p = Path(info['replay_file'])
    if p.stat().st_size > MAX_REPLAY_BYTES:
        raise ValueError('预览回放文件超过 64 MB 上限。')
    with zipfile.ZipFile(p) as z:
        # Bound all uncompressed data before handing the ZIP to WASM.
        if sum(e.file_size for e in z.infolist()) > 256 * 1024 * 1024:
            raise ValueError('回放解压大小超过预览上限。')
        meta = json.loads(z.read('meta.json').decode('utf-8-sig'))
        origin=replay_origin(z)
    return {**info, 'sha256': info['replay_sha256'], 'map_key': meta.get('mapName'), 'replay_origin_sec':origin,
            'bytes': p.stat().st_size}


def heightmap_corner_bytes(raw):
    """Agent map_assets::parse_heightmap, layout 2. Not a simple image flip."""
    import struct
    from array import array
    import sys
    if len(raw) < 8:
        raise ValueError('高度图头不完整。')
    n, tile = struct.unpack_from('<II', raw)
    if n != 512 or tile != 16 or len(raw) != 8 + n*n*2:
        raise ValueError('地图高度图布局尚未适配（需要 512/16）。')
    source = array('H'); source.frombytes(raw[8:])
    if sys.byteorder != 'little': source.byteswap()
    grid = array('H', [0]) * (n*n)
    cursor = 0
    for by in range(n//tile):
        for bx in range(n//tile):
            for ly in range(tile):
                dest = (by*tile+ly)*n+bx*tile
                grid[dest:dest+tile] = source[cursor:cursor+tile]
                cursor += tile
    result = array('H', (grid[r*n+min(n-c, n-1)] for r in range(n) for c in range(n)))
    if sys.byteorder != 'little': result.byteswap()
    return result.tobytes()


class ReplayPreview:
    def __init__(self, cache=None, client_locator=None):
        self.cache = Path(cache or OUTPUT/'replay-preview-cache')
        self.client_locator = client_locator
        self.lock = threading.RLock()
        self.build_lock = threading.Lock()
        self.cancel = threading.Event()
        self.source = None
        self.assets = {}  # opaque URL ids -> exact registered paths, no general file server
        self.status = {'state': 'empty', 'message': '载入本地回放，在离线场景中设计镜头。'}
        self.generation = 0
        self.thread = None

    def snapshot(self):
        with self.lock:
            return deepcopy({**self.status, 'source': self.source})

    def select(self, path):
        info = replay_metadata(path)
        with self.lock:
            self.generation += 1
            self.source = {**info, 'id': uuid4().hex}
            self.assets = {}
            self.status = {'state': 'selected', 'message': '回放已载入，准备解析。'}
            return self.snapshot()

    def replay_bytes(self, identity):
        with self.lock:
            if not self.source or identity != self.source['id']:
                raise ValueError('预览回放已经更换，请重新载入。')
            path, expected = Path(self.source['replay_file']), self.source['sha256']
        data = path.read_bytes()
        if len(data) > MAX_REPLAY_BYTES or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('回放文件已变化，请重新载入。')
        return data

    def asset_path(self, identity):
        with self.lock:
            if identity not in self.assets:
                raise ValueError('预览资源不存在或属于旧回放。')
            return self.assets[identity]

    def prepare(self, identity, map_id, tank_ids):
        if type(map_id) is not int or not 0 < map_id < 10000:
            raise ValueError('解析得到的地图编号无效。')
        if not isinstance(tank_ids, list) or len(tank_ids) > 64 or any(type(x) is not int or not 0 < x < 2**24 for x in tank_ids):
            raise ValueError('解析得到的车辆列表无效。')
        with self.lock:
            if not self.source or identity != self.source['id']:
                raise ValueError('预览回放已经更换。')
            if self.thread and self.thread.is_alive() and self.status['state'] == 'preparing':
                raise ValueError('正在准备场景，请稍候再载入。')
            gen, source = self.generation, deepcopy(self.source)
            self.status = {'state': 'preparing', 'message': '正在读取 Steam 客户端资源…', 'progress': 0}
            self.thread = threading.Thread(target=self._prepare, args=(gen, source, map_id, sorted(set(tank_ids))), daemon=True)
            self.thread.start()

    def _publish(self, gen, **values):
        with self.lock:
            if gen != self.generation or self.cancel.is_set():
                return False
            self.status.update(values)
            return True

    def _prepare(self, gen, source, map_id, tank_ids):
        # Local exporters have shared module caches. Serialize conversions while
        # allowing replacement requests to cancel/queue without poisoning UI.
        with self.build_lock:
            if not self._publish(gen, message='正在准备本地场景…'): return
            self._build(gen, source, map_id, tank_ids)

    def _build(self, gen, source, map_id, tank_ids):
        try:
            from .preview_assets import AssetBuilder
            from .replay_launcher import locate_client
            executable = Path((self.client_locator or locate_client)())
            builder = AssetBuilder(executable, self.cache)
            def progress(message, fraction):
                if not self._publish(gen, message=message, progress=fraction):
                    raise InterruptedError('已取消旧回放的场景准备。')
            manifest, files = builder.build(map_id, source['map_key'], tank_ids, progress)
            with self.lock:
                if gen != self.generation or self.cancel.is_set(): return
                self.assets = {}
                for key, path in files.items():
                    token = uuid4().hex + Path(path).suffix
                    self.assets[token] = Path(path)
                    manifest['urls'][key] = '/api/preview/asset/' + token
                self.status = {'state': 'ready', 'progress': 1, 'message': '离线场景已准备。',
                               'manifest': manifest}
        except InterruptedError:
            pass
        except Exception as exc:
            self._publish(gen, state='error', message=f'离线预览准备失败：{exc}')

    def close(self):
        self.cancel.set()
        with self.lock:
            self.generation += 1
