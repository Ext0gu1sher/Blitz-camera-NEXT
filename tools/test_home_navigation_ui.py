"""Regress focus/click races using disposable projects and the real local API."""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

from blitzcam.project import atomic_json, read_project
from blitzcam.server import Workstation, make_handler
from blitzcam.settings import save_settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as folder, \
            patch.dict(os.environ, {'BLITZCAM_PROFILE_ROOT': str(Path(folder)/'account')}), \
            patch('blitzcam.server.OUTPUT', Path(folder)):
        root = Path(folder).resolve()
        projects = root/'sample-projects'
        save_settings(root, {'project_directory': str(projects)})
        source = read_project(ROOT/'examples/eight-second.json').to_dict()
        for name in ('项目甲', '项目乙'):
            atomic_json(projects/(name+'.json'), source)
        app = Workstation(None); app.stop.set(); app.poller.join()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
        try:
            with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('game access')):
                subprocess.run(['node', str(ROOT/'tools/test_home_navigation_ui.cjs'),
                                f'http://127.0.0.1:{server.server_port}', str(projects), *sys.argv[1:]],
                               cwd=ROOT, env=env, check=True, timeout=90)
        finally:
            server.shutdown(); server.server_close(); worker.join(); app.close()


if __name__ == '__main__':
    main()
