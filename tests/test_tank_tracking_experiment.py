"""Geometry and log-analysis regressions for the isolated research tool."""
import math
import unittest
from research.scripts.tank_tracking_trial import project_pixel, measure, anchor_at, stats


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


if __name__=='__main__':unittest.main()
