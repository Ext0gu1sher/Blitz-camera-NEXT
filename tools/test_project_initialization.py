"""Isolated browser regression for new projects; never connects to a game."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
        app = Workstation(Path(tmp)/'initial.json')
        app.stop.set(); app.poller.join()
        app.new_project_file('initial')
        # Persisted game telemetry must not bind this previous replay on reload.
        app.replay_launch = {'state': 'launched', 'id': 'previous-project-launch', 'project_path': str(app.project_path), 'info': {
            'replay_file': 'previous.wotbreplay', 'duration_sec': 300, 'name': 'previous',
            'battle_start_status': 'identified', 'battle_start_sec': 20}}
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = dict(os.environ)
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            subprocess.run(['node', str(ROOT/'tools/test_project_initialization.cjs'),
                            f'http://127.0.0.1:{server.server_port}'], cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
