"""Independent camera persistence and empty tracks; no game access."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from blitzcam.channels import CHANNELS, track_controls
from blitzcam.multicam import alternatives, camera_project
from blitzcam.project import controls, edit_project, read_project, samples, validate_project
from blitzcam.server import Workstation


def fixture():
    data = {'shooting_mode': 'replay', 'keyframes': [
        {'time_sec': t, 'position': [t, 2, 3], 'quaternion': [1, 0, 0, 0], 'horizontal_fov_deg': 60}
        for t in (20, 30)], 'replay_timeline': {'time_basis': 'replay', 'duration_sec': 100, 'work_start_sec': 20, 'work_end_sec': 30},
        'replay_speed': {'mode': 'fixed', 'rate': 1, 'camera_clock': 'replay'}}
    tracks = track_controls(validate_project(data))
    second = deepcopy(tracks)
    for key in second['x']:
        key['value'] += 100
    data['camera_tracks'] = tracks
    data['multicam'] = {'version': 2, 'active_camera_id': 'a', 'cameras': [
        {'id': 'a', 'name': '主机位', 'camera_tracks': tracks},
        {'id': 'b', 'name': '侧面', 'camera_tracks': second, 'replay_speed': {'mode': 'fixed', 'rate': .5},
         'work_range': {'work_start_sec': 21, 'work_end_sec': 29}, 'easing': 'ease_in'}]}
    return data


class MulticamTests(unittest.TestCase):
    def test_roundtrip_keeps_complete_independent_cameras(self):
        p = validate_project(fixture())
        self.assertEqual(p.sample(25).position[0], 25)
        other = alternatives(p)['b']
        self.assertEqual(other.sample(20).position[0], 120)
        self.assertEqual(other.replay_speed['rate'], .5)
        self.assertEqual(other.replay_timeline['work_start_sec'], 21)
        self.assertEqual(other.easing, 'ease_in')
        self.assertEqual(validate_project(p.to_dict()).to_dict(), p.to_dict())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'project.json'
            path.write_text(json.dumps(p.to_dict()), encoding='utf-8')
            self.assertEqual(read_project(path).to_dict(), p.to_dict())

    def test_edit_and_switch_preserve_other_camera_settings(self):
        p = validate_project(fixture())
        tracks = track_controls(p);tracks['x'][0]['value'] = 55
        updated = edit_project({'keyframes': controls(p), 'camera_track_controls': tracks, 'multicam': p.multicam,
                                'replay_timeline': p.replay_timeline, 'shooting_mode': 'replay', 'replay_speed': {'mode': 'fixed', 'rate': .25}})
        cameras = updated.multicam['cameras']
        self.assertEqual(cameras[0]['camera_tracks']['x'][0]['value'], 55)
        self.assertEqual(cameras[1]['camera_tracks']['x'][0]['value'], 120)
        self.assertEqual(cameras[0]['replay_speed']['rate'], .25)
        self.assertEqual(cameras[1]['replay_speed']['rate'], .5)
        switched = camera_project(updated, cameras[1]).to_dict()
        switched['multicam'] = deepcopy(updated.multicam)
        switched['multicam']['active_camera_id'] = 'b'
        new = validate_project(switched)
        self.assertEqual(new.replay_speed['rate'], .5)
        self.assertEqual(new.replay_timeline['work_start_sec'], 21)
        self.assertEqual(new.multicam['cameras'][0], cameras[0])

    def test_empty_camera_can_save_reload_and_add_single_channel(self):
        data = fixture()
        data['camera_tracks'] = {name: [] for name in CHANNELS};data['keyframes'] = []
        p = validate_project(data)
        self.assertEqual(p.keyframes, ())
        self.assertEqual(p.keyframe_times(), [])
        self.assertEqual(samples(p, 30), [])
        self.assertEqual(p.sample_uniform(30), [])
        self.assertEqual(p.length, 0)
        self.assertEqual(p.duration, 0)
        self.assertEqual(p.to_dict()['keyframes'], [])
        with tempfile.TemporaryDirectory() as folder, patch('blitzcam.server.OUTPUT', Path(folder)):
            app = Workstation()
            try:
                app.project_path = Path(folder)/'empty.json';app.project = p
                app.set_project(p, 0)
                restored = read_project(app.project_path)
                self.assertEqual(restored.to_dict(), p.to_dict())
                with self.assertRaisesRegex(ValueError, '机位为空'): app.play()
            finally: app.close()
        data['camera_tracks']['x'] = [{'time_sec': 22, 'value': 45}]
        p = validate_project(data)
        self.assertEqual(p.sample(22).position, (45, 0, 0))
        self.assertEqual(p.sample(22).horizontal_fov_deg, 60)
        self.assertEqual(p.camera_tracks['zoom'], [])
        self.assertEqual(len(p.keyframes), 1)

    def test_zero_cameras_and_limit(self):
        data = fixture()
        data['camera_tracks'] = {name: [] for name in CHANNELS};data['keyframes'] = []
        data['multicam'] = {'version': 2, 'active_camera_id': None, 'cameras': []}
        p = validate_project(data)
        self.assertEqual(validate_project(p.to_dict()).multicam, data['multicam'])
        data = fixture()
        first = data['multicam']['cameras'][0]
        data['multicam']['cameras'] = [{**deepcopy(first), 'id': str(i)} for i in range(16)]
        data['multicam']['active_camera_id'] = '0'
        self.assertEqual(len(validate_project(data).multicam['cameras']), 16)
        data['multicam']['cameras'].append({**deepcopy(first), 'id': '16'})
        with self.assertRaisesRegex(ValueError, '16'):validate_project(data)

    def test_invalid_inactive_camera_and_ids_are_rejected(self):
        def invalid_zoom(d): d['multicam']['cameras'][1]['camera_tracks']['zoom'][0]['value'] = 180
        def absent_active(d): d['multicam']['active_camera_id'] = 'missing'
        def duplicate_camera(d): d['multicam']['cameras'][1]['id'] = 'a'
        def bad_time(d): d['multicam']['cameras'][1]['camera_tracks']['x'][1]['time_sec'] = 101
        def bad_version(d): d['multicam']['version'] = True
        for mutate in (invalid_zoom, absent_active, duplicate_camera, bad_time, bad_version):
            data = fixture();mutate(data)
            with self.subTest(mutate=mutate.__name__), self.assertRaises(ValueError): validate_project(data)

    def test_camera_slots_validate_and_roundtrip(self):
        data = fixture()
        data['multicam']['cameras'][0]['slot'] = 3
        data['multicam']['cameras'][1]['slot'] = 7
        p = validate_project(data)
        self.assertEqual([c['slot'] for c in p.multicam['cameras']], [3, 7])
        self.assertEqual([c['slot'] for c in validate_project(p.to_dict()).multicam['cameras']], [3, 7])
        legacy = fixture()
        self.assertNotIn('slot', validate_project(legacy).multicam['cameras'][0])
        def out_of_range(d): d['multicam']['cameras'][0]['slot'] = 16
        def negative(d): d['multicam']['cameras'][0]['slot'] = -1
        def bool_slot(d): d['multicam']['cameras'][0]['slot'] = True
        def text_slot(d): d['multicam']['cameras'][0]['slot'] = '0'
        def duplicate(d): d['multicam']['cameras'][1]['slot'] = 3
        for mutate in (out_of_range, negative, bool_slot, text_slot, duplicate):
            data = fixture();data['multicam']['cameras'][0]['slot'] = 3;mutate(data)
            with self.subTest(mutate=mutate.__name__), self.assertRaises(ValueError): validate_project(data)

    def test_existing_single_camera_projects_keep_their_format(self):
        data = fixture();data.pop('multicam')
        p = validate_project(data)
        self.assertNotIn('multicam', p.to_dict())
        self.assertEqual(alternatives(p), {})

    def test_old_grouped_cameras_flatten_without_losing_any_tracks(self):
        data = fixture();cameras = data['multicam']['cameras']
        shot = {'id': 'one', 'name': '旧分组', 'start_sec': 20, 'end_sec': 30,
                'active_camera_id': 'a', 'adopted_camera_id': 'b', 'cameras': cameras}
        data['multicam'] = {'version': 1, 'active_shot_id': 'one', 'shots': [shot, {**deepcopy(shot), 'id': 'two'}]}
        p = validate_project(data)
        self.assertEqual(len(p.multicam['cameras']), 4)
        self.assertEqual(len({c['id'] for c in p.multicam['cameras']}), 4)
        self.assertEqual(p.multicam['version'], 2)
        self.assertNotIn('shots', p.multicam)
        self.assertEqual(p.multicam['cameras'][1]['camera_tracks'], cameras[1]['camera_tracks'])

    def test_workstation_save_revision_and_selected_playback(self):
        with tempfile.TemporaryDirectory() as folder, patch('blitzcam.server.OUTPUT', Path(folder)):
            app = Workstation()
            try:
                app.project_path = Path(folder)/'project.json';app.project = validate_project(fixture())
                app.set_project(validate_project(fixture()), 0)
                with self.assertRaises(ValueError): app.set_project(validate_project(fixture()), 0)
                self.assertEqual(read_project(app.project_path).multicam, app.project.multicam)
                app.session = Mock();app.session.capture.return_value = {'camera': {}, 'replay': {'time': 25, 'paused': True}}
                app.playback = Mock();app.playback.state.return_value = {'active': False}
                app.play(mode='current')
                played = app.playback.start.call_args.args[0]
                self.assertEqual(played.sample(25).position[0], 25)
                self.assertEqual(app.project.sample(25).position[0], 25)
                app.session = None
            finally: app.close()

    def test_guard_checks_inactive_cameras_too(self):
        with tempfile.TemporaryDirectory() as folder, patch('blitzcam.server.OUTPUT', Path(folder)):
            app = Workstation()
            try:
                data = fixture();data['replay_timeline']['replay_file'] = 'missing.wotbreplay'
                app.project_path = Path(folder)/'project.json';app.project = validate_project(data)
                changed = deepcopy(data)
                changed['multicam']['cameras'][1]['camera_tracks']['x'][0]['time_sec'] = 10
                with patch.object(app, '_keyframe_metadata', return_value={'battle_start_status': 'identified', 'battle_start_sec': 15}):
                    with self.assertRaises(ValueError):app.set_project(validate_project(changed))
                self.assertFalse(app.project_path.exists())
            finally:app.close()


if __name__ == '__main__': unittest.main()
