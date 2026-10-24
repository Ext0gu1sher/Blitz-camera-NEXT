"""Production seek orchestration and native supervisor with fake objects only."""
import ctypes as C
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from blitzcam import replay_seek as seek
from blitzcam.playback import PositionPlayback
from blitzcam.profile import CameraError, PROFILE_1121
from blitzcam.project import atomic_json
from blitzcam.server import Workstation
from blitzcam.seek_phase_trial import Config, Header, UiRepairState
from tests.test_replay_preparation import project


def snapshot(now):
    return dict(session_id='123:fake:camera', build={'sha256':PROFILE_1121.sha256},
                addresses={'player':hex(0x1234)},
                replay=dict(time=now, paused=True),
                camera=dict(position=[0,0,10], quaternion=[1,0,0,0], horizontal_fov_deg=60))


class SeekWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        patch('blitzcam.server.OUTPUT', Path(self.tmp.name)/'output').start()
        self.manager=PositionPlayback(Path(self.tmp.name)/'playback-runs')
        self.manager.preparation={'state':'seeking_replay'}
        self.project=project();self.before=self.project.to_dict()
        self.old=Mock(profile=PROFILE_1121);self.old.capture.return_value=snapshot(20)
        self.old.objects.player=0x1234
        self.old.memory.exit_code.return_value=None
        self.fresh=Mock();self.fresh.capture.return_value=snapshot(10.08)
        self.connect=patch.object(seek.CameraSession,'connect',side_effect=[self.old,self.fresh]).start()
        self.native=patch.object(seek,'native_seek',side_effect=self.land).start()
        self.ensure=patch.object(seek,'ensure_free_camera',return_value=True).start()
        self.addCleanup(patch.stopall)
        self.adopt=Mock(return_value=True);self.invalidate=Mock(return_value=True)
        self.reopen=Mock(return_value=True)
        self.manager._run=Mock(side_effect=lambda *_:self.manager.update(state='completed',hooks_detached=True))

    def land(self,session,sample,target,folder,cancel,report):
        self.assertIs(session,self.old);self.assertEqual(target,10)
        self.invalidate.assert_called_once()
        self.assertTrue(self.manager.state()['preparing_replay'])
        self.assertFalse(self.manager.state()['hooks_detached'])
        report.update(hooks_detached=True)
        return {'time':10.08}

    def run_seek(self):
        seek.seek_replay(self.manager,self.project,snapshot(20),self.adopt,self.invalidate,self.reopen)
        self.assertEqual(self.project.to_dict(),self.before)
        self.assertFalse(self.manager.state()['active'])

    def test_backward_jump_discards_old_scene_restores_pose_without_advancing_and_adopts_fresh(self):
        self.run_seek()
        self.native.assert_called_once()
        self.ensure.assert_called_once()
        self.assertEqual(self.ensure.call_args.args[:3],(self.old,0x1234,{'time':10.08}))
        self.assertEqual(self.old.capture.call_count,1)  # No old-scene capture after native seek.
        self.old.close.assert_called_once();self.fresh.close.assert_not_called()
        self.adopt.assert_called_once_with(self.fresh,snapshot(10.08))
        pose_project=self.manager._run.call_args.args[0]
        self.assertEqual(pose_project.shooting_mode,'camera_only')
        self.assertEqual(pose_project.replay_speed['mode'],'paused')
        self.assertEqual(pose_project.sample(0),self.project.sample(10))
        self.assertEqual(self.manager.state()['state'],'completed')
        self.assertTrue(self.manager.state()['experimental_seek'])

    def test_failed_reconnection_does_not_restore_or_retry_seek_or_relaunch_alive_game(self):
        self.connect.side_effect=[self.old,CameraError('tracked camera')]
        self.run_seek()
        self.native.assert_called_once();self.manager._run.assert_not_called();self.adopt.assert_not_called()
        self.ensure.assert_called_once();self.reopen.assert_not_called()
        self.assertEqual(self.manager.state()['state'],'error')

    def test_unsettled_free_camera_does_not_bind_or_restore_or_relaunch_alive_game(self):
        self.ensure.side_effect=CameraError('render roots unsettled')
        self.run_seek()
        self.assertEqual(self.connect.call_count,1)
        self.manager._run.assert_not_called();self.adopt.assert_not_called();self.reopen.assert_not_called()

    def test_different_rebuilt_player_is_rejected(self):
        self.fresh.capture.return_value={**snapshot(10.08),'addresses':{'player':'0x8888'}}
        self.run_seek()
        self.assertEqual(self.manager.state()['state'],'error');self.adopt.assert_not_called()

    def bind_replay(self):
        self.project.replay_timeline.update(replay_file='A.wotbreplay', battle_start_status='identified', battle_start_sec=10.);self.before=self.project.to_dict()
        patch.object(seek,'session_timeline',return_value={'replay_file':'A.wotbreplay'}).start()

    def test_confirmed_process_exit_skips_camera_steps_and_relaunches_bound_replay_once(self):
        self.bind_replay();self.old.memory.exit_code.return_value=0xc0000005
        self.native.side_effect=CameraError('process read failed')
        self.run_seek()
        self.ensure.assert_not_called();self.manager._run.assert_not_called();self.adopt.assert_not_called()
        self.reopen.assert_called_once_with();self.assertTrue(self.manager.state()['replay_relaunch_requested'])
        self.assertTrue(self.manager.state()['hooks_detached'])
        self.assertEqual(self.connect.call_count,1);self.old.close.assert_called_once()

    def test_confirmed_exit_during_camera_switch_relaunches_without_binding_or_pose(self):
        self.bind_replay();self.old.memory.exit_code.return_value=1
        self.ensure.side_effect=CameraError('native camera read failed')
        self.run_seek()
        self.reopen.assert_called_once();self.assertEqual(self.connect.call_count,1)
        self.manager._run.assert_not_called()

    def test_cancellation_and_unknown_exit_status_never_relaunch(self):
        self.bind_replay();self.old.memory.exit_code.side_effect=OSError('query failed')
        self.native.side_effect=CameraError('timeout')
        self.run_seek();self.reopen.assert_not_called()
        self.old.memory.exit_code.side_effect=None;self.old.memory.exit_code.return_value=1
        self.manager.cancel.set();self.run_seek();self.reopen.assert_not_called()

    def test_exit_during_pose_restoration_skips_adoption_and_relaunches_once(self):
        self.bind_replay();self.old.memory.exit_code.return_value=1
        self.manager._run.side_effect=lambda *_:self.manager.update(state='error',message='process exited',hooks_detached=False)
        self.run_seek();self.reopen.assert_called_once();self.adopt.assert_not_called()
        self.assertTrue(self.manager.state()['hooks_detached'])

    def test_cancellation_during_seek_does_not_reconnect_or_restore(self):
        def cancel(*_):self.manager.cancel.set();return None
        self.native.side_effect=cancel
        self.run_seek()
        self.assertEqual(self.connect.call_count,1)
        self.assertEqual(self.manager.state()['state'],'stopped')
        self.manager._run.assert_not_called();self.adopt.assert_not_called()

    def test_unknown_native_detachment_is_not_reported_as_success(self):
        def fail(*args):
            args[-1]['hooks_detached']=False
            raise CameraError('detach unknown')
        self.native.side_effect=fail
        self.run_seek()
        self.assertEqual(self.manager.state()['state'],'error')
        self.assertFalse(self.manager.state()['hooks_detached'])
        self.adopt.assert_not_called()

    def test_at_inpoint_only_restores_pose_without_native_request(self):
        self.old.capture.return_value=snapshot(10)
        self.run_seek()
        self.native.assert_not_called();self.invalidate.assert_not_called()
        self.ensure.assert_not_called()
        self.adopt.assert_called_once_with(self.old,snapshot(10))

    def test_bound_replay_mismatch_rejects_before_invalidating_or_seeking(self):
        self.project.replay_timeline['replay_file']='A.wotbreplay';self.before=self.project.to_dict()
        with patch.object(seek,'session_timeline',return_value={'replay_file':'B.wotbreplay'}):self.run_seek()
        self.native.assert_not_called();self.invalidate.assert_not_called()
        self.assertEqual(self.manager.state()['state'],'error')

    def test_copied_replay_with_saved_identity_can_seek(self):
        self.project.replay_timeline.update(replay_file='old/A.wotbreplay',replay_sha256='a'*64)
        self.before=self.project.to_dict()
        with patch.object(seek,'session_timeline',return_value={
                'replay_file':'new/B.wotbreplay','replay_sha256':'a'*64}):self.run_seek()
        self.native.assert_called_once()
        self.assertEqual(self.manager.state()['state'],'completed')

    def test_workstation_routes_locate_to_native_worker_and_guards_both_callbacks(self):
        w=Workstation(Path(self.tmp.name)/'project.json');w.stop.set();w.poller.join();w.stop.clear()
        atomic_json(w.project_path,self.project.to_dict());w.open_project(w.project_path)
        w.session=self.old;w.sample=snapshot(20)
        try:
            with patch.object(w.playback,'seek') as start,patch.object(w.playback,'prepare') as forward:
                w.play(mode='locate')
                start.assert_called_once();forward.assert_not_called()
                adopt,invalidate,reopen=start.call_args.args[2:]
                self.assertTrue(invalidate());self.assertIsNone(w.session);self.assertIsNone(w.sample)
                self.fresh.discovery_stats={}
                self.assertTrue(adopt(self.fresh,snapshot(10.08)))
                w.generation+=1
                self.assertFalse(invalidate());self.assertFalse(adopt(Mock(),snapshot(10)))
                self.assertIs(w.session,self.fresh)
                with patch.object(w,'open_replay') as launch:
                    self.assertFalse(reopen());launch.assert_not_called()  # Unbound project.
        finally:w.close()

    def test_recovery_launch_uses_original_bound_path_and_rejects_stale_request(self):
        self.bind_replay()
        w=Workstation(Path(self.tmp.name)/'project.json');w.stop.set();w.poller.join();w.stop.clear()
        # Simulate loading an already-authored bound project, including legacy
        # keys; recovery never adds camera keyframes to the unavailable source.
        atomic_json(w.project_path,self.project.to_dict());w.open_project(w.project_path)
        w.session=self.old;w.sample=snapshot(20)
        try:
            with patch.object(w.playback,'seek') as start, \
                 patch('blitzcam.server.session_timeline', return_value={'replay_file': 'A.wotbreplay'}):
                w.play(mode='locate')
                reopen=start.call_args.args[-1]
            with patch.object(w,'open_replay',return_value=True) as launch:
                self.assertTrue(reopen())
                self.assertEqual(launch.call_args.args,('A.wotbreplay',))
                guard=launch.call_args.kwargs['recovery_guard']
            self.assertTrue(guard())
            w.project_revision+=1;self.assertFalse(guard())
            self.assertFalse(reopen())  # Real opener rejects before starting a worker.
            w.project_revision-=1;w.playback.cancel.set();self.assertFalse(guard())
            w.playback.cancel.clear();w.generation+=1;self.assertFalse(guard())
            self.assertFalse(reopen())
        finally:w.close()


class NativeSeekSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.cancel=threading.Event();self.report={'hooks_detached':True}
        self.cfg=Config(player=123,player_vft=124,functor=125,tick_entry=126,job_manager=127,rate=1)
        self.h=Header();self.ui=UiRepairState();self.calls=[];self.failed_detach=False;self.request_count=1
        def read(address,size):
            if address==0x3000+C.sizeof(Config):return bytes(self.h)
            if address==0x6000:return bytes(self.ui)
            raise AssertionError(f'Unexpected memory read: {address:#x}')
        self.session=SimpleNamespace(memory=SimpleNamespace(read=read,u32=lambda _:126,exit_code=lambda:None),live=lambda a:a)
        owner=self
        class Driver:
            def __init__(self,*_):self.k=SimpleNamespace(GetTickCount=lambda:123);self.detach_address=None
            def __enter__(self):return self
            def __exit__(self,*_):
                if self.detach_address:self.call(self.detach_address,0,'fallback detach')
            def load(self,_):return 0x1000
            def write(self,address,data,_):
                if address==0x3000+C.sizeof(Config) and len(data)==C.sizeof(Header):owner.h=Header()
            def call(self,address,*_):
                owner.calls.append(address)
                if address==0x7000:
                    owner.h=Header(status=4,requests=owner.request_count,job_calls=1,emitting_nodes=1,thread=2,job_thread=2,
                        emitting_vft=0x372ab00,emitting_owner=127,emitting_entry=0x92aec0,observer=1)
                elif address==0x8000 and not owner.failed_detach:owner.h.observer=0
                return 0
        self.remote=patch.object(seek,'Remote',Driver).start()
        self.prep=patch.object(seek,'prepare',return_value=(self.cfg,{})).start()
        patch.object(seek,'pe_exports',return_value={'g_shared':0x2000,'g_ui_repair':0x5000,'HookAttach@4':0x6000,'HookDetach@4':0x7000}).start()
        self.value=dict(time=10.08,raw=19.08,origin=9,rate=1,active=1,paused=1,initialized=1,seek=0,waiting=0,task=0xffffffff,source=1)
        patch.object(seek,'clock',return_value=self.value).start()
        self.tick=0
        def monotonic():self.tick+=.3;return self.tick
        patch.object(seek.time,'monotonic',side_effect=monotonic).start()
        self.addCleanup(patch.stopall)

    def run_native(self):return seek.native_seek(self.session,snapshot(20),10,self.folder,self.cancel,self.report)

    def test_exactly_one_native_request_and_verified_detachment(self):
        self.assertEqual(self.run_native()['time'],10.08)
        self.assertEqual(self.calls,[0x7000,0x8000])
        self.assertTrue(self.report['hooks_detached'])
        self.assertFalse(self.prep.call_args.kwargs['ui_repair'])
        self.assertEqual(self.prep.call_args.kwargs['max_delta'],3600)

    def test_failed_execution_audit_still_detaches_and_never_retries(self):
        self.request_count=2
        with self.assertRaisesRegex(CameraError,'执行记录异常'):self.run_native()
        self.assertEqual(self.calls,[0x7000,0x8000]);self.assertTrue(self.report['hooks_detached'])

    def test_off_target_landing_rejects_and_does_not_retry(self):
        self.value['time']=14
        with self.assertRaisesRegex(CameraError,'未到达入点'):self.run_native()
        self.assertEqual(self.calls,[0x7000,0x8000])

    def test_failed_detachment_remains_unknown(self):
        self.failed_detach=True
        with self.assertRaisesRegex(CameraError,'尚未退出'):self.run_native()
        self.assertFalse(self.report['hooks_detached'])

    def test_resident_failed_repair_rejected_before_any_request(self):
        self.ui.installed=1
        with self.assertRaisesRegex(CameraError,'旧修补状态'):self.run_native()
        self.assertEqual(self.calls,[])

    def test_confirmed_process_exit_skips_detach_and_all_later_remote_calls(self):
        def die(*_):
            self.session.memory.exit_code=lambda:1
            raise CameraError('process exited')
        with patch.object(seek,'clock',side_effect=die):
            with self.assertRaisesRegex(CameraError,'process exited'):self.run_native()
        self.assertEqual(self.calls,[0x7000]);self.assertTrue(self.report['hooks_detached'])


if __name__=='__main__':unittest.main()
