"""Versioned, deterministic internal adapter masters; inspection executes no code."""
import ast
import io
import json
import os
from pathlib import Path
import re
import struct
import zipfile
from uuid import uuid4

from blitzcam.packages import API, ADAPTER_MODULES, MAX_PACKAGE, canonical, digest, file_map, read_zip, safe_name

SOURCE_FORMAT = 'blitz-camera-pro-source-v1'
MASTER_FORMAT = 'blitz-camera-pro-master-v1'
HOST_MODULES = ('pose', 'project', 'speed', 'trajectory', 'replay_timeline')
ENTRYPOINTS = {'reader': 'reader:CameraSession', 'playback': 'playback:PositionPlayback'}


def read_json(path, limit=2*1024*1024):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError('文件不存在或大小不符合规范：' + path.name)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def text_field(value, name, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c)<32 for c in value):
        raise ValueError('字段无效：' + name)
    return value


def version_key(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:-(alpha|beta|rc)(?:[.-]?(\d+))?)?', str(value))
    if not match:
        raise ValueError('主程序版本须为数字版本，可带 alpha / beta / rc 后缀。')
    major, minor, patch, fourth, phase, number = match.groups()
    return tuple(map(int, (major, minor, patch, fourth or '0'))) + ({'alpha':0,'beta':1,'rc':2,None:3}[phase], int(number or 0))


def validate_release(value):
    if not isinstance(value, dict) or set(value) != {'adapter_id','version','adapter_api','host_min_version','client','entrypoints','notes','validation'}:
        raise ValueError('适配清单字段不完整或包含未定义字段。')
    if not re.fullmatch('[a-z0-9][a-z0-9.-]{2,79}', str(value['adapter_id'])):
        raise ValueError('adapter_id 只允许小写字母、数字、点和短横线。')
    text_field(value['version'], 'version', 60)
    if type(value['adapter_api']) is not int or value['adapter_api'] != API:
        raise ValueError('适配接口不兼容；更改接口时需同步更新宿主与制作工具。')
    version_key(value['host_min_version'])
    if value['entrypoints'] != ENTRYPOINTS:
        raise ValueError('v1 入口必须为 reader:CameraSession 和 playback:PositionPlayback。')
    client = value['client']
    if not isinstance(client, dict) or set(client) != {'channel','version','sha256','architecture'}:
        raise ValueError('客户端构建信息不完整。')
    text_field(client['channel'], 'client.channel'); text_field(client['version'], 'client.version')
    file_map({'client.exe': client['sha256']})
    if client['architecture'] != 'x86':
        raise ValueError('当前 v1 宿主仅支持已验证的 x86 客户端。')
    if not isinstance(value['notes'], str) or len(value['notes']) > 4000:
        raise ValueError('更新说明不能超过 4000 字。')
    validation = value['validation']
    if not isinstance(validation, dict) or set(validation) != {'level','summary'}:
        raise ValueError('需要明确验证级别与验证说明。')
    if validation['level'] not in ('offline', 'game'):
        raise ValueError('验证级别为 offline 或 game；未完成离线检查不能制作母包。')
    text_field(validation['summary'], 'validation.summary', 1500)
    return value


