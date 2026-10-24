import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from blitzcam.terrain import TerrainStore


class TerrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root/'cache'; self.cache.mkdir()
        self.maps = self.root/'maps'
        sources = []
        for name in ('11_plant_pn.sc2.dvpl', 'landscape/height_test.heightmap.dvpl'):
            p = self.maps/'11_plant_pn'/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(name.encode())
            sources.append({'relative_path': name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
        self.data = {'schema':1, 'map_id':'11_plant_pn', 'coordinate_space':'scene_world_z_up',
                     'size':2, 'rows':[[10,20],[30,40]], 'bounds':{'min':[-300,-300,0], 'max':[300,300,80]}, 'sources':sources}
        self.store = TerrainStore(self.cache, self.maps)
        self.write(self.data)

    def tearDown(self): self.tmp.cleanup()

    def write(self, data): (self.cache/'11_plant_pn.json').write_text(json.dumps(data), encoding='utf8')

    def test_load_does_not_change_assets_and_rejects_client_update(self):
        self.assertEqual(self.store.load('11_plant_pn'), self.data)
        p = self.maps/'11_plant_pn/11_plant_pn.sc2.dvpl'; p.write_bytes(b'new client')
        with self.assertRaisesRegex(ValueError, '已更新'): self.store.load('11_plant_pn')
        self.assertEqual(p.read_bytes(), b'new client')

    def test_arbitrary_paths_and_bad_height_data_are_rejected(self):
        for map_id in ('../project', 'other_map', '', r'..\11_plant_pn'):
            with self.assertRaises(ValueError): self.store.load(map_id)
        for update in ({'size':True}, {'rows':[[10,20],[30,float('nan')]]}, {'rows':[[10,20],[30,81]]},
                       {'bounds':{'min':[0,0,0],'max':[0,300,80]}}, {'sources':[{'relative_path':'../secret'}]}):
            self.write({**copy.deepcopy(self.data), **update})
            with self.assertRaises(ValueError): self.store.load('11_plant_pn')

    def test_missing_or_malformed_cache_does_not_fallback_to_wrong_map(self):
        p = self.cache/'11_plant_pn.json'; p.unlink()
        with self.assertRaisesRegex(ValueError, '未生成'): self.store.load('11_plant_pn')
        p.write_text('{}')
        with self.assertRaises(ValueError): self.store.load('11_plant_pn')


if __name__ == '__main__': unittest.main()
