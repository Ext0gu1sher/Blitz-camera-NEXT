"""Isolated, offscreen WebView2 clipboard acceptance; no game or global input.

The paired probe snapshots the Windows clipboard, uses trusted renderer-targeted
keyboard events, and restores the snapshot only while our test still owns it.
It compiles a temporary probe against the production native WebView settings;
the distributed host and package are never changed.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/keyframe-clipboard-native-acceptance'

PAGE = r'''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/timeline.css">
<style>body{background:#191919;color:#ddd}#editor{display:flex;flex-direction:column;width:1000px;height:400px}.ic{width:12px;height:12px}</style>
<div id="editor"></div><div id="inspector"><span data-selection></span><span data-time-label></span><input data-field="time"><span data-value-label></span><input data-field="value"></div><input id="plain" value="BlitzCamera isolated native input">
<script src="/preview-time.js"></script><script src="/keyframe-clipboard.js"></script><script src="/timeline.js"></script>
<script>
window.notices=[];window.changes=[];window.pastes=[];window.copies=[];
window.editor=new BlitzTimeline.Editor(document.getElementById('editor'),{inspector:document.getElementById('inspector'),change:d=>changes.push(d),seek:()=>{},error:m=>notices.push(m)});
const tracks=Object.fromEntries(BlitzTimeline.CHANNELS.map(([name])=>[name,[2,6].map(time_sec=>({time_sec,value:name==='zoom'?60:name==='x'?17:name==='y'?27:0}))]));
editor.load(tracks,{mode:'paused',rate:1,keyframes:[{progress:0,rate:1},{progress:1,rate:1}]});
editor.selected=new Set([editor.doc.tracks.x[0]._id,editor.doc.tracks.y[1]._id]);editor.updatePlayhead(10);editor.render();
document.addEventListener('paste',e=>pastes.push({trusted:e.isTrusted,types:[...e.clipboardData.types],plain:e.clipboardData.getData('text/plain')}));
document.addEventListener('copy',e=>copies.push({trusted:e.isTrusted,types:[...e.clipboardData.types],target:e.target.tagName,active:document.activeElement.tagName,requested:editor.copyRequested,scope:editor.clipboardScope(e.target)}));
window.ready=true;
</script>'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / 'tools/overlay-runtime'
    with tempfile.TemporaryDirectory(dir=OUT, ignore_cleanup_errors=True) as folder:
        root = Path(folder)
        framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
        args = [str(framework/'csc.exe'), '/nologo', '/target:exe', '/platform:x64',
                '/main:KeyframeClipboardProbe', '/out:'+str(root/'probe.exe')]
        for name in ('WindowsBase.dll', 'PresentationCore.dll', 'PresentationFramework.dll',
                     'System.Xaml.dll', 'System.dll', 'System.Core.dll', 'System.Drawing.dll',
                     'System.Windows.Forms.dll', 'System.Web.Extensions.dll'):
            path = framework/name
            if not path.exists():
                path = framework/'WPF'/name
            args.append('/reference:'+str(path))
        for name in ('Core', 'Wpf'):
            dll = runtime/f'Microsoft.Web.WebView2.{name}.dll'
            args.append('/reference:'+str(dll))
            shutil.copyfile(dll, root/dll.name)
        shutil.copyfile(runtime/'WebView2Loader.dll', root/'WebView2Loader.dll')
        args += [str(ROOT/'blitzcam/desktop/OverlayHost.cs'), str(ROOT/'tools/keyframe_clipboard_probe.cs')]
        subprocess.run(args, check=True)

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT/'blitzcam/web'), **kwargs)

            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path.startswith('/clipboard-probe'):
                    data = PAGE.encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    super().do_GET()

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            run = subprocess.run([str(root/'probe.exe'), f'http://127.0.0.1:{server.server_port}/clipboard-probe', str(root)],
                                 capture_output=True, text=True, encoding='utf-8', timeout=60,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            if run.returncode:
                (OUT/'failure.txt').write_text(run.stdout+run.stderr, encoding='utf-8')
                raise AssertionError(run.stdout+run.stderr)
            result = json.loads(run.stdout)
            assert result['passed'], result
            (OUT/'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            (OUT/'failure.txt').unlink(missing_ok=True)
            print(json.dumps(result, ensure_ascii=False))
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    main()
