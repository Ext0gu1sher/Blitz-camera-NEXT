import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from blitzcam.server import Workstation, make_handler, read_recent, record_recent, startup_project


class ProjectFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.patcher = patch('blitzcam.server.OUTPUT', self.out)
        self.patcher.start()
        self.app = Workstation(self.out/'project.json')
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.http.server_address[1])

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.app.close(); self.patcher.stop(); self.tmp.cleanup()

    def request(self, path, data=None):
        request = urllib.request.Request(self.base + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_new_open_recent_and_forget(self):
        result = self.request('/api/projects/new', {'name': '航拍 项目'})
        path = Path(result['path'])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, (self.out/'projects').resolve())
        state = self.request('/api/state')
        self.assertEqual(state['project_path'], str(path.resolve()))
        self.assertEqual(state['project_name'], '航拍 项目')
        listing = self.request('/api/projects/recent')['projects']
        self.assertEqual(listing[0]['path'], str(path.resolve()))
        self.assertTrue(listing[0]['exists'])
        self.assertEqual(listing[0]['shooting_mode'], 'replay')
        self.assertIsInstance(listing[0]['keyframes'], int)
        self.assertIsNotNone(listing[0]['size_bytes'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/projects/new', {'name': '航拍 项目'})
        first_path = self.out/'project.json'
        first_path.write_text(json.dumps(self.app.project.to_dict()), encoding='utf-8')
        first = str(first_path.resolve())
        self.request('/api/projects/open', {'path': first})
        self.assertEqual(self.request('/api/state')['project_path'], first)
        self.request('/api/projects/forget', {'path': first})
        self.assertNotIn(first, [e['path'] for e in self.request('/api/projects/recent')['projects']])

    def test_recent_marks_missing_and_keeps_entry(self):
        result = self.request('/api/projects/new', {'name': 'gone'})
        path = Path(result['path'])
        self.assertTrue(path.is_file())
        path.unlink()
        listing = self.request('/api/projects/recent')['projects']
        entry = next(e for e in listing if e['path'] == str(path.resolve()))
        self.assertFalse(entry['exists'])
        self.assertEqual(entry['name'], 'gone')

    def test_save_project_as_switches_path_and_records(self):
        target = self.out/'projects'/'elsewhere.json'
        result = self.app.save_project_as(target)
        self.assertTrue(target.is_file())
        self.assertEqual(self.app.project_path, target.resolve())
        self.assertEqual(result, str(target.resolve()))
        self.assertEqual(read_recent()[0]['path'], str(target.resolve()))
        loaded = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(loaded['schema_version'], 1)

    def test_startup_project_prefers_recent_existing(self):
        self.assertEqual(startup_project(), self.out/'project.json')
        other = self.out/'projects'/'x.json'
        other.parent.mkdir(parents=True)
        other.write_text('{}', encoding='utf-8')
        record_recent(other)
        self.assertEqual(startup_project(), other.resolve())
        other.unlink()
        self.assertEqual(startup_project(), self.out/'project.json')

    def test_settings_persist_and_new_projects_use_selected_directory(self):
        from blitzcam.settings import read_settings
        original=self.app.project_path
        defaults=self.request('/api/settings')
        self.assertEqual(Path(defaults['project_directory']),(self.out/'projects').resolve())
        folder=(self.out/'摄影 项目'/'新目录').resolve()
        result=self.request('/api/settings',{'project_directory':str(folder)})
        self.assertEqual(Path(result['project_directory']),folder)
        self.assertEqual(read_settings(self.out),result)
        self.assertTrue(folder.is_dir());self.assertEqual(self.app.project_path,original)
        created=self.request('/api/projects/new',{'name':'航拍'})
        self.assertEqual(Path(created['path']).parent,folder)
        self.assertTrue(Path(created['path']).is_file())
        record_recent(original)
        original.unlink(missing_ok=True)
        Path(created['path']).unlink()
        self.assertEqual(startup_project(),folder/'project.json')

    def test_folder_picker_cancel_and_dialogs_use_setting(self):
        folder=(self.out/'custom').resolve();self.request('/api/settings',{'project_directory':str(folder)})
        with patch('blitzcam.replay_launcher.choose_directory',return_value=None) as choose:
            self.assertEqual(self.request('/api/settings/directory',{}),{'cancelled':True})
            choose.assert_called_once_with(folder)
        with patch('blitzcam.replay_launcher.choose_project',return_value=None) as choose:
            self.assertEqual(self.request('/api/projects/open',{}),{'cancelled':True})
            choose.assert_called_once_with(folder)
        target=folder/'saved.json'
        with patch('blitzcam.replay_launcher.save_project',return_value=target) as choose:
            self.request('/api/projects/save_as',{})
            choose.assert_called_once_with('project',folder)
        self.assertEqual(self.app.project_path,target)

    def test_invalid_directory_preserves_saved_settings(self):
        good=self.request('/api/settings',{'project_directory':str(self.out/'valid')})
        file=self.out/'not-a-directory';file.write_text('existing file',encoding='utf-8')
        for value in ('','relative/path',str(file),None,3,'bad\0path'):
            with self.subTest(value=value),self.assertRaises(urllib.error.HTTPError):
                self.request('/api/settings',{'project_directory':value})
            self.assertEqual(self.request('/api/settings'),good)
        self.assertEqual(file.read_text(encoding='utf-8'),'existing file')

    def test_corrupt_settings_fall_back_without_changing_project(self):
        (self.out/'settings.json').write_text('{broken',encoding='utf-8')
        self.assertEqual(Path(self.request('/api/settings')['project_directory']),(self.out/'projects').resolve())


class DesktopReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def _service(self):
        (self.out/'workstation-service.json').write_text(
            json.dumps({'url': 'http://127.0.0.1:9/', 'pid': 1, 'version': 'x', 'project_path': str(self.out/'other.json')}),
            encoding='utf-8')

    def _fake_urlopen(self, state):
        calls = []
        def fake(request, timeout=0):
            calls.append(request if isinstance(request, str) else request.full_url)
            return io.BytesIO(json.dumps(state).encode())
        return fake, calls

    def test_reuse_without_explicit_project(self):
        from blitzcam import __version__
        state = {'version': __version__, 'project_path': str(self.out/'other.json')}
        self._service()
        with patch('blitzcam.desktop.OUTPUT', self.out), \
             patch('urllib.request.urlopen', self._fake_urlopen(state)[0]), \
             patch('blitzcam.server.serve') as serve_mock:
            from blitzcam import desktop
            desktop.launch(None, 0, view='workbench')
        self.assertFalse(serve_mock.called)

    def test_explicit_project_mismatch_starts_fresh(self):
        from blitzcam import __version__
        state = {'version': __version__, 'project_path': str(self.out/'other.json')}
        self._service()
        with patch('blitzcam.desktop.OUTPUT', self.out), \
             patch('urllib.request.urlopen', self._fake_urlopen(state)[0]), \
             patch('blitzcam.server.serve') as serve_mock:
            from blitzcam import desktop
            desktop.launch(self.out/'mine.json', 0, view='workbench')
        serve_mock.assert_called_once()
        self.assertEqual(serve_mock.call_args[0][0], (self.out/'mine.json').resolve())


if __name__ == '__main__':
    unittest.main()
