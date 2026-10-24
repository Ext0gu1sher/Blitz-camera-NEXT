"""Exercise real project endpoints against isolated disposable files only."""
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler, record_recent

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as folder, patch('blitzcam.server.OUTPUT',Path(folder)):
        root = Path(folder).resolve()
        app = Workstation(root/'project.json');app.stop.set();app.poller.join()
        alpha = app.new_project_file('旧项目')
        forgotten = app.new_project_file('仅移出列表')
        beta = app.new_project_file('当前项目')
        missing = root/'projects'/'已丢失.json';record_recent(missing)
        replay = root/'keep.wotbreplay';replay.write_bytes(b'keep replay')
        trash = root/'fake-recycle-bin';trash.mkdir()
        def recycle(path):
            assert path.parent == (root/'projects').resolve()
            path.rename(trash/path.name)
            return True
        server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env = dict(os.environ)
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.server.recycle_project',side_effect=recycle), \
                    patch('blitzcam.server.CameraSession.connect',side_effect=AssertionError('game access')), \
                    patch.object(app.playback,'start',side_effect=AssertionError('game playback')):
                subprocess.run(['node',str(ROOT/'tools/test_project_management_ui.cjs'),
                    f'http://127.0.0.1:{server.server_address[1]}',alpha,beta,forgotten,str(replay)],
                    cwd=ROOT,env=env,check=True)
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__ == '__main__':main()
