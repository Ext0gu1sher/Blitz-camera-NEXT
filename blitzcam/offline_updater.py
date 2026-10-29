"""Standalone updater copied outside app/ before shutdown.

Only signed app packages are accepted. Runtime files must be unchanged. All
target files are verified before switching directories; a write-ahead move
journal permits rollback after either an error or an interrupted process.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

from .packages import canonical, checked_payload, digest, file_map, read_signed, safe_name

ROOT_FILES = {'BlitzCamera.exe', 'BlitzCamera.exe.config', 'BlitzCamera.ico', '使用说明.txt'}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def clean_path(root, relative):
    safe_name(relative)
    root = Path(root).resolve()
    path = root
    for part in relative.split('/'):
        path = path / part
        if path.exists() and (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('更新目录包含链接或重解析点，已停止。')
    if not path.resolve().is_relative_to(root):
        raise ValueError('更新路径超出安装目录。')
    return path


def validate_target(manifest):
    target = manifest.get('target_manifest')
    if not isinstance(target, dict) or target.get('version') != manifest.get('version'):
        raise ValueError('目标版本清单无效。')
    files = file_map(target.get('files'))
    if not {'app/blitzcam/__init__.py', 'app/blitzcam/server.py', 'runtime/pythonw.exe', 'BlitzCamera.exe'}.issubset(files):
        raise ValueError('升级包缺少完整桌面应用。')
    for name in files:
        if not name.startswith(('app/', 'runtime/', 'licenses/')) and name not in ROOT_FILES:
            raise ValueError('升级包试图更改用户数据或不支持的文件。')
    if any(name not in files or files[name] != sha for name, sha in manifest['files'].items()):
        raise ValueError('升级文件不属于目标版本。')
    return target


def prepare(root, package, trust, work):
    root, work = Path(root).resolve(), Path(work).resolve()
    manifest, payload = read_signed(package, trust)
    if manifest['kind'] != 'app':
        raise ValueError('请选择主程序升级包。')
    current_raw = (root/'manifest.json').read_bytes()
    if digest(canonical(json.loads(current_raw))) != manifest.get('base_manifest_sha256'):
        raise ValueError('此升级包不适用于当前安装基线，请向发布者获取匹配的升级包。')
    current = json.loads(current_raw)
    target = validate_target(manifest)
    files = checked_payload(payload, manifest['files'])
    if 'BlitzCamera.exe' in files or current['files'].get('BlitzCamera.exe') != target['files'].get('BlitzCamera.exe'):
        raise ValueError('此更新需要更换启动器，请使用完整安装包。')
    if any(n.startswith('runtime/') for n in files) or {
            n: h for n, h in current['files'].items() if n.startswith('runtime/')} != {
            n: h for n, h in target['files'].items() if n.startswith('runtime/')}:
        raise ValueError('此更新需要更换 Python 运行环境，请使用完整安装包。')
    # A partial staging directory is never promoted, and never re-used.
    release = work/'release'
    release.mkdir(parents=True, exist_ok=False)
    for name, expected in target['files'].items():
        if name.startswith('runtime/'):
            if digest(clean_path(root, name).read_bytes()) != expected:
                raise ValueError('本机运行环境损坏，请重新解压完整安装包。')
            continue
        source = files.get(name)
        if source is None:
            if current['files'].get(name) != expected:
                raise ValueError('升级包缺少必需文件。')
            source = clean_path(root, name).read_bytes()
        if digest(source) != expected:
            raise ValueError(f'本机文件已改变或包内容损坏：{name}')
        destination = clean_path(release, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source)
    write_json(release/'manifest.json', target)
    return manifest, release


def recover(root, data_root):
    root, data_root = Path(root).resolve(), Path(data_root).resolve()
    journal_path = data_root/'output/deployment/transaction.json'
    if not journal_path.exists():
        return False
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    if journal.get('state') != 'applying':
        return False
    if journal.get('root') != str(root):
        raise ValueError('更新恢复目录不一致。')
    # Each recorded move is root-relative. Reversing them preserves both the
    # old release and any partially installed release without recursive delete.
    while journal['moves']:
        item = journal['moves'][-1]
        source, destination = clean_path(root, item['source']), clean_path(root, item['destination'])
        if destination.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(source)
        elif source.exists() and destination.exists():
            raise ValueError('更新恢复遇到文件冲突，原版本备份已保留。')
        elif not source.exists():
            raise ValueError('更新恢复缺少文件，原版本备份已保留。')
        # Recovery itself may be interrupted. Retire each inverse move before
        # an earlier move can reuse its destination for the previous release.
        journal['moves'].pop()
        write_json(journal_path, journal)
    journal['state'] = 'rolled_back'
    write_json(journal_path, journal)
    write_json(data_root/'output/deployment/last-result.json', {'ok': False, 'message': '升级未完成，已恢复原版本。'})
    return True


def apply(root, data_root, package, trust, work, *, fault_after=None):
    root, data_root, work = Path(root).resolve(), Path(data_root).resolve(), Path(work).resolve()
    if not work.is_relative_to(root/'output/deployment'):
        raise ValueError('升级暂存目录必须位于当前安装目录中。')
    recover(root, data_root)
    manifest, release = prepare(root, package, trust, work)
    # Preparation can take time: revalidate before the first mutation.
    if digest(canonical(json.loads((root/'manifest.json').read_bytes()))) != manifest['base_manifest_sha256']:
        raise ValueError('准备期间安装版本发生变化，已取消升级。')
    backup = root/'output/deployment/backups'/(manifest['id'] + '-' + uuid4().hex[:12])
    backup.mkdir(parents=True, exist_ok=False)
    journal_path = data_root/'output/deployment/transaction.json'
    journal = {'state': 'applying', 'root': str(root), 'version': manifest['version'], 'moves': []}
    write_json(journal_path, journal)
    count = 0
    def move(source, destination):
        nonlocal count
        record = {'source': source.relative_to(root).as_posix(), 'destination': destination.relative_to(root).as_posix()}
        journal['moves'].append(record)
        write_json(journal_path, journal)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        count += 1
        if fault_after == count:
            raise OSError('Simulated interrupted deployment')
    try:
        for name in ['app', 'licenses', *sorted(ROOT_FILES - {'BlitzCamera.exe'}), 'manifest.json']:
            old, new = clean_path(root, name), clean_path(release, name)
            if old.exists():
                move(old, backup/name)
            if new.exists():
                move(new, root/name)
        journal['state'] = 'completed'
        write_json(journal_path, journal)
        result = {'ok': True, 'version': manifest['version'], 'message': '主程序升级完成。', 'backup': str(backup)}
        write_json(data_root/'output/deployment/last-result.json', result)
        return result
    except BaseException:
        recover(root, data_root)
        raise


def wait_processes(pids, timeout=120):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handles = []
    try:
        for pid in set(pids):
            if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
                raise ValueError('等待退出的进程无效。')
            handle = kernel.OpenProcess(0x100000, False, pid)
            if handle:
                handles.append(handle)
            elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: process already exited
                raise OSError('无法确认应用已经退出，升级已取消。')
        end = time.monotonic() + timeout
        for handle in handles:
            if kernel.WaitForSingleObject(handle, max(0, int((end - time.monotonic()) * 1000))) != 0:
                raise ValueError('应用尚未退出，升级已取消；请保存并关闭应用后重试。')
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', type=Path)
    parser.add_argument('--recover', nargs=2)
    args = parser.parse_args()
    if args.recover:
        recover(*args.recover)
        return
    job = json.loads(args.job.read_text(encoding='utf-8'))
    root, data = Path(job['root']), Path(job['data_root'])
    action = job.get('action', 'app')
    try:
        if action not in ('app', 'restart'):
            raise ValueError('重启任务类型无效。')
        wait_processes(job['pids'])
        if action == 'app':
            apply(root, data, job['package'], job['trust'], job['work'])
    except Exception as exc:
        write_json(data/'output/deployment/last-result.json', {'ok': False, 'message': str(exc)})
        # Never relaunch if the application did not exit, or rollback failed.
        if action != 'app' or '退出' in str(exc):
            return
        try:
            journal = json.loads((data/'output/deployment/transaction.json').read_text(encoding='utf-8'))
            if journal.get('state') == 'applying':
                return
        except FileNotFoundError:
            pass
    if (root/'app/blitzcam/__init__.py').is_file():
        env = dict(os.environ, BLITZCAM_DATA_ROOT=str(data))
        try:
            subprocess.Popen([str(root/'BlitzCamera.exe')], cwd=root, env=env,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            write_json(data/'output/deployment/last-result.json',
                       {'ok': False, 'message': '升级已部署，但应用未能重新打开，请手动启动。', 'error': str(exc)})
        else:
            if action == 'restart':
                write_json(data/'output/deployment/last-result.json',
                           {'ok': True, 'message': '升级包已部署，已重新启动应用。'})


if __name__ == '__main__':
    main()
