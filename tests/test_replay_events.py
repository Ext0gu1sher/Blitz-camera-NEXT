import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from blitzcam.channels import track_controls
from blitzcam.project import validate_project
from blitzcam.replay_events import battle_start_from_data
from blitzcam.replay_timeline import (file_timeline, replay_keyframe_guard,
                                     validate_new_keyframes, validate_timeline)
from blitzcam.settings import read_settings, save_settings
from tests.fixtures.replay_data import header, packet


def arena_payload(period=3, remaining=420., method=48, wrapper=3):
    # period3 bytes match the pinned Agent's real J39 PERIOD regression fixture:
    # 1a0e0803110000000000407a4018a403.
    nested = bytes((8, period, 17)) + struct.pack('<d', remaining) + bytes.fromhex('18a403')
    root = bytes((26, len(nested))) + nested
    args = bytes((wrapper, len(root))) + root
    return struct.pack('<III', 123, method, len(args)) + args


def data_with_events(events=None, origin=4.25):
    events = [(8, 18.727, arena_payload())] if events is None else events
    return (header() + packet(0x11, origin)
            + b''.join(packet(kind, clock, payload) for kind, clock, payload in events)
            + packet(0xFFFFFFFF, 0))


def project(times=(20, 40), **timeline):
    return validate_project({'keyframes':[
        {'time_sec':t, 'position':[t,0,20], 'quaternion':[1,0,0,0], 'horizontal_fov_deg':60}
        for t in times], 'shooting_mode':'replay',
        'replay_timeline':{'time_basis':'replay', 'duration_sec':300,
                           'work_start_sec':0, 'work_end_sec':60,
                           'replay_file':'chosen.wotbreplay', 'battle_start_status':'identified',
                           'battle_start_sec':15., **timeline}})


