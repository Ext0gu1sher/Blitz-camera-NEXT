"""Isolated UI acceptance for bound replay launch and pointer-locked preview flight."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import os
import subprocess
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from blitzcam.server import Workstation, make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles
from blitzcam.settings import save_settings
from blitzcam.replay_timeline import file_timeline

ROOT = Path(__file__).resolve().parents[1]


def main(script='test_preview_controls.cjs', launches=2, unchanged=True):
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
        save_settings(Path(tmp), {'project_directory':tmp, 'replay_keyframe_start_seconds':0})
        replay = Path(tmp)/'项目 A & B.wotbreplay'
        with zipfile.ZipFile(replay, 'w') as archive:
            archive.writestr('meta.json', json.dumps({'battleDuration':60, 'version':'11.21'}))
        app = Workstation(Path(tmp)/'project.json')
        app.stop.set(); app.poller.join(); app.stop.clear()
        app.set_project(validate_project({
            'shooting_mode':'replay',
            'replay_timeline':{**file_timeline(replay), 'time_basis':'replay',
                               'work_start_sec':0, 'work_end_sec':8},
            'keyframes':[{'time_sec':t, 'position':[t, 0, 10], 'quaternion':list(quaternion_from_angles(0, 0, 0)),
                          'horizontal_fov_deg':60} for t in (0, 8)]}))
        before = app.project.to_dict()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = dict(os.environ)
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.memory._kernel',side_effect=AssertionError('launch inspected game')), \
                 patch('blitzcam.replay_launcher.locate_client', return_value=Path('wotblitz.exe')), \
                 patch('blitzcam.replay_launcher.choose_replay', side_effect=AssertionError('bound replay opened picker')), \
                 patch('blitzcam.replay_launcher.launch_replay', return_value=SimpleNamespace(pid=65432)) as launch, \
                 patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('preview connected to game')):
                subprocess.run(['node', str(ROOT/'tools'/script),
                                f'http://127.0.0.1:{server.server_address[1]}', str(replay)],
                               cwd=ROOT, env=env, check=True)
                assert launch.call_count==launches, 'Unexpected replay launch count'
                for call in launch.call_args_list:
                    assert call.args==(Path('wotblitz.exe'),str(replay.resolve())) and not call.kwargs
                if unchanged:
                    assert app.project.to_dict() == before, 'Controls modified the saved project'
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
