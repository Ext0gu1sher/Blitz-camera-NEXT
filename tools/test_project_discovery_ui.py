"""Home discovers disposable project folders without touching game or user files."""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.project import atomic_json, read_project
from blitzcam.server import Workstation, make_handler
from blitzcam.settings import save_settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as folder, patch('blitzcam.server.OUTPUT', Path(folder)):
        root = Path(folder).resolve()
        first, second = root/'项目目录一', root/'项目目录二'
        save_settings(root, {'project_directory': str(first)})
        source = read_project(ROOT/'examples/eight-second.json').to_dict()
        for target in (first/'未打开甲.json', first/'未打开乙.json', second/'另一个目录.json'):
            atomic_json(target, source)
        app = Workstation();app.stop.set();app.poller.join()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app));server.daemon_threads=True
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
        try:
            with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('game access')):
                subprocess.run(['node', str(ROOT/'tools/test_project_discovery_ui.cjs'),
                                f'http://127.0.0.1:{server.server_address[1]}', str(first), str(second)],
                               cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__ == '__main__':
    main()
