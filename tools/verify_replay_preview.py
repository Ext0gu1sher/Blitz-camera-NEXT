"""Automated isolated preview acceptance. Reads assets/replay; never connects game."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles

ROOT=Path(__file__).resolve().parents[1]


def main(replay,additional_replay=None):
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp:
        app=Workstation(Path(tmp)/'project.json')
        app.stop.set();app.poller.join()
        app.set_project(validate_project({'shooting_mode':'replay','timing':'keyframes','easing':'ease_in_out',
            'replay_timeline':{'time_basis':'replay','duration_sec':253.12938,'work_start_sec':40,'work_end_sec':80,'replay_file':str(Path(replay).resolve())},
            'keyframes':[{'time_sec':t,'position':p,'quaternion':list(quaternion_from_angles(a,-10,0)), 'horizontal_fov_deg':z}
                for t,p,a,z in [(40,[150,100,60],-130,70),(80,[-20,30,50],-90,50)]]}))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env=dict(os.environ);env['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            # Assert even accidental game access fails the acceptance run.
            with patch('blitzcam.server.CameraSession.connect',side_effect=AssertionError('preview touched game')),patch('blitzcam.replay_launcher.launch_replay',side_effect=AssertionError('preview launched game')):
                subprocess.run(['node',str(ROOT/'tools/verify_replay_preview.cjs'),f'http://127.0.0.1:{server.server_address[1]}',*([additional_replay]if additional_replay else [])],env=env,cwd=ROOT,check=True)
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',required=True);p.add_argument('--additional-replay');args=p.parse_args();main(args.replay,args.additional_replay)
