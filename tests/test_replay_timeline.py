import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from blitzcam.project import validate_project, edit_project, controls
from blitzcam.channels import track_controls
from blitzcam.playback import compile_positions
from blitzcam.replay_timeline import validate_timeline, file_timeline, playback_window
from blitzcam.profile import CameraError
from blitzcam.server import Workstation


def project():
    return validate_project({'keyframes':[
        {'time_sec':t,'position':[t,0,20],'quaternion':[1,0,0,0],'horizontal_fov_deg':60}
        for t in (10,40,100,220)],
        'position_interpolation':'linear','replay_speed':{'mode':'fixed','rate':1,'camera_clock':'replay'},
        'replay_timeline':{'time_basis':'replay','duration_sec':305.66,'work_start_sec':30,'work_end_sec':60}})


class ReplayTimelineTests(unittest.TestCase):
    def test_absolute_roundtrip_and_edit_keep_global_times(self):
        p=project()
        data={'keyframes':controls(p),'camera_track_controls':track_controls(p),
              'replay_speed':p.replay_speed,'replay_timeline':p.replay_timeline}
        q=edit_project(data)
        self.assertEqual(q.replay_timeline,p.replay_timeline)
        self.assertEqual(q.keyframe_times(),[10,40,100,220])
        q=validate_project(q.to_dict())
        self.assertEqual(q.replay_timeline['duration_sec'],305.66)

    def test_window_uses_actual_battle_time_without_retiming_whole_project(self):
        p=project();before=p.to_dict()
        window=playback_window(p,{'replay':{'time':35}},False)
        self.assertEqual((window.start_time,window.end_time,window.duration),(35,60,25))
        self.assertEqual(window.keyframe_times(),[35,40,60])
        rows,duration=compile_positions(window)
        self.assertEqual(duration,25)
        self.assertAlmostEqual(rows[0].position.x,35)
        at40=next(row for row in rows if row.time==5)
        self.assertAlmostEqual(at40.position.x,40)
        self.assertEqual(p.to_dict(),before)

    def test_window_boundary_rounding_does_not_report_authored_keys_too_close(self):
        p=project();p.replay_timeline.update(work_start_sec=38.26241493225098,work_end_sec=60.)
        data=p.to_dict()
        for key,t in zip(data['keyframes'],(38.262415,46.146686,49.146686,59.9999996)):
            key['time_sec']=t
        p=validate_project(data);before=p.to_dict()
        for start in (p.replay_timeline['work_start_sec'],46.14668593225098):
            with self.subTest(start=start):
                w=playback_window(p,{'replay':{'time':start}})
                rows,duration=compile_positions(w)
                self.assertEqual(rows[0].time,0.)
                self.assertEqual(rows[-1].time,duration)
                self.assertTrue(all(a.time<b.time for a,b in zip(rows,rows[1:])))
                self.assertEqual(p.to_dict(),before)

    def test_absolute_window_rejects_wrong_time_and_battle_reverse(self):
        for now in (0,29,60,120):
            with self.subTest(now=now),self.assertRaises(CameraError):
                playback_window(project(),{'replay':{'time':now}})
        with self.assertRaises(CameraError):playback_window(project(),{'replay':{'time':30}},True)

    def test_last_half_second_is_not_misclassified_as_outside_work_area(self):
        w=playback_window(project(),{'replay':{'time':59.5}})
        self.assertEqual(w.duration,.5)
        for now in (59.501,59.9):
            with self.subTest(now=now),self.assertRaisesRegex(ValueError,'不足 0.5 秒'):
                playback_window(project(),{'replay':{'time':now}})

    def test_window_limits_do_not_limit_editable_global_replay(self):
        p=project();p.replay_timeline['work_end_sec']=220
        self.assertEqual(p.duration,210)
        with self.assertRaises(ValueError):playback_window(p,{'replay':{'time':30}})
        p.replay_speed['mode']='paused'
        p.replay_timeline['work_end_sec']=60
        w=playback_window(p,{'replay':{'time':200}},True)
        self.assertEqual((w.start_time,w.end_time),(30,60))

    def test_curve_continues_original_schedule_without_retiming_keys(self):
        from blitzcam.speed import playback_timing,rate_integral,mean_rate
        for interpolation in ('linear','smooth'):
            p=project();p.replay_speed.update(mode='curve',interpolation=interpolation)
            before=p.to_dict()
            for now in (30,30.02,35,45,58):
                with self.subTest(interpolation=interpolation,now=now):
                    w=playback_window(p,{'replay':{'time':now}})
                    remaining,total,offset=playback_timing(w,p.replay_speed)
                    self.assertEqual(w.start_time,now)
                    self.assertAlmostEqual(total,30/mean_rate(p.replay_speed))
                    self.assertAlmostEqual(total*rate_integral(p.replay_speed,offset/total),now-30)
                    self.assertAlmostEqual(total-offset,remaining)
                    self.assertEqual(w.sample(now),p.sample(now))
                    self.assertEqual(p.to_dict(),before)

    def test_invalid_global_bounds(self):
        good=project().replay_timeline
        for patch in ({'duration_sec':float('nan')},{'work_start_sec':-1},{'work_end_sec':400},{'work_end_sec':30},{'duration_sec':True}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_timeline({**good,**patch})
        data=project().to_dict();data['keyframes'][-1]['time_sec']=306
        with self.assertRaises(ValueError):validate_project(data)

    def test_read_only_metadata_uses_battle_duration_and_checks_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'chosen.wotbreplay'
            with zipfile.ZipFile(path,'w') as z:z.writestr('meta.json',json.dumps({'battleDuration':305.66,'version':'11.21'}))
            before=path.read_bytes();info=file_timeline(path)
            self.assertEqual(info['duration_sec'],305.66)
            self.assertEqual(path.read_bytes(),before)
            with zipfile.ZipFile(path,'w') as z:z.writestr('meta.json','{"battleDuration":false}')
            with self.assertRaises(ValueError):file_timeline(path)

    def test_capture_ignores_requested_relative_time_in_absolute_project(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Workstation(Path(folder)/'project.json');app.stop.set();app.poller.join()
            try:
                app.set_project(project())
                app.session=Mock()
                app.session.capture.return_value={'replay':{'time':45.125,'paused':True},'camera':{
                    'position':[45,0,20],'quaternion':[1,0,0,0],'horizontal_fov_deg':60,
                    'yaw_deg':0,'pitch_deg':0,'roll_deg':0}}
                app.capture(0)
                self.assertIn(45.125,app.project.keyframe_times())
                self.assertNotIn(0,app.project.keyframe_times())
                app.playback=Mock();app.playback.state.return_value={'active':False}
                app.play()
                args=app.playback.start.call_args.args
                self.assertEqual(args[0].start_time,45.125)
                self.assertEqual(args[0].end_time,60)
            finally:app.close()


if __name__=='__main__':unittest.main()
