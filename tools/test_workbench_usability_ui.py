"""Isolated Home, preferences, cut, and zoom acceptance; never touches the game."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import os
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, \
         patch('blitzcam.server.OUTPUT', Path(tmp)), \
         patch('blitzcam.settings.documents_directory', return_value=Path(tmp)/'Documents'):
        app = Workstation()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = dict(os.environ)
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('game access')), \
                 patch('blitzcam.replay_launcher.launch_replay', side_effect=AssertionError('game launch')):
                subprocess.run(['node', str(ROOT/'tools/test_workbench_usability_ui.cjs'),
                                f'http://127.0.0.1:{server.server_port}', tmp], cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
