"""BPM settings survive project saves and camera changes; malformed data is rejected."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from blitzcam.beat_grid import validate_beat_grid
from blitzcam.multicam import alternatives
from blitzcam.project import atomic_json, controls, edit_project, read_project, validate_project
from tests.test_multicam import fixture


SETTINGS = {'version': 1, 'enabled': True, 'bpm': 137.125, 'division': 4,
            'origin': 'playhead', 'anchor_sec': 23.75, 'offset_sec': -0.123456}


class BeatGridTests(unittest.TestCase):
    def test_legacy_project_has_no_added_track(self):
        self.assertNotIn('beat_grid', validate_project(fixture()).to_dict())

    def test_save_edit_and_all_cameras_preserve_settings(self):
        source = fixture()
        source['beat_grid'] = deepcopy(SETTINGS)
        project = validate_project(source)
        for camera in alternatives(project).values():
            self.assertEqual(camera.to_dict()['beat_grid'], SETTINGS)
        updated = edit_project({**project.to_dict(), 'keyframes': controls(project),
                               'camera_track_controls': project.camera_tracks})
        self.assertEqual(updated.to_dict()['beat_grid'], SETTINGS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bpm.json'
            atomic_json(path, updated.to_dict())
            self.assertEqual(read_project(path).to_dict()['beat_grid'], SETTINGS)
        project.beat_grid['enabled'] = False
        self.assertEqual(validate_project(project.to_dict()).beat_grid, {**SETTINGS, 'enabled': False})

    def test_invalid_values_do_not_enter_saved_projects(self):
        cases = {'version': [2, True], 'enabled': [1, 'yes'], 'bpm': [0, 301, True, float('nan')],
                 'division': [0, 3, True, 2.0], 'origin': ['event', None],
                 'offset_sec': [-61, 61, float('inf')], 'anchor_sec': [-1, 1e8, False]}
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_beat_grid({**SETTINGS, key: value})


if __name__ == '__main__':
    unittest.main()
