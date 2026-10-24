"""Portable replay identity and relinking; no game process is accessed."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from blitzcam.project import read_project, validate_project
from blitzcam.replay_timeline import file_timeline, replay_matches, validate_timeline
from blitzcam.server import Workstation
from tests.test_replay_launcher import await_state
from tests.test_replay_events import arena_payload, data_with_events


def write_replay(path, payload=b'original replay'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('meta.json', json.dumps({'battleDuration':60, 'version':'11.21'}))
        archive.writestr('data.wotreplay', data_with_events([(0,0,payload),(8,4.25,arena_payload())]))


class ReplayIdentityTests(unittest.TestCase):
    def test_content_identity_survives_copy_rename_timestamp_and_missing_original(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder)/'old computer'/'source.wotbreplay'
            write_replay(original)
            bound = file_timeline(original)
            copy = Path(folder)/'新电脑'/'renamed.wotbreplay'
            copy.parent.mkdir(); copy.write_bytes(original.read_bytes())
            os.utime(copy, (1000000000, 1000000000))
            original.unlink()
            self.assertEqual(bound['replay_sha256'], hashlib.sha256(copy.read_bytes()).hexdigest())
            self.assertTrue(replay_matches(bound, file_timeline(copy)))

    def test_same_filename_duration_and_metadata_do_not_accept_different_content(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = (Path(folder)/name/'same.wotbreplay' for name in ('a', 'b'))
            write_replay(a); write_replay(b, b'different replay')
            bound = file_timeline(a)
            self.assertFalse(replay_matches(bound, file_timeline(b)))
            a.write_bytes(b.read_bytes())
            self.assertFalse(replay_matches(bound, file_timeline(a)))

    def test_hash_roundtrip_and_validation(self):
        timeline = dict(time_basis='replay', duration_sec=60, work_start_sec=10,
                        work_end_sec=18, replay_file='old.wotbreplay', replay_sha256='AB'*32)
        self.assertEqual(validate_timeline(timeline)['replay_sha256'], 'ab'*32)
        for digest in (None, 3, '', 'a'*63, 'g'*64):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                validate_timeline({**timeline, 'replay_sha256':digest})

    def test_readable_legacy_project_can_compare_content_at_another_path(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = (Path(folder)/name for name in ('a.wotbreplay', 'b.wotbreplay'))
            write_replay(a); b.write_bytes(a.read_bytes())
            self.assertTrue(replay_matches({'replay_file':str(a)}, file_timeline(b)))
            a.unlink()
            self.assertFalse(replay_matches({'replay_file':str(a)}, file_timeline(b)))


class ProjectReplayRelinkingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = patch('blitzcam.server.OUTPUT', self.root/'output')
        self.output.start(); self.addCleanup(self.output.stop)
        self.original = self.root/'old computer'/'shot.wotbreplay'
        write_replay(self.original)
        self.info = file_timeline(self.original)
        self.project_path = self.root/'projects'/'镜头.json'
        self.app = Workstation(self.project_path)
        self.addCleanup(self.app.close)
        self.app.stop.set(); self.app.poller.join(); self.app.stop.clear()
        self.app.set_project(validate_project({
            'shooting_mode':'replay', 'position_interpolation':'linear',
            'replay_timeline':dict(self.info, time_basis='replay', duration_sec=60,
                work_start_sec=10, work_end_sec=18, replay_file=str(self.original),
                replay_sha256=self.info['replay_sha256']),
            'replay_speed':{'mode':'curve', 'camera_clock':'replay'},
            'keyframes':[dict(time_sec=t, position=[t,2,10], quaternion=[1,0,0,0],
                              horizontal_fov_deg=60) for t in (10,18)]}))
        self.before = self.app.project.to_dict()
        self.local = self.root/'new computer'/'renamed.wotbreplay'
        self.local.parent.mkdir(); self.local.write_bytes(self.original.read_bytes())
        self.original.unlink()
        self.picker = patch('blitzcam.replay_launcher.choose_replay', return_value=self.local).start()
        self.locator = patch('blitzcam.replay_launcher.locate_client', return_value=Path('wotblitz.exe')).start()
        self.launch = patch('blitzcam.replay_launcher.launch_replay', return_value=SimpleNamespace(pid=123)).start()
        self.addCleanup(patch.stopall)

    def assert_authored_data_preserved(self):
        actual = self.app.project.to_dict()
        expected = deepcopy(self.before)
        expected['replay_timeline'].update(replay_file=str(self.local.resolve()),
                                          replay_sha256=self.info['replay_sha256'])
        self.assertEqual(actual, expected)
        self.assertEqual(read_project(self.project_path).to_dict(), expected)

    def test_project_replay_picker_relinks_and_saves_same_copy_then_reopens_directly(self):
        self.app.open_project_replay()
        state = await_state(self.app, {'launched', 'error'})
        self.assertEqual(state['replay_launch']['state'], 'launched')
        self.picker.assert_called_once(); self.assert_authored_data_preserved()
        self.picker.reset_mock(); self.app.open_project_replay()
        self.assertEqual(await_state(self.app, {'launched', 'error'})['replay_launch']['state'], 'launched')
        self.picker.assert_not_called()

    def test_same_folder_copy_is_resolved_automatically_by_saved_hash(self):
        nearby = self.project_path.parent/self.original.name
        nearby.write_bytes(self.local.read_bytes()); self.local = nearby
        self.app.open_project_replay()
        self.assertEqual(await_state(self.app, {'launched', 'error'})['replay_launch']['state'], 'launched')
        self.picker.assert_not_called(); self.assert_authored_data_preserved()

    def test_wrong_selected_content_never_launches_or_rebinds(self):
        write_replay(self.local, b'another battle with the same metadata')
        self.app.open_project_replay()
        state = await_state(self.app, {'launched', 'error'})
        self.assertEqual(state['replay_launch']['state'], 'error')
        self.assertIn('回放内容不同', state['replay_launch']['message'])
        self.launch.assert_not_called()
        self.assertEqual(self.app.project.to_dict(), self.before)
        self.assertEqual(read_project(self.project_path).to_dict(), self.before)

    def test_cancel_relink_does_not_launch_or_change_project(self):
        self.picker.return_value = None
        self.app.open_project_replay()
        self.assertEqual(await_state(self.app, {'cancelled', 'error'})['replay_launch']['state'], 'cancelled')
        self.launch.assert_not_called()
        self.assertEqual(read_project(self.project_path).to_dict(), self.before)

    def test_legacy_missing_source_can_be_selected_once_and_upgraded(self):
        legacy = deepcopy(self.before); legacy['replay_timeline'].pop('replay_sha256')
        self.app.set_project(validate_project(legacy))
        self.app.open_project_replay()
        self.assertEqual(await_state(self.app, {'launched', 'error'})['replay_launch']['state'], 'launched')
        self.picker.assert_called_once(); self.assert_authored_data_preserved()

    def test_save_as_upgrades_readable_legacy_source(self):
        legacy = deepcopy(self.before)
        legacy['replay_timeline'].pop('replay_sha256')
        legacy['replay_timeline']['replay_file'] = str(self.local)
        self.app.project = validate_project(legacy)
        saved = self.root/'saved.json'
        self.app.save_project_as(saved)
        self.assertEqual(read_project(saved).replay_timeline['replay_sha256'], self.info['replay_sha256'])

    def test_play_uses_content_identity_without_original_path(self):
        self.app.session = Mock()
        self.app.session.capture.return_value = {'replay':{'time':12, 'paused':True}}
        with patch('blitzcam.server.session_timeline', return_value=file_timeline(self.local)), \
                patch.object(self.app.playback, 'start') as start:
            self.app.play()
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0].start_time, 12)
        self.assertEqual(self.app.project.to_dict(), self.before)


if __name__ == '__main__':
    unittest.main()
