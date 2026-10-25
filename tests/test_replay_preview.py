from pathlib import Path
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

from blitzcam.replay_preview import ReplayPreview, heightmap_corner_bytes
from blitzcam.preview_assets import model_metadata, playback_pitch_limits, pitch_range, VENDOR
from tests.fixtures.replay_data import replay_data


class PreviewTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required for preview flight validation')
    def test_flight_seek_acceleration_caps_and_camera_roll_directions(self):
        script=Path(__file__).parent/'fixtures/replay_flight_controls.mjs'
        result=subprocess.run(['node',str(script)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    @unittest.skipUnless(shutil.which('node'),'Node required for preview pose validation')
    def test_pose_validation_preserves_smooth_curves_and_rejects_invalid_data(self):
        script=Path(__file__).parent/'fixtures/replay_pose_validation.mjs'
        result=subprocess.run(['node',str(script)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    @unittest.skipUnless(shutil.which('node'),'Node required for preview aim validation')
    def test_barrel_direction_combines_hull_turret_and_elevation_without_drift(self):
        script=Path(__file__).parent/'fixtures/replay_aim_validation.mjs'
        result=subprocess.run(['node',str(script)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_pitch_range_keeps_front_back_and_transition_in_degrees(self):
        f=lambda tag,value:bytes([(tag<<3)|5])+struct.pack('<f',value)
        front=f(1,-16)+f(2,4)+f(3,30)
        back=f(1,-10)+f(2,2)+f(3,40)
        raw=f(1,-20)+f(2,8)+bytes([26,len(front)])+front+bytes([34,len(back)])+back+f(5,12)
        self.assertEqual(pitch_range(raw),{'dep':8,'ele':20,'front':{'min':-16,'max':4,'range':30},
                                         'back':{'min':-10,'max':2,'range':40},'transition':12})
        self.assertIsNone(pitch_range(None))
        self.assertIsNone(pitch_range(f(1,float('nan'))))

    def test_pitch_roster_rejects_invalid_inputs(self):
        valid={'eid':1,'tank_id':6929,'turret_local':45,'gun_local':1041,'nickname':'test'}
        for rows in (None,{},[valid]*65,[{**valid,'tank_id':True}],[{**valid,'gun_local':-1}],[{**valid,'nickname':None}]):
            with self.subTest(rows=str(rows)[:70]),self.assertRaises(ValueError):playback_pitch_limits(rows)

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

    @unittest.skipUnless((VENDOR/'data/models.pb').is_file(),
                         'Optional preview metadata missing; use tools/restore_preview_metadata.py')
    def test_pinned_model_origins_and_mounted_ids(self):
        m=model_metadata(6929)
        self.assertEqual(m['model_origins']['track'],[0,0,0])
        self.assertEqual(m['configs'][0]['turret_local'],45)
        self.assertEqual(m['configs'][0]['gun_local'],1041)
        self.assertAlmostEqual(m['model_origins']['turret'][2],2.140294,places=5)
        self.assertEqual(m['configs'][0]['pitch_limits'],{'dep':8,'ele':24})
        self.assertIsNone(model_metadata(999999))

    @unittest.skipUnless((VENDOR/'data/models.pb').is_file(), 'Optional preview metadata missing')
    def test_pitch_limits_follow_mounted_gun_and_keep_unicode_names(self):
        rows=[{'eid':i,'tank_id':1,'turret_local':0,'gun_local':gun,'nickname':nick}
              for i,gun,nick in [(1,0,'中文玩家'),(2,5,'other'),(3,999,'unknown')]]
        result=playback_pitch_limits(rows)
        self.assertEqual(result['anchored'],[1,2]);self.assertEqual(result['missing'],[3])
        self.assertEqual(result['limits']['中文玩家'],{'dep':6,'ele':17})
        self.assertEqual(result['limits']['other'],{'dep':8,'ele':20,'back':{'min':-20,'max':-2,'range':15}})
        # Older replays can omit comp broadcasts: one known configuration is
        # usable, but multiple configurations must not be guessed.
        unknown=playback_pitch_limits([{'eid':4,'tank_id':1,'nickname':'ambiguous'},
                                      {'eid':5,'tank_id':6929,'nickname':'single','turret_local':None,'gun_local':None}])
        self.assertEqual(unknown['anchored'],[5]);self.assertEqual(unknown['missing'],[4])
        self.assertEqual(unknown['limits']['single'],{'dep':8,'ele':24})
