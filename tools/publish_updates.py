"""Publisher-only offline package builder. Never included in client releases."""
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blitzcam import package_crypto as crypto
from blitzcam.packages import (API, ADAPTER_MODULES, PRO_MANIFESTS, canonical, digest,
                               file_map, pro_aad, safe_name, unbase64, write_signed, zip_bytes)
from blitzcam.offline_updater import clean_path, validate_target, write_json


def initialize(key_file, trust_file):
    key_file, trust_file = Path(key_file), Path(trust_file)
    if key_file.exists() or trust_file.exists():
        raise ValueError('密钥或信任文件已存在；不会覆盖发布者身份。')
    public, private = crypto.generate_publisher()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(crypto.protect_local(private))
    write_json(trust_file, {'keys': {digest(public): base64.b64encode(public).decode('ascii')}})
    return digest(public)


def signing_keys(key_file, trust_file):
    private = crypto.protect_local(Path(key_file).read_bytes(), decrypt=True)
    trust = json.loads(Path(trust_file).read_text(encoding='utf-8'))
    # Test every configured public key; no private material is ever logged.
    challenge = os.urandom(32)
    signature = crypto.sign(private, challenge)
    for raw in trust['keys'].values():
        public = unbase64(raw)
        try:
            crypto.verify(public, challenge, signature)
            return public, private
        except crypto.CryptoError:
            pass
    raise ValueError('发布私钥与客户端信任文件不匹配。')


def backup_key(key_file, trust_file, destination, password):
    if len(password) < 16:
        raise ValueError('备份口令至少需要 16 个字符。')
    if Path(destination).exists():
        raise ValueError('备份文件已存在，不会覆盖。')
    public, private = signing_keys(key_file, trust_file)
    salt, nonce = os.urandom(16), os.urandom(12)
    secret = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600000, 32)
    context = b'blitz-camera-publisher-backup-v1'
    cipher, tag = crypto.aes_gcm(secret, nonce, private, context)
    write_json(destination, {'format': context.decode(), 'rounds': 600000,
               **{k: base64.b64encode(v).decode('ascii') for k,v in
                  {'public': public, 'salt': salt, 'nonce': nonce, 'tag': tag, 'cipher': cipher}.items()}})


def restore_key(backup, key_file, trust_file, password):
    if Path(key_file).exists():
        raise ValueError('发布私钥已存在，不会覆盖。')
    value = json.loads(Path(backup).read_text(encoding='utf-8'))
    if value.get('format') != 'blitz-camera-publisher-backup-v1' or value.get('rounds') != 600000:
        raise ValueError('备份格式不兼容。')
    salt = unbase64(value['salt'])
    if len(salt) != 16:
        raise ValueError('备份参数无效。')
    secret = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600000, 32)
    private, _ = crypto.aes_gcm(secret, unbase64(value['nonce']), unbase64(value['cipher']),
                             value['format'].encode(), tag=unbase64(value['tag']))
    public = unbase64(value['public']); crypto.validate_public(public)
    crypto.verify(public, b'backup-identity', crypto.sign(private, b'backup-identity'))
    trust = json.loads(Path(trust_file).read_text(encoding='utf-8'))
    if trust.get('keys', {}).get(digest(public)) != value['public']:
        raise ValueError('备份与现有客户端信任身份不一致。')
    Path(key_file).parent.mkdir(parents=True, exist_ok=True)
    Path(key_file).write_bytes(crypto.protect_local(private))


def seal_pro(files, request, destination, *, version, public, private, game_sha256, notes='', metadata=None):
    """Shared v1 device envelope; source building and master issuance use this."""
    if request.get('format') != 'blitz-camera-device-v1' or request.get('api') != API:
        raise ValueError('设备配置格式不兼容。')
    device_public = unbase64(request.get('public_key'))
    if crypto.validate_public(device_public) != request.get('device'):
        raise ValueError('设备公钥与配置不一致。')
    file_map({'client.exe': game_sha256})
    manifest = {'id': uuid4().hex, 'kind': 'pro', 'version': version, 'adapter_api': API,
                'device': request['device'], 'game_sha256': game_sha256, 'notes': notes,
                'files': {n: digest(b) for n, b in files.items()}}
    if metadata:
        manifest['source_master'] = metadata
    secret, nonce = os.urandom(32), os.urandom(12)
    cipher, tag = crypto.aes_gcm(secret, nonce, zip_bytes(files), pro_aad(manifest))
    for key, value in {'nonce': nonce, 'tag': tag, 'wrapped_key': crypto.wrap_key(device_public, secret)}.items():
        manifest[key] = base64.b64encode(value).decode('ascii')
    return write_signed(destination, manifest, cipher, public, private)


