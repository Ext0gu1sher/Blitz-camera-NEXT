@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\chcp.com" 65001 >nul 2>&1
cd /d "%~dp0"
set "SUPPORT_EXIT=1"
if exist "%~dp0runtime\python.exe" goto support_embedded
if exist "%~dp0blitzcam\__init__.py" goto support_source
echo 请把此文件放在 BlitzCamera.exe 旁边，保留 app、runtime 和 output 文件夹，再双击。
goto support_finish
:support_embedded
"%~dp0runtime\python.exe" -X utf8 -B -c "import pathlib,sys;src=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig');exec(compile(src.split(chr(10)+'# BEGIN PYTHON'+chr(10),1)[1],sys.argv[1],'exec'))" "%~f0"
set "SUPPORT_EXIT=%errorlevel%"
goto support_finish
:support_source
python -X utf8 -B -c "import pathlib,sys;src=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig');exec(compile(src.split(chr(10)+'# BEGIN PYTHON'+chr(10),1)[1],sys.argv[1],'exec'))" "%~f0"
set "SUPPORT_EXIT=%errorlevel%"
:support_finish
echo.
echo 按任意键关闭此窗口。
pause >nul
exit /b %SUPPORT_EXIT%
# BEGIN PYTHON
"""Collect existing logs and the service's current state, without importing the app.

Works with older portable/installed builds. No game scan, reconnect, project write,
browser profile, deployment keys or upload. Only GET the existing loopback service.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile

MAX_LOG = 1024 * 1024
MAX_STATE = 8 * MAX_LOG


def read_bounded(path, limit=MAX_LOG, tail=False):
    with path.open('rb') as stream:
        size = path.stat().st_size
        if size > limit:
            if not tail:
                raise ValueError('文件超过收集上限')
            stream.seek(-limit, 2)
        return stream.read(limit), size > limit


def project_timing(project):
    if not isinstance(project, dict):
        return None
    result = {key: project.get(key) for key in ('shooting_mode', 'replay_timeline', 'replay_speed')}
    result['keyframe_times'] = [row.get('time_sec') for row in project.get('keyframes', []) if isinstance(row, dict)]
    result['camera_track_times'] = {key: [row.get('time_sec') for row in rows if isinstance(row, dict)]
                                    for key, rows in (project.get('camera_tracks') or {}).items()}
    multi = project.get('multicam') or {}
    result['active_camera_id'] = multi.get('active_camera_id')
    result['cameras'] = [{key: row.get(key) for key in ('id', 'name', 'work_range')}
                         for row in multi.get('cameras', []) if isinstance(row, dict)]
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('本机服务返回了重定向，已停止读取')


def live_state(output):
    raw, _ = read_bounded(output / 'workstation-service.json', 65536)
    service = json.loads(raw.decode('utf-8-sig'))
    url = service['url']
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port
            or parts.path != '/' or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError('不是有效的本机服务地址')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url + 'api/state', timeout=3) as response:
        raw = response.read(MAX_STATE + 1)
    if len(raw) > MAX_STATE:
        raise ValueError('本机状态超过收集上限')
    state = json.loads(raw)
    if not isinstance(state, dict) or 'connection' not in state or 'version' not in state:
        raise ValueError('当前端口未返回 Blitz Camera 状态')
    result = {key: state.get(key) for key in ('version', 'edition', 'connection', 'replay_info', 'replay_launch',
                                             'playback', 'keyframe_guard', 'project_revision')}
    result['game_sample'] = {key: (state.get('sample') or {}).get(key) for key in ('replay', 'quality')}
    result['project_timing'] = project_timing(state.get('project'))
    result['service_pid'] = service.get('pid')
    return result


def memory_status():
    if sys.platform != 'win32':
        return None
    import ctypes as C
    class Status(C.Structure):
        _fields_ = [('length', C.c_ulong), ('load_percent', C.c_ulong)] + [
            (name, C.c_ulonglong) for name in ('total_physical', 'available_physical', 'total_pagefile',
                                              'available_pagefile', 'total_virtual', 'available_virtual', 'available_extended')]
    status = Status()
    status.length = C.sizeof(status)
    if not C.windll.kernel32.GlobalMemoryStatusEx(C.byref(status)):
        return None
    return {name: getattr(status, name) for name, _ in status._fields_ if name != 'length'}


def collect(root):
    root = Path(root).resolve()
    output = root / 'output'
    report = {'format': 'blitz-camera-support-v1', 'collected_at_utc': datetime.now(timezone.utc).isoformat(),
              'environment': {'windows': platform.platform(), 'python': platform.python_version()},
              'memory': memory_status(), 'files': [], 'errors': [], 'source_hashes': {}}
    try:
        report['state'] = live_state(output)
    except Exception as exc:
        report['state_unavailable'] = str(exc)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    filename = 'BlitzCamera-logs-' + stamp + '-' + uuid.uuid4().hex[:6] + '.zip'
    destination = output / 'support-logs'
    try:
        destination.mkdir(parents=True, exist_ok=True)
        archive = zipfile.ZipFile(destination / filename, 'x', zipfile.ZIP_DEFLATED)
    except OSError:
        destination = Path(tempfile.gettempdir())
        archive = zipfile.ZipFile(destination / filename, 'x', zipfile.ZIP_DEFLATED)
    with archive:
        def add(path, name, tail=False):
            if not path.is_file():
                return
            try:
                raw, truncated = read_bounded(path, tail=tail)
                archive.writestr(name, raw)
                report['files'].append({'name': name, 'bytes': len(raw), 'tail_only': truncated})
            except OSError as exc:
                report['errors'].append({'file': name, 'error': str(exc)})
            except ValueError as exc:
                report['errors'].append({'file': name, 'error': str(exc)})
        for name in ('desktop-service.log', 'desktop-error.txt', 'overlay-error.txt', 'overlay-workbench-error.txt',
                     'desktop-process-failed.json', 'overlay-status.json', 'overlay-layout.json'):
            add(output / name, 'logs/' + name, tail=not name.endswith('.json'))
        for name in ('events.jsonl', 'events.1.jsonl', 'events.2.jsonl', 'events.3.jsonl'):
            add(output / 'diagnostics' / name, 'diagnostics/' + name, tail=True)
        for name in ('connection-diagnostics', 'playback-runs'):
            directory = output / name
            if not directory.is_dir():
                continue
            if name == 'connection-diagnostics':
                for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                    add(path, name + '/' + path.name)
                add(directory / 'diagnostic-startup.log', name + '/diagnostic-startup.log', tail=True)
            else:
                for folder in sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                    for item in ('report.json', 'events.jsonl', 'operations.jsonl'):
                        add(folder / item, name + '/' + folder.name + '/' + item, tail=item.endswith('.jsonl'))
        app = root / 'app' if (root / 'app/blitzcam').is_dir() else root
        for name in ('__init__.py', 'server.py', 'replay_timeline.py', 'speed.py', 'playback.py'):
            path = app / 'blitzcam' / name
            if path.is_file():
                try:
                    raw, _ = read_bounded(path)
                    report['source_hashes'][name] = hashlib.sha256(raw).hexdigest()
                except (OSError, ValueError) as exc:
                    report['errors'].append({'file': name, 'error': str(exc)})
        add(app / 'tools/overlay-runtime/host.json', 'desktop-host.json')
        archive.writestr('diagnostics.json', json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr('说明.txt', '这是一次现场快照，并非完整的历史操作日志。\n'
                        'diagnostics.json 含当前连接错误、回放状态、区间与倍率；logs 含已有错误记录。\n'
                        '未读取授权密钥、浏览器缓存、回放内容或项目原文件；未重新扫描游戏或修改设置。\n'
                        '报告可能包含日志已有的本地文件路径。没有自动上传。\n')
    return destination / filename


def main(root=None):
    root = Path(sys.argv[1]).resolve().parent if root is None else Path(root).resolve()
    print('正在收集现有日志和当前错误状态，请稍候……', flush=True)
    try:
        path = collect(root)
    except Exception as exc:
        print('收集未完成：' + str(exc))
        return 1
    print('已生成日志包，请把这个 ZIP 文件拖入聊天：\n' + str(path), flush=True)
    print('若已关闭软件，包中仍有历史日志，但可能没有本次报错的现场状态。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
