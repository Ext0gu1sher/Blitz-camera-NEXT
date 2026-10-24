import ctypes as C
import json
import math
from pathlib import Path
import subprocess
import unittest

from blitzcam.speed import validate_speed,bezier_area,rate_integral,mean_rate,shooting_progress,schedule_time
from blitzcam.hook_layout import SpeedPoint
from blitzcam.project import validate_project


class SpeedBezierTests(unittest.TestCase):
    def speed(self,ease):
        return validate_speed({'mode':'curve','camera_clock':'replay','time_range':{'start_sec':10,'end_sec':30},
                               'keyframes':[{'progress':0,'rate':1,'ease':ease},{'progress':1,'rate':.125}]})

    def test_exact_area_against_independent_parametric_quadrature(self):
        for ease in ([0,0,1,0],[.2,.9,.7,.3],[1/3,0,2/3,1],[0,1,0,0],[1,0,1,1]):
            for t in (.1,.5,.9,1):
                x1,y1,x2,y2=ease
                x=3*(1-t)**2*t*x1+3*(1-t)*t*t*x2+t**3
                def f(v):
                    y=3*(1-v)**2*v*y1+3*(1-v)*v*v*y2+v**3
                    dx=3*(1-v)**2*x1+6*(1-v)*v*(x2-x1)+3*v*v*(1-x2)
                    return y*dx
                n=1000;h=t/n
                expected=h/3*(f(0)+f(t)+sum((4 if i%2 else 2)*f(i*h) for i in range(1,n)))
                self.assertAlmostEqual(bezier_area(ease,x),expected,places=10)

    def test_preview_split_inverse_and_window_match_backend(self):
        cases=[self.speed(e) for e in ([0,0,1,0],[.2,.9,.7,.3],[1/3,0,2/3,1],[0,1,0,0],[1,0,1,1])]
        result=subprocess.run(['node',str(Path(__file__).parent/'fixtures/speed_bezier.cjs')],input=json.dumps(cases),text=True,capture_output=True,check=True)
        for s,row in zip(cases,json.loads(result.stdout)):
            self.assertTrue(row['valid']);self.assertTrue(row['splitValid'])
            for i,((rate,integral),(split_rate,split_integral)) in enumerate(zip(row['samples'],row['split'])):
                p=i/100
                self.assertAlmostEqual(integral,rate_integral(s,p),places=10)
                self.assertAlmostEqual(rate,split_rate,places=9)
                self.assertAlmostEqual(integral,split_integral,places=10)
                self.assertAlmostEqual(shooting_progress(s,integral/mean_rate(s)),p,places=10)
            self.assertAlmostEqual(row['window'][0],schedule_time(s,22,10,30)-schedule_time(s,12,10,30),places=9)
            frame=row['window'][1];total=20/mean_rate(s);offset=schedule_time(s,12,10,30)
            self.assertAlmostEqual(frame['replayElapsed'],10+total*rate_integral(s,(offset+2)/total)-12,places=9)

    def test_handles_roundtrip_and_native_layout(self):
        s=self.speed([.2,.9,.7,.3]);p=validate_project({'replay_speed':s,'keyframes':[{'time_sec':t,'position':[0,0,0],'quaternion':[1,0,0,0],'horizontal_fov_deg':60} for t in (10,30)]})
        self.assertEqual(validate_project(p.to_dict()).replay_speed,s)
        native=SpeedPoint.from_key(s['keyframes'][0]);self.assertEqual(native.custom_ease,1)
        for actual,expected in zip(native.ease,s['keyframes'][0]['ease']):self.assertAlmostEqual(actual,expected,places=6)
        self.assertEqual(C.sizeof(SpeedPoint),28)
        self.assertEqual(SpeedPoint.from_key({'progress':1,'rate':.25}).custom_ease,0)

    def test_reject_bad_handles(self):
        for ease in (None,[],[0,0,1],[0,0,1,True],[.8,0,.2,1],[0,-1,1,1],[0,0,math.nan,1]):
            with self.subTest(ease=ease),self.assertRaises(ValueError):self.speed(ease)
