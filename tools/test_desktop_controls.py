"""Verify native hotkeys, hidden capture and minimized-overlay restoration.

Uses only an isolated message window, offscreen WebView and synthetic camera.
Never opens, discovers or attaches to a game process.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch

from blitzcam.server import Workstation, make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles

ROOT = Path(__file__).resolve().parents[1]


class CameraFixture:
    def capture(self, require_paused=True):
        return {'camera': {'position': [50, 60, 70], 'quaternion': list(quaternion_from_angles(0, 0, 0)),
                           'yaw_deg': 0, 'pitch_deg': 0, 'roll_deg': 0, 'horizontal_fov_deg': 60},
                'replay': {'time': 12, 'paused': True, 'rate': 1}, 'quality': {}}

    def close(self):
        pass


def main(host_executable=None):
    runtime = ROOT / 'tools/overlay-runtime'
    manifest = json.loads((runtime/'host.json').read_text())
    report = ROOT/'output/desktop-controls-acceptance'
    report.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as folder:
        root = Path(folder)
        framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
        references = ['WindowsBase.dll', 'PresentationCore.dll', 'PresentationFramework.dll',
                      'System.Xaml.dll', 'System.dll', 'System.Core.dll', 'System.Drawing.dll',
                      'System.Windows.Forms.dll', 'System.Web.Extensions.dll']
        args = [str(framework/'csc.exe'), '/nologo', '/target:exe', '/platform:x64',
                '/main:DesktopControlsProbe', '/out:'+str(root/'probe.exe')]
        for name in references:
            path = framework/name
            if not path.exists():
                path = framework/'WPF'/name
            args.append('/reference:'+str(path))
        for name in ('Core', 'Wpf'):
            dll = runtime/f'Microsoft.Web.WebView2.{name}.dll'
            args.append('/reference:'+str(dll))
            shutil.copyfile(dll, root/dll.name)
        args.extend([str(ROOT/'blitzcam/desktop/OverlayHost.cs'), str(ROOT/'tools/desktop_controls_probe.cs')])
        subprocess.run(args, check=True)
        requests = []

        class CaptureHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                requests.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), CaptureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = dict(os.environ)
            env.pop('BLITZCAM_DESKTOP_SMOKE', None)
            probe = subprocess.run([str(root/'probe.exe'), f'http://127.0.0.1:{server.server_port}/', str(root)],
                                   env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
            if probe.returncode:
                raise AssertionError(probe.stdout+probe.stderr)
            hotkeys = json.loads(probe.stdout)
            assert all(hotkeys.values()), hotkeys
            assert requests == [('/api/capture/hotkey', b'{}')], requests
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        with patch('blitzcam.server.OUTPUT', root):
            app = Workstation(root/'project.json')
            app.stop.set()
            app.poller.join()
            app.set_project(validate_project({'shooting_mode': 'camera_only', 'keyframes': [
                {'time_sec': t, 'position': [t, 0, 20], 'quaternion': list(quaternion_from_angles(0, 0, 0)),
                 'horizontal_fov_deg': 60} for t in (0, 8)]}))
            app.session = CameraFixture()
            app.sample = app.session.capture()
            app.connection = {'state': 'connected', 'message': 'Synthetic replay'}
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = dict(os.environ, BLITZCAM_DESKTOP_SMOKE='1', BLITZCAM_OVERLAY_SMOKE='1', BLITZCAM_CAPTURE_SMOKE='1')
                with patch('blitzcam.server.CameraSession.connect', side_effect=AssertionError('native test accessed game')):
                    native = subprocess.run([str(runtime/(host_executable or manifest['executable'])), f'http://127.0.0.1:{server.server_port}/', str(root), 'workbench'],
                                            env=env, creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
                errors = {p.name: p.read_text(encoding='utf-8-sig') for p in (root/'output').glob('*error.txt')}
                if errors:
                    for evidence in (root/'output').iterdir():
                        if evidence.is_file():
                            shutil.copyfile(evidence, report/evidence.name)
                assert native.returncode == 0 and not errors, errors
                overlay = json.loads((root/'output/desktop-overlay-smoke.json').read_text(encoding='utf-8-sig'))
                capture = json.loads((root/'output/desktop-capture-smoke.json').read_text(encoding='utf-8-sig'))
                assert all(overlay.values()) and all(capture.values()), (overlay, capture)
                frames = app.project.to_dict()['keyframes']
                assert len(frames) == 3, frames
                frame = next(k for k in frames if abs(k['time_sec']-2) < 1e-6)
                assert frame['position'] == [50, 60, 70], frame
                result = {'hotkeys': hotkeys, 'overlay': overlay, 'capture': capture, 'captured_time_sec': frame['time_sec']}
                for name in ('desktop-process-failed.json', 'desktop-smoke-error.txt', 'overlay-layout.json', 'overlay-status.json'):
                    (report/name).unlink(missing_ok=True)
                (report/'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                app.close()


if __name__ == '__main__':
    main()
