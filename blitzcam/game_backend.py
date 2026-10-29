"""Narrow host interface to authenticated, device-bound game components."""
import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import threading
import types
from uuid import uuid4

from . import profile
from .offline_updater import clean_path
from .packages import digest


class PackageModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, namespace, files, directory):
        self.namespace, self.files, self.directory = namespace, files, directory

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(self.namespace + '.'):
            return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__.removeprefix(self.namespace + '.')
        source = self.files.get(name + '.py')
        if source is None:
            # Shared helpers keep class and exception identity with the host.
            original = importlib.import_module('blitzcam.' + name)
            module.__dict__.update({k: v for k, v in vars(original).items()
                                    if k not in ('__name__', '__loader__', '__spec__', '__package__')})
            return
        module.__file__ = str(self.directory/(name + '.py'))
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        if name == 'profile':
            for key in ('CameraError', 'SessionChanged', 'IncoherentSample'):
                setattr(module, key, getattr(profile, key))


class GameBackend:
    def __init__(self, deployment):
        self.deployment = deployment
        self.namespace = None
        self.loaded = False
        self.lock = threading.RLock()

    def require(self):
        if not self.deployment.enabled or self.deployment.restart_pending:
            raise profile.CameraError('此操作当前不可用。')

    def load(self):
        with self.lock:
            self.require()
            if self.loaded:
                return
            files, manifest = self.deployment.files, self.deployment.manifest
            directory = clean_path(self.deployment.output, 'deployment/runtime/' + manifest['id'])
            directory.mkdir(parents=True, exist_ok=True)
            # Python modules stay in memory. Windows' normal DLL loader requires
            # files; materialize only authenticated native components on demand.
            for name, content in files.items():
                if name.startswith('native/'):
                    target = clean_path(directory, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists() or digest(target.read_bytes()) != digest(content):
                        target.write_bytes(content)
            namespace = '_blitzcam_adapter_' + uuid4().hex
            module = types.ModuleType(namespace)
            module.__path__ = []
            sys.modules[namespace] = module
            self.finder = PackageModules(namespace, files, directory)
            sys.meta_path.insert(0, self.finder)
            self.namespace, self.loaded = namespace, True

    def module(self, name):
        self.load()
        return importlib.import_module(self.namespace + '.' + name)

    def connect(self, *args, **kwargs):
        session = self.module('reader').CameraSession.connect(*args, **kwargs)
        if session.profile.sha256 != self.deployment.manifest['game_sha256']:
            session.close()
            raise profile.CameraError('当前客户端与升级包适配版本不一致，请获取匹配的升级包。')
        return session


class PositionPlayback:
    def __init__(self, output, backend):
        self.output, self.backend, self.delegate = output, backend, None
        self._cancel = threading.Event()

    @property
    def cancel(self):
        return self.delegate.cancel if self.delegate else self._cancel

    def state(self):
        return self.delegate.state() if self.delegate else {'active': False, 'state': 'idle', 'message': '', 'progress': 0}

    def stop(self, *args, **kwargs):
        if self.delegate:
            return self.delegate.stop(*args, **kwargs)

    def __getattr__(self, name):
        if name not in ('start', 'prepare', 'seek', 'pause'):
            raise AttributeError(name)
        def call(*args, **kwargs):
            self.backend.require()
            if self.delegate is None:
                self.delegate = self.backend.module('playback').PositionPlayback(self.output)
            return getattr(self.delegate, name)(*args, **kwargs)
        return call
