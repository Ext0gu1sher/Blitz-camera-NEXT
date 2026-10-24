"""Open a user-chosen local replay with the installed Steam client.

No shell commands, file association execution, game input or process writes.
The selected file identifies the launch request, not later in-client switches.
"""
import os
from pathlib import Path
import re
import subprocess

from .profile import CameraError
from .file_dialogs import show_dialog
from .replay_timeline import replay_matches

APP_ID = '444200'


class ReplaySourceUnavailable(CameraError):
    """A valid camera connection can survive a missing file-source observation."""


def verify_launch_source(process_info, launch, replay_info, source_error=None):
    """Steam may relaunch the executable; verify the observed file, not its PID.

    The camera reader has already required one supported replay process. This
    checks its executable and observed file against the explicit Open request.
    Runtime observations refer to the active player; legacy arguments do not
    detect subsequent replay switches inside that process.
    """
    if Path(process_info.path).resolve() != Path(launch['executable']).resolve():
        raise CameraError('当前游戏的安装位置与本次启动的客户端不一致。')
    if not replay_info:
        detail = f'：{source_error}' if source_error else '，请重新连接'
        raise ReplaySourceUnavailable('无法读取游戏当前的回放文件' + detail.rstrip('。') + '。')
    if not replay_matches(launch['info'], replay_info):
        raise CameraError('游戏当前的回放与本次选择不一致。')
    return {'launch_pid':launch.get('pid'), 'connected_pid':process_info.pid,
            'process_handoff':process_info.pid != launch.get('pid'),
            'verification':'runtime_replay' if replay_info.get('verification') == 'runtime_replay' else 'launch_arguments'}


def _vdf_string(text, key):
    match = re.search(r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"\\])*)"', text)
    return match.group(1).replace('\\\\', '\\').replace('\\"', '"') if match else None


def steam_client(path):
    """Require the executable to belong to this Steam app's installed directory."""
    exe = Path(path).resolve()
    if not exe.is_file() or exe.name.lower() != 'wotblitz.exe':
        return None
    steamapps = exe.parent.parent.parent
    manifest = steamapps / f'appmanifest_{APP_ID}.acf'
    if steamapps.name.lower() != 'steamapps' or exe.parent.parent.name.lower() != 'common' or not manifest.is_file():
        return None
    text = manifest.read_text(encoding='utf-8-sig')
    directory = _vdf_string(text, 'installdir')
    if _vdf_string(text, 'appid') != APP_ID or not directory or (steamapps/'common'/directory).resolve() != exe.parent:
        return None
    return exe


def locate_client():
    if os.name != 'nt':
        raise CameraError('从回放启动游戏需要 Windows。')
    import winreg
    def registry(root, key, name=''):
        try:
            with winreg.OpenKey(root, key) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except OSError:
            return ''
    # Read the registered executable, but never execute the registry command.
    progid = registry(winreg.HKEY_CLASSES_ROOT, '.wotbreplay')
    if isinstance(progid, str) and progid:
        command = registry(winreg.HKEY_CLASSES_ROOT, progid + r'\shell\open\command')
        match = re.match(r'\s*"([^"\r\n]+)"', command) if isinstance(command, str) else None
        if match and (exe := steam_client(match.group(1))):
            return exe
    roots = [registry(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
             registry(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
             str(Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))/'Steam')]
    libraries = set()
    for root in filter(None, roots):
        libraries.add(Path(root))
        folders = Path(root)/'steamapps/libraryfolders.vdf'
        if folders.is_file():
            text = folders.read_text(encoding='utf-8-sig')
            for match in re.finditer(r'"path"\s*"((?:\\.|[^"\\])*)"', text):
                libraries.add(Path(match.group(1).replace('\\\\', '\\')))
    candidates = set()
    for library in libraries:
        manifest = library/'steamapps'/f'appmanifest_{APP_ID}.acf'
        if manifest.is_file():
            directory = _vdf_string(manifest.read_text(encoding='utf-8-sig'), 'installdir')
            if directory and (exe := steam_client(library/'steamapps/common'/directory/'wotblitz.exe')):
                candidates.add(exe)
    if len(candidates) != 1:
        raise CameraError('未找到唯一的 Steam 国际版游戏安装目录，请检查 Steam 安装和回放文件关联。')
    return candidates.pop()


def choose_replay():
    """Modern Windows picker; invoked only by an explicit Open action."""
    initial = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'wotblitz/DAVAProject/replays'
    return show_dialog(title='选择本地回放 · Blitz Camera',
                       filters=[('World of Tanks Blitz 回放 (*.wotbreplay)', '*.wotbreplay')],
                       initial=initial, remember_location=True)


def choose_project(directory=None):
    from .paths import OUTPUT
    return show_dialog(title='打开项目 · Blitz Camera',
                       filters=[('Blitz Camera 项目 (*.json)', '*.json')],
                       initial=directory or OUTPUT/'projects')


def save_project(default_name='', directory=None):
    from .paths import OUTPUT
    directory = Path(directory or OUTPUT/'projects')
    directory.mkdir(parents=True, exist_ok=True)
    return show_dialog(title='另存为 · Blitz Camera', save=True,
                       filters=[('Blitz Camera 项目 (*.json)', '*.json')],
                       initial=directory, default_ext='json', default_name=default_name)


def choose_directory(initial=None):
    return show_dialog(title='选择项目保存文件夹 · Blitz Camera', folder=True, initial=initial)


def launch_replay(executable, replay):
    exe = steam_client(executable)
    if exe is None:
        raise CameraError('游戏路径不属于已安装的 Steam 国际版客户端。')
    replay = Path(replay).resolve(strict=True)
    if replay.suffix.lower() != '.wotbreplay':
        raise ValueError('请选择 .wotbreplay 回放文件。')
    # Submit the same command on every click, including while the game is running.
    return subprocess.Popen([str(exe), str(replay)], cwd=exe.parent, shell=False)
