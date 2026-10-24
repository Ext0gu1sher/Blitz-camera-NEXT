"""Isolated speed-curve trim acceptance; never opens or connects to the game."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import os
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles
from blitzcam.server import Workstation,make_handler

ROOT=Path(__file__).resolve().parents[1]


def main(fixture='test_speed_window_ui.cjs'):
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp,patch('blitzcam.server.OUTPUT',Path(tmp)):
        app=Workstation(Path(tmp)/'project.json');app.stop.set();app.poller.join()
        app.set_project(validate_project({'shooting_mode':'replay',
            'replay_timeline':{'time_basis':'replay','duration_sec':100,'work_start_sec':10,'work_end_sec':30},
            'replay_speed':{'mode':'curve','camera_clock':'replay'},
            'keyframes':[{'time_sec':t,'position':[t,0,20],'quaternion':list(quaternion_from_angles(0,0,0)),'horizontal_fov_deg':60}for t in (10,20,30)]}))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env=dict(os.environ);env['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.server.CameraSession.connect',side_effect=AssertionError('game access')),patch.object(app.playback,'start',side_effect=AssertionError('game playback')):
                subprocess.run(['node',str(ROOT/'tools'/fixture),f'http://127.0.0.1:{server.server_address[1]}'],env=env,cwd=ROOT,check=True)
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':main()
