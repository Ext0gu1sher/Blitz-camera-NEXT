"""Bounded, signed offline package format shared by publisher and client."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from . import package_crypto as crypto

FORMAT = 'blitz-camera-package-v1'
API = 1
MAX_PACKAGE = 512 * 1024 * 1024
MAX_FILES = 6000
PRO_MODULES = ('playback', 'hook_guards', 'hook_layout', 'hook_transport',
               'replay_trial', 'seek_trial', 'seek_phase_trial', 'replay_seek',
               'replay_preparation', 'freecamera')
ADAPTER_MODULES = PRO_MODULES + ('profile', 'reader', 'memory', 'replay_source')
PRO_MANIFESTS = ('position_hook_1121.json', 'replay_seek_phase_trial_1121.json',
                 'freecamera_switch_1121.json')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unbase64(value):
    if not isinstance(value, str) or len(value) > 32768:
        raise ValueError('包中的密钥或签名无效。')
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('包中的编码无效。') from exc


def safe_name(value):
    if not isinstance(value, str) or not value or len(value) > 230 or '\\' in value or ':' in value:
        raise ValueError('包中包含无效文件路径。')
    parts = value.split('/')
    if any(not p or p in ('.', '..') or p[-1:] in ('.', ' ') or
           any(ord(c) < 32 or c in '<>"|?*' for c in p) or
           re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', p) for p in parts):
        raise ValueError('包中包含不安全的文件路径。')
    if PurePosixPath(value).is_absolute():
        raise ValueError('包中的路径必须是相对路径。')
    return value


def file_map(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_FILES:
        raise ValueError('包文件清单无效。')
    names = set()
    for name, sha in value.items():
        safe_name(name)
        if name.casefold() in names or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('包文件清单存在重复名称或无效哈希。')
        names.add(name.casefold())
    return value


def read_zip(source, *, limit=MAX_PACKAGE):
    """Validate all names, types and uncompressed bounds before extracting."""
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_FILES or sum(i.file_size for i in infos) > limit:
            raise ValueError('包文件数量或展开大小超出限制。')
        seen = set()
        for item in infos:
            name = safe_name(item.filename)
            mode = item.external_attr >> 16
            if (name.casefold() in seen or item.is_dir() or item.flag_bits & 1 or
                    stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError('包中存在重复文件、链接或不支持的文件类型。')
            seen.add(name.casefold())
        return {i.filename: archive.read(i) for i in infos}


def zip_bytes(files):
    file_map({name: digest(data) for name, data in files.items()})
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return out.getvalue()


def checked_payload(payload, expected):
    files = read_zip(io.BytesIO(payload))
    if set(files) != set(file_map(expected)) or any(digest(data) != expected[n] for n, data in files.items()):
        raise ValueError('包内容与签名清单不一致。')
    return files


def read_signed(path, trust_path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_PACKAGE:
        raise ValueError('升级包不存在或大小超出限制。')
    # The small header is authenticated before processing any executable content.
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) != 3 or {i.filename for i in infos} != {'manifest.json', 'signature.bin', 'payload.bin'}:
            raise ValueError('不是有效的 Blitz Camera 离线包。')
        if archive.getinfo('manifest.json').file_size > 2 * 1024 * 1024 or archive.getinfo('signature.bin').file_size > 1024:
            raise ValueError('包清单大小无效。')
        header = archive.read('manifest.json')
        manifest = json.loads(header)
        if not isinstance(manifest, dict) or canonical(manifest) != header:
            raise ValueError('包清单格式无效。')
        trust = json.loads(Path(trust_path).read_text(encoding='utf-8'))
        public = unbase64(trust.get('keys', {}).get(manifest.get('signer')))
        if digest(public) != manifest.get('signer'):
            raise ValueError('无法确认包的发布者。')
        crypto.verify(public, header, archive.read('signature.bin'))
    if (manifest.get('format') != FORMAT or manifest.get('api') != API or
            manifest.get('kind') not in ('app', 'pro') or
            not re.fullmatch('[0-9a-f]{32}', str(manifest.get('id', ''))) or
            not isinstance(manifest.get('version'), str) or not 1 <= len(manifest['version']) <= 60):
        raise ValueError('包格式或接口版本不兼容，请使用兼容的完整安装包。')
    file_map(manifest.get('files'))
    outer = read_zip(path)
    payload = outer['payload.bin']
    if digest(payload) != manifest.get('payload_sha256'):
        raise ValueError('包内容损坏或已被修改。')
    return manifest, payload


def write_signed(path, manifest, payload, public, private):
    manifest = dict(manifest, format=FORMAT, api=API, signer=digest(public), payload_sha256=digest(payload))
    header = canonical(manifest)
    data = zip_bytes({'manifest.json': header, 'signature.bin': crypto.sign(private, header), 'payload.bin': payload})
    if len(data) > MAX_PACKAGE:
        raise ValueError('发布包过大。')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)
    return manifest


def pro_aad(manifest):
    return canonical({k: manifest[k] for k in ('id', 'version', 'device', 'game_sha256', 'adapter_api')})


def decrypt_pro(manifest, payload, device):
    if manifest.get('kind') != 'pro' or manifest.get('adapter_api') != API:
        raise ValueError('升级包接口版本不兼容。')
    if not device or manifest.get('device') != device.get('device'):
        raise ValueError('此升级包与本机配置不匹配，请导出配置交给发布者。')
    public = crypto.device_public(device['key_name'], device['provider'])
    if digest(public) != device['device']:
        raise ValueError('本机密钥与设备登记不一致，请重新登记。')
    secret = crypto.unwrap_device(device['key_name'], device['provider'], unbase64(manifest.get('wrapped_key')))
    clear, _ = crypto.aes_gcm(secret, unbase64(manifest.get('nonce')), payload, pro_aad(manifest),
                              tag=unbase64(manifest.get('tag')))
    files = checked_payload(clear, manifest['files'])
    allowed = {name + '.py' for name in ADAPTER_MODULES}
    if not allowed.issubset(files):
        raise ValueError('升级包缺少运行模块。')
    for name in files:
        if name not in allowed and not (name.startswith('native/') and '/' not in name[7:] and Path(name).suffix in ('.dll', '.json')):
            raise ValueError('升级包包含不支持的文件。')
        if name in allowed:
            try:
                compile(files[name], name, 'exec')
            except (SyntaxError, ValueError) as exc:
                raise ValueError('升级包中的运行模块无法加载。') from exc
        elif name.endswith('.json'):
            native = json.loads(files[name])
            dll = 'native/' + safe_name(native['dll'])
            if dll not in files or digest(files[dll]) != native['sha256']:
                raise ValueError('升级包中的组件校验不一致。')
    return files