class BattleStartTests(unittest.TestCase):
    def test_explicit_period_uses_replay_player_origin_not_packet_clock(self):
        info = battle_start_from_data(data_with_events(), '11.21.0')
        raw = struct.unpack('<f', struct.pack('<f', 18.727))[0]
        self.assertEqual(info['battle_start_status'], 'identified')
        self.assertEqual(info['battle_start_raw_sec'], raw)
        self.assertEqual(info['battle_start_sec'], raw - 4.25)
        self.assertEqual(info['replay_origin_sec'], 4.25)

    def test_first_battle_event_wins_after_waiting_and_prebattle(self):
        info = battle_start_from_data(data_with_events([
            (8, 5, arena_payload(1)), (8, 10, arena_payload(2)),
            (8, 20, arena_payload(3)), (8, 25, arena_payload(3)),
            (8, 50, arena_payload(4))]), '11.19.0_china')
        self.assertEqual(info['battle_start_sec'], 15.75)

    def test_phase_and_packet_markers_embedded_in_other_payloads_are_not_events(self):
        fake = packet(8, 20, arena_payload())
        for events in ([], [(0, 0, fake)], [(7, 20, arena_payload())],
                       [(8, 20, arena_payload(method=47))], [(8, 20, arena_payload(wrapper=1))],
                       [(8, 20, arena_payload(period=2))]):
            with self.subTest(events=events):
                self.assertEqual(battle_start_from_data(data_with_events(events), '11.21.0')['battle_start_status'], 'unavailable')

    def test_no_fixed_countdown_or_metadata_timestamp_fallback(self):
        info = battle_start_from_data(data_with_events([]), '11.21.0')
        self.assertIsNone(info['battle_start_sec'])
        self.assertEqual(info['battle_start_status'], 'unavailable')
        self.assertIn('手动', info['battle_start_reason'])

    def test_unknown_version_is_unavailable(self):
        for version in ('', '11.17.0', '11.22.0', '12.0.0', 'garbage'):
            with self.subTest(version=version):
                info = battle_start_from_data(data_with_events(), version)
                self.assertEqual(info['battle_start_status'], 'unavailable')
                self.assertIsNone(info['battle_start_sec'])

    def test_started_before_replay_origin_has_no_protected_segment(self):
        self.assertEqual(battle_start_from_data(data_with_events(origin=30), '11.21.0')['battle_start_sec'], 0)

    def test_bad_envelopes_protobuf_lengths_clocks_and_remaining_are_not_promoted(self):
        payloads = [b'', arena_payload()[:-1], arena_payload(remaining=float('nan')),
                    arena_payload(remaining=-1), arena_payload(remaining=float('inf'))]
        for offset, value in ((8, 100000), (13, 254), (15, 250)):
            body = bytearray(arena_payload())
            if offset == 8: struct.pack_into('<I', body, offset, value)
            else: body[offset] = value
            payloads.append(body)
        for body in payloads:
            with self.subTest(body=body):
                self.assertEqual(battle_start_from_data(data_with_events([(8, 20, body)]), '11.21.0')['battle_start_status'], 'unavailable')
        for clock in (float('nan'), float('inf'), -1, 3601):
            with self.subTest(clock=clock):
                self.assertEqual(battle_start_from_data(data_with_events([(8, clock, arena_payload())]), '11.21.0')['battle_start_status'], 'unavailable')

    def test_missing_origin_truncated_frame_and_post_terminator_do_not_create_start(self):
        inputs = [header()+packet(8, 20, arena_payload()),
                  header()+packet(0x11, 4.25)+packet(8, 20, arena_payload())[:-1],
                  data_with_events([])+packet(8, 20, arena_payload())]
        for data in inputs:
            with self.subTest(data=data):
                self.assertEqual(battle_start_from_data(data, '11.21.0')['battle_start_status'], 'unavailable')

    def test_missing_data_is_unavailable_and_bounded_metadata_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'replay.wotbreplay'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('meta.json', json.dumps({'battleDuration':300, 'version':'11.21.0'}))
            info = file_timeline(path)
            self.assertEqual(info['duration_sec'], 300)
            self.assertEqual(info['battle_start_status'], 'unavailable')

    def test_file_timeline_and_project_roundtrip_keep_event_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'replay.wotbreplay'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('meta.json', json.dumps({'battleDuration':300, 'version':'11.21.0'}))
                archive.writestr('data.wotreplay', data_with_events())
            before = path.read_bytes(); info = file_timeline(path)
            self.assertEqual(path.read_bytes(), before)
            timeline = validate_timeline({**info, 'time_basis':'replay', 'work_start_sec':0, 'work_end_sec':30})
            for name in ('battle_start_sec', 'battle_start_raw_sec', 'replay_origin_sec', 'battle_start_status'):
                self.assertEqual(timeline[name], info[name])
            saved = project(**timeline).to_dict()['replay_timeline']
            self.assertEqual(saved['battle_start_sec'], info['battle_start_sec'])

    def test_start_outside_metadata_duration_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'replay.wotbreplay'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('meta.json', json.dumps({'battleDuration':2, 'version':'11.21.0'}))
                archive.writestr('data.wotreplay', data_with_events())
            self.assertEqual(file_timeline(path)['battle_start_status'], 'unavailable')


