"""Offline deployment, device registration and signed package activation."""
import base64
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from uuid import uuid4
import zipfile

from . import __version__, package_crypto as crypto
from .packages import API, MAX_PACKAGE, digest, read_signed, decrypt_pro
from .offline_updater import clean_path, prepare, write_json
from .device_store import DeviceStore, atomic_bytes


class Deployment:
    def __init__(self, output, *, root=None, trust=None, profile_root=None):
        self.output = Path(output).resolve()
        self.directory = self.output/'deployment'
        # Local jobs/runtime remain portable. Authorization belongs to the
        # Windows user; the application passes its shared account profile.
        # Low-level isolated callers can retain a private directory by default.
        self.profile = Path(profile_root).resolve() if profile_root is not None else self.directory
        self.devices = DeviceStore(self.profile,self.directory)
        self.root = Path(root or os.environ.get('BLITZCAM_INSTALL_ROOT', Path(__file__).resolve().parents[1])).resolve()
        self.trust = Path(trust or Path(__file__).with_name('package-trust.json'))
        self.lock = threading.RLock()
        self.pending = None
        self.manifest, self.files, self.error = None, None, ''
        self.restart_pending = False
        self.refresh()

    @property
    def enabled(self):
        return self.files is not None

    def can_restart(self):
        return all((self.root/name).is_file() for name in
                   ('manifest.json', 'runtime/pythonw.exe', 'BlitzCamera.exe'))

    def startup_state(self):
        """Read without consuming: only a completed splash acknowledges the token."""
        with self.lock:
            token = ''
            if self.enabled:
                try:
                    value = json.loads((self.profile/'pro-intro.json').read_text(encoding='utf-8'))
                    candidate = value.get('token') if isinstance(value, dict) else None
                    if isinstance(candidate, str) and re.fullmatch('[0-9a-f]{32}', candidate):
                        token = candidate
                except (OSError, ValueError):
                    pass
            return {'edition': 'pro' if self.enabled else 'next', 'intro_token': token}

    def acknowledge_startup(self, token):
        with self.lock:
            if not token or token != self.startup_state()['intro_token']:
                return False
            (self.profile/'pro-intro.json').unlink(missing_ok=True)
            return True

    def device(self, *, create=False, expected=None):
        return self.devices.resolve(create=create,expected=expected)

    def export_config(self, destination):
        with self.lock:
            device, public = self.device(create=True)
            value = {'format': 'blitz-camera-device-v1', 'api': API,
                     'app_version': __version__, 'device': device['device'],
                     'public_key': base64.b64encode(public).decode('ascii'),
                     'protection': 'tpm' if device['provider'] == 'Microsoft Platform Crypto Provider' else 'windows-user'}
            write_json(destination, value)
            return {'ok': True, 'message': '配置已导出并记住。可关闭软件，收到升级包后直接导入，无需再次导出。'}

    def refresh(self):
        with self.lock:
            self.manifest, self.files, self.error = None, None, ''
            path = self.profile/'active.bcupdate'
            migrate = not path.exists() and self.profile != self.directory
            if migrate: path = self.directory/'active.bcupdate'
            if not path.exists():
                return
            try:
                manifest, payload = read_signed(path, self.trust)
                device, _ = self.device(expected=manifest.get('device'))
                files = decrypt_pro(manifest, payload, device)
                if migrate:
                    # Import a valid legacy activation once. Existing shared
                    # activation always wins over stale older install copies.
                    try: atomic_bytes(self.profile/'active.bcupdate',path.read_bytes(),replace=False)
                    except FileExistsError:
                        return self.refresh()
                self.manifest, self.files = manifest, files
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
                self.error = '已部署文件无法验证，请重新导入升级包。' + str(exc)

    def status(self):
        result = None
        try:
            result = json.loads((self.directory/'last-result.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        return {'version': __version__, 'edition': 'pro' if self.enabled else 'next',
                'message': self.error, 'last_result': result,
                'restart_pending': self.restart_pending,
                'can_update_app': (self.root/'manifest.json').is_file() and (self.root/'runtime/pythonw.exe').is_file()}

    def inspect(self, path):
        with self.lock:
            if self.restart_pending:
                raise ValueError('正在等待重启，请完成本次升级后再导入。')
            self.pending = None
            path = Path(path)
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_PACKAGE:
                raise ValueError('升级包不存在或大小超出限制。')
            # Keep a private snapshot; replacing the originally selected file
            # cannot substitute a different package between preview and install.
            work = self.directory/'incoming'/uuid4().hex
            work.mkdir(parents=True)
            copied = work/'package.bcupdate'
            with path.open('rb') as source, copied.open('xb') as target:
                remaining = MAX_PACKAGE + 1
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    target.write(chunk)
                    remaining -= len(chunk)
                if not remaining:
                    raise ValueError('升级包过大。')
            try:
                manifest, payload = read_signed(copied, self.trust)
                if manifest['kind'] == 'pro':
                    device, _ = self.device(expected=manifest.get('device'))
                    decrypt_pro(manifest, payload, device)
                else:
                    if not self.status()['can_update_app']:
                        raise ValueError('源码运行不支持主程序升级，请在完整桌面版中部署。')
                    prepare(self.root, copied, self.trust, work/'validation')
            except zipfile.BadZipFile as exc:
                raise ValueError('无法读取升级包，文件可能损坏。') from exc
            token = uuid4().hex
            self.pending = {'token': token, 'path': copied, 'manifest': manifest}
            return {'token': token, 'name': path.name, 'version': manifest['version'],
                    'notes': str(manifest.get('notes', ''))[:4000],
                    'bytes': copied.stat().st_size,
                    'restart': manifest['kind'] == 'app' or self.can_restart()}

    def install(self, token, *, pids=(), backend_loaded=False, restart_pro=False):
        with self.lock:
            if not self.pending or token != self.pending['token'] or self.restart_pending:
                raise ValueError('请重新选择并检查升级包。')
            path = self.pending['path']
            manifest, payload = read_signed(path, self.trust)
            if manifest['kind'] == 'pro':
                restart = restart_pro and self.can_restart()
                if backend_loaded and not restart:
                    raise ValueError('本次运行已加载游戏组件，请关闭并重新启动应用，再导入升级包。')
                device, _ = self.device(expected=manifest.get('device'))
                files = decrypt_pro(manifest, payload, device)
                first_upgrade = not self.enabled
                active = self.profile/'active.bcupdate'
                if active.exists():
                    atomic_bytes(self.profile/'previous.bcupdate',active.read_bytes())
                atomic_bytes(active,path.read_bytes())
                if self.profile != self.directory:
                    # Keep this installation usable if opened with 0.9.6 again.
                    # The shared committed package is authoritative afterwards.
                    try:
                        write_json(self.directory/'device.json',device)
                        atomic_bytes(self.directory/'active.bcupdate',path.read_bytes())
                    except OSError: pass
                self.manifest, self.files, self.error = manifest, files, ''
                if first_upgrade:
                    write_json(self.profile/'pro-intro.json', {'token': uuid4().hex})
                self.pending = None
                result = {'ok': True, 'restart': False, 'reload': first_upgrade,
                          'edition': 'pro', 'message': '升级包已部署。'}
                if restart:
                    # Keep existing loaded modules idle until this process exits.
                    # Low-level issuance/tests opt out; the desktop API opts in.
                    self.restart_pending = True
                    try:
                        self._schedule_restart(pids)
                    except (OSError, ValueError) as exc:
                        result.update(reload=False, restart_failed=True, restart_error=str(exc),
                                      message='升级包已部署，但自动重启未能启动。请退出并重新打开应用。')
                    else:
                        result.update(restart=True, reload=False, message='升级包已部署，正在重新启动应用。')
                write_json(self.directory/'last-result.json', result)
                return result
            self._schedule_restart(pids, path)
            self.restart_pending = True
            self.pending = None
            return {'ok': True, 'restart': True, 'message': '升级已就绪，保存并关闭应用后自动完成更新并重新打开。'}

    def _schedule_restart(self, pids, package_path=None):
        # The helper and trust root must live outside app/, whose files will
        # be exchanged only after launcher, service and desktop all exit.
        work = clean_path(self.root, 'output/deployment/jobs/' + uuid4().hex)
        helper = clean_path(self.root, 'output/deployment/helper/blitzcam')
        helper.mkdir(parents=True, exist_ok=True)
        (helper/'__init__.py').write_text('', encoding='utf-8')
        for name in ('offline_updater.py', 'packages.py', 'package_crypto.py'):
            shutil.copyfile(Path(__file__).with_name(name), helper/name)
        trust = helper.parent/'trust.json'
        shutil.copyfile(self.trust, trust)
        work.mkdir(parents=True)
        runner = helper.parent/'run.py'
        runner.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).parent))\nfrom blitzcam.offline_updater import main\nmain()\n", encoding='utf-8')
        job = work/'job.json'
        value = {'root': str(self.root), 'data_root': str(self.output.parent),
                 'pids': list(set([os.getpid(), *pids])), 'action': 'restart'}
        if package_path is not None:
            package = work/'package.bcupdate'
            shutil.copyfile(package_path, package)
            value.update(action='app', package=str(package), trust=str(trust), work=str(work))
        write_json(job, value)
        subprocess.Popen([str(self.root/'runtime/pythonw.exe'), '-X', 'utf8', '-B', str(runner), '--job', str(job)],
                         cwd=helper.parent, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
