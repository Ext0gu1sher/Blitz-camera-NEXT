"""Compare a captured live state against an isolated offline preview."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler

ROOT = Path(__file__).resolve().parents[1]


def main(state_file, output):
    state_file = Path(state_file).resolve()
    state = json.loads(state_file.read_text(encoding='utf-8-sig'))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
        project = Path(tmp)/'project.json'
        project.write_text(json.dumps(state['project']), encoding='utf-8')
        app = Workstation(project)
        app.stop.set()
        app.poller.join()
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = dict(os.environ)
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('preview touched game')), patch('blitzcam.replay_launcher.launch_replay', side_effect=AssertionError('preview launched game')):
                subprocess.run(['node', str(ROOT/'tools/verify_replay_alignment.cjs'), f'http://127.0.0.1:{server.server_port}', str(state_file), str(output)], cwd=ROOT, env=env, check=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            app.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', default='output/preview-alignment-acceptance')
    args = parser.parse_args()
    main(args.state, args.output)
