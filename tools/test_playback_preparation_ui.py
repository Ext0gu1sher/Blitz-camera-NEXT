"""Isolated browser acceptance; every playback request is intercepted by the test."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import os
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles
from blitzcam.server import Workstation, make_handler

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, patch('blitzcam.server.OUTPUT',Path(tmp)):
        app=Workstation(Path(tmp)/'project.json');app.stop.set();app.poller.join()
        app.set_project(validate_project({'shooting_mode':'replay',
            'replay_timeline':{'time_basis':'replay','duration_sec':60,'work_start_sec':10,'work_end_sec':18},
            'keyframes':[{'time_sec':t,'position':[t,0,10],'quaternion':list(quaternion_from_angles(0,0,0)),
                          'horizontal_fov_deg':60} for t in (0,10,18)]}))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env=dict(os.environ)
        env['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.reader.CameraSession.connect',side_effect=AssertionError('UI test attempted game access')):
                subprocess.run(['node',str(ROOT/'tools/test_playback_preparation_ui.cjs'),
                                f'http://127.0.0.1:{server.server_address[1]}'],cwd=ROOT,env=env,check=True)
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':main()
