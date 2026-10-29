import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / 'Collect Support Logs.cmd'
namespace = {'__name__': 'support_logs_test'}
exec(compile(SCRIPT.read_text(encoding='utf-8').split('\n# BEGIN PYTHON\n', 1)[1], str(SCRIPT), 'exec'), namespace)


class SupportLogsTests(unittest.TestCase):
    def test_collects_current_error_timing_and_bounded_logs_without_private_files(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests.append(self.path)
                data = {'version': '1.0.0', 'connection': {'state': 'error', 'message': '关联校验失败'},
                        'sample': {'replay': {'time': 247, 'paused': True}, 'camera': {'position': 'omit'}},
                        'project': {'shooting_mode': 'replay',
                                    'replay_timeline': {'work_start_sec': 243.597, 'work_end_sec': 255.983},
                                    'replay_speed': {'mode': 'fixed', 'rate': .0625, 'camera_clock': 'replay'},
                                    'keyframes': [{'time_sec': 243.597, 'position': 'omit'}]}}
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                output = root / 'output'
                output.mkdir()
                (output / 'workstation-service.json').write_text(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/', 'pid': 123}))
                (output / 'desktop-service.log').write_bytes(b'x' * (namespace['MAX_LOG'] + 100) + b'end')
                (output / 'deployment').mkdir()
                (output / 'deployment/device.json').write_text('PRIVATE')
                (output / 'project.json').write_text('PROJECT')
                (output / 'diagnostics').mkdir()
                (output / 'diagnostics/events.jsonl').write_text('{"event":"connection.failed"}\n')
                with zipfile.ZipFile(namespace['collect'](root)) as archive:
                    report = json.loads(archive.read('diagnostics.json'))
                    self.assertEqual(report['state']['connection']['message'], '关联校验失败')
                    timing = report['state']['project_timing']
                    self.assertEqual(timing['replay_timeline']['work_end_sec'], 255.983)
                    self.assertEqual(timing['replay_speed']['rate'], .0625)
                    self.assertEqual(timing['keyframe_times'], [243.597])
                    self.assertNotIn('camera', report['state']['game_sample'])
                    self.assertEqual(len(archive.read('logs/desktop-service.log')), namespace['MAX_LOG'])
                    self.assertTrue(archive.read('logs/desktop-service.log').endswith(b'end'))
                    self.assertTrue(report['files'][0]['tail_only'])
                    self.assertIn('diagnostics/events.jsonl',archive.namelist())
                    self.assertFalse(any('deployment' in name or 'project.json' in name for name in archive.namelist()))
                self.assertEqual(requests, ['/api/state'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_closed_service_still_produces_a_report(self):
        with tempfile.TemporaryDirectory() as folder:
            with zipfile.ZipFile(namespace['collect'](folder)) as archive:
                report = json.loads(archive.read('diagnostics.json'))
                self.assertIn('state_unavailable', report)
                self.assertEqual(report['files'], [])

    def test_remote_or_credentialed_service_url_is_never_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            for url in ('https://example.com/', 'http://localhost:80/', 'http://127.0.0.1:80/path/',
                        'http://user:pass@127.0.0.1:80/', 'http://127.0.0.1:80/?target=external'):
                (output / 'workstation-service.json').write_text(json.dumps({'url': url}))
                with self.assertRaises(ValueError):
                    namespace['live_state'](output)

    @unittest.skipUnless(os.name == 'nt', 'Windows batch launcher')
    def test_delivered_script_in_unicode_and_shell_metacharacter_folder(self):
        delivered = SCRIPT.read_bytes()
        self.assertTrue(delivered.startswith(b'@echo off\r\n'))
        self.assertNotIn(b'\n', delivered.replace(b'\r\n', b''))
        with tempfile.TemporaryDirectory(prefix='support 中文 & (a) ! ') as folder:
            root = Path(folder)
            (root / 'blitzcam').mkdir()
            (root / 'blitzcam/__init__.py').write_bytes(b'')
            launcher = root / SCRIPT.name
            launcher.write_bytes(delivered)
            command = '"' + os.environ.get('COMSPEC', 'cmd.exe') + '" /d /s /c ""' + str(launcher) + '""'
            result = subprocess.run(command, input='\n', capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(root.glob('output/support-logs/*.zip'))), 1)
            self.assertIn('已生成日志包', result.stdout)

    def test_older_bundled_runtime_needs_no_application_modules(self):
        runtime = next((path for version in ('1.0.0-beta', '0.9.6-beta-release', '0.9.4.1', '0.9.3')
                        if (path := SCRIPT.parent / ('dist/BlitzCamera-' + version + '/runtime/python.exe')).is_file()), None)
        if runtime is None:
            self.skipTest('Older portable runtime not available')
        with tempfile.TemporaryDirectory(prefix='support 旧版 ') as folder:
            root = Path(folder)
            launcher = root / SCRIPT.name
            launcher.write_bytes(SCRIPT.read_bytes())
            loader = "import pathlib,sys;src=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig');exec(compile(src.split(chr(10)+'# BEGIN PYTHON'+chr(10),1)[1],sys.argv[1],'exec'))"
            result = subprocess.run([str(runtime), '-X', 'utf8', '-B', '-c', loader, str(launcher)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(root.glob('output/support-logs/*.zip'))), 1)


if __name__ == '__main__':
    unittest.main()
