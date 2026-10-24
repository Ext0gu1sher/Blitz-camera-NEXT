from pathlib import Path
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

from blitzcam.replay_preview import ReplayPreview, heightmap_corner_bytes
from blitzcam.preview_assets import model_metadata
from tests.fixtures.replay_data import replay_data


class PreviewTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required for preview pose validation')
    def test_pose_validation_preserves_smooth_curves_and_rejects_invalid_data(self):
        script=Path(__file__).parent/'fixtures/replay_pose_validation.mjs'
        result=subprocess.run(['node',str(script)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_selected_source_is_bound_to_full_content_hash_and_opaque_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.wotbreplay'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('meta.json',json.dumps({'battleDuration':45,'version':'11.21.0','mapName':'canal'}))
                z.writestr('data.wotreplay',replay_data())
            preview=ReplayPreview(Path(tmp)/'cache');source=preview.select(path)['source']
            self.assertEqual(source['replay_origin_sec'],4.25)
            self.assertEqual(preview.replay_bytes(source['id']),path.read_bytes())
            with self.assertRaises(ValueError):preview.replay_bytes('../sample.wotbreplay')
            with path.open('ab') as f:f.write(b'changed')
            with self.assertRaises(ValueError):preview.replay_bytes(source['id'])
            preview.close()

    def test_replacing_source_invalidates_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.wotbreplay'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('meta.json',json.dumps({'battleDuration':45,'version':'11.21.0','mapName':'canal'}))
                z.writestr('data.wotreplay',replay_data())
            preview=ReplayPreview(Path(tmp));first=preview.select(path)['source']['id']
            preview.assets['known']=path;preview.select(path)
            with self.assertRaises(ValueError):preview.asset_path('known')
            with self.assertRaises(ValueError):preview.replay_bytes(first)
            with self.assertRaises(ValueError):preview.prepare(preview.source['id'],21,[True])

    def test_heightmap_corner_mirror_is_not_pixel_flip(self):
        n,tile=512,16
        source=[((by*tile+ly)*n+bx*tile+lx)%65535 for by in range(n//tile) for bx in range(n//tile) for ly in range(tile) for lx in range(tile)]
        raw=struct.pack('<II',n,tile)+struct.pack('<'+str(n*n)+'H',*source)
        out=heightmap_corner_bytes(raw)
        for r,c in [(0,0),(0,1),(0,511),(15,128),(123,456),(511,511)]:
            self.assertEqual(struct.unpack_from('<H',out,2*(r*n+c))[0],(r*n+min(n-c,n-1))%65535)
        with self.assertRaises(ValueError):heightmap_corner_bytes(raw[:-1])

    def test_pinned_model_origins_and_mounted_ids(self):
        m=model_metadata(6929)
        self.assertEqual(m['model_origins']['track'],[0,0,0])
        self.assertEqual(m['configs'][0]['turret_local'],45)
        self.assertEqual(m['configs'][0]['gun_local'],1041)
        self.assertAlmostEqual(m['model_origins']['turret'][2],2.140294,places=5)
        self.assertIsNone(model_metadata(999999))
