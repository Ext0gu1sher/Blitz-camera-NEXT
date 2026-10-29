"""Native folder foreground acceptance; isolated data, no game access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler
from blitzcam.settings import save_settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    parent = ROOT/'output/project-folder-native-acceptance'
    parent.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    (run/'output').mkdir()
    projects = run/('Folder-'+run.name)
    with patch('blitzcam.server.OUTPUT', run), patch.dict(os.environ, {'BLITZCAM_PROFILE_ROOT':str(run/'account')}):
        save_settings(run, {'project_directory':str(projects)})
        app = Workstation();app.stop.set();app.poller.join()
        app.new_project_file('Folder test')
        app.project = app.project_path = None
        server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(app))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        runtime = ROOT/'tools/overlay-runtime'
        host = json.loads((runtime/'host.json').read_text())['executable']
        framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
        args = [str(framework/'csc.exe'),'/nologo','/target:winexe','/platform:x64','/out:'+str(run/'probe.exe')]
        for name in ('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll','System.Xaml.dll','System.dll','System.Core.dll','System.Web.Extensions.dll'):
            dll = framework/name
            args.append('/reference:'+str(dll if dll.exists() else framework/'WPF'/name))
        for name in (host,'Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.Wpf.dll'):
            shutil.copyfile(runtime/name,run/name)
            args.append('/reference:'+str(run/name))
        shutil.copyfile(runtime/'WebView2Loader.dll',run/'WebView2Loader.dll')
        shutil.copyfile(runtime/(host+'.config'),run/'probe.exe.config')
        args.append(str(ROOT/'tools/project_folder_probe.cs'))
        try:
            subprocess.run(args,check=True)
            env=dict(os.environ);env.pop('BLITZCAM_DESKTOP_SMOKE',None)
            with patch('blitzcam.server.os.startfile',side_effect=AssertionError('background service must not launch Explorer')) as fallback:
                probe_args=['--lookup-only',str(run)] if '--lookup-only' in sys.argv else [f'http://127.0.0.1:{server.server_port}/',str(run),str(projects)]
                result=subprocess.run([str(run/'probe.exe'),*probe_args],env=env,cwd=run,timeout=90)
                fallback.assert_not_called()
                if result.returncode:raise AssertionError((run/'error.txt').read_text(encoding='utf-8'))
            print((run/'result.json').read_text(encoding='utf-8'),str(run))
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':main()
