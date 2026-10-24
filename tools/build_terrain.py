"""Build a local terrain preview cache, reading client assets without changing them.

Run: python -m tools.build_terrain
Only the inspected plant asset hashes/layout are accepted in this first adapter.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

from research.scripts.inspect_map_assets import MAPS, decode, heights
from research.scripts.scene_archive import scene, walk

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    '11_plant_pn.sc2.dvpl': '3c45601ce160a8aa57f27bf128753f4557e314b652b2d9ee18b7a1cd36746ace',
    'landscape/height_test.heightmap.dvpl': '8098bf4cb3ff9bbfd686e2c3c544d8b307d14a453de366eafd00c9e0805bd023',
}


def build(folder=MAPS/'11_plant_pn'):
    assets = {}; sources = []
    for name, digest in EXPECTED.items():
        raw = (folder/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Map assets changed; inspect their layout before rebuilding')
        assets[name], evidence = decode(folder/name)
        sources.append({'relative_path': name, 'sha256': digest, 'decoded_size': len(assets[name])})
    root = scene(assets['11_plant_pn.sc2.dvpl'])
    matches = [(path, value) for path, value in walk(root) if 'hmap' in value]
    if len(matches) != 1:
        raise ValueError('Expected exactly one landscape')
    path, landscape = matches[0]
    if path[:2] != ('#hierarchy', 32) or len(path) != 5:
        raise ValueError('Landscape entity hierarchy changed')
    entity = root['#hierarchy'][path[1]]
    transform, = [c for c in entity['components'].values() if isinstance(c, dict) and c.get('comp.typename') == 'TransformComponent']
    # This adapter deliberately rejects translated/rotated/scaled or nested terrain.
    expected = {'Rotation': (0., 0., 0., 1.), 'Scale': (1., 1., 1.), 'Translation': (0., 0., 0.)}
    for space in ('local', 'world'):
        for kind, value in expected.items():
            if tuple(transform['tc.'+space+kind]) != value:
                raise ValueError('Nonidentity terrain transform needs an explicit adapter')
    bbox = list(struct.unpack('<6f', landscape['bbox']))
    if bbox != [-300., -300., 0., 300., 300., 80.] or landscape['hmap'] != 'landscape/height_test.heightmap':
        raise ValueError('Landscape bounds/reference changed')
    size, tile, rows = heights(assets['landscape/height_test.heightmap.dvpl'])
    # DAVA Heightmap::GetPoint uses x/size, y/size and raw/65535; the last
    # boundary uses the clamped final sample. No centering, Y flip or Z gain.
    step = 8
    grid = [min(i, size-1) for i in range(0, size+1, step)]
    output_rows = [[round(bbox[2]+rows[y][x]/65535*(bbox[5]-bbox[2]), 5) for x in grid] for y in grid]
    probes = [{'grid': [x, y], 'raw': rows[y][x], 'position': [bbox[0]+x/size*600, bbox[1]+y/size*600, rows[y][x]/65535*80]}
              for x, y in ((0, 0), (256, 256), (511, 511))]
    return {'schema': 1, 'map_id': '11_plant_pn', 'label': 'plant', 'client_version': '11.21.0.1235',
            'coordinate_space': 'scene_world_z_up', 'bounds': {'min': bbox[:3], 'max': bbox[3:]},
            'size': len(grid), 'rows': output_rows, 'source_resolution': size, 'sample_spacing': 600*step/size,
            'sources': sources, 'built_at_utc': datetime.now(timezone.utc).isoformat(),
            'validation': {'asset_transform_verified': True, 'visual_alignment_verified': False,
                           'replay_map_automatically_identified': False, 'buildings_included': False},
            'evidence': {'landscape_archive_offset': landscape.offset, 'entity_root_index': path[1],
                         'local_and_world_transform': transform, 'height_tile': tile, 'height_probes': probes,
                         'mapping_reference': 'https://github.com/smile4u/dava.engine/blob/master/Sources/Internal/Render/Highlevel/Heightmap.h'}}


def main():
    result = build()
    path = ROOT/'output/map-cache/11_plant_pn.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf8')
    print(json.dumps({'path': str(path), 'size': result['size'], 'bounds': result['bounds'], 'validation': result['validation']}, ensure_ascii=False))


if __name__ == '__main__': main()
