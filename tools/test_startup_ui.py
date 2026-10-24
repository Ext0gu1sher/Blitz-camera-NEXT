"""Exercise production startup with delayed/failed local responses, then WebView2."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import os
import subprocess
import sys
import shutil
import tempfile
import threading
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles

ROOT=Path(__file__).resolve().parents[1]


def main():
    report=ROOT/'output/startup-acceptance';report.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp,patch('blitzcam.server.OUTPUT',Path(tmp)):
        app=Workstation(Path(tmp)/'project.json');app.stop.set();app.poller.join()
        app.set_project(validate_project({'shooting_mode':'camera_only','keyframes':[
            {'time_sec':t,'position':[t,0,20],'quaternion':quaternion_from_angles(0,0,0),'horizontal_fov_deg':60} for t in (0,8)]}))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env=dict(os.environ);env['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.server.CameraSession.connect',side_effect=AssertionError('startup accessed game')),patch('blitzcam.replay_launcher.launch_replay',side_effect=AssertionError('startup launched game')):
                base=f'http://127.0.0.1:{server.server_address[1]}'
                if '--native-only' not in sys.argv:
                    subprocess.run(['node',str(ROOT/'tools/test_startup_ui.cjs'),base],cwd=ROOT,env=env,check=True)
                manifest=json.loads((ROOT/'tools/overlay-runtime/host.json').read_text())
                (Path(tmp)/'output').mkdir(exist_ok=True)
                native_env=dict(env,BLITZCAM_DESKTOP_SMOKE='1')
                result=subprocess.run([str(ROOT/'tools/overlay-runtime'/manifest['executable']),base,str(tmp),'workbench'],cwd=ROOT,env=native_env,creationflags=subprocess.CREATE_NO_WINDOW,timeout=50)
                evidence=Path(tmp)/'output/desktop-smoke.json'
                if not evidence.exists():
                    shutil.copytree(Path(tmp)/'output',report/'native-failure',dirs_exist_ok=True)
                    raise AssertionError({p.name:p.read_text(encoding='utf-8-sig') for p in (Path(tmp)/'output').glob('*error.txt')})
                smoke=json.loads(json.loads(evidence.read_text(encoding='utf-8-sig')))
                assert result.returncode==0 and all(smoke[k] for k in ('loaded','startup','webview','timeline')),smoke
                assert smoke['background']=='rgb(23, 23, 23)',smoke
                actions=json.loads((Path(tmp)/'output/desktop-actions.json').read_text(encoding='utf-8-sig'))
                assert all(actions.values()),actions
                (report/'native.json').write_text(json.dumps({'smoke':smoke,'actions':actions},indent=2,ensure_ascii=False),encoding='utf-8')
                print(json.dumps({'native':smoke,'actions':actions},ensure_ascii=False))
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':main()
