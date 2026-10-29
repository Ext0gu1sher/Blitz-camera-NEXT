"""Real workbench/server with isolated Pro activation and audio preferences."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler
from blitzcam.offline_updater import write_json
from blitzcam.project import validate_project
from blitzcam.settings import read_settings, save_settings

ROOT = Path(__file__).resolve().parents[1]

# Injected only by this isolated acceptance server, before the production script.
AUDIO_PROBE = b"""(()=>{
 const contexts=[],Original=window.AudioContext,connect=AudioNode.prototype.connect;
 let peak=0,running=false;
 window.AudioContext=class extends Original{constructor(...args){super(...args);contexts.push(this);}};
 AudioNode.prototype.connect=function(destination,...args){
  if(destination instanceof AudioDestinationNode){
   const analyser=this.context.createAnalyser();connect.call(this,analyser);
   const buffer=new Float32Array(analyser.fftSize),timer=setInterval(()=>{
    if(this.context.state==='closed'){clearInterval(timer);return;}
    running=running||this.context.state==='running';analyser.getFloatTimeDomainData(buffer);
    for(const sample of buffer)peak=Math.max(peak,Math.abs(sample));
   },30);
  }
  return connect.call(this,destination,...args);
 };
 addEventListener('blitz-app-ready',()=>setTimeout(()=>fetch('/startup-audio-probe',{
  method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
   edition:document.documentElement.dataset.edition,contexts:contexts.length,running,peak,
   closed:contexts.every(ctx=>ctx.state==='closed'),webview:!!window.chrome?.webview
  })
 }),500),{once:true});
})();\n"""


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, \
            patch.dict(os.environ, {'BLITZCAM_PROFILE_ROOT': str(Path(tmp)/'account')}), \
            patch('blitzcam.server.OUTPUT', Path(tmp)/'output'), \
            patch('blitzcam.settings.documents_directory', return_value=Path(tmp)/'Documents'):
        folder = Path(tmp)
        app = Workstation(folder/'project.json')
        app.stop.set(); app.poller.join()
        app.deployment.files = {}  # Only edition selection, never a game adapter.
        write_json(app.deployment.profile/'pro-intro.json', {'token': 'a'*32})
        app.set_project(validate_project({'shooting_mode': 'camera_only', 'keyframes': [
            {'time_sec': t, 'position': [t, 0, 20], 'quaternion': [1, 0, 0, 0], 'horizontal_fov_deg': 60}
            for t in (0, 8)]}))
        probe = {'enabled': False, 'result': None}
        class Handler(make_handler(app)):
            def _send(self, status, data, *args, **kwargs):
                if probe['enabled'] and self.path == '/startup.js' and status == 200:
                    data = AUDIO_PROBE + data
                return super()._send(status, data, *args, **kwargs)

            def do_POST(self):
                if probe['enabled'] and self.path == '/startup-audio-probe' and self._allowed():
                    probe['result'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    self._send(200, {'ok': True})
                else:
                    super().do_POST()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
        try:
            with patch.object(app.backend, 'connect', side_effect=AssertionError('startup accessed game')):
                subprocess.run(['node', str(ROOT/'tools/test_pro_startup_ui.cjs'),
                                f'http://127.0.0.1:{server.server_port}'], cwd=ROOT, env=env, check=True)
            assert app.deployment.startup_state()['intro_token'] == ''
            assert not app.backend.loaded
            # Verify autoplay in the actual rebuilt desktop WebView2 without a click.
            save_settings(folder/'output', {**read_settings(folder/'output'), 'startup_sound': True})
            write_json(app.deployment.profile/'pro-intro.json', {'token': 'b'*32})
            probe['enabled'] = True
            manifest = json.loads((ROOT/'tools/overlay-runtime/host.json').read_text())
            subprocess.run([str(ROOT/'tools/overlay-runtime'/manifest['executable']),
                            f'http://127.0.0.1:{server.server_port}', str(folder), 'workbench'],
                           cwd=ROOT, env=dict(env, BLITZCAM_DESKTOP_SMOKE='1'),
                           creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=50)
            result = probe['result']
            assert result and result['edition'] == 'pro' and result['contexts'] == 1, result
            assert result['webview'] and result['running'] and result['closed'] and result['peak'] > .01, result
            assert app.deployment.startup_state()['intro_token'] == ''
            write_json(ROOT/'output/pro-startup-acceptance/native.json', result)
            print(json.dumps({'native': result}))
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.close()


if __name__ == '__main__':
    main()
