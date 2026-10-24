import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from blitzcam.desktop import open_overlay


class DesktopHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        host = self.root/'tools/overlay-runtime'
        host.mkdir(parents=True)
        exe = host/'host.exe'
        exe.write_bytes(b'local-built-host-fixture')
        (host/'host.json').write_text(json.dumps({'executable':exe.name, 'sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}))

    def test_native_workbench_uses_bundled_host_and_separate_data_root(self):
        with patch('blitzcam.desktop.RESOURCE_ROOT', self.root), \
             patch('blitzcam.desktop.DATA_ROOT', self.root/'data'), \
             patch('blitzcam.desktop.OUTPUT', self.root/'data/output'), \
             patch('blitzcam.desktop.subprocess.Popen') as launch:
            open_overlay('http://127.0.0.1:12345/', view='workbench')
        args = launch.call_args.args[0]
        self.assertEqual(args[-2:], [str(self.root/'data'), 'workbench'])
        self.assertEqual(args[0], str(self.root/'tools/overlay-runtime/host.exe'))
        self.assertTrue((self.root/'data/output').is_dir())

    def test_foreign_origin_and_unknown_window_never_launch(self):
        with patch('blitzcam.desktop.subprocess.Popen') as launch:
            for url in ('https://127.0.0.1:1234/', 'http://example.com:1234/', 'file:///tmp/host'):
                with self.assertRaises(ValueError):
                    open_overlay(url)
            with self.assertRaises(ValueError):
                open_overlay('http://127.0.0.1:1234/', view='unknown')
            launch.assert_not_called()

    def test_modified_host_is_rejected(self):
        (self.root/'tools/overlay-runtime/host.exe').write_bytes(b'changed')
        with patch('blitzcam.desktop.RESOURCE_ROOT', self.root), patch('blitzcam.desktop.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                open_overlay('http://127.0.0.1:1234/')
            launch.assert_not_called()

    def test_owned_host_exit_closes_service(self):
        from blitzcam.server import serve
        workstation, server = Mock(), Mock()
        server.server_address = ('127.0.0.1', 12345)
        process = Mock()
        # Execute the monitor synchronously only in the fixture. Production
        # creates a daemon thread and performs shutdown outside HTTP handlers.
        with patch('blitzcam.server.Workstation', return_value=workstation), \
             patch('blitzcam.server.ThreadingHTTPServer', return_value=server), \
             patch('blitzcam.server.OUTPUT', self.root/'output'), \
             patch('blitzcam.server.atomic_json'), \
             patch('blitzcam.desktop.open_overlay', return_value=process) as opened, \
             patch('blitzcam.server.threading.Thread') as thread:
            thread.return_value.start.side_effect = lambda: thread.call_args.kwargs['target']()
            serve(self.root/'project.json', open_browser=False, desktop=True, desktop_view='workbench', exit_with_desktop=True)
        opened.assert_called_once_with('http://127.0.0.1:12345/', view='workbench')
        process.wait.assert_called_once()
        server.shutdown.assert_called_once()
        workstation.close.assert_called_once()
        server.server_close.assert_called_once()

    def test_desktop_launch_failure_closes_service(self):
        from blitzcam.server import serve
        workstation, server = Mock(), Mock()
        server.server_address = ('127.0.0.1', 12345)
        with patch('blitzcam.server.Workstation', return_value=workstation), \
             patch('blitzcam.server.ThreadingHTTPServer', return_value=server), \
             patch('blitzcam.server.OUTPUT', self.root/'output'), \
             patch('blitzcam.server.atomic_json'), \
             patch('blitzcam.desktop.open_overlay', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                serve(open_browser=False, desktop=True)
        workstation.close.assert_called_once()
        server.server_close.assert_called_once()
