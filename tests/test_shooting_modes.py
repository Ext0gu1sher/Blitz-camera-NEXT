"""Mode boundaries and long independent paths, without accessing the game."""
import bisect
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from blitzcam.channels import track_controls
from blitzcam.project import validate_project, edit_project, controls, samples
from blitzcam.playback import compile_positions
from blitzcam.hook_layout import plain, MAX_POINTS
from blitzcam.hook_guards import angle_difference
from blitzcam.pose import quaternion_from_angles
from blitzcam.trajectory import quaternion_slerp
from blitzcam.replay_timeline import playback_window
from blitzcam.profile import CameraError
from blitzcam.server import Workstation
from blitzcam.speed import shooting_duration


def project(mode='camera_only'):
    return validate_project({'shooting_mode':mode,'keyframes':[
        {'time_sec':t,'position':p,'quaternion':quaternion_from_angles(a,5,0),'horizontal_fov_deg':f}
        for t,p,a,f in ((5,[0,0,20],10,60),(10,[10,20,25],30,70),(7200,[30,10,25],55,80))],
        'replay_speed':{'mode':'curve'},
        'replay_timeline':{'time_basis':'replay','duration_sec':100,'work_start_sec':30,'work_end_sec':40}})


class ShootingModeTests(unittest.TestCase):
    def test_short_independent_clip_does_not_inherit_replay_minimum_duration(self):
        data=project().to_dict()
        data['keyframes']=data['keyframes'][:2]
        data['keyframes'][0]['time_sec']=0
        data['keyframes'][1]['time_sec']=.1
        p=validate_project(data);w=playback_window(p,{'replay':{'time':1000}})
        rows,duration=compile_positions(w)
        self.assertAlmostEqual(duration,.1,places=7)
        self.assertEqual(shooting_duration(w.duration,w.replay_speed,w.shooting_mode),.1)
        self.assertGreaterEqual(len(rows),2)
    def test_independent_mode_ignores_replay_time_and_window_both_directions(self):
        p=project()
        for now in (-100,0,30,500,10000):
            for reverse in (False,True):
                w=playback_window(p,{'replay':{'time':now}},reverse)
                self.assertEqual((w.start_time,w.end_time,w.duration),(0,7200,7200))
                self.assertEqual(w.replay_speed['mode'],'paused')
                self.assertEqual(w.replay_speed['camera_clock'],'shooting')
                self.assertEqual(w.sample(0),p.sample(5))
                self.assertEqual(shooting_duration(w.duration,w.replay_speed,w.shooting_mode),7200)

    def test_mode_and_long_independent_tracks_roundtrip_without_replay_bounds(self):
        p=project()
        q=edit_project({'keyframes':controls(p),'camera_track_controls':track_controls(p),
                        'shooting_mode':'camera_only','replay_timeline':p.replay_timeline,
                        'replay_speed':p.replay_speed})
        self.assertEqual(validate_project(q.to_dict()).to_dict(),q.to_dict())
        self.assertEqual(q.end_time,7200)
        self.assertEqual(q.shooting_mode,'camera_only')
        points=samples(q,60)
        self.assertLessEqual(len(points),6201)
        self.assertEqual(points[0]['time_sec'],0)
        self.assertTrue({5,10,7200}.issubset({p['time_sec'] for p in points}))

    def test_adaptive_table_preserves_short_intervals_in_long_path(self):
        p=project();data=p.to_dict();data['camera_tracks']=track_controls(p)
        data['easing']='ease_in_out'
        p=validate_project(data);w=playback_window(p,{'replay':{'time':99}})
        rows,duration=compile_positions(w)
        self.assertEqual(duration,7200)
        self.assertLessEqual(len(rows),MAX_POINTS)
        times=[row.time for row in rows]
        self.assertTrue({0,5,10,7200}.issubset(set(times)))
        for a,b in ((0,5),(5,10),(10,7200)):
            for i in range(101):
                t=a+(b-a)*i/100;index=max(0,min(len(rows)-2,bisect.bisect_right(times,t)-1))
                lo,hi=rows[index:index+2];u=(t-lo.time)/(hi.time-lo.time)
                expected=w.sample(t)
                actual=[x+(y-x)*u for x,y in zip(plain(lo.position),plain(hi.position))]
                self.assertLess(math.dist(expected.position,actual),.003)
                rotation=quaternion_slerp(plain(lo.quaternion),plain(hi.quaternion),u)
                self.assertLess(angle_difference(expected.quaternion,rotation),.02)

    def test_replay_mode_retains_absolute_time_validation(self):
        p=project();data=p.to_dict();data['shooting_mode']='replay'
        with self.assertRaises(ValueError):validate_project(data)
        data['keyframes'][-1]['time_sec']=50
        p=validate_project(data)
        self.assertEqual(p.replay_speed['mode'],'curve')
        for reverse,now in ((False,0),(False,40),(True,30)):
            with self.assertRaises(CameraError):playback_window(p,{'replay':{'time':now}},reverse)
        self.assertEqual(playback_window(p,{'replay':{'time':30}}).duration,10)
        self.assertEqual(playback_window(p,{'replay':{'time':35}}).duration,5)

    def test_capture_uses_requested_camera_time_and_opening_file_does_not_change_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Workstation(Path(folder)/'project.json');app.stop.set();app.poller.join()
            try:
                app.set_project(project());app.session=Mock()
                app.session.capture.return_value={'replay':{'time':99,'paused':True},'camera':{
                    'position':[2,3,20],'quaternion':[1,0,0,0],'horizontal_fov_deg':60,
                    'yaw_deg':0,'pitch_deg':0,'roll_deg':0}}
                app.capture(8000)
                self.assertIn(8000,app.project.keyframe_times())
                self.assertNotIn(99,app.project.keyframe_times())
                app._bind_opened_replay({'duration_sec':50,'replay_file':'different.wotbreplay'})
                self.assertEqual(app.project.shooting_mode,'camera_only')
                app.playback=Mock();app.playback.state.return_value={'active':False}
                app.play(reverse=True)
                w=app.playback.start.call_args.args[0]
                self.assertEqual((w.start_time,w.end_time),(0,8000))
                self.assertEqual(w.replay_speed['mode'],'paused')
                with self.assertRaises(ValueError):app.play(speed_only=True)
                app.new_project()
                self.assertEqual(app.project.shooting_mode,'camera_only')
                self.assertEqual(app.project.keyframe_times(),[0])
            finally:app.close()


if __name__=='__main__':unittest.main()
