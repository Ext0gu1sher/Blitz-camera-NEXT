"""Real app guard acceptance with an explicit synthetic BATTLE event."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import os
import struct
import subprocess
import tempfile
import threading
from unittest.mock import patch
import zipfile

from blitzcam.server import Workstation, make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles
from tests.fixtures.replay_data import header, packet

ROOT = Path(__file__).resolve().parents[1]


def main(fixture='test_keyframe_guard_app_ui.cjs'):
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
        replay = Path(tmp)/'比赛开始事件.wotbreplay'
        nested = bytes.fromhex('080311') + struct.pack('<d', 420.) + bytes.fromhex('18a403')
        body = bytes((26, len(nested))) + nested
        args = bytes((3, len(body))) + body
        payload = struct.pack('<III', 123, 48, len(args)) + args
        data = header() + packet(0x11, 4.25) + packet(8, 19.25, payload) + packet(0xFFFFFFFF, 0)
        with zipfile.ZipFile(replay, 'w') as archive:
            archive.writestr('meta.json', json.dumps({'battleDuration': 100, 'version': '11.21.0'}))
            archive.writestr('data.wotreplay', data)
        app = Workstation(Path(tmp)/'project.json'); app.stop.set(); app.poller.join()
        app.set_project(validate_project({'shooting_mode':'replay',
            'replay_timeline':{'time_basis':'replay', 'duration_sec':100, 'work_start_sec':10, 'work_end_sec':30},
            'keyframes':[{'time_sec':t, 'position':[t,0,20], 'quaternion':list(quaternion_from_angles(0,0,0)), 'horizontal_fov_deg':60}
                         for t in (10,20,30)]}))
        server = ThreadingHTTPServer(('127.0.0.1',0), make_handler(app)); server.daemon_threads=True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = dict(os.environ)
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('game access')):
                subprocess.run(['node', str(ROOT/'tools'/fixture),
                    f'http://127.0.0.1:{server.server_address[1]}', str(replay)], cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
