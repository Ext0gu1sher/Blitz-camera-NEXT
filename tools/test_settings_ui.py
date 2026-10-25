"""Settings page acceptance with native dialogs replaced by local fixture paths."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import os
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.server import Workstation,make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp,patch('blitzcam.server.OUTPUT',Path(tmp)), \
         patch('blitzcam.settings.documents_directory',return_value=Path(tmp)/'Documents'):
        app=Workstation(Path(tmp)/'original.json');app.stop.set();app.poller.join()
        app.set_project(validate_project({'shooting_mode':'camera_only','keyframes':[
            {'time_sec':t,'position':[t,0,20],'quaternion':quaternion_from_angles(0,0,0),'horizontal_fov_deg':60} for t in (0,8)]}))
        folder=Path(tmp)/'摄影 项目';folder.mkdir()
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env=dict(os.environ);env['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            with patch('blitzcam.replay_launcher.choose_directory',side_effect=[None,folder]),patch('blitzcam.server.CameraSession.connect',side_effect=AssertionError('settings accessed game')):
                subprocess.run(['node',str(ROOT/'tools/test_settings_ui.cjs'),f'http://127.0.0.1:{server.server_address[1]}',str(folder.resolve())],cwd=ROOT,env=env,check=True)
            assert (folder/'设置验收项目.json').is_file()
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':main()
