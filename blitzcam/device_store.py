"""Current Windows user's durable device identities, independent of installs."""
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from . import package_crypto as crypto
from .packages import canonical, digest

PROVIDERS = ('Microsoft Platform Crypto Provider', 'Microsoft Software Key Storage Provider')
KEY_PATTERN = re.compile(r'BlitzCamera-(?:[0-9a-f]{32}|Device-v1-[0-9a-f]{24})\Z')


def shared_profile_root():
    override = os.environ.get('BLITZCAM_PROFILE_ROOT')
    if override: return Path(override).resolve()
    local = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))
    return (local/'BlitzCamera/deployment').resolve()


def atomic_bytes(path, content, *, replace=True):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name('.'+path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        if replace: temporary.replace(path)
        elif os.name == 'nt': os.rename(temporary,path)
        else: os.link(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


class DeviceStore:
    def __init__(self, profile, legacy):
        self.profile, self.legacy = Path(profile).resolve(), Path(legacy).resolve()
        self.default = self.profile/'device.json'
        # The path is the stable account profile, never the installation path.
        self.stable_name = 'BlitzCamera-Device-v1-'+digest(str(self.profile).casefold().encode())[:24]

    def read(self, path):
        try:
            if Path(path).stat().st_size > 16384: return None
            value = json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(value,dict) or not re.fullmatch('[0-9a-f]{64}', str(value.get('device',''))): return None
            if not isinstance(value.get('key_name'),str) or not 1 <= len(value['key_name']) <= 200: return None
            if value.get('provider') not in PROVIDERS: return None
            return {k:value[k] for k in ('device','key_name','provider')}
        except (OSError,ValueError): return None

    def validate(self, value):
        public = crypto.device_public(value['key_name'],value['provider'])
        if digest(public) != value['device']:
            raise ValueError('本机登记与安全存储不一致。')
        return value, public

    def remember(self, value):
        path = self.profile/'devices'/(value['device']+'.json')
        if self.read(path) != value: atomic_bytes(path,canonical(value))
        # First usable identity stays the export identity. Importing a package
        # issued to another legacy key never rotates future exported configs.
        if not self.default.exists():
            try: atomic_bytes(self.default,canonical(value),replace=False)
            except FileExistsError: pass

    def resolve(self, *, expected=None, create=False):
        if expected is not None and not re.fullmatch('[0-9a-f]{64}', str(expected)):
            raise ValueError('升级包设备标识无效。')
        candidates = ([self.profile/'devices'/(expected+'.json')] if expected else [])
        candidates += [self.default, self.legacy/'device.json']
        if not expected and self.default.exists():
            value = self.read(self.default)
            if value:
                try: return self.validate(value)
                except crypto.CryptoError:
                    raise ValueError('原本机密钥暂时不可用，请使用原 Windows 用户重试；不会重新生成身份。')
            raise ValueError('本机登记文件损坏，请重新导入原升级包以恢复登记。')
        for path in dict.fromkeys(candidates):
            value = self.read(path)
            if not value or expected and value['device'] != expected: continue
            try: result = self.validate(value)
            except (ValueError,OSError): continue
            self.remember(value); return result
        if expected:
            # A delayed package may arrive after the user changes installation
            # folders or loses device.json. Locate only this app's own keys,
            # then match the signed recipient fingerprint and actually decrypt.
            for provider in PROVIDERS:
                try: names = crypto.stored_key_names(provider)
                except crypto.CryptoError: continue
                for name in names:
                    if not KEY_PATTERN.fullmatch(name): continue
                    try: public = crypto.device_public(name,provider)
                    except crypto.CryptoError: continue
                    if digest(public) == expected:
                        value = {'device':expected,'key_name':name,'provider':provider}
                        self.remember(value)
                        if self.default.exists() and not self.read(self.default): atomic_bytes(self.default,canonical(value))
                        return value,public
            raise ValueError('此升级包与当前 Windows 用户的本机密钥不匹配。请使用原来导出配置的电脑和 Windows 用户；关闭软件或等待不会使配置失效。')
        if not create:
            raise ValueError('尚未建立本机登记。导入已有升级包会自动恢复；首次发包时导出一次配置即可。')
        # Recover a stable key before generating one, even if the profile's
        # metadata was removed. Different install folders use this same name.
        for provider in PROVIDERS:
            try: public = crypto.device_public(self.stable_name,provider)
            except crypto.CryptoError: continue
            value = {'device':digest(public),'key_name':self.stable_name,'provider':provider}
            self.remember(value)
            return self.resolve()
        for provider in PROVIDERS:
            try:
                try: public = crypto.device_public(self.stable_name,provider,create=True)
                except crypto.CryptoError:
                    # A concurrent first launch may have created it already.
                    public = crypto.device_public(self.stable_name,provider)
            except crypto.CryptoError:
                if provider == PROVIDERS[-1]: raise
                continue
            value = {'device':digest(public),'key_name':self.stable_name,'provider':provider}
            self.remember(value)
            return self.resolve()
