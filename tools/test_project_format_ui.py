"""Real conversion endpoints and editor interactions with disposable projects."""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles
from blitzcam.server import Workstation, make_handler
from blitzcam.settings import save_settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, \
         patch('blitzcam.server.OUTPUT', Path(tmp)), \
         patch.dict(os.environ, {'BLITZCAM_PROFILE_ROOT': str(Path(tmp)/'account')}):
        folder = Path(tmp).resolve()
        source, bcn, restored = folder/'原项目.json', folder/'转换 项目.bcnproj', folder/'还原.json'
        broken = folder/'损坏.json';broken.write_text('{', encoding='utf-8')
        save_settings(folder, {'project_directory': str(folder)})
        app = Workstation(source);app.stop.set();app.poller.join()
        app.set_project(validate_project({'shooting_mode': 'camera_only', 'keyframes': [
            {'time_sec': t, 'position': [t, 0, 20], 'quaternion': quaternion_from_angles(0, 0, 0), 'horizontal_fov_deg': 60} for t in (0, 8)]}))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app));server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
        try:
            with patch('blitzcam.replay_launcher.choose_project', side_effect=[None, source, bcn, source, broken]), \
                 patch('blitzcam.replay_launcher.save_project', side_effect=[bcn, restored, bcn]), \
                 patch('blitzcam.desktop.open_overlay'), \
                 patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('game access')):
                subprocess.run(['node', str(ROOT/'tools/test_project_format_ui.cjs'),
                                f'http://127.0.0.1:{server.server_port}', str(source), str(bcn), str(restored)],
                               cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__ == '__main__':
    main()
