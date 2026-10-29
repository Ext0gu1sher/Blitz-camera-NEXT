"""Offline trajectory/HTTP boundaries. Native x86 tests run separately."""
import ctypes as C
import hashlib,json,math
from pathlib import Path
from types import SimpleNamespace
import tempfile,threading,unittest
from unittest.mock import Mock,patch
from blitzcam.hook_layout import Config,Header,Event,PathPoint,SpeedPoint,RECORDS,POINTS,SPEED_POINTS,SHARED_SIZE,plain
from blitzcam.hook_transport import pe_exports
from blitzcam.playback import compile_positions,check_positions,validate_channels,playback_progress,PositionPlayback,NATIVE
from blitzcam.pose import quaternion_from_angles
from blitzcam.hook_guards import angle_difference
from blitzcam.project import validate_project
from blitzcam.profile import CameraError,PROFILE_1121
from tests.fixtures.game_workstation import Workstation

def trajectory(timing='keyframes',easing='linear'):
    return validate_project({'timing':timing,'easing':easing,'keyframes':[
        {'time_sec':t,'position':p,'quaternion':[1,0,0,0],'horizontal_fov_deg':70}
        for t,p in [(0,[1,2,3]),(3,[4,8,12]),(8,[10,3,20])]]})

class PositionPlaybackTests(unittest.TestCase):
    def test_interrupted_progress_preserves_final_native_position_and_clock(self):
        # Regression values from an interrupted 38.265–60 s replay. The replay
        # tick advanced once after the last camera update; expose both clocks.
        t=SimpleNamespace(start_time=38.26470756530762,end_time=60.,duration=21.735292434692383)
        c=Config(duration=t.duration,approach_seconds=3,replay_mode=2,origin=4.18244743347168)
        h=Header(last_elapsed=16.3028564453125,clock_raw=55.76653289794922,
                 replay_elapsed=13.319377899169922,shooting_elapsed=13.319361003115773,error=27)
        p=playback_progress(t,c,h)
        self.assertAlmostEqual(p['timeline_position'],51.56756401062012)
        self.assertAlmostEqual(p['actual_replay_time'],51.58408546447754)
        self.assertLess(p['progress'],1)
        self.assertEqual(p['shooting_elapsed'],h.shooting_elapsed)

    def test_completed_native_progress_clamps_to_exact_outpoint(self):
        t=SimpleNamespace(start_time=38.3,end_time=49.93333333333333,duration=49.93333333333333-38.3)
        c=Config(duration=t.duration,approach_seconds=1,replay_mode=2,origin=4.18)
        h=Header(last_elapsed=1+c.duration+.016)
        p=playback_progress(t,c,h)
        self.assertEqual(p['progress'],1)
        self.assertEqual(p['timeline_position'],t.end_time)

    def test_reverse_and_approach_progress_keep_paused_replay_clock(self):
        t=trajectory();c=Config(duration=8,approach_seconds=3,reverse=1,raw_time=54,origin=4)
        for last,position,progress in [(1,8,0),(5,6,.25),(12,0,1)]:
            with self.subTest(last=last):
                p=playback_progress(t,c,Header(last_elapsed=last))
                self.assertEqual(p['timeline_position'],position)
                self.assertEqual(p['progress'],progress)
                self.assertEqual(p['actual_replay_time'],50)

    def test_camera_table_preserves_orientation_fov_and_exact_knots(self):
        data=trajectory().to_dict()
        for k,a,f in zip(data['keyframes'],[(10,-15,0),(35,5,12),(50,10,-8)],[45,60,80]):
            k['quaternion']=quaternion_from_angles(*a);k['horizontal_fov_deg']=f
        t=validate_project(data);rows,_=compile_positions(t)
        for when,k in zip(t.keyframe_times(),t.keyframes):
            row=next(r for r in rows if r.time==C.c_float(when).value)
            self.assertLess(angle_difference(plain(row.quaternion),k.pose.quaternion),.00001)
            self.assertEqual(row.horizontal_fov,k.pose.horizontal_fov_deg)
        self.assertTrue(all(abs(sum(x*x for x in plain(r.quaternion))-1)<1e-6 for r in rows))
        self.assertGreater(angle_difference(plain(rows[0].quaternion),plain(rows[-1].quaternion)),20)
    def test_fov_domain_uses_current_viewport_scale_and_channel_switch(self):
        rows,_=compile_positions(trajectory());c=Config();c.fov_scale=2;c.fov_enabled=1
        validate_channels(c,rows);rows[-1].horizontal_fov=181
        with self.assertRaises(CameraError):validate_channels(c,rows)
        c.fov_enabled=0;validate_channels(c,rows)
    def test_pitch_domain_only_applies_when_orientation_channel_enabled(self):
        data=trajectory().to_dict();data['keyframes'][-1]['quaternion']=quaternion_from_angles(20,85,0)
        rows,_=compile_positions(validate_project(data));c=Config();c.orientation_enabled=1
        with self.assertRaises(CameraError):validate_channels(c,rows)
        c.orientation_enabled=0;validate_channels(c,rows)
    def test_channel_options_require_bools_before_worker_start(self):
        manager=PositionPlayback(Path('unused'))
        for kwargs in ({'orientation_enabled':1},{'fov_enabled':'true'}):
            with self.assertRaises(ValueError):manager.start(trajectory(),{},**kwargs)
        self.assertIsNone(manager.thread)
    def test_workstation_passes_channel_options_without_altering_project(self):
        with tempfile.TemporaryDirectory()as tmp:
            w=Workstation(Path(tmp)/'p.json');w.stop.set();w.poller.join()
            w.session=Mock();w.session.capture.return_value={'replay':{'paused':True}}
            try:
                with patch.object(w.playback,'start')as start:
                    w.play(True,False,True)
                    start.assert_called_once_with(w.project,{'replay':{'paused':True}},True,False,True)
            finally:w.close()
    def test_table_contains_all_knots_under_both_time_mappings(self):
        for timing in ('keyframes','constant_speed'):
            for easing in ('linear','ease_in_out'):
                t=trajectory(timing,easing);rows,duration=compile_positions(t)
                self.assertEqual(duration,8);self.assertEqual(rows[0].time,0);self.assertEqual(rows[-1].time,8)
                self.assertTrue(all(a.time<b.time for a,b in zip(rows,rows[1:])))
                for when,k in zip(t.keyframe_times(),t.keyframes):
                    row=next(r for r in rows if r.time==C.c_float(when).value)
                    self.assertEqual(plain(row.position),list(k.pose.position))
    def test_sampling_grid_near_authored_key_does_not_reject_valid_trajectory(self):
        data=trajectory().to_dict();data['keyframes'][1]['time_sec']=3.0000004
        p=validate_project(data);before=p.to_dict()
        rows,_=compile_positions(p)
        times=[r.time for r in rows]
        self.assertIn(3.,times)
        key=next(r for r in rows if r.time==C.c_float(3.0000004).value)
        self.assertEqual(plain(key.position),list(p.keyframes[1].pose.position))
        self.assertTrue(all(a<b for a,b in zip(times,times[1:])))
        self.assertEqual(p.to_dict(),before)
    def test_duration_limits_do_not_touch_remote_process(self):
        t=trajectory();data=t.to_dict();data['keyframes'][-1]['time_sec']=121
        with self.assertRaises(ValueError):compile_positions(validate_project(data))
    def test_native_manifest_and_x86_exports(self):
        d=json.loads((NATIVE/'position_hook_1121.json').read_text());dll=NATIVE/d['dll']
        self.assertEqual(hashlib.sha256(dll.read_bytes()).hexdigest(),d['sha256'])
        self.assertEqual((d['config_size'],d['event_size'],d['records'],d['points']),(C.sizeof(Config),C.sizeof(Event),RECORDS,POINTS))
        self.assertEqual((d['path_point_size'],d['speed_point_size'],d['speed_points'],d['shared_size']),(C.sizeof(PathPoint),C.sizeof(SpeedPoint),SPEED_POINTS,SHARED_SIZE))
        self.assertTrue({'g_shared','HookAttach@4','HookDetach@4'}<=pe_exports(dll).keys())
    def test_curve_and_approach_are_bounded_before_installation(self):
        rows,_=compile_positions(trajectory());c=Config();c.b.x=1;c.b.y=2;c.b.z=3
        extra={'bounds_min':[0,0,0],'bounds_max':[100,100,100],'position_boxes_begin_end':['0x0','0x0']}
        check_positions(Mock(),extra,c,rows)
        extra['bounds_max'][2]=10
        with self.assertRaises(CameraError):check_positions(Mock(),extra,c,rows)
    def test_start_refuses_playing_replay_and_unknown_build(self):
        manager=PositionPlayback(Path('unused'))
        for digest,paused in [(PROFILE_1121.sha256,False),('unknown',True)]:
            with self.assertRaises(CameraError):manager.start(trajectory(),{'build':{'sha256':digest},'replay':{'paused':paused}})
        self.assertIsNone(manager.thread)
    def test_preparation_can_be_cancelled_before_any_live_access(self):
        with tempfile.TemporaryDirectory()as tmp:
            m=PositionPlayback(tmp);m.cancel.set()
            with patch('blitzcam.playback.Remote')as remote:
                m._run(trajectory(),{},False);remote.assert_not_called()
    def test_running_project_cannot_be_changed_or_captured(self):
        with tempfile.TemporaryDirectory()as tmp:
            w=Workstation(Path(tmp)/'p.json');w.stop.set();w.poller.join();before=w.project.to_dict()
            w.playback.update(active=True)
            try:
                with self.assertRaises(CameraError):w.set_project(trajectory())
                with self.assertRaises(CameraError):w.capture(0)
                self.assertEqual(w.project.to_dict(),before)
            finally:w.playback.update(active=False);w.close()
    def test_new_path_archives_project_and_captures_one_real_waypoint(self):
        with tempfile.TemporaryDirectory()as tmp,patch('blitzcam.server.OUTPUT',Path(tmp)):
            w=Workstation(Path(tmp)/'p.json');w.stop.set();w.poller.join();before=w.project.to_dict()
            w.session=Mock();w.session.capture.return_value={'camera':{'position':[1,2,3],'quaternion':[1,0,0,0],'horizontal_fov_deg':70}}
            try:
                w.new_project();self.assertEqual(len(w.project.keyframes),1)
                self.assertEqual(w.project.keyframes[0].pose.position,(1,2,3))
                old=next((Path(tmp)/'project-history').glob('*.json'));self.assertEqual(json.loads(old.read_text()),before)
            finally:w.close()
