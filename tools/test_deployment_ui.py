"""Exercise the real offline crypto/deployment API through a browser UI."""
import base64
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.deployment import Deployment
from blitzcam.offline_updater import write_json
from blitzcam.packages import digest
from blitzcam.server import Workstation, make_handler
from tools.publish_updates import build_pro

ROOT = Path(__file__).resolve().parents[1]


def main():
    public, private = crypto.generate_publisher()
    key = 'BlitzCamera-UI-Test-' + uuid4().hex
    provider = 'Microsoft Software Key Storage Provider'
    device_public = crypto.device_public(key, provider, create=True)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp, \
                patch.dict(os.environ, {'BLITZCAM_PROFILE_ROOT':str(Path(tmp)/'account')}), \
                patch('blitzcam.server.OUTPUT', Path(tmp)/'output'), \
                patch('blitzcam.settings.documents_directory', return_value=Path(tmp)/'Documents'):
            folder = Path(tmp)
            trust = folder/'trust.json'
            write_json(trust, {'keys': {digest(public): base64.b64encode(public).decode('ascii')}})
            app = Workstation(folder/'project.json'); app.stop.set(); app.poller.join()
            manager = Deployment(folder/'output', root=folder, trust=trust)
            app.deployment = app.backend.deployment = manager
            write_json(manager.directory/'device.json', {'key_name': key, 'provider': provider, 'device': digest(device_public)})
            config, package, invalid = folder/'local.bcconfig', folder/'update.bcupdate', folder/'invalid.bcupdate'
            invalid.write_bytes(b'not a package')
            calls = {'export': 0, 'select': 0}
            def choose(**kwargs):
                if kwargs.get('save'):
                    calls['export'] += 1
                    return None if calls['export'] == 1 else config
                calls['select'] += 1
                if calls['select'] == 1:
                    return invalid
                build_pro(ROOT/'blitzcam', config, package, version='11.21-r1', public=public, private=private,
                          game_sha256='5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608', notes='离线部署验收')
                return package
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app)); server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            env = dict(os.environ, NODE_PATH=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
            try:
                with patch('blitzcam.file_dialogs.show_dialog', side_effect=choose), \
                        patch.object(app.backend, 'connect', side_effect=AssertionError('UI test accessed game')):
                    subprocess.run(['node', str(ROOT/'tools/test_deployment_ui.cjs'),
                                    f'http://127.0.0.1:{server.server_address[1]}'], cwd=ROOT, env=env, check=True)
                assert manager.enabled and not app.backend.loaded
            finally:
                server.shutdown(); server.server_close(); thread.join(); app.close()
    finally:
        with crypto.device_key(key, provider) as (dll, handle):
            crypto._check(crypto._fn(dll, 'NCryptDeleteKey', [crypto.HANDLE, crypto.U32])(handle, 0), '清理测试密钥')
            handle.value = 0


if __name__ == '__main__':
    main()
