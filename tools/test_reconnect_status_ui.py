"""Reconnect the real floating-bar UI to a synthetic camera, without game access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch
import zipfile

from blitzcam.replay_timeline import file_timeline
from blitzcam.server import Workstation, make_handler
from tests.test_replay_events import arena_payload, data_with_events

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
        app = Workstation(Path(tmp)/'project.json')
        app.stop.set()
        app.poller.join()
        replay = Path(tmp)/'重连测试.wotbreplay'
        with zipfile.ZipFile(replay, 'w') as archive:
            archive.writestr('meta.json', json.dumps({'battleDuration': 100, 'version': '11.21'}))
            archive.writestr('data.wotreplay', data_with_events([(8, 4.25, arena_payload())]))
        info = file_timeline(replay)
        app.replay_launch = {'id': 'reconnect-fixture', 'state': 'invalidated', 'verified': False,
                             'info': info, 'pid': 12345, 'executable': str(Path(tmp)/'wotblitz.exe'),
                             'message': '回放对象已改变，本次文件关联已失去核对。请退出游戏后从 Blitz Camera 重新打开回放。'}
        app.connection = {'state': 'error', 'message': '回放对象已改变，请重新连接。'}
        session = Mock()
        session.memory.info = SimpleNamespace(pid=12345, path=Path(tmp)/'wotblitz.exe')
        session.discovery_stats = {'valid_chain_count': 1}
        session.capture.return_value = {'replay': {'time': 12, 'paused': True, 'rate': 1},
                                        'camera': {'position': [0, 0, 20], 'quaternion': [1, 0, 0, 0],
                                                   'yaw_deg': 0, 'pitch_deg': 0, 'roll_deg': 0,
                                                   'horizontal_fov_deg': 60}, 'quality': {}}
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
        try:
            with patch('blitzcam.server.CameraSession.connect', return_value=session), \
                 patch('blitzcam.server.session_timeline', return_value={**info, 'source':'runtime_replay', 'verification':'runtime_replay'}), \
                 patch('blitzcam.memory._kernel', side_effect=AssertionError('fixture accessed game')):
                subprocess.run(['node', str(ROOT/'tools/test_reconnect_status_ui.cjs'),
                                f'http://127.0.0.1:{server.server_port}'], env=env, cwd=ROOT, check=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            app.close()


if __name__ == '__main__':
    main()