class KeyframeGuardTests(unittest.TestCase):
    def test_boundary_is_automatic_unless_manually_overridden(self):
        t = project().replay_timeline
        self.assertEqual(replay_keyframe_guard(t, {})['start_sec'], 15)
        self.assertEqual(replay_keyframe_guard(t, {'replay_keyframe_start_seconds':8})['start_sec'], 8)
        self.assertEqual(replay_keyframe_guard(t, {'replay_keyframe_start_seconds':0})['start_sec'], 0)
        self.assertFalse(replay_keyframe_guard({**t, 'replay_file':''}, {})['enabled'])

    def test_guard_accepts_cached_metadata_for_legacy_timeline(self):
        t = project().replay_timeline
        del t['battle_start_status']; del t['battle_start_sec']
        self.assertIsNone(replay_keyframe_guard(t, {})['start_sec'])
        self.assertEqual(replay_keyframe_guard(t, {}, {'battle_start_status':'identified', 'battle_start_sec':12})['start_sec'],12)

    def test_early_add_and_move_rejected_but_boundary_and_later_keys_allowed(self):
        old = project()
        for times in ((10, 20, 40), (10, 40)):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, '此前不能'):
                validate_new_keyframes(old, project(times), {})
        validate_new_keyframes(old, project((15, 20, 40)), {})
        validate_new_keyframes(old, project((20, 30, 40)), {})

    def test_existing_early_keys_remain_loadable_and_editable_in_place(self):
        old = project((1, 40)); candidate = old.to_dict()
        candidate['keyframes'][0]['position'][0] = 3
        validate_new_keyframes(old, validate_project(candidate), {})
        validate_new_keyframes(old, project((40,)), {})
        with self.assertRaises(ValueError):validate_new_keyframes(old, project((2,40)), {})

    def test_unknown_battle_start_blocks_new_camera_times_only(self):
        old = project(battle_start_status='unavailable', battle_start_sec=None)
        validate_new_keyframes(old, old, {})
        candidate = old.to_dict(); candidate['replay_speed'] = {'mode':'fixed', 'rate':.5}
        validate_new_keyframes(old, validate_project(candidate), {})
        with self.assertRaisesRegex(ValueError, '手动填写'):
            validate_new_keyframes(old, project((20, 40, 50), battle_start_status='unavailable', battle_start_sec=None), {})

    def test_independent_camera_tracks_check_their_own_times_not_union(self):
        old = project((1, 40)); old_data = old.to_dict()
        old_data['camera_tracks'] = track_controls(old)
        # Keep only x's legacy early key. A new y key at that same union time
        # is still a new early key and must not slip through the projection.
        old_data['camera_tracks']['y'] = [old_data['camera_tracks']['y'][-1]]
        old = validate_project(old_data); new_data = old.to_dict()
        new_data['camera_tracks']['y'].insert(0, {'time_sec':1., 'value':0.})
        with self.assertRaises(ValueError):validate_new_keyframes(old, validate_project(new_data), {})

    def test_camera_only_and_unbound_projects_can_still_author_early_keys(self):
        old = project(); new = project((1,20,40))
        for p in (old,new):p.shooting_mode='camera_only'
        validate_new_keyframes(old,new,{})
        for p in (old,new):p.shooting_mode='replay';p.replay_timeline.pop('replay_file')
        validate_new_keyframes(old,new,{})


class KeyframeStartSettingsTests(unittest.TestCase):
    def test_default_automatic_manual_override_and_reset_are_persistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_settings(tmp)['replay_keyframe_start_seconds'])
            directory = str((Path(tmp)/'projects').resolve())
            manual = save_settings(tmp, {'project_directory':directory, 'replay_keyframe_start_seconds':12.5})
            self.assertEqual(manual['replay_keyframe_start_seconds'],12.5)
            self.assertEqual(save_settings(tmp, {'project_directory':directory})['replay_keyframe_start_seconds'],12.5)
            automatic = save_settings(tmp, {'project_directory':directory, 'replay_keyframe_start_seconds':None})
            self.assertIsNone(automatic['replay_keyframe_start_seconds'])

    def test_invalid_manual_boundaries_do_not_overwrite_saved_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = str((Path(tmp)/'projects').resolve())
            good = save_settings(tmp, {'project_directory':directory, 'replay_keyframe_start_seconds':0})
            for invalid in (-1, 3601, True, '15', float('nan'), float('inf')):
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                    save_settings(tmp, {'project_directory':directory, 'replay_keyframe_start_seconds':invalid})
                self.assertEqual(read_settings(tmp),good)
