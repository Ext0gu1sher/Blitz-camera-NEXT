"""Edition selection must be present in the HTML before any workbench API runs."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from blitzcam.server import Workstation, make_handler
from blitzcam.offline_updater import write_json


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for context in (patch('blitzcam.server.OUTPUT', self.root/'output'),
                        patch.dict(os.environ, {'BLITZCAM_PROFILE_ROOT': str(self.root/'account')}),
                        patch('blitzcam.settings.documents_directory', return_value=self.root/'Documents')):
            context.start()
            self.addCleanup(context.stop)
        self.app = Workstation(None)
        self.addCleanup(self.app.close)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def close_http(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def request(self, path='/', value=None):
        data = None if value is None else json.dumps(value).encode()
        with urlopen(Request(self.base+path, data=data, headers={'Content-Type': 'application/json'})) as response:
            return response.read().decode()

    def test_next_is_selected_without_workbench_state_and_ignores_pending_pro(self):
        write_json(self.app.deployment.profile/'pro-intro.json', {'token': 'a'*32})
        with patch.object(self.app, 'state', side_effect=AssertionError('early API state')):
            html = self.request()
        self.assertIn('<html lang="zh-CN" data-edition="next" data-pro-intro=""', html)
        self.assertIn('<section id="appSplash" data-edition="next"', html)
        self.assertIn('Blitz Camera NEXT 正在启动', html)
        self.assertFalse(json.loads(self.request('/api/deployment/startup-seen', {'token': 'a'*32}))['ok'])

    def test_pro_first_survives_page_requests_and_acknowledges_on_empty_home(self):
        self.app.deployment.files = {}  # authenticated deployment fixture, no game use
        write_json(self.app.deployment.profile/'pro-intro.json', {'token': 'a'*32})
        for _ in range(2):
            html = self.request()
            self.assertIn('data-pro-intro="'+'a'*32+'"', html)
            self.assertIn('<section id="appSplash" data-edition="pro"', html)
            self.assertIn('<title>Blitz Camera Pro', html)
        self.assertTrue(json.loads(self.request('/api/deployment/startup-seen', {'token': 'a'*32}))['ok'])
        self.assertIn('data-pro-intro=""', self.request())
        self.assertFalse((self.app.deployment.profile/'pro-intro.json').exists())

    def test_startup_sound_persists_and_is_delivered_before_scripts(self):
        settings = json.loads(self.request('/api/settings'))
        self.assertIs(settings['startup_sound'], True)
        settings = json.loads(self.request('/api/settings', {**settings, 'startup_sound': False}))
        self.assertIs(settings['startup_sound'], False)
        # Saving another settings category must preserve the audio preference.
        settings = json.loads(self.request('/api/settings', {'project_directory': settings['project_directory'], 'ui_scale': 125}))
        self.assertIs(settings['startup_sound'], False)
        self.assertIn('data-startup-sound="false"', self.request())
        with self.assertRaises(HTTPError) as error:
            self.request('/api/settings', {**settings, 'startup_sound': 'false'})
        self.assertEqual(error.exception.code, 400)
        self.assertIs(json.loads(self.request('/api/settings'))['startup_sound'], False)

    def test_corrupt_or_untrusted_intro_metadata_cannot_inject_html(self):
        self.app.deployment.files = {}
        for value in ([], {'token': '"><script>alert(1)</script>'}, {'token': 12}):
            write_json(self.app.deployment.profile/'pro-intro.json', value)
            self.assertIn('data-pro-intro=""', self.request())

    def test_desktop_deployment_api_opts_into_pro_restart(self):
        with patch.object(self.app.deployment, 'install', return_value={'ok':True,'restart':True}) as install:
            self.assertTrue(json.loads(self.request('/api/deployment/install', {'token':'test'}))['restart'])
        self.assertTrue(install.call_args.kwargs['restart_pro'])


if __name__ == '__main__':
    unittest.main()
