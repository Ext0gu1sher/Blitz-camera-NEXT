import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from blitzcam import replay_launcher as launcher
from blitzcam.profile import CameraError, SessionChanged
from blitzcam.server import Workstation
from tests.test_replay_events import arena_payload, data_with_events


def await_state(app, wanted):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = app.state()
        if state['replay_launch']['state'] in wanted:
            return state
        time.sleep(.01)
    raise AssertionError(app.state()['replay_launch'])


class ReplayLauncherTests(unittest.TestCase):
    def test_launch_source_accepts_same_content_at_different_paths(self):
        info=SimpleNamespace(pid=65388,path=Path('wotblitz.exe'))
        launch={'pid':64604,'executable':'wotblitz.exe',
                'info':{'replay_file':'original.wotbreplay','replay_sha256':'a'*64}}
        candidate={'replay_file':'copied.wotbreplay','replay_sha256':'a'*64}
        self.assertEqual(launcher.verify_launch_source(info,launch,candidate)['verification'],'launch_arguments')
        with self.assertRaises(CameraError):
            launcher.verify_launch_source(info,launch,{**candidate,'replay_sha256':'b'*64})

    def test_handoff_checks_executable_and_file_instead_of_original_pid(self):
        info=SimpleNamespace(pid=65388,path=Path('wotblitz.exe'))
        launch={'pid':64604,'executable':'wotblitz.exe','info':{'replay_file':'chosen.wotbreplay'}}
        result=launcher.verify_launch_source(info,launch,{'replay_file':'chosen.wotbreplay'})
        self.assertTrue(result['process_handoff'])
        self.assertEqual(result['connected_pid'],65388)
        with self.assertRaisesRegex(CameraError,'回放与本次选择不一致'):
            launcher.verify_launch_source(info,launch,{'replay_file':'other.wotbreplay'})
        with self.assertRaisesRegex(CameraError,'安装位置'):
            launcher.verify_launch_source(SimpleNamespace(pid=65388,path=Path('other/wotblitz.exe')),launch,{'replay_file':'chosen.wotbreplay'})
        with self.assertRaisesRegex(CameraError,'无法读取.*回放文件.*fixture read error'):
            launcher.verify_launch_source(info,launch,None,'fixture read error')
        with self.assertRaisesRegex(CameraError,'安装位置'):
            launcher.verify_launch_source(SimpleNamespace(pid=65388,path=Path('other/wotblitz.exe')),launch,None)

    def test_replay_picker_preserves_unicode_and_cancel(self):
        with patch.object(launcher, 'show_dialog', return_value=None) as dialog:
            self.assertIsNone(launcher.choose_replay())
            self.assertTrue(dialog.call_args.kwargs['remember_location'])
            self.assertEqual(dialog.call_args.kwargs['filters'][0][1], '*.wotbreplay')
            dialog.return_value = Path(r'C:\回放\A B.wotbreplay')
            self.assertEqual(launcher.choose_replay(), dialog.return_value)

    def test_client_requires_matching_steam_app_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            steamapps = Path(folder)/'steamapps'
            exe = steamapps/'common/World of Tanks Blitz/wotblitz.exe'
            exe.parent.mkdir(parents=True); exe.write_bytes(b'not executed')
            self.assertIsNone(launcher.steam_client(exe))
            manifest = steamapps/'appmanifest_444200.acf'
            manifest.write_text('"AppState" { "appid" "444200" "installdir" "World of Tanks Blitz" }')
            self.assertEqual(launcher.steam_client(exe), exe.resolve())
            manifest.write_text('"AppState" { "appid" "999" "installdir" "World of Tanks Blitz" }')
            self.assertIsNone(launcher.steam_client(exe))

    def test_spawn_passes_exact_file_as_one_argument_without_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder)/'wotblitz.exe'
            replay = Path(folder)/'镜头 A & B.wotbreplay'; replay.write_bytes(b'fixture')
            with patch('blitzcam.memory._kernel',side_effect=AssertionError('launch inspected game')), patch.object(launcher, 'steam_client', return_value=exe), \
                 patch.object(launcher.subprocess, 'Popen') as spawn:
                launcher.launch_replay(exe, replay)
            spawn.assert_called_once_with([str(exe), str(replay.resolve())], cwd=exe.parent, shell=False)

    def test_repeated_launch_uses_same_command_while_first_process_is_running(self):
        with tempfile.TemporaryDirectory() as folder:
            exe=Path(folder)/'wotblitz.exe';replay=Path(folder)/'chosen.wotbreplay';replay.write_bytes(b'fixture')
            process=Mock();process.poll.return_value=None
            with patch('blitzcam.memory._kernel',side_effect=AssertionError('launch inspected game')), \
                 patch.object(launcher,'steam_client',return_value=exe), \
                 patch.object(launcher.subprocess,'Popen',return_value=process) as spawn:
                self.assertIs(launcher.launch_replay(exe,replay),process)
                self.assertIs(launcher.launch_replay(exe,replay),process)
            self.assertEqual(spawn.call_count,2)
            self.assertEqual(spawn.call_args_list[0],spawn.call_args_list[1])
            process.poll.assert_not_called()
            process.terminate.assert_not_called();process.kill.assert_not_called()


class ReplayOpenWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output_patch = patch('blitzcam.server.OUTPUT', self.root)
        self.output_patch.start()
        self.replay = self.root/'镜头 A.wotbreplay'
        with zipfile.ZipFile(self.replay, 'w') as archive:
            archive.writestr('meta.json', json.dumps({'battleDuration':305.66, 'version':'11.21'}))
            archive.writestr('data.wotreplay', data_with_events([(8,4.25,arena_payload())]))
        self.app = Workstation(self.root/'project.json')
        self.app.stop.set(); self.app.poller.join()
        # Stop only the periodic game reader; opening should still be enabled.
        self.app.stop.clear()
        self.process = SimpleNamespace(pid=12345, poll=lambda: None)
        self.patches = [patch('blitzcam.memory._kernel',side_effect=AssertionError('open inspected game')),
                        patch.object(launcher, 'locate_client', return_value=Path('wotblitz.exe')),
                        patch.object(launcher, 'choose_replay', return_value=self.replay),
                        patch.object(launcher, 'launch_replay', return_value=self.process)]
        self.mocks = [p.start() for p in self.patches]

    def tearDown(self):
        self.app.close()
        for p in reversed(self.patches): p.stop()
        self.output_patch.stop()
        self.tmp.cleanup()

    def test_open_binds_file_and_length_preserves_camera_and_backs_up(self):
        before = self.app.project.to_dict(); replay_bytes = self.replay.read_bytes()
        self.app.open_replay(str(self.replay))
        state = await_state(self.app, {'launched','error'})
        self.assertEqual(state['replay_launch']['state'], 'launched')
        timeline = state['project']['replay_timeline']
        self.assertEqual(timeline['duration_sec'], 305.66)
        self.assertEqual(timeline['replay_file'], str(self.replay.resolve()))
        self.assertEqual(state['project']['keyframes'], before['keyframes'])
        self.assertEqual(state['project']['replay_speed'], before['replay_speed'])
        self.assertEqual(self.replay.read_bytes(), replay_bytes)
        backups = list((self.root/'project-history').glob('*.json'))
        self.assertEqual(len(backups),1)
        self.assertEqual(json.loads(backups[0].read_text(encoding='utf-8')), before)
        self.assertFalse(state['replay_launch']['verified'])
        self.assertFalse(state['playback']['active'])
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_called_once()

    def test_cancel_leaves_game_and_project_alone(self):
        before = self.app.project.to_dict(); self.mocks[2].return_value = None
        self.app.open_replay()
        state = await_state(self.app, {'cancelled','error'})
        self.assertEqual(state['replay_launch']['state'], 'cancelled')
        self.assertEqual(state['project'], before)
        self.assertFalse(self.app.project_path.exists())
        self.mocks[3].assert_not_called()

    def test_bad_file_never_spawns_or_saves(self):
        self.app.open_replay(str(self.root/'missing.wotbreplay'))
        await_state(self.app, {'error'})
        self.mocks[3].assert_not_called()
        self.assertFalse(self.app.project_path.exists())

    def test_recovery_cancelled_after_metadata_read_does_not_launch(self):
        before=self.app.project.to_dict()
        guard=Mock(side_effect=[True,False])
        self.assertTrue(self.app.open_replay(str(self.replay),recovery_guard=guard))
        state=await_state(self.app,{'cancelled','error'})
        self.assertEqual(state['replay_launch']['state'],'cancelled')
        self.assertEqual(self.app.project.to_dict(),before)
        self.mocks[2].assert_not_called();self.mocks[3].assert_not_called()

    def test_recovery_uses_existing_launch_command_once_without_picker(self):
        guard=Mock(return_value=True)
        self.assertTrue(self.app.open_replay(str(self.replay),recovery_guard=guard))
        state=await_state(self.app,{'launched','error'})
        self.assertEqual(state['replay_launch']['state'],'launched')
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_called_once_with(Path('wotblitz.exe'),str(self.replay.resolve()))

    def test_reopen_sends_another_launch_request_without_game_check(self):
        for _ in range(2):
            self.app.open_replay(str(self.replay))
            self.assertEqual(await_state(self.app,{'launched','error'})['replay_launch']['state'],'launched')
        self.assertEqual(self.mocks[3].call_count,2)
        self.mocks[0].assert_not_called();self.mocks[2].assert_not_called()

    def test_selection_is_async_and_blocks_duplicate_open_and_connect(self):
        selected, release = threading.Event(), threading.Event()
        def choose():
            selected.set(); release.wait(3); return None
        self.mocks[2].side_effect = choose
        self.app.open_replay(); self.assertTrue(selected.wait(2))
        try:
            self.assertEqual(self.app.state()['replay_launch']['state'], 'choosing')
            with self.assertRaises(CameraError):self.app.open_replay()
            with self.assertRaises(CameraError):self.app.connect()
        finally:
            release.set(); await_state(self.app, {'cancelled'})

    def test_open_during_camera_playback_is_rejected(self):
        with patch.object(self.app.playback, 'state', return_value={'active':True}):
            with self.assertRaises(CameraError):self.app.open_replay()
        self.mocks[0].assert_not_called()

    def test_launch_failure_preserves_project(self):
        before = self.app.project.to_dict(); self.mocks[3].side_effect = OSError('fixture launch failed')
        self.app.open_replay(str(self.replay))
        state = await_state(self.app, {'error'})
        self.assertEqual(state['project'], before)
        self.assertIn('fixture launch failed', state['replay_launch']['message'])
        self.assertFalse(self.app.project_path.exists())

    def test_shorter_replay_does_not_delete_or_retime_existing_keys(self):
        with zipfile.ZipFile(self.replay,'w') as archive:
            archive.writestr('meta.json',json.dumps({'battleDuration':.25}))
        before = self.app.project.to_dict()
        self.app.open_replay(str(self.replay))
        state = await_state(self.app, {'launched','error'})
        self.assertEqual(state['replay_launch']['state'], 'launched')
        self.assertIn('时间轴未改动', state['replay_launch']['message'])
        self.assertEqual(state['project'], before)

    def test_connection_checks_launch_process_and_argument_but_never_assumes_later_switches(self):
        self.app.open_replay(str(self.replay)); state = await_state(self.app, {'launched'})
        session = Mock(); session.memory.info.pid = self.process.pid
        session.memory.info.path = Path('wotblitz.exe')
        candidate = {**state['replay_launch']['info'], 'source':'launch_argument'}
        with patch('blitzcam.server.CameraSession.connect',return_value=session), \
             patch('blitzcam.server.session_timeline',return_value=candidate):
            self.app.connect()
            deadline = time.monotonic()+3
            while self.app.connection['state']=='connecting' and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue(self.app.replay_launch['verified'])
        self.assertEqual(self.app.replay_info['verification'],'launch_arguments')

    def test_exited_launcher_with_same_file_in_new_process_connects(self):
        self.app.open_replay(str(self.replay)); state=await_state(self.app,{'launched'})
        self.process.poll=Mock(return_value=0)
        session=Mock();session.memory.info.pid=65388;session.memory.info.path=Path('wotblitz.exe')
        candidate={**state['replay_launch']['info'],'source':'launch_argument'}
        with patch('blitzcam.server.CameraSession.connect',return_value=session), \
             patch('blitzcam.server.session_timeline',return_value=candidate):
            self.app.connect()
            deadline=time.monotonic()+3
            while self.app.connection['state']=='connecting' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.connection['state'],'connected')
        self.assertTrue(self.app.replay_launch['verified'])
        self.assertTrue(self.app.replay_launch['process_handoff'])
        self.assertEqual(self.app.replay_launch['connected_pid'],65388)
        self.process.poll.assert_not_called()

    def test_mismatched_launch_argument_does_not_connect_under_wrong_file_identity(self):
        self.app.open_replay(str(self.replay)); await_state(self.app, {'launched'})
        session=Mock();session.memory.info.pid=self.process.pid;session.memory.info.path=Path('wotblitz.exe')
        with patch('blitzcam.server.CameraSession.connect',return_value=session), \
             patch('blitzcam.server.session_timeline',return_value={'replay_file':str(self.root/'other.wotbreplay')}):
            self.app.connect()
            deadline=time.monotonic()+3
            while self.app.connection['state']=='connecting' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.connection['state'],'error')
        self.assertIsNone(self.app.session)
        self.assertFalse(self.app.replay_launch['verified'])
        session.close.assert_called_once()

    def connect_session(self, session, candidate=None, error=None):
        with patch('blitzcam.server.CameraSession.connect', return_value=session), \
             patch('blitzcam.server.session_timeline', return_value=candidate, side_effect=error):
            self.app.connect()
            deadline = time.monotonic() + 3
            while self.app.connection['state'] == 'connecting' and time.monotonic() < deadline:
                time.sleep(.01)

    def camera_session(self):
        session = Mock()
        session.memory.info.pid = 65388
        session.memory.info.path = Path('wotblitz.exe')
        session.capture.return_value = {'replay': {'time': 2, 'paused': True}, 'camera': {
            'position': [0, 0, 20], 'quaternion': [1, 0, 0, 0], 'horizontal_fov_deg': 60}}
        session.discovery_stats = {'valid_chain_count': 1}
        return session

    def invalidated_replay(self):
        self.app.open_replay(str(self.replay))
        state = await_state(self.app, {'launched'})
        candidate = {**state['replay_launch']['info'], 'source': 'launch_argument'}
        first = self.camera_session()
        self.connect_session(first, candidate)
        first.capture.side_effect = SessionChanged('回放对象已改变，请重新连接。')
        with patch.object(self.app.stop, 'wait', side_effect=[False, True]):
            self.app._poll()
        self.assertEqual(self.app.replay_launch['state'], 'invalidated')
        self.assertFalse(self.app.replay_launch['verified'])
        self.assertEqual(self.app.connection['state'], 'error')
        return candidate

    def test_reconnect_rechecks_invalidated_source_and_clears_old_error(self):
        candidate = self.invalidated_replay()
        session = self.camera_session()
        self.connect_session(session, candidate)
        state = self.app.state()
        self.assertEqual(state['connection']['state'], 'connected')
        self.assertEqual(state['replay_launch']['state'], 'launched')
        self.assertTrue(state['replay_launch']['verified'])
        self.assertEqual(state['replay_launch']['source_state'], 'verified')
        self.assertNotIn('已改变', state['replay_launch']['message'])
        self.assertNotIn('source_warning', state['connection'])

    def test_reconnect_invalidated_source_still_rejects_a_different_file(self):
        self.invalidated_replay()
        session = self.camera_session()
        self.connect_session(session, {'replay_file': str(self.root/'other.wotbreplay')})
        self.assertEqual(self.app.connection['state'], 'error')
        self.assertIsNone(self.app.session)
        self.assertFalse(self.app.replay_launch['verified'])
        self.assertIn('不一致', self.app.connection['message'])
        session.close.assert_called_once()

    def test_reconnect_invalidated_source_without_arguments_reports_current_warning(self):
        self.invalidated_replay()
        session = self.camera_session()
        self.connect_session(session, error=ValueError('no replay argument'))
        self.assertEqual(self.app.connection['state'], 'connected')
        self.assertEqual(self.app.replay_launch['state'], 'launched')
        self.assertFalse(self.app.replay_launch['verified'])
        self.assertEqual(self.app.replay_launch['source_state'], 'unavailable')
        self.assertIn('当前回放文件暂未识别', self.app.connection['message'])
        self.assertNotIn('已改变', self.app.replay_launch['message'])
        self.assertIsNone(self.app.replay_info)
        session.close.assert_not_called()

    def test_missing_source_keeps_camera_and_capture_without_verifying_selected_file(self):
        self.app.open_replay(str(self.replay)); await_state(self.app, {'launched'})
        before = self.app.project.to_dict()
        session = self.camera_session()
        self.connect_session(session, error=ValueError('启动参数没有唯一回放文件。'))
        self.assertEqual(self.app.connection['state'], 'connected')
        self.assertIs(self.app.session, session)
        self.assertIsNone(self.app.replay_info)
        self.assertFalse(self.app.replay_launch['verified'])
        self.assertEqual(self.app.replay_launch['source_state'], 'unavailable')
        self.assertIn('加载稳定后重新连接', self.app.connection['message'])
        self.assertIn('唯一回放文件', self.app.replay_launch['source_error'])
        self.assertEqual(self.app.project.to_dict(), before)
        session.close.assert_not_called()
        # A subsequent successful camera poll must not erase the source warning.
        with patch.object(self.app.stop, 'wait', side_effect=[False, True]):
            self.app._poll()
        self.assertIn('当前回放文件暂未识别', self.app.connection['message'])
        self.app.new_project()
        self.assertEqual(self.app.project.keyframe_times(), [2])

    def test_reconnect_does_not_reuse_an_earlier_verified_file_when_arguments_disappear(self):
        self.app.open_replay(str(self.replay)); state = await_state(self.app, {'launched'})
        first = self.camera_session()
        candidate = {**state['replay_launch']['info'], 'source': 'launch_argument'}
        self.connect_session(first, candidate)
        self.assertTrue(self.app.replay_launch['verified'])
        second = self.camera_session()
        self.connect_session(second, error=ValueError('no replay argument'))
        self.assertEqual(self.app.connection['state'], 'connected')
        first.close.assert_called_once()
        second.close.assert_not_called()
        self.assertFalse(self.app.replay_launch['verified'])
        self.assertIsNone(self.app.replay_info)
        self.app.disconnect()
        self.assertFalse(self.app.replay_launch['verified'])
        third = self.camera_session()
        self.connect_session(third, candidate)
        self.assertTrue(self.app.replay_launch['verified'])
        self.assertEqual(self.app.replay_launch['source_state'], 'verified')
        self.assertNotIn('source_error', self.app.replay_launch)
        self.assertNotIn('source_warning', self.app.connection)

    def test_missing_arguments_allow_independent_camera_playback_but_not_bound_replay_playback(self):
        from blitzcam.project import validate_project
        self.app.open_replay(str(self.replay)); await_state(self.app, {'launched'})
        session = self.camera_session()
        self.connect_session(session, error=ValueError('no replay argument'))
        self.app.project = validate_project({
            'shooting_mode': 'replay', 'replay_timeline': self.app.project.replay_timeline,
            'keyframes': [dict(time_sec=t, position=[t, 0, 20], quaternion=[1, 0, 0, 0],
                               horizontal_fov_deg=60) for t in (0, 8)]})
        with patch('blitzcam.replay_map.launch_replay_path', side_effect=ValueError('no replay argument')), \
             patch.object(self.app.playback, 'start') as start:
            for options in ({}, {'mode': 'current'}, {'mode': 'prepare'}, {'mode': 'locate'},
                            {'reverse': True}, {'speed_only': True}):
                with self.subTest(options=options), \
                     self.assertRaisesRegex(launcher.ReplaySourceUnavailable, '加载稳定后重新连接'):
                    self.app.play(**options)
            start.assert_not_called()
            self.app.project = validate_project({**self.app.project.to_dict(), 'shooting_mode': 'camera_only'})
            self.app.play()
            start.assert_called_once()

    def test_missing_arguments_do_not_bypass_installation_identity(self):
        self.app.open_replay(str(self.replay)); await_state(self.app, {'launched'})
        session = self.camera_session()
        session.memory.info.path = Path('different/wotblitz.exe')
        self.connect_session(session, error=ValueError('no replay argument'))
        self.assertEqual(self.app.connection['state'], 'error')
        self.assertIsNone(self.app.session)
        session.close.assert_called_once()

    def test_manual_runtime_connection_can_create_project_and_play_without_app_launch(self):
        from blitzcam.project import validate_project
        from blitzcam.replay_timeline import file_timeline
        self.app.project = validate_project({**self.app.project.to_dict(), 'shooting_mode':'replay'})
        session = self.camera_session()
        session.capture.return_value['replay']['time'] = 12
        current = {**file_timeline(self.replay), 'source':'runtime_replay', 'verification':'runtime_replay'}
        self.connect_session(session, current)
        self.assertEqual(self.app.replay_launch['state'], 'idle')
        self.assertEqual(self.app.connection['state'], 'connected')
        self.assertNotIn('source_warning', self.app.connection)
        self.app.new_project()
        self.assertEqual(self.app.project.replay_timeline['replay_file'], str(self.replay.resolve()))
        self.assertEqual(self.app.project.keyframe_times(), [12])
        self.app.project = validate_project({
            'shooting_mode':'replay', 'replay_timeline':self.app.project.replay_timeline,
            'keyframes':[dict(time_sec=t, position=[t,0,20], quaternion=[1,0,0,0],
                             horizontal_fov_deg=60) for t in (12,18)]})
        with patch('blitzcam.server.session_timeline', return_value=current), \
                patch.object(self.app.playback, 'start') as start:
            self.app.play(mode='current')
            start.assert_called_once()

    def test_runtime_file_can_match_a_copied_replay_after_process_handoff(self):
        self.app.open_replay(str(self.replay)); state = await_state(self.app, {'launched'})
        session = self.camera_session()
        current = {**state['replay_launch']['info'], 'replay_file':str(self.root/'cached.wotbreplay'),
                   'source':'runtime_replay', 'verification':'runtime_replay'}
        self.connect_session(session, current)
        self.assertEqual(self.app.connection['state'], 'connected')
        self.assertTrue(self.app.replay_launch['verified'])
        self.assertEqual(self.app.replay_info['verification'], 'runtime_replay')
        self.assertEqual(self.app.project.replay_timeline['replay_file'], current['replay_file'])

    def test_manual_replay_switch_is_not_rejected_by_a_previous_launch_request(self):
        from blitzcam.project import validate_project
        self.app.open_replay(str(self.replay)); await_state(self.app, {'launched'})
        self.app.project = validate_project({**self.app.project.to_dict(), 'shooting_mode':'replay'})
        before = self.app.project.to_dict()
        session = self.camera_session()
        current = {'replay_file':str(self.root/'other.wotbreplay'), 'replay_sha256':'b'*64,
                   'source':'runtime_replay', 'verification':'runtime_replay', 'duration_sec':300}
        self.connect_session(session, current)
        self.assertEqual(self.app.connection['state'], 'connected')
        self.assertEqual(self.app.replay_launch['state'], 'idle')
        self.assertEqual(self.app.replay_info, current)
        self.assertEqual(self.app.project.to_dict(), before)
        session.close.assert_not_called()
        with patch('blitzcam.server.session_timeline', return_value=current), \
                patch.object(self.app.playback, 'start') as start:
            with self.assertRaisesRegex(CameraError, '与项目绑定不一致'):
                self.app.play()
            start.assert_not_called()

    def test_new_path_uses_verified_opened_file_after_old_keys_failed_to_fit(self):
        self.app.session=Mock()
        self.app.session.capture.return_value={'replay':{'time':12,'paused':True},'camera':{
            'position':[0,0,20],'quaternion':[1,0,0,0],'horizontal_fov_deg':60}}
        self.app.replay_info={'source':'blitz_camera','duration_sec':20,'replay_file':str(self.replay)}
        self.app.replay_launch.update(verified=True)
        self.app.new_project()
        self.assertEqual(self.app.project.replay_timeline['duration_sec'],20)
        self.assertEqual(self.app.project.replay_timeline['replay_file'],str(self.replay))
        self.assertEqual(self.app.project.keyframe_times(),[12])


if __name__ == '__main__':unittest.main()
