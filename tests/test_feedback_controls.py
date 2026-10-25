"""Service regression coverage for capture controls and pre-battle protection."""
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch
import zipfile

from blitzcam.channels import track_controls
from blitzcam.editor_state import editor_state_path
from blitzcam.project import atomic_json, controls, validate_project
from blitzcam.replay_timeline import file_timeline
from blitzcam.server import Workstation, make_handler
from tests.test_replay_events import arena_payload, data_with_events


class FeedbackControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.patchers = [patch('blitzcam.server.OUTPUT', self.out),
                         patch('blitzcam.settings.documents_directory', return_value=self.out/'Documents'),
                         patch('blitzcam.replay_preview.OUTPUT', self.out)]
        for patcher in self.patchers:patcher.start()
        self.app = Workstation(self.out/'project.json')
        self.app.stop.set(); self.app.poller.join()
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.http.server_address[1])
        self.replay = self.out/'chosen.wotbreplay'
        self.write_replay(self.replay)
        self.bind()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.app.close()
        for patcher in reversed(self.patchers):patcher.stop()
        self.tmp.cleanup()

    def write_replay(self, path, start=20., *, event=True):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('meta.json', json.dumps({'battleDuration':300, 'version':'11.21.0'}))
            archive.writestr('data.wotreplay', data_with_events([(8,start,arena_payload())] if event else []))

    def project(self, times=(1.,40.), mode='replay', timeline=None):
        if timeline is None:
            timeline = {'time_basis':'replay', 'duration_sec':300., 'work_start_sec':0.,
                        'work_end_sec':60., 'replay_file':str(self.replay)}
        return validate_project({'keyframes':[
            {'time_sec':t, 'position':[t,0,20], 'quaternion':[1,0,0,0], 'horizontal_fov_deg':60}
            for t in times], 'shooting_mode':mode, 'position_interpolation':'linear',
            'replay_timeline':timeline, 'replay_speed':{'mode':'fixed', 'rate':1., 'camera_clock':'replay'}})

    def bind(self, times=(1.,40.), mode='replay', timeline=None):
        project = self.project(times, mode, timeline)
        atomic_json(self.app.project_path, project.to_dict())
        self.app._switch_to(self.app.project_path, project)

    def request(self, path, data=None, *, status=200):
        request = urllib.request.Request(self.base+path,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status,status)
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = json.load(exc)
            self.assertEqual(exc.code,status,body)
            return body

    def session(self, when):
        snapshot = {'replay':{'time':when,'paused':True},'camera':{
            'position':[100,200,20], 'quaternion':[1,0,0,0], 'horizontal_fov_deg':60,
            'yaw_deg':0.,'pitch_deg':0.,'roll_deg':0.}}
        self.app.session = Mock()
        self.app.session.capture.return_value = snapshot
        return snapshot

    def draft(self, times=(1.,40.), **extra):
        project = self.project(times, self.app.project.shooting_mode, deepcopy(self.app.project.replay_timeline))
        return {'keyframes':controls(project), 'camera_track_controls':track_controls(project),
                'shooting_mode':project.shooting_mode, 'replay_timeline':project.replay_timeline,
                'replay_speed':project.replay_speed, 'position_interpolation':'linear', **extra}

    def editor_value(self, playhead):
        return {'schema_version':1, 'timeline':{'playhead':playhead, 'scale':90., 'scroll_left':0.}}

    def stable(self):
        return (self.app.project.to_dict(),self.app.project_revision,self.app.selected_time,
                deepcopy(self.app.editor_state),self.app.project_path.read_bytes())

    def test_state_reads_real_file_once_and_cache_invalidates_on_file_change(self):
        with patch('blitzcam.server.file_timeline', wraps=file_timeline) as read:
            for _ in range(3):
                guard = self.request('/api/state')['keyframe_guard']
                self.assertEqual((guard['status'],guard['start_sec']),('identified',15.75))
            self.assertEqual(read.call_count,1)
            stamp=self.replay.stat().st_mtime_ns
            self.write_replay(self.replay,start=30.)
            os.utime(self.replay,ns=(stamp+1000000,stamp+1000000))
            guard = self.request('/api/state')['keyframe_guard']
            self.assertEqual(guard['start_sec'],25.75)
            self.assertEqual(read.call_count,2)

    def test_real_event_overrides_forged_persisted_boundary(self):
        timeline={**self.app.project.replay_timeline, 'battle_start_status':'identified',
                  'battle_start_sec':0.,'battle_start_raw_sec':4.25,'replay_origin_sec':4.25}
        self.bind(timeline=timeline)
        guard=self.request('/api/state')['keyframe_guard']
        self.assertEqual(guard['start_sec'],15.75)
        forged=self.project((1.,2.,40.),timeline=timeline).to_dict()
        self.request('/api/project', {'project':forged},status=400)

    def test_event_absence_cannot_be_overridden_by_forged_saved_status(self):
        self.write_replay(self.replay,event=False)
        self.bind(timeline={**self.app.project.replay_timeline,'battle_start_status':'identified','battle_start_sec':0.})
        self.assertEqual(self.request('/api/state')['keyframe_guard']['status'],'unavailable')
        self.session(50.)
        error=self.request('/api/capture/hotkey',{},status=400)
        self.assertIn('手动',error['error'])

    def test_cached_real_file_does_not_hide_a_new_project_content_mismatch(self):
        self.assertEqual(self.request('/api/state')['keyframe_guard']['start_sec'],15.75)
        self.bind(timeline={**self.app.project.replay_timeline,'replay_sha256':'a'*64})
        guard=self.request('/api/state')['keyframe_guard']
        self.assertEqual(guard['status'],'unavailable')
        self.assertIn('内容',guard['message'])

    def test_capture_and_hotkey_reject_early_time_even_when_replacing_old_key(self):
        self.session(1.)
        before=self.stable()
        for route,payload in (('/api/capture',{'time_sec':99.,'replace_existing':True}),
                              ('/api/capture/hotkey',{}),('/api/project/new',{})):
            with self.subTest(route=route):
                self.request(route,payload,status=400)
                self.assertEqual(self.stable(),before)
        self.assertFalse((self.out/'captures').exists())

    def test_capture_uses_actual_game_time_and_accepts_exact_start_and_later(self):
        for when in (15.75,25.):
            with self.subTest(when=when):
                self.session(when)
                self.request('/api/capture',{'time_sec':2.})
                self.assertIn(when,self.app.project.keyframe_times())
                self.assertEqual(self.app.selected_time,when)
        self.assertNotIn(2.,self.app.project.keyframe_times())
        self.session(30.)
        result=self.request('/api/capture/hotkey',{})
        self.assertEqual(result['time_sec'],30.)

    def test_from_current_camera_new_project_validates_new_verified_replay_boundary(self):
        self.bind(times=(10.,40.), timeline={'time_basis':'replay','duration_sec':300.,'work_start_sec':0.,'work_end_sec':60.})
        self.app.replay_info={**file_timeline(self.replay),'source':'blitz_camera'}
        self.app.replay_launch.update(verified=True)
        self.session(10.)
        before=self.stable()
        self.request('/api/project/new',{},status=400)
        self.assertEqual(self.stable(),before)
        self.session(20.)
        self.request('/api/project/new',{})
        self.assertEqual(self.app.project.keyframe_times(),[20.])

    def test_project_import_edit_and_track_drag_reject_new_early_points(self):
        before=self.stable()
        self.request('/api/project',{'project':self.project((1.,2.,40.)).to_dict()},status=400)
        self.request('/api/project/edit',self.draft((1.,2.,40.)),status=400)
        self.request('/api/project/edit',self.draft((2.,41.)),status=400)
        self.assertEqual(self.stable(),before)

    def test_legacy_early_key_value_edit_delete_and_later_add_remain_allowed(self):
        draft=self.draft()
        draft['camera_track_controls']['x'][0]['value']=123.
        self.request('/api/project/edit',draft)
        self.assertEqual(track_controls(self.app.project)['x'][0]['value'],123.)
        self.request('/api/project/edit',self.draft((40.,)))
        self.assertEqual(self.app.project.keyframe_times(),[40.])
        self.request('/api/project/edit',self.draft((20.,40.)))
        self.assertEqual(self.app.project.keyframe_times(),[20.,40.])

    def test_evaluate_sample_and_editor_draft_cannot_add_early_points(self):
        initial=self.editor_value(25.)
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),'value':initial})
        before=self.stable()
        for route in ('/api/evaluate','/api/sample/draft'):
            with self.subTest(route=route):
                self.request(route,self.draft((1.,2.,40.),time_sec=2.),status=400)
                self.assertEqual(self.stable(),before)
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),
                     'value':self.editor_value(2.),'draft':self.draft((1.,2.,40.)),
                     'expected_revision':self.app.project_revision},status=400)
        self.assertEqual(self.stable(),before)
        self.assertEqual(json.loads(editor_state_path(self.out,self.app.project_path).read_text(encoding='utf-8')),initial)

    def test_stale_editor_draft_keeps_project_and_saves_current_valid_view(self):
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),'value':self.editor_value(30.)})
        before=self.stable()
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),
                     'value':self.editor_value(20.),'draft':self.draft((1.,20.,40.)),
                     'expected_revision':self.app.project_revision-1},status=400)
        after=self.stable()
        self.assertEqual(after[:3],before[:3])
        self.assertEqual(after[4],before[4])
        self.assertEqual(after[3],self.editor_value(20.))

    def test_project_write_failure_does_not_change_project_or_view(self):
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),'value':self.editor_value(30.)})
        before=self.stable()
        real_atomic=atomic_json
        def fail_project(path,value):
            if Path(path)==self.app.project_path:raise OSError('模拟项目保存失败')
            return real_atomic(path,value)
        with patch('blitzcam.server.atomic_json',side_effect=fail_project):
            self.request('/api/ui/editor',{'project_path':str(self.app.project_path),
                         'value':self.editor_value(20.),'draft':self.draft((1.,20.,40.)),
                         'expected_revision':self.app.project_revision},status=400)
        self.assertEqual(self.stable(),before)

    def test_capture_hotkey_and_new_project_write_failures_keep_authored_state(self):
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),'value':self.editor_value(30.)})
        self.session(20.)
        before=self.stable()
        real_atomic=atomic_json
        def fail_project(path,value):
            if Path(path)==self.app.project_path:raise OSError('模拟项目保存失败')
            return real_atomic(path,value)
        with patch('blitzcam.server.atomic_json',side_effect=fail_project):
            for route in ('/api/capture/hotkey','/api/project/new'):
                with self.subTest(route=route):
                    self.request(route,{},status=400)
                    self.assertEqual(self.stable(),before)

    def test_camera_only_hotkey_records_global_playhead_and_falls_back_to_selection(self):
        self.bind(times=(2.,40.),mode='camera_only')
        self.session(1.)
        self.request('/api/ui/editor',{'project_path':str(self.app.project_path),'value':self.editor_value(123.5)})
        result=self.request('/api/capture/hotkey',{})
        self.assertEqual(result['time_sec'],123.5)
        self.assertIn(123.5,self.app.project.keyframe_times())
        self.assertFalse(self.request('/api/state')['keyframe_guard']['enabled'])
        self.app.editor_state=None; self.app.selected_time=200.
        self.assertEqual(self.request('/api/capture/hotkey',{})['time_sec'],200.)

    def test_inpoint_guard_applies_to_every_draft_and_save_route_atomically(self):
        draft = self.draft()
        draft['replay_timeline']['work_start_sec'] = 12.
        imported = deepcopy(self.app.project.to_dict())
        imported['replay_timeline']['work_start_sec'] = 12.
        before = self.stable()
        for route, payload in (('/api/project/edit', draft), ('/api/project', {'project': imported}),
                               ('/api/evaluate', {**draft, 'time_sec': 20.}), ('/api/sample/draft', draft),
                               ('/api/ui/editor', {'project_path':str(self.app.project_path),
                                'value':self.editor_value(20.), 'draft':draft,
                                'expected_revision':self.app.project_revision})):
            with self.subTest(route=route):
                error = self.request(route, payload, status=400)
                self.assertIn('入点不能早于', error['error'])
                self.assertEqual(self.stable(), before)
        draft['replay_timeline']['work_start_sec'] = 15.75
        self.request('/api/project/edit', draft)
        self.assertEqual(self.app.project.replay_timeline['work_start_sec'], 15.75)
        self.assertEqual(track_controls(self.app.project), track_controls(self.project()))

    def test_inpoint_uses_current_manual_or_unknown_boundary_and_exempts_mode_one(self):
        settings = self.request('/api/settings')
        self.request('/api/settings', {'project_directory':settings['project_directory'], 'replay_keyframe_start_seconds':25.})
        draft = self.draft(); draft['replay_timeline']['work_start_sec'] = 20.
        self.request('/api/project/edit', draft, status=400)
        draft['replay_timeline']['work_start_sec'] = 25.
        self.request('/api/project/edit', draft)
        self.write_replay(self.replay, event=False)
        self.request('/api/settings', {'project_directory':settings['project_directory'], 'replay_keyframe_start_seconds':None})
        draft = self.draft(); draft['replay_timeline']['work_start_sec'] = 30.
        self.assertIn('尚未解析', self.request('/api/project/edit', draft, status=400)['error'])
        draft['shooting_mode'] = 'camera_only'
        self.request('/api/project/edit', draft)

    def test_replay_binding_aligns_early_range_without_moving_keys_or_speed(self):
        for start, end, expected_end in ((0.,8.,23.75), (10.,60.,60.)):
            with self.subTest(start=start):
                self.bind(timeline={'time_basis':'replay', 'duration_sec':300., 'work_start_sec':start, 'work_end_sec':end})
                before = track_controls(self.app.project)
                self.app._bind_opened_replay(file_timeline(self.replay))
                self.assertEqual(self.app.project.replay_timeline['work_start_sec'], 15.75)
                self.assertEqual(self.app.project.replay_timeline['work_end_sec'], expected_end)
                self.assertEqual(track_controls(self.app.project), before)

    def test_legacy_early_range_cannot_be_used_for_game_play_or_seek(self):
        self.session(20.)
        with patch('blitzcam.server.session_timeline', side_effect=lambda _:file_timeline(self.replay)):
            for mode in ('auto', 'current', 'locate'):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, '入点不能早于'):
                    self.app.play(mode=mode)
            self.write_replay(self.replay, event=False)
            with self.assertRaisesRegex(ValueError, '尚未解析'):
                self.app.play(mode='locate')
        self.app.session.capture.assert_not_called()

    def test_default_new_project_import_moves_both_bounds_after_battle_start(self):
        for index, raw_start in enumerate((33.106, 303.75)):
            with self.subTest(raw_start=raw_start):
                self.write_replay(self.replay, start=raw_start)
                self.request('/api/projects/new', {'name':f'默认项目导入 {index}'})
                before = deepcopy(self.app.project.to_dict())
                self.assertTrue(self.app.project.replay_timeline['starter_keyframes_pending'])
                info = file_timeline(self.replay)
                self.app._bind_opened_replay(info)
                t = self.app.project.replay_timeline
                self.assertAlmostEqual(t['work_start_sec'], info['battle_start_sec'])
                self.assertAlmostEqual(t['work_end_sec'], min(300.,info['battle_start_sec']+8.))
                self.assertGreater(t['work_end_sec'], t['work_start_sec'])
                frames = self.app.project.to_dict()['keyframes']
                self.assertAlmostEqual(frames[0]['time_sec'], t['work_start_sec'])
                self.assertAlmostEqual(frames[-1]['time_sec'], t['work_end_sec'])
                self.assertNotIn('starter_keyframes_pending', t)
                for old, new in zip(before['keyframes'], frames):
                    self.assertEqual({k:v for k,v in old.items() if k!='time_sec'},
                                     {k:v for k,v in new.items() if k!='time_sec'})
                saved = self.app.project.to_dict()
                self.app._bind_opened_replay(info)
                self.assertEqual(self.app.project.to_dict(), saved)
                self.app.open_project(self.app.project_path)
                self.assertEqual(self.app.project.to_dict(), saved)

    def test_starter_marker_survives_draft_save_and_reopen_then_aligns_all_tracks(self):
        from blitzcam.project import edit_project
        self.app.new_project_file('保存后载入')
        p = self.app.project
        self.app.set_project(edit_project({'keyframes': controls(p), 'camera_track_controls': track_controls(p),
            'shooting_mode': 'replay', 'replay_timeline': deepcopy(p.replay_timeline), 'replay_speed': p.replay_speed}))
        self.app.open_project(self.app.project_path)
        self.assertTrue(self.app.project.replay_timeline['starter_keyframes_pending'])
        self.app._bind_opened_replay(file_timeline(self.replay))
        for rows in track_controls(self.app.project).values():
            self.assertEqual([k['time_sec'] for k in rows], [15.75, 23.75])

    def test_edited_starter_keys_are_never_repositioned(self):
        self.app.new_project_file('已修改的默认点')
        data = self.app.project.to_dict()
        data['keyframes'][0]['position'][0] += 1
        self.app.set_project(validate_project(data))
        self.assertNotIn('starter_keyframes_pending', self.app.project.replay_timeline)
        before = track_controls(self.app.project)
        self.app._bind_opened_replay(file_timeline(self.replay))
        self.assertEqual(track_controls(self.app.project), before)

    def test_starter_keys_wait_for_known_boundary_and_honor_manual_start(self):
        self.app.new_project_file('缺少开始事件')
        self.write_replay(self.replay, event=False)
        self.app._bind_opened_replay(file_timeline(self.replay))
        self.assertTrue(self.app.project.replay_timeline['starter_keyframes_pending'])
        self.assertEqual([k.time_sec for k in self.app.project.keyframes], [0.,8.])
        settings = self.request('/api/settings')
        self.request('/api/settings', {**settings, 'replay_keyframe_start_seconds': 5.})
        self.app._bind_opened_replay(file_timeline(self.replay))
        self.assertEqual([k.time_sec for k in self.app.project.keyframes], [5.,13.])

    def test_manual_setting_http_state_updates_and_restores_automatic(self):
        settings=self.request('/api/settings')
        self.assertIsNone(settings['replay_keyframe_start_seconds'])
        self.request('/api/settings',{'project_directory':settings['project_directory'],'replay_keyframe_start_seconds':5.})
        state=self.request('/api/state')
        self.assertEqual(state['replay_keyframe_start_seconds'],5.)
        self.assertEqual((state['keyframe_guard']['source'],state['keyframe_guard']['start_sec']),('manual',5.))
        self.session(6.); self.request('/api/capture/hotkey',{})
        self.request('/api/settings',{'project_directory':settings['project_directory'],'replay_keyframe_start_seconds':None})
        state=self.request('/api/state')
        self.assertEqual(state['keyframe_guard']['start_sec'],15.75)
        self.session(7.); self.request('/api/capture/hotkey',{},status=400)


if __name__=='__main__':unittest.main()
