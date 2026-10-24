"""Regression for visible acceleration jumps, including the reported shot."""
from copy import deepcopy
import math
import unittest

from blitzcam.channels import ScalarTrack
from blitzcam.camera_smoothing import _accelerations
from tests.test_automatic_camera_curves import rows_at, endpoint_state, PRESETS


class CameraAccelerationTests(unittest.TestCase):
    def test_reported_camera_join_matches_acceleration_on_all_moving_channels(self):
        times=(149.03333333333333,152.71666666666667,155.2)
        values={
            'x':(-210.78912442061753,-216.76701473220498,-204.22717270391541),
            'y':(-61.87091299186791,-60.01321550495706,-49.26100465136598),
            'z':(48.410663137915655,43.079759309325055,40.47753550467428),
            'yaw':(54.72824542312951,61.95943639232535,70.17756894958795),
            'pitch':(-14.672651374261598,-9.380457039171066,-8.96955041130794),
        }
        for channel,points in values.items():
            with self.subTest(channel=channel):
                rows=rows_at(zip(times,points),[.42,0,.58,1]);before=deepcopy(rows)
                track=ScalarTrack(rows,channel,channel in ('x','y','z'),'ease_in_out')
                left,right=track.smooth_curves[0][-1],track.smooth_curves[1][0]
                vl,al=endpoint_state(left,True);vr,ar=endpoint_state(right,False)
                self.assertAlmostEqual(vl,vr,places=10)
                self.assertAlmostEqual(al,ar,places=10)
                # Verify the public sampler, independently of the control data.
                t=times[1];e=.0005
                l=(track.sample(t)-2*track.sample(t-e)+track.sample(t-2*e))/e**2
                r=(track.sample(t+2*e)-2*track.sample(t+e)+track.sample(t))/e**2
                self.assertAlmostEqual(l,r,delta=.04)
                self.assertEqual(track.rows,before)
                self.assertEqual(rows,before)
                for when,value in zip(times,points):self.assertEqual(track.sample(when),value)

    def test_holds_join_with_zero_speed_and_acceleration(self):
        for points in ([(0,0),(1,10),(3,10),(4,20)],[(0,20),(1,10),(3,10),(4,0)]):
            track=ScalarTrack(rows_at(points,PRESETS[1]),'x',True,'linear')
            for i in (1,2):
                for a in endpoint_state(track.smooth_curves[i-1][-1],True):self.assertAlmostEqual(a,0,places=10)
                for a in endpoint_state(track.smooth_curves[i][0],False):self.assertAlmostEqual(a,0,places=10)
            for t in (1,1.3,2,2.7,3):self.assertEqual(track.sample(t),10)

    def test_dense_keys_extrema_and_near_constant_values_are_bounded_everywhere(self):
        for preset in [None,*PRESETS]:
            for points in ([(0,0),(.000011,20),(.2,-3),(8,6)],
                           [(0,179.9),(.03,179.8999999),(4,179.8999998),(5,179.9)],
                           [(0,-90),(1,90),(2,-90),(3,0)]):
                track=ScalarTrack(rows_at(points,preset),'x',False,'ease_in_out')
                for group in track.smooth_curves:
                    for _,_,_,control in group:
                        sign=1 if control[-1]>=0 else -1
                        # The ordered control polygon bounds the whole
                        # polynomial, so sampling cannot miss a narrow overshoot.
                        self.assertTrue(all(math.isfinite(v) for v in control))
                        self.assertTrue(all(sign*(b-a)>=-1e-8 for a,b in zip(control,control[1:])))
                pieces=[p for group in track.smooth_curves for p in group]
                for a,b in zip(pieces,pieces[1:]):
                    for left,right in zip(endpoint_state(a,True),endpoint_state(b,False)):
                        self.assertAlmostEqual(left,right,delta=1e-5*max(1,abs(left)))

    def test_linear_template_stays_linear_including_multiple_keys(self):
        points=[(10,70),(10.2,69.6),(12,66),(17,56)]
        track=ScalarTrack(rows_at(points,[0,0,1,1]),'yaw',False,'ease_in_out')
        for i in range(701):
            t=10+i/100
            self.assertAlmostEqual(track.sample(t),90-2*t,places=9)

    def test_templates_remain_distinct_and_do_not_modify_unselected_segments(self):
        points=[(0,0),(1,10),(3,30),(6,60)]
        gentle=ScalarTrack(rows_at(points,PRESETS[1]),'x',False,'linear')
        strong=ScalarTrack(rows_at(points,[.83,0,.17,1]),'x',False,'linear')
        self.assertGreater(abs(gentle.sample(.25)-strong.sample(.25)),.1)
        mixed=rows_at(points,PRESETS[1]);del mixed[1]['curve']
        baseline=ScalarTrack([{k:v for k,v in row.items() if k!='curve'} for row in mixed],'x',True,'ease_in')
        track=ScalarTrack(mixed,'x',True,'ease_in')
        for i in range(101):self.assertEqual(track.sample(1+2*i/100),baseline.sample(1+2*i/100))

    def test_acceleration_solve_reduces_jerk_relative_to_zero_acceleration(self):
        h,delta,velocity=[1.,2.,1.5],[1.,4.,2.],[0.,1.,1.,0.]
        result=_accelerations(h,delta,velocity)
        # Integrate the squared third derivative of the quintic analytically.
        def energy(acceleration):
            total=0
            for i,span in enumerate(h):
                d=delta[i];v0=span*velocity[i];v1=span*velocity[i+1]
                a0=span**2*acceleration[i];a1=span**2*acceleration[i+1]
                coefficients=[6*(10*d-6*v0-4*v1-1.5*a0+.5*a1),
                              24*(-15*d+8*v0+7*v1+1.5*a0-a1),
                              60*(6*d-3*v0-3*v1-.5*a0+.5*a1)]
                total+=sum(a*b/(j+k+1) for j,a in enumerate(coefficients) for k,b in enumerate(coefficients))/span**5
            return total
        self.assertLess(energy(result),energy([0]*4)-1e-4)


if __name__=='__main__':unittest.main()
