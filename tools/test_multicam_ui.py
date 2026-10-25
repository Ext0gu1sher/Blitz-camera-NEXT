"""Independent camera UI regression with disposable data and no game access."""
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.project import validate_project
from blitzcam.server import Workstation, make_handler
from blitzcam.settings import save_settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as folder, patch('blitzcam.server.OUTPUT', Path(folder)):
        root = Path(folder)
        save_settings(root, {'project_directory': str(root/'projects'), 'replay_keyframe_start_seconds': 0})
        app = Workstation(root/'project.json')
        app.stop.set(); app.poller.join()
        data = json.loads((ROOT/'examples/three-keyframe-preview.json').read_text())
        for frame, time in zip(data['keyframes'], [72, 78, 84]):
            frame['time_sec'] = time
        data['shooting_mode'] = 'replay'
        data['replay_timeline'] = {'time_basis': 'replay', 'duration_sec': 180, 'work_start_sec': 72, 'work_end_sec': 84}
        data['replay_speed'] = {'mode': 'fixed', 'rate': 1, 'camera_clock': 'replay'}
        app.set_project(validate_project(data))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app)); server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
        try:
            with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('game access')), \
                 patch.object(app.playback, 'start', side_effect=AssertionError('game playback')):
                subprocess.run(['node', str(ROOT/'tools/test_multicam_ui.cjs'), f'http://127.0.0.1:{server.server_port}/'], cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
