"""Visible, isolated WebView2 composition-host flight acceptance fixture.

The paired browser checks pause for real desktop input in the selected test window.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from blitzcam.pose import quaternion_from_angles
from blitzcam.project import validate_project
from blitzcam.server import Workstation, make_handler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/native-flight-acceptance'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ('phase.json', 'motion.done', 'click.done', 'blur.done'):
        (OUT/name).unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=OUT) as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)/'output'):
        app = Workstation(Path(tmp)/'project.json')
        app.stop.set(); app.poller.join(); app.stop.clear()
        app.set_project(validate_project({
            'shooting_mode':'replay',
            'replay_timeline':{'time_basis':'replay', 'duration_sec':60, 'work_start_sec':0, 'work_end_sec':8},
            'keyframes':[{'time_sec':t, 'position':[t, 0, 10], 'quaternion':list(quaternion_from_angles(0, 0, 0)),
                          'horizontal_fov_deg':60} for t in (0, 8)]}))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        with socket.socket() as port:
            port.bind(('127.0.0.1', 0)); debug_port = port.getsockname()[1]
        env = dict(os.environ)
        env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = f'--remote-debugging-port={debug_port}'
        env['NODE_PATH'] = str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        executable = ROOT/'tools/overlay-runtime'/json.loads((ROOT/'tools/overlay-runtime/host.json').read_text())['executable']
        url = f'http://127.0.0.1:{server.server_address[1]}/?workbench'
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 1  # This fixture deliberately tests a visible desktop window.
        native = subprocess.Popen([str(executable), url, tmp, 'workbench'], env=env, startupinfo=startup)
        try:
            subprocess.run(['node', str(ROOT/'tools/test_native_flight.cjs'), url,
                            str(debug_port), tmp, str(OUT)], cwd=ROOT, env=env, check=True)
        finally:
            # Only the test-owned process/profile is terminated on failure.
            if native.poll() is None:
                native.terminate(); native.wait(timeout=10)
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
