"""Exercise the registered Windows OLE target, WPF hit testing, project creation and save."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/replay-drop-acceptance'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runtime = ROOT/'tools/overlay-runtime'
    with tempfile.TemporaryDirectory(dir=OUT, ignore_cleanup_errors=True) as folder, \
            patch.dict(os.environ,{'BLITZCAM_PROFILE_ROOT':str(Path(folder)/'account')}), \
            patch('blitzcam.server.OUTPUT', Path(folder)/'output'), \
            patch('blitzcam.settings.documents_directory', return_value=Path(folder)/'Documents'):
        root = Path(folder).resolve()
        (root/'output').mkdir()
        first, second = root/'第一场 回放.wotbreplay', root/'第二场.WOTBREPLAY'
        for replay in (first, second):
            with zipfile.ZipFile(replay, 'w') as archive:
                archive.writestr('meta.json', json.dumps({'battleDuration':100, 'version':'11.21'}))
        wrong, corrupt = root/'not-replay.txt', root/'损坏.wotbreplay'
        wrong.write_text('fixture'); corrupt.write_text('invalid archive')
        app = Workstation(None); app.stop.set(); app.poller.join()
        server = ThreadingHTTPServer(('127.0.0.1',0), make_handler(app))
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
        args = [str(framework/'csc.exe'), '/nologo', '/target:exe', '/platform:x64',
                '/main:ReplayDropProbe', '/out:'+str(root/'probe.exe'),
                '/resource:'+str(ROOT/'blitzcam/desktop/assets/BlitzCamera.ico')+',BlitzCamera.Icon']
        for name in ('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll','System.Xaml.dll',
                     'System.dll','System.Core.dll','System.Drawing.dll','System.Windows.Forms.dll','System.Web.Extensions.dll'):
            lib = framework/name
            if not lib.exists(): lib = framework/'WPF'/name
            args.append('/reference:'+str(lib))
        for name in ('Core','Wpf'):
            lib = runtime/f'Microsoft.Web.WebView2.{name}.dll'
            args.append('/reference:'+str(lib)); shutil.copyfile(lib,root/lib.name)
        shutil.copyfile(runtime/'WebView2Loader.dll',root/'WebView2Loader.dll')
        shutil.copyfile(ROOT/'blitzcam/desktop/BlitzCameraOverlay.exe.config',root/'probe.exe.config')
        args += [str(ROOT/'blitzcam/desktop/OverlayHost.cs'), str(ROOT/'tools/replay_drop_probe.cs')]
        try:
            subprocess.run(args,check=True)
            with patch('blitzcam.server.replay_launcher.choose_replay',side_effect=[first,None]), \
                    patch.object(app.replay_preview,'select',side_effect=ValueError('测试预览不可用')), \
                    patch('blitzcam.server.CameraSession.connect',side_effect=AssertionError('game access')), \
                    patch.object(app,'open_replay',side_effect=AssertionError('game launch')):
                run = subprocess.run([str(root/'probe.exe'),f'http://127.0.0.1:{server.server_port}/',str(root),
                                      str(first),str(second),str(wrong),str(corrupt)],capture_output=True,
                                     text=True,encoding='utf-8',timeout=110,creationflags=subprocess.CREATE_NO_WINDOW)
            for image in root.glob('*.png'): shutil.copyfile(image,OUT/image.name)
            if run.returncode: raise AssertionError(run.stdout+run.stderr)
            projects = root/'Documents/Blitz-Camera-Project'
            saved = json.loads((projects/'第一场 回放.json').read_text(encoding='utf-8'))
            assert saved['replay_timeline']['replay_file'] == str(second)
            assert saved['replay_timeline']['replay_sha256']
            assert len(list(projects.glob('*.json'))) == 3
            assert first.is_file() and second.is_file()
            (OUT/'result.txt').write_text(run.stdout,encoding='utf-8')
            print(run.stdout.strip())
        finally:
            server.shutdown(); server.server_close(); worker.join(); app.close()


if __name__ == '__main__': main()
