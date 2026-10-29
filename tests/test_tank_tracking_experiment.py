"""Geometry and log-analysis regressions for the isolated research tool."""
import math
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import json
import tempfile
from pathlib import Path
from urllib.error import URLError
from research.scripts.tank_tracking_trial import project_pixel, measure, anchor_at, stats, run, parser, require_idle, initial_pose
from blitzcam.profile import CameraError


class TrackingMetricsTests(unittest.TestCase):
    def setUp(self):
        self.view=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
        self.projection=[math.sqrt(3),0,0,0,0,math.sqrt(3)*16/9,0,0,0,0,-1,-1,0,0,-.2,0]

    def test_centimeters_to_pixels_and_behind_camera(self):
        self.assertAlmostEqual(project_pixel([.02,0,-10],self.view,self.projection)[0],3.3255375505)
        self.assertEqual(project_pixel([0,0,-10],self.view,self.projection),[0,0])
        self.assertIsNone(project_pixel([0,0,10],self.view,self.projection))

    def test_local_anchor_rotates_and_translates(self):
        matrix=[0,1,0,0,-1,0,0,0,0,0,1,0,100,200,30,1]
        self.assertEqual(anchor_at(matrix,[2,3,1.5]),[97,202,31.5])

    def test_muzzle_camera_uses_articulated_part_basis_and_position(self):
        args=parser().parse_args(['--preset','muzzle','--distance','3','--height','.3','--anchor','0','0','0','--muzzle-angle','90'])
        part=[0,1,0,0,-1,0,0,0,0,0,1,0,100,200,30,1]
        target={'matrix':self.view,'muzzle':{'matrix':part}}
        pose=initial_pose(target,args,20)
        self.assertEqual(pose['position'],[100,203,30.3])
        from blitzcam.pose import angles_from_quaternion
        angles=angles_from_quaternion(pose['quaternion'])
        self.assertAlmostEqual(angles['yaw_deg'],-90,places=5)

    def test_measure_does_not_hide_dropped_or_invalid_samples(self):
        cams=[dict(commit=i,kind=2,stage=2,updates=i,raw_time=i,view=self.view,projection=self.projection) for i in (1,2,3)]
        targets=[dict(commit=1,valid=1,updates=1,anchor=[0,0,-10],root=[0,0,-10]),dict(commit=2,valid=0)]
        result=measure(cams,targets)
        self.assertEqual(result['center_error_px']['count'],1)
        self.assertEqual(result['invalid'],1);self.assertEqual(result['unmatched'],1)
        self.assertIsNone(measure([],[])['center_error_px'])

    def test_percentile_uses_observations(self):
        self.assertEqual(stats(range(1,101))['p95'],95)
        self.assertIsNone(stats([]))

    def test_launcher_cancel_before_connect_does_not_touch_game(self):
        with patch('research.scripts.tank_tracking_trial.CameraSession.connect') as connect,redirect_stdout(io.StringIO()):
            result=run(parser().parse_args(['--execute']),stop_requested=lambda:True)
        connect.assert_not_called();self.assertEqual(result['state'],'cancelled')

    def test_stale_workstation_record_requires_confirmed_process_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'output').mkdir()
            (root/'output/workstation-service.json').write_text(json.dumps({'url':'http://127.0.0.1:1','pid':123}))
            with patch('research.scripts.tank_tracking_trial.ROOT',root),patch('urllib.request.urlopen',side_effect=URLError('refused')):
                with patch('research.scripts.tank_tracking_trial.process_exited',return_value=True):require_idle()
                with patch('research.scripts.tank_tracking_trial.process_exited',return_value=False):
                    with self.assertRaises(CameraError):require_idle()


if __name__=='__main__':unittest.main()
