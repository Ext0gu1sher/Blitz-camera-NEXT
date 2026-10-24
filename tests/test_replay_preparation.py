"""Preparation orchestration against fake sessions; never accesses the game."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from blitzcam.playback import PositionPlayback
from blitzcam.profile import CameraError, PROFILE_1121, SessionChanged
from blitzcam.project import validate_project
from blitzcam.replay_preparation import prepare_replay
from blitzcam.server import Workstation


def project():
    return validate_project({'shooting_mode':'replay',
        'replay_timeline':{'time_basis':'replay','duration_sec':60,'work_start_sec':10,'work_end_sec':18},
        'replay_speed':{'mode':'curve','camera_clock':'replay'},
        'keyframes':[{'time_sec':t,'position':[t,2,10],'quaternion':[1,0,0,0],
                      'horizontal_fov_deg':60} for t in (0,10,18)]})


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.project=project();self.before=self.project.to_dict()
        self.now=8.;self.paused=True;self.runs=[];self.phases=[]
        self.manager=PositionPlayback('unused')
        self.manager.preparation={'state':'waiting_replay'}
        self.session=Mock();self.session.capture.side_effect=lambda **_:self.snapshot()
        self.connect=patch('blitzcam.replay_preparation.CameraSession.connect',return_value=self.session).start()
        self.addCleanup(patch.stopall)
        self.manager._run=Mock(side_effect=self.run_stage)
        self.adopt=Mock(return_value=True)

    def snapshot(self):
        return {'session_id':'123:abc:def','build':{'sha256':PROFILE_1121.sha256},
                'replay':{'time':self.now,'paused':self.paused},
                'camera':{'position':[2,2,10],'quaternion':[1,0,0,0],'horizontal_fov_deg':60}}

    def run_stage(self,p,reference,reverse,orientation,fov):
        self.runs.append(p);self.phases.append(self.manager.state())
        self.assertTrue(self.manager.state()['active'])
        if p.shooting_mode=='replay' and p.replay_speed['camera_clock']=='shooting':
            # A worst-case 150 ms frame overshoot, as allowed by the native guard.
            self.now+=p.duration*p.replay_speed['rate']+.15*p.replay_speed['rate']
        self.manager.update(state='completed',active=False,hooks_detached=True)

    def prepare(self,locate=False):
        prepare_replay(self.manager,self.project,self.snapshot(),locate,self.adopt)
        self.assertEqual(self.project.to_dict(),self.before)
        self.assertFalse(self.manager.state()['active'])

    def test_forward_preparation_slow_arrival_and_one_automatic_start(self):
        self.prepare()
        self.assertLessEqual(abs(self.now-10),.05)
        self.assertEqual([s['state'] for s in self.phases],['advancing_replay','advancing_replay','preparing'])
        self.assertAlmostEqual(self.runs[-1].start_time,self.now)
        self.assertEqual(self.runs[-1].end_time,18)
        self.assertEqual(self.adopt.call_count,1)
        self.session.close.assert_not_called()  # Ownership transferred to workstation.

    def test_locate_only_restores_pose_and_leaves_replay_paused(self):
        self.prepare(locate=True)
        self.assertEqual(self.runs[-1].shooting_mode,'camera_only')
        self.assertEqual(self.runs[-1].replay_speed['mode'],'paused')
        self.assertEqual(self.runs[-1].sample(0),self.project.sample(self.now))
        self.assertTrue(self.paused)
        self.assertIn('并暂停',self.manager.state()['message'])

    def test_past_in_point_stops_without_impossible_manual_rewind_wait(self):
        self.now=20
        with patch.object(self.manager.cancel,'wait') as wait:self.prepare()
        wait.assert_not_called()
        self.assertEqual(self.connect.call_count,1)
        self.session.close.assert_called_once()
        self.adopt.assert_not_called()
        self.assertEqual(self.manager.state()['state'],'error')
        self.assertIn('实验性跳转',self.manager.state()['message'])
        self.assertEqual(self.runs,[])

    def test_native_record_grid_landing_does_not_demand_another_seek(self):
        self.now=10.09
        self.prepare()
        self.assertEqual(len(self.runs),1)
        self.assertEqual(self.runs[0].start_time,self.now)

    def test_early_grid_landing_still_advances_inside_playable_window(self):
        self.now=9.92
        self.prepare()
        self.assertEqual(len(self.runs),2)
        self.assertLessEqual(abs(self.now-10),.05)
        self.assertEqual(self.runs[-1].start_time,self.now)

    def test_wait_for_pause_then_auto_start(self):
        self.now=10;self.paused=False
        def wait(_):
            self.assertEqual(self.manager.state()['state'],'waiting_replay')
            self.paused=True
        with patch.object(self.manager.cancel,'wait',side_effect=wait):self.prepare()
        self.assertEqual(len(self.runs),1)

    def test_merged_play_rechecks_current_time_after_waiting_for_pause(self):
        self.now=8;self.paused=False
        def wait(_):self.now=14;self.paused=True
        with patch.object(self.manager.cancel,'wait',side_effect=wait):self.prepare()
        self.assertEqual(len(self.runs),1)
        self.assertEqual(self.runs[0].start_time,14)
        self.assertEqual(self.runs[0].end_time,18)
        self.assertEqual(self.manager.state()['state'],'completed')

    def test_merged_play_before_inpoint_still_prepares_then_starts(self):
        self.prepare()
        self.assertEqual([s['state'] for s in self.phases],['advancing_replay','advancing_replay','preparing'])
        self.assertLessEqual(abs(self.runs[-1].start_time-10),.05)

    def test_merged_play_past_outpoint_does_not_trigger_experimental_seek(self):
        self.now=20
        self.prepare()
        self.assertEqual(self.runs,[])
        self.assertEqual(self.manager.state()['state'],'error')
        self.assertIn('实验性跳转',self.manager.state()['message'])

    def test_cancel_wait_does_not_start_or_adopt_session(self):
        self.paused=False
        with patch.object(self.manager.cancel,'wait',side_effect=lambda _:self.manager.stop()):self.prepare()
        self.assertEqual(self.runs,[]);self.adopt.assert_not_called()
        self.assertEqual(self.manager.state()['state'],'stopped')
        self.session.close.assert_called_once()

    def test_cancel_during_forward_does_not_start_camera_shot(self):
        self.manager._run.side_effect=lambda *args:self.manager.stop()
        self.prepare()
        self.assertEqual(self.manager._run.call_count,1)
        self.adopt.assert_not_called()

    def test_stage_error_is_not_hidden_by_cancellation(self):
        def fail(*_):
            self.manager.cancel.set()
            self.manager.update(state='error',hooks_detached=False,message='detach failed')
        self.manager._run.side_effect=fail
        self.prepare()
        self.assertEqual(self.manager.state()['state'],'error')
        self.assertEqual(self.manager.state()['message'],'detach failed')
        self.adopt.assert_not_called()

    def test_bound_replay_mismatch_stops_before_native_run(self):
        self.project.replay_timeline['replay_file']='A.wotbreplay';self.before=self.project.to_dict()
        with patch('blitzcam.replay_preparation.session_timeline',return_value={'replay_file':'B.wotbreplay'}):self.prepare()
        self.assertEqual(self.runs,[])
        self.assertEqual(self.manager.state()['state'],'error')
        self.assertIn('绑定不一致',self.manager.state()['message'])

    def test_native_stage_must_detach_before_next_stage(self):
        self.manager._run.side_effect=lambda *_:self.manager.update(state='completed',hooks_detached=False)
        self.prepare();self.assertEqual(self.manager.state()['state'],'error')
        self.assertEqual(self.manager._run.call_count,1)
        self.adopt.assert_not_called()

    def test_workstation_retains_reader_until_success_and_guards_stale_adoption(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=Workstation(Path(tmp)/'project.json');w.stop.set();w.poller.join();w.stop.clear()
            w.set_project(self.project);old=Mock();w.session=old;old.capture.return_value=self.snapshot()
            try:
                with patch.object(w.playback,'prepare') as start:
                    w.play(mode='prepare')
                    self.assertIs(w.session,old);old.close.assert_not_called()
                    adopt=start.call_args.args[3]
                    w.playback.cancel.clear()
                    fresh=Mock();fresh.discovery_stats={}
                    self.assertTrue(adopt(fresh,self.snapshot()))
                    old.close.assert_called_once();self.assertIs(w.session,fresh)
                    w.generation+=1
                    self.assertFalse(adopt(Mock(),self.snapshot()))
                    self.assertIs(w.session,fresh)
                with patch.object(w.playback,'prepare') as start:
                    with self.assertRaises(ValueError):w.play(mode='prepare',expected_revision=-1)
                    start.assert_not_called()
            finally:w.close()

    def test_main_auto_chooses_current_or_preparation_from_actual_game_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=Workstation(Path(tmp)/'project.json');w.stop.set();w.poller.join();w.stop.clear()
            w.set_project(self.project);w.session=Mock();w.session.capture.side_effect=lambda **_:self.snapshot()
            try:
                with patch.object(w.playback,'start') as start,patch.object(w.playback,'prepare') as prepare,patch.object(w.playback,'seek') as experimental:
                    self.now=14
                    w.play(mode='auto')
                    start.assert_called_once();prepare.assert_not_called()
                    window=start.call_args.args[0]
                    self.assertEqual((window.start_time,window.end_time),(14,18))
                    self.assertEqual(window.source.to_dict(),self.before)
                    self.assertGreater(window.speed_schedule[1],0)  # Preserve authored speed-curve progress.
                    start.reset_mock()
                    for now,paused in ((8,True),(14,False),(18,True)):
                        with self.subTest(now=now,paused=paused):
                            self.now,self.paused=now,paused
                            w.play(mode='auto')
                            prepare.assert_called_once();start.assert_not_called()
                            prepare.reset_mock()
                    experimental.assert_not_called()
                    self.project.replay_timeline['replay_file']='A.wotbreplay'
                    w.set_project(self.project);self.now,self.paused=14,True
                    with patch('blitzcam.server.session_timeline',return_value={'replay_file':'B.wotbreplay'}):
                        with self.assertRaisesRegex(CameraError,'绑定不一致'):w.play(mode='auto')
                    start.assert_not_called();prepare.assert_not_called();experimental.assert_not_called()
            finally:w.close()

    def test_preparation_entry_resumes_inside_workspace_without_opt_in(self):
        self.now=14
        self.manager.prepare(self.project,self.snapshot(),False,self.adopt)
        self.manager.thread.join(timeout=2)
        self.assertFalse(self.manager.thread.is_alive())
        self.assertEqual(self.manager.state()['state'],'completed')
        self.assertEqual([(p.start_time,p.end_time) for p in self.runs],[(14,18)])
        self.assertEqual(self.project.to_dict(),self.before)

    def test_legacy_prepare_and_default_main_play_continue_at_current_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=Workstation(Path(tmp)/'project.json');w.stop.set();w.poller.join();w.stop.clear()
            w.set_project(self.project);w.session=Mock();w.session.capture.side_effect=lambda **_:self.snapshot()
            try:
                for now in (10.01,14,17.5):
                    for mode in (None,'auto','prepare'):
                        with self.subTest(now=now,mode=mode),patch.object(w.playback,'start') as start,patch.object(w.playback,'prepare') as prepare:
                            self.now=now
                            w.play(**({'mode':mode} if mode else {}))
                            start.assert_called_once();prepare.assert_not_called()
                            window=start.call_args.args[0]
                            self.assertEqual((window.start_time,window.end_time),(now,18))
                            self.assertEqual(window.sample(now),self.project.sample(now))
                            self.assertEqual(window.source.to_dict(),self.before)
            finally:w.close()

    def test_tail_is_inside_work_area_and_reports_short_duration_without_seek(self):
        self.now=17.8
        self.prepare()
        self.assertEqual(self.manager.state()['state'],'error')
        self.assertIn('不足 0.5 秒',self.manager.state()['message'])
        self.assertNotIn('跳转',self.manager.state()['message'])
        self.assertEqual(self.runs,[])

    def test_copied_replay_with_saved_identity_can_prepare(self):
        self.project.replay_timeline.update(replay_file='old/A.wotbreplay',replay_sha256='a'*64)
        self.before=self.project.to_dict()
        with patch('blitzcam.replay_preparation.session_timeline',return_value={
                'replay_file':'new/B.wotbreplay','replay_sha256':'a'*64}):self.prepare()
        self.assertEqual(self.manager.state()['state'],'completed')
        self.adopt.assert_called_once()


if __name__=='__main__':unittest.main()

