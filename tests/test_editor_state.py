import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blitzcam.editor_state import editor_state_path, read_editor_state, validate_editor_state
from blitzcam.server import Workstation


class EditorSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        documents = patch('blitzcam.settings.documents_directory', return_value=self.out/'Documents')
        documents.start(); self.addCleanup(documents.stop)
        self.patch = patch('blitzcam.server.OUTPUT', self.out)
        self.patch.start()
        self.app = Workstation(self.out/'project.json')
        self.app.set_project(self.app.project)
        self.value = {'schema_version': 1, 'saved_at': 1234, 'timeline': {'scale': 90, 'scroll_left': 123, 'scroll_top': 42, 'playhead': 4.2},
                      'preview': {'view': 'camera', 'override': {'position': [1, 2, 3], 'yaw': 42, 'pitch': -3, 'roll': 0, 'zoom': 65}}}

    def tearDown(self):
        self.app.close(); self.patch.stop(); self.tmp.cleanup()

    def save(self, value=None, **kwargs):
        return self.app.save_editor_state(str(self.app.project_path), value or self.value, **kwargs)

    def test_session_survives_restart_without_changing_authored_project(self):
        before = self.app.project_path.read_bytes()
        revision = self.app.project_revision
        self.save()
        self.assertEqual(self.app.project_path.read_bytes(), before)
        self.assertEqual(self.app.project_revision, revision)
        self.assertEqual(self.app.state()['editor_state'], self.value)
        self.app.close()
        self.app = Workstation(self.out/'project.json')
        self.assertEqual(self.app.state()['editor_state'], self.value)

    def test_sessions_are_per_project_and_save_as_copies_current_view(self):
        original = self.app.project_path
        self.save()
        self.app.save_project_as(self.out/'copy.json')
        self.assertEqual(self.app.state()['editor_state'], self.value)
        changed = copy.deepcopy(self.value); changed['timeline']['playhead'] = 7
        self.save(changed)
        self.app.open_project(original)
        self.assertEqual(self.app.state()['editor_state'], self.value)
        self.assertNotEqual(editor_state_path(self.out, original), editor_state_path(self.out, self.out/'copy.json'))

    def test_delayed_old_window_cannot_save_to_new_project(self):
        original = str(self.app.project_path)
        self.app.new_project_file('second')
        with self.assertRaisesRegex(ValueError, '项目已切换'):
            self.app.save_editor_state(original, self.value)
        self.assertIsNone(self.app.state()['editor_state'])

    def test_close_can_atomically_save_valid_final_draft(self):
        data = self.app.state()
        frames = data['keyframe_controls']; frames[0]['position'][0] += 9
        draft = {'keyframes': frames, 'camera_track_controls': data['camera_track_controls'],
                 'shooting_mode': self.app.project.shooting_mode, 'replay_timeline': data['project'].get('replay_timeline')}
        draft['camera_track_controls']['x'][0]['value'] += 9
        self.save(draft=draft, expected_revision=data['project_revision'])
        self.assertEqual(self.app.project_revision, data['project_revision']+1)
        self.assertEqual(self.app.state()['camera_track_controls']['x'][0]['value'], draft['camera_track_controls']['x'][0]['value'])

    def test_stale_draft_is_not_allowed_to_overwrite_other_window(self):
        data = self.app.state()
        with self.assertRaisesRegex(ValueError, '其他窗口'):
            self.save(draft={'keyframes': data['keyframe_controls']}, expected_revision=-1)
        self.assertEqual(self.app.project_revision, data['project_revision'])
        self.assertEqual(self.app.state()['editor_state'], self.value)

    def test_invalid_or_oversized_state_is_rejected_and_corrupt_file_ignored(self):
        for value in ({'schema_version': 2}, {'schema_version': 1, 'timeline': {'scale': float('nan')}}, {'schema_version': 1, 'preview': 'x'*40000}):
            with self.assertRaises(ValueError): validate_editor_state(value)
        path = editor_state_path(self.out, self.app.project_path); path.parent.mkdir(parents=True)
        path.write_text('{broken', encoding='utf-8')
        self.assertIsNone(read_editor_state(self.out, self.app.project_path))


if __name__ == '__main__': unittest.main()
