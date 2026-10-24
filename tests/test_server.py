import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile
import urllib.request
import urllib.error
from unittest.mock import patch, Mock
from http.server import ThreadingHTTPServer

from blitzcam.server import Workstation, make_handler
from blitzcam.pose import quaternion_from_angles
from tests.fixtures.replay_data import replay_data


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Workstation(Path(self.tmp.name)/'project.json')
        self.http = ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever,daemon=True); self.thread.start()
        self.base = 'http://127.0.0.1:'+str(self.http.server_address[1])

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(); self.app.close(); self.tmp.cleanup()

    def request(self,path,data=None,headers=None):
        h={'Content-Type':'application/json'}
        h.update(headers or {})
        request=urllib.request.Request(self.base+path, data=None if data is None else json.dumps(data).encode(),headers=h)
        with urllib.request.urlopen(request) as response:return json.load(response)

    def test_offline_edit_export_samples_and_persistence(self):
        state=self.request('/api/state'); self.assertEqual(state['connection']['state'],'disconnected')
        data=state['project']; data['keyframes'][-1]['time_sec']=8
        self.request('/api/project',{'project':data})
        sampled=self.request('/api/sample',{'rate_hz':100})
        self.assertEqual(len(sampled['samples']),801)
        self.assertEqual(sampled['samples'][-1]['position'],data['keyframes'][-1]['position'])
        exported=self.request('/api/export')
        self.assertEqual(exported['keyframes'],data['keyframes'])
        self.assertEqual(json.loads(self.app.project_path.read_text(encoding='utf-8')),exported)

    def test_bad_import_preserves_existing_project(self):
        before=self.request('/api/export')
        with self.assertRaises(urllib.error.HTTPError) as exc:self.request('/api/project',{'project':{'keyframes':[]}})
        self.assertEqual(exc.exception.code,400)
        self.assertEqual(self.request('/api/export'),before)

    def test_open_replay_route_dispatches_without_blocking_on_picker(self):
        with patch.object(self.app, 'open_replay') as open_replay:
            self.assertEqual(self.request('/api/replay/open', {}), {'ok':True})
            open_replay.assert_called_once_with(None)
            self.request('/api/replay/open', {'path':r'C:\replays\chosen.wotbreplay'})
            open_replay.assert_called_with(r'C:\replays\chosen.wotbreplay')

    def test_open_project_replay_route_uses_portable_relinking(self):
        with patch.object(self.app, 'open_project_replay') as open_replay:
            self.assertEqual(self.request('/api/replay/open_project', {}), {'ok':True})
            open_replay.assert_called_once_with()

    def test_main_play_http_defaults_and_legacy_prepare_continue_inside_workspace(self):
        from blitzcam.project import validate_project
        self.app.stop.set();self.app.poller.join()
        self.app.set_project(validate_project({'shooting_mode':'replay',
            'replay_timeline':{'time_basis':'replay','duration_sec':60,'work_start_sec':10,'work_end_sec':18},
            'replay_speed':{'mode':'curve','camera_clock':'replay'},
            'keyframes':[{'time_sec':t,'position':[t,2,10],'quaternion':[1,0,0,0],
                          'horizontal_fov_deg':60} for t in (10,18)]}))
        self.app.session=Mock()
        self.app.session.capture.return_value={'replay':{'time':14,'paused':True}}
        with patch.object(self.app.playback,'start') as start,patch.object(self.app.playback,'prepare') as prepare,patch.object(self.app.playback,'seek') as seek:
            for body in ({},{'mode':'prepare'},{'mode':'auto'}):
                with self.subTest(body=body):
                    self.request('/api/playback/start',body)
                    start.assert_called_once();prepare.assert_not_called();seek.assert_not_called()
                    window=start.call_args.args[0]
                    self.assertEqual((window.start_time,window.end_time),(14,18))
                    self.assertEqual(window.sample(14),self.app.project.sample(14))
                    self.assertGreater(window.speed_schedule[1],0)
                    start.reset_mock()

    def test_parameter_draft_is_read_only_and_saves_independent_tracks(self):
        before=self.request('/api/state')
        body={'keyframes':before['keyframe_controls'],'camera_track_controls':before['camera_track_controls'],
              'replay_speed':{'mode':'fixed','rate':.25,'camera_clock':'replay'}}
        body['camera_track_controls']['zoom'].insert(1,{'time_sec':1.125,'value':80})
        draft=self.request('/api/sample/draft',body)
        self.assertIn(1.125,draft['keyframe_times'])
        value=self.request('/api/evaluate',{**body,'time_sec':1.125})
        self.assertEqual(value['values']['zoom'],80)
        after=self.request('/api/state')
        self.assertEqual(after['project'],before['project'])
        self.assertEqual(after['project_revision'],before['project_revision'])
        self.assertFalse(after['playback']['active'])
        self.request('/api/project/edit',{**body,'expected_revision':before['project_revision']})
        saved=self.request('/api/state')
        self.assertEqual(saved['project']['camera_tracks']['zoom'][1]['time_sec'],1.125)
        self.assertNotIn(1.125,[k['time_sec'] for k in saved['camera_track_controls']['x']])
        self.request('/api/project/retime',{'seconds':16,'expected_revision':saved['project_revision']})
        retimed=self.request('/api/state')
        self.assertEqual(retimed['project']['camera_tracks']['zoom'][1]['time_sec'],2.25)

    def test_multiwindow_selection_is_read_only_and_shared(self):
        before=self.request('/api/state')
        time=before['project']['keyframes'][-1]['time_sec']
        self.request('/api/ui/selection', {'time_sec':time})
        after=self.request('/api/state')
        self.assertEqual(after['ui']['selected_time'],time)
        self.assertEqual(before['project'],after['project'])
        self.assertEqual(before['project_revision'],after['project_revision'])
        self.assertFalse(after['playback']['active'])
        for invalid in (True,'bad',999999):
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/ui/selection', {'time_sec':invalid})

    def test_capture_into_independent_tracks_updates_all_seven_parameters(self):
        before=self.request('/api/state')
        body={'keyframes':before['keyframe_controls'],'camera_track_controls':before['camera_track_controls']}
        self.request('/api/project/edit',body)
        camera={'position':[12,15,20],'quaternion':list(quaternion_from_angles(25,10,5)),
                'horizontal_fov_deg':75,'yaw_deg':25,'pitch_deg':10,'roll_deg':5}
        self.app.session=Mock();self.app.session.capture.return_value={'camera':camera,'replay':{'paused':True}}
        self.request('/api/capture',{'time_sec':2.5})
        after=self.request('/api/state')
        for name,value in zip(('x','y','z','yaw','pitch','roll','zoom'),(12,15,20,25,10,5,75)):
            self.assertEqual(next(k['value'] for k in after['camera_track_controls'][name] if k['time_sec']==2.5),value)

    def test_stale_window_cannot_overwrite_new_project(self):
        first=self.request('/api/state')
        data=first['project'];data['keyframes'][0]['name']='街角 A'
        self.request('/api/project',{'project':data,'expected_revision':first['project_revision']})
        for endpoint,payload in (
            ('/api/project',{'project':first['project']}),
            ('/api/capture',{'time_sec':12}),
            ('/api/project/new',{}),
        ):
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.request(endpoint,{**payload,'expected_revision':first['project_revision']})
            self.assertIn('其他窗口',exc.exception.read().decode())
        current=self.request('/api/state')
        self.assertEqual(current['project']['keyframes'][0]['name'],'街角 A')
        self.assertEqual(current['project_revision'],first['project_revision']+1)

    def test_names_survive_workbench_edit_and_export(self):
        state=self.request('/api/state');data=state['project'];data['keyframes'][0]['name']='建筑近景'
        self.request('/api/project',{'project':data})
        current=self.request('/api/state')
        self.request('/api/project/edit',{'keyframes':current['keyframe_controls'], 'expected_revision':current['project_revision']})
        self.assertEqual(self.request('/api/export')['keyframes'][0]['name'],'建筑近景')
        for name in (123,'a'*65,'bad\nname'):
            data['keyframes'][0]['name']=name
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/project',{'project':data})

    def test_overlay_assets_are_local_and_not_frames(self):
        for path in ('/overlay','/overlay.js','/overlay.css'):
            with urllib.request.urlopen(self.base+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/ui/selection',{'time_sec':0},{'Origin':'https://example.invalid'})

    def test_terrain_api_is_read_only_and_same_origin(self):
        before=self.request('/api/state')
        with patch.object(self.app.terrain,'load',return_value={'map_id':'11_plant_pn'}) as load:
            self.assertEqual(self.request('/api/terrain/11_plant_pn'),{'map_id':'11_plant_pn'})
            load.assert_called_once_with('11_plant_pn')
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/terrain/11_plant_pn',headers={'Origin':'https://example.invalid'})
            self.assertEqual(load.call_count,1)
        after=self.request('/api/state')
        self.assertEqual(before['project'],after['project'])
        self.assertEqual(before['project_revision'],after['project_revision'])
        self.assertFalse(after['playback']['active'])

    def test_retime_preserves_pose_names_speed_and_selection(self):
        before=self.request('/api/state');project=before['project']
        project['keyframes'][0]['name']='起点'
        self.request('/api/project',{'project':project})
        current=self.request('/api/state')
        self.request('/api/ui/selection',{'time_sec':project['keyframes'][-1]['time_sec']})
        self.request('/api/project/retime',{'seconds':12,'expected_revision':current['project_revision']})
        after=self.request('/api/state')
        self.assertEqual(after['ui']['selected_time'],project['keyframes'][0]['time_sec']+12)
        for old,new in zip(project['keyframes'],after['project']['keyframes']):
            self.assertEqual({k:v for k,v in old.items() if k!='time_sec'},{k:v for k,v in new.items() if k!='time_sec'})
        self.assertEqual(project['replay_speed'],after['project']['replay_speed'])
        for invalid in (True,0,121,'8'):
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/project/retime',{'seconds':invalid})
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/project/retime',{'seconds':8,'expected_revision':current['project_revision']})

    def test_stale_play_request_never_captures_or_starts_hook(self):
        with patch.object(self.app.playback,'start') as start:
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.request('/api/playback/start',{'expected_revision':-1})
            self.assertIn('其他窗口',exc.exception.read().decode());start.assert_not_called()

    def test_workbench_launch_uses_only_own_service_url(self):
        with patch('blitzcam.desktop.open_overlay') as launch:
            self.request('/api/desktop/workbench',{'url':'https://example.invalid'})
            self.assertEqual(launch.call_args.args[0], self.base+'/')
            self.assertEqual(launch.call_args.kwargs, {'view':'workbench'})
        with patch('blitzcam.desktop.open_overlay',side_effect=OSError('桌面外壳不可用')):
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/desktop/workbench',{})

    def test_preview_effective_times_and_revision_match_samples(self):
        before=self.request('/api/state')
        result=self.request('/api/sample',{'rate_hz':30,'expected_revision':before['project_revision']})
        self.assertEqual(result['project_revision'],before['project_revision'])
        self.assertEqual(result['keyframe_times'],self.app.project.keyframe_times())
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/sample',{'rate_hz':30,'expected_revision':-1})

    def test_unconnected_capture_and_foreign_origin_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:self.request('/api/capture',{'time_sec':0})
        self.assertEqual(exc.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as exc:self.request('/api/project',{}, {'Origin':'https://example.invalid'})
        self.assertEqual(exc.exception.code,403)

    def test_offline_preview_source_never_launches_or_changes_project(self):
        replay=Path(self.tmp.name)/'preview.wotbreplay'
        with zipfile.ZipFile(replay,'w') as z:
            z.writestr('meta.json',json.dumps({'battleDuration':45,'version':'11.21.0','mapName':'canal'}))
            z.writestr('data.wotreplay',replay_data(4.18244743347168))
        before=self.request('/api/export')
        with patch.object(self.app,'connect',side_effect=AssertionError('game access')),patch.object(self.app,'open_replay',side_effect=AssertionError('game launch')):
            source=self.request('/api/preview/select',{'path':str(replay)})['source']
            self.assertEqual(source['replay_origin_sec'],4.18244743347168)
            with urllib.request.urlopen(self.base+'/api/preview/replay/'+source['id']) as response:
                self.assertEqual(response.read(),replay.read_bytes())
        self.assertEqual(self.request('/api/export'),before)
        self.assertEqual(self.request('/api/preview/state')['source']['id'],source['id'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/preview/asset/not-registered')

    def test_preview_resources_are_local_and_cannot_escape_vendor_directory(self):
        with urllib.request.urlopen(self.base+'/vendor/agent/wotb_replay_wasm_bg.wasm') as response:
            self.assertEqual(response.headers['Content-Type'],'application/wasm')
            self.assertEqual(response.read(4),b'\x00asm')
            self.assertIn("'wasm-unsafe-eval'",response.headers['Content-Security-Policy'])
        for path in ('/vendor/../../app.js','/vendor/agent/../../../../output/project.json','/vendor/agent/not-shipped.js'):
            with self.assertRaises(urllib.error.HTTPError) as error:self.request(path)
            self.assertEqual(error.exception.code,404)
        with self.assertRaises(urllib.error.HTTPError) as exc:self.request('/api/state',None,{'Host':'example.invalid'})
        self.assertEqual(exc.exception.code,403)

    def test_preview_pitch_limits_pass_unicode_roster_without_touching_project(self):
        roster=[{'eid':7,'nickname':'中文玩家','tank_id':6929,'turret_local':45,'gun_local':1041}]
        before=self.request('/api/export')
        expected={'limits':{'中文玩家':{'dep':8,'ele':24}},'anchored':[7],'missing':[]}
        with patch('blitzcam.preview_assets.playback_pitch_limits',return_value=expected) as resolve:
            self.assertEqual(self.request('/api/preview/pitch-limits',{'vehicles':roster}),expected)
            resolve.assert_called_once_with(roster)
        self.assertEqual(self.request('/api/export'),before)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/preview/pitch-limits',{})


if __name__=='__main__':unittest.main()
