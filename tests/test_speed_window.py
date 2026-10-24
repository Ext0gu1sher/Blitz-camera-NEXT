from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from blitzcam.project import validate_project,edit_project,controls
from blitzcam.replay_timeline import playback_window
from blitzcam.speed import validate_speed,mean_rate,rate_integral,schedule_time,playback_timing


def project():
    return validate_project({'shooting_mode':'replay','replay_timeline':{
        'time_basis':'replay','duration_sec':100,'work_start_sec':10,'work_end_sec':30},
        'replay_speed':{'mode':'curve','camera_clock':'replay'},
        'keyframes':[{'time_sec':t,'position':[t,0,20],'quaternion':[1,0,0,0],'horizontal_fov_deg':60}for t in (10,20,30)]})


class SpeedWindowTests(unittest.TestCase):
    def test_legacy_project_anchors_curve_once_and_roundtrips(self):
        p=project();speed=deepcopy(p.replay_speed)
        self.assertEqual(speed['time_range'],{'start_sec':10,'end_sec':30})
        data=p.to_dict();data['replay_timeline'].update(work_start_sec=14,work_end_sec=22)
        q=validate_project(data)
        self.assertEqual(q.replay_speed,speed);self.assertEqual(q.keyframe_times(),p.keyframe_times())
        edited=edit_project({'keyframes':controls(q),'shooting_mode':'replay',
                             'replay_timeline':q.replay_timeline,'replay_speed':q.replay_speed})
        self.assertEqual(edited.replay_speed,speed)

    def test_crop_and_extension_keep_original_schedule(self):
        for interpolation in ('linear','smooth'):
            p=project();p.replay_speed['interpolation']=interpolation
            for start,end in ((10,18),(14,24),(2,40),(32,38),(2,7)):
                with self.subTest(interpolation=interpolation,start=start,end=end):
                    p.replay_timeline.update(work_start_sec=start,work_end_sec=end)
                    before=deepcopy(p.to_dict());window=playback_window(p,{'replay':{'time':start}})
                    seconds,total,offset=playback_timing(window,p.replay_speed)
                    self.assertAlmostEqual(total,20/mean_rate(p.replay_speed))
                    self.assertAlmostEqual(offset,schedule_time(p.replay_speed,start,10,30))
                    self.assertAlmostEqual(seconds,schedule_time(p.replay_speed,end,10,30)-offset)
                    self.assertEqual(p.to_dict(),before)

    def test_continuation_inside_trimmed_window_keeps_curve_progress(self):
        p=project();p.replay_timeline.update(work_start_sec=14,work_end_sec=24)
        for start in (14,16,20,23):
            w=playback_window(p,{'replay':{'time':start}})
            seconds,total,offset=playback_timing(w,p.replay_speed)
            self.assertAlmostEqual(total*rate_integral(p.replay_speed,offset/total),start-10)
            self.assertAlmostEqual(seconds+offset,schedule_time(p.replay_speed,24,10,30))

    def test_invalid_curve_domains_are_rejected(self):
        for bounds in (None,[],{'start_sec':True,'end_sec':30},{'start_sec':10,'end_sec':10},
                       {'start_sec':-1,'end_sec':30},{'start_sec':10,'end_sec':3601},
                       {'start_sec':10,'end_sec':float('nan')}):
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):validate_speed({'time_range':bounds})

    @unittest.skipUnless(shutil.which('node'),'Node required for preview parity')
    def test_preview_time_and_rate_knot_positions_match_native_schedule(self):
        cases=[]
        for interpolation in ('linear','smooth'):
            speed=project().replay_speed;speed['interpolation']=interpolation
            for start,end in ((10,30),(10,18),(14,24),(2,40),(32,38),(2,7)):
                cases.append({'speed':deepcopy(speed),'start':start,'end':end,
                              'times':[start+(end-start)*p for p in (0,.1,.35,.75,1)]})
        result=subprocess.run(['node',str(Path(__file__).parent/'fixtures/speed_window.cjs')],
                              input=json.dumps(cases),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        for case,actual in zip(cases,json.loads(result.stdout),strict=True):
            s=case['speed'];start,end=case['start'],case['end'];total=20/mean_rate(s)
            base=schedule_time(s,start,10,30)
            self.assertAlmostEqual(actual['duration'],schedule_time(s,end,10,30)-base,places=8)
            for knot,key in zip(actual['knots'],s['keyframes'],strict=True):
                self.assertAlmostEqual(knot,10+total*rate_integral(s,key['progress']),places=8)
            for row in actual['samples']:
                self.assertAlmostEqual(row['shootingElapsed'],schedule_time(s,row['time'],10,30)-base,places=8)
                self.assertAlmostEqual(row['back'],row['time'],places=8)
                self.assertAlmostEqual(row['mapBack'],row['time'],places=8)