def build_pro(source, request, destination, *, version, public, private, game_sha256, notes='', native_manifests=None):
    source = Path(source).resolve()
    request = json.loads(Path(request).read_text(encoding='utf-8'))
    files = {name + '.py': (source/(name + '.py')).read_bytes() for name in ADAPTER_MODULES}
    for name in (native_manifests or PRO_MANIFESTS):
        safe_name(name)
        if '/' in name or not name.endswith('.json'):
            raise ValueError('原生组件清单名称无效。')
        raw = (source/'native'/name).read_bytes()
        native = json.loads(raw)
        safe_name(native['dll'])
        if '/' in native['dll'] or not native['dll'].endswith('.dll'):
            raise ValueError('原生组件路径无效。')
        data = (source/'native'/native['dll']).read_bytes()
        if digest(data) != native['sha256']:
            raise ValueError('原生组件哈希不一致。')
        files['native/' + name] = raw
        files['native/' + native['dll']] = data
    return seal_pro(files, request, destination, version=version, public=public, private=private,
                    game_sha256=game_sha256, notes=notes)


def build_app(base, target, destination, *, public, private, notes=''):
    base, target = Path(base).resolve(), Path(target).resolve()
    base_raw = (base/'manifest.json').read_bytes()
    old = json.loads(base_raw)
    new = json.loads((target/'manifest.json').read_text(encoding='utf-8'))
    file_map(old['files']); file_map(new['files'])
    runtime = lambda value: {n: h for n, h in value['files'].items() if n.startswith('runtime/')}
    if runtime(old) != runtime(new):
        raise ValueError('运行环境变化，需要分发完整安装包。')
    if old['files'].get('BlitzCamera.exe') != new['files'].get('BlitzCamera.exe'):
        raise ValueError('启动器变化，需要分发完整安装包。')
    files = {}
    for name, expected in new['files'].items():
        data = clean_path(target, name).read_bytes()
        if digest(data) != expected:
            raise ValueError('目标文件与发布清单不一致：' + name)
        if old['files'].get(name) != expected:
            files[name] = data
    if not files:
        raise ValueError('目标版本没有文件变化。')
    manifest = {'id': uuid4().hex, 'kind': 'app', 'version': new['version'], 'notes': notes,
                'base_manifest_sha256': digest(canonical(old)), 'base_version': old['version'],
                'target_manifest': new, 'files': {n: digest(b) for n, b in files.items()}}
    validate_target(manifest)
    return write_signed(destination, manifest, zip_bytes(files), public, private)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', type=Path, required=True, help='Current Windows user DPAPI-protected publisher private key')
    parser.add_argument('--trust', type=Path, default=ROOT/'blitzcam/package-trust.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    backup = sub.add_parser('backup-key')
    backup.add_argument('--output', type=Path, required=True)
    restore = sub.add_parser('restore-key')
    restore.add_argument('--backup', type=Path, required=True)
    app = sub.add_parser('app')
    app.add_argument('--base', type=Path, required=True)
    app.add_argument('--target', type=Path, required=True)
    pro = sub.add_parser('pro')
    pro.add_argument('--source', type=Path, default=ROOT/'blitzcam')
    pro.add_argument('--config', type=Path, required=True)
    pro.add_argument('--version', required=True)
    pro.add_argument('--game-sha256', required=True)
    pro.add_argument('--native-manifest', action='append', help='Override native manifests when adapting a new client build')
    for command in (app, pro):
        command.add_argument('--output', type=Path, required=True)
        command.add_argument('--notes', default='')
    args = parser.parse_args()
    if args.command == 'init':
        print('Publisher public identity: ' + initialize(args.key, args.trust))
        return
    if args.command in ('backup-key', 'restore-key'):
        password = getpass.getpass('Backup password: ')
        if args.command == 'backup-key':
            if password != getpass.getpass('Repeat backup password: '):
                raise ValueError('两次口令不一致。')
            backup_key(args.key, args.trust, args.output, password)
        else:
            restore_key(args.backup, args.key, args.trust, password)
        print('Publisher key operation completed. Keep the encrypted backup and password separately.')
        return
    public, private = signing_keys(args.key, args.trust)
    common = dict(public=public, private=private, notes=args.notes)
    if args.command == 'app':
        value = build_app(args.base, args.target, args.output, **common)
    else:
        value = build_pro(args.source, args.config, args.output, version=args.version, game_sha256=args.game_sha256,
                          native_manifests=args.native_manifest, **common)
    print(json.dumps({'output': str(args.output), 'version': value['version'], 'bytes': args.output.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