def deterministic_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(safe_name(name), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def validate_payload(files):
    required = {name + '.py' for name in ADAPTER_MODULES}
    if not required.issubset(files):
        raise ValueError('缺少必需适配模块：' + ', '.join(sorted(required-set(files))))
    trees, referenced = {}, set()
    for name, data in files.items():
        safe_name(name)
        if name in required:
            try:
                tree = ast.parse(data, filename=name)
                compile(tree, name, 'exec')
            except (SyntaxError, ValueError) as exc:
                raise ValueError('模块语法不兼容：' + name) from exc
            trees[name] = tree
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    if node.level != 1 or node.module not in (*ADAPTER_MODULES, *HOST_MODULES):
                        raise ValueError(f'{name} 引用了 v1 契约之外的相对模块：{node.module}')
                if isinstance(node, (ast.Import, ast.ImportFrom)) and not getattr(node, 'level', 0):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
                    if any(n == 'blitzcam' or n.startswith('blitzcam.') for n in names):
                        raise ValueError(name + ' 必须使用相对导入，避免绕过适配命名空间。')
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch('[a-zA-Z0-9_.-]+\.json', node.value):
                    referenced.add(node.value)
        elif not (name.startswith('native/') and '/' not in name[7:] and Path(name).suffix in ('.dll','.json')):
            raise ValueError('母包中不允许包含此文件：' + name)
    for filename, classname, methods in (('reader.py','CameraSession',{'connect','capture','close'}),
                                         ('playback.py','PositionPlayback',{'state','start','stop','pause','prepare','seek'})):
        classes = [n for n in trees[filename].body if isinstance(n, ast.ClassDef) and n.name == classname]
        available = {n.name for c in classes for n in c.body if isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef))}
        if not methods.issubset(available):
            raise ValueError(f'{classname} 缺少 v1 入口方法：' + ', '.join(sorted(methods-available)))
    natives = [name for name in files if name.startswith('native/') and name.endswith('.json')]
    if not natives:
        raise ValueError('缺少原生组件清单。')
    dlls = set()
    for name in natives:
        native = json.loads(files[name])
        dll = native.get('dll')
        safe_name(dll)
        if '/' in dll or not dll.endswith('.dll'):
            raise ValueError('原生 DLL 名称无效。')
        path = 'native/' + dll; dlls.add(path)
        if path not in files or digest(files[path]) != native.get('sha256'):
            raise ValueError('原生组件哈希不匹配：' + name)
        data = files[path]
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError('原生组件不是有效 PE 文件：' + dll)
        offset = struct.unpack_from('<I', data, 60)[0]
        if offset > len(data)-24 or data[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H',data,offset+4)[0] != 0x14c:
            raise ValueError('原生组件架构不是 x86：' + dll)
    if dlls != {n for n in files if n.endswith('.dll')}:
        raise ValueError('存在未被原生清单引用的 DLL。')
    # Native component filenames referenced in code must be included. JSON
    # diagnostics such as run.json are not native manifests and are excluded.
    for name in referenced:
        if ('hook_' in name or '_trial_' in name or 'freecamera_' in name) and 'native/'+name not in files:
            raise ValueError('代码引用的原生清单未包含在母包中：' + name)
    return {'modules':len(required), 'native_manifests':len(natives), 'native_dlls':len(dlls),
            'syntax':True, 'entrypoints':True, 'native_hashes':True, 'native_architecture':'x86', 'executed_adapter':False}


def collect(recipe_path):
    recipe_path = Path(recipe_path).resolve()
    recipe = read_json(recipe_path)
    if not isinstance(recipe, dict) or set(recipe) != {'format','release','source_root','native_manifests','evidence'} or recipe['format'] != SOURCE_FORMAT:
        raise ValueError('请选择符合 pro-source-v1 的适配源码清单。')
    release = validate_release(recipe['release'])
    text_field(recipe['source_root'], 'source_root', 1000)
    source = (recipe_path.parent/recipe['source_root']).resolve()
    files = {n+'.py': (source/(n+'.py')).read_bytes() for n in ADAPTER_MODULES}
    natives = recipe['native_manifests']
    if not isinstance(natives,list) or not 1 <= len(natives) <= 16 or len(set(natives)) != len(natives):
        raise ValueError('原生清单列表无效。')
    for name in natives:
        safe_name(name)
        if '/' in name or not name.endswith('.json'):
            raise ValueError('原生清单必须是 native 目录内的 JSON 文件名。')
        raw = (source/'native'/name).read_bytes()
        native = json.loads(raw); dll = safe_name(native['dll'])
        if '/' in dll:
            raise ValueError('原生组件路径无效。')
        files['native/'+name] = raw
        files['native/'+dll] = (source/'native'/dll).read_bytes()
    evidence = {}
    if not isinstance(recipe['evidence'], list) or not 1 <= len(recipe['evidence']) <= 32 or len(set(recipe['evidence'])) != len(recipe['evidence']):
        raise ValueError('至少需要一份验证记录，最多 32 份。')
    for name in recipe['evidence']:
        safe_name(name)
        path = (recipe_path.parent/name).resolve()
        if not path.is_relative_to(recipe_path.parent) or path.suffix not in ('.json','.txt','.md'):
            raise ValueError('验证记录必须在源码清单目录内，格式为 JSON、TXT 或 MD。')
        if not path.is_file() or path.stat().st_size > 2*1024*1024:
            raise ValueError('验证记录不存在或过大。')
        evidence[name] = path.read_bytes()
    checks = validate_payload(files)
    return release, files, evidence, checks


def create_master(recipe_path, destination):
    release, files, evidence, checks = collect(recipe_path)
    manifest = {'format':MASTER_FORMAT, 'release':release,
                'files':{n:digest(b) for n,b in files.items()}, 'evidence':{n:digest(b) for n,b in evidence.items()}}
    manifest['master_id'] = digest(canonical(manifest))
    data = deterministic_zip({'manifest.json':canonical(manifest),
                             **{'payload/'+n:b for n,b in files.items()}, **{'evidence/'+n:b for n,b in evidence.items()}})
    if len(data) > MAX_PACKAGE:
        raise ValueError('母包过大。')
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('目标母包已存在，请选择新文件名；已有发布不会被覆盖。')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary = destination.with_name('.master-'+uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        # Windows rename refuses to replace an existing file. On other hosts,
        # a hard link gives the same publish-without-overwrite guarantee.
        if os.name == 'nt': os.rename(temporary,destination)
        else: os.link(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    return summary(manifest, checks, len(data), destination)


def read_master(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_PACKAGE:
        raise ValueError('母包不存在或大小超限。')
    try:
        archive = read_zip(path)
        raw = archive.pop('manifest.json')
        if len(raw) > 2*1024*1024:
            raise ValueError('母包清单过大。')
        manifest = json.loads(raw)
        if not isinstance(manifest,dict) or set(manifest) != {'format','release','files','evidence','master_id'} or manifest['format'] != MASTER_FORMAT or canonical(manifest) != raw:
            raise ValueError('母包格式不兼容。')
        validate_release(manifest['release'])
        file_map(manifest['files']); file_map(manifest['evidence'])
        if not 1 <= len(manifest['evidence']) <= 32 or any(Path(n).suffix not in ('.json','.txt','.md') for n in manifest['evidence']):
            raise ValueError('母包缺少规范的验证记录。')
        identity = {k:v for k,v in manifest.items() if k != 'master_id'}
        if digest(canonical(identity)) != manifest['master_id']:
            raise ValueError('母包身份与内容清单不一致。')
        expected = {**{'payload/'+n:h for n,h in manifest['files'].items()}, **{'evidence/'+n:h for n,h in manifest['evidence'].items()}}
        if set(archive) != set(expected) or any(digest(archive[n]) != h for n,h in expected.items()):
            raise ValueError('母包文件与内容清单不一致。')
        if any(len(archive['evidence/'+n]) > 2*1024*1024 for n in manifest['evidence']):
            raise ValueError('验证记录过大。')
        files = {n:archive['payload/'+n] for n in manifest['files']}
        checks = validate_payload(files)
        return manifest, files, checks
    except (KeyError,TypeError,zipfile.BadZipFile,UnicodeError) as exc:
        raise ValueError('无法读取母包，格式损坏或缺少必需字段。') from exc


def summary(manifest, checks, size, path):
    return {'master_id':manifest['master_id'], **manifest['release'], 'checks':checks,
            'bytes':size, 'path':str(Path(path).resolve()), 'sha256':digest(Path(path).read_bytes())}


def inspect_master(path):
    manifest, _, checks = read_master(path)
    return summary(manifest, checks, Path(path).stat().st_size, path)
