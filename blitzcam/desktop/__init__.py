"""Launch the local desktop host, without accessing the game process."""
from pathlib import Path
import os
import subprocess
import json
import hashlib
from urllib.parse import urlsplit
from ..paths import RESOURCE_ROOT, DATA_ROOT, OUTPUT


def open_overlay(url, previous=None, view='overlay'):
    parts = urlsplit(url)
    if os.name != 'nt' or parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port:
        raise ValueError('悬浮窗需要 Windows 本机服务。')
    if view not in ('overlay', 'workbench'):
        raise ValueError('桌面窗口类型无效。')
    directory = RESOURCE_ROOT/'tools/overlay-runtime'
    if not (directory/'host.json').exists():
        raise ValueError('请先运行 python tools/build_overlay.py 构建桌面外壳。')
    manifest = json.loads((directory/'host.json').read_text())
    executable = directory/manifest['executable']
    if executable.parent != directory or hashlib.sha256(executable.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('桌面外壳校验失败，请重新构建。')
    # A second invocation signals the existing host to show itself.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1
    OUTPUT.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([str(executable), url, str(DATA_ROOT), view], cwd=DATA_ROOT, startupinfo=startup,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def launch(project_path=None, port=0, view='overlay', owned=False):
    import urllib.request
    from .. import __version__
    from ..server import serve
    explicit = project_path is not None
    target = (project_path or OUTPUT/'project.json').resolve()
    try:
        saved = json.loads((OUTPUT/'workstation-service.json').read_text())
        url = saved['url']
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != '/':
            raise ValueError('Invalid local service URL')
        with urllib.request.urlopen(url+'api/state',timeout=2) as response:
            state=json.load(response)
        if state.get('version') != __version__ or (explicit and Path(state['project_path']).resolve()!=target):
            raise ValueError('Different workstation')
        endpoint = 'api/desktop/workbench' if view == 'workbench' else 'api/desktop/open'
        request=urllib.request.Request(url+endpoint,data=b'{}',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response: json.load(response)
        print('桌面窗口已显示 · 工作台 '+url); return
    except (OSError, ValueError, KeyError):
        pass
    serve(target if explicit else None,port,open_browser=False,desktop=True,desktop_view=view,exit_with_desktop=owned)
