"""Install, repair, launch and uninstall the real installer in a disposable path.

Refuses to touch any pre-existing installation, association or shortcut. Leaves
the acceptance directory and logs for inspection. No game access is enabled.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import winreg

from blitzcam.project import read_project, write_project

ROOT = Path(__file__).resolve().parents[1]
UNINSTALL = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BlitzCamera.Next_is1'
ASSOCIATION = r'Software\Classes\BlitzCamera.Project'


def registry_value(key, name=''):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except FileNotFoundError:
        return None


def known_folder(index):
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, index, None, 0, buffer):
        raise OSError('Cannot resolve user shortcut folder')
    return Path(buffer.value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('installer', type=Path)
    args = parser.parse_args()
    installer = args.installer.resolve()
    shortcuts = [known_folder(0x10)/'Blitz Camera.lnk', known_folder(0x02)/'Blitz Camera.lnk']
    if registry_value(UNINSTALL, 'InstallLocation') or registry_value(ASSOCIATION) or registry_value(r'Software\Classes\.bcnproj') or any(p.exists() for p in shortcuts):
        raise RuntimeError('Existing installation or association: use a clean Windows user for this acceptance test')
    report_root = ROOT/'output/installer-acceptance';report_root.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=report_root))
    app = run/'安装 中文 with spaces'
    def install(log):
        return subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                               '/DIR='+str(app), '/LOG='+str(run/log)], timeout=120).returncode
    uninstaller = app/'unins000.exe'
    evidence = {'installer': str(installer), 'sha256': hashlib.sha256(installer.read_bytes()).hexdigest(), 'directory': str(app)}
    try:
        assert install('install.log') == 0
        manifest = json.loads((app/'manifest.json').read_text(encoding='utf-8'))
        for name, digest in manifest['files'].items():
            assert hashlib.sha256((app/name).read_bytes()).hexdigest() == digest, name
        assert all(p.exists() for p in shortcuts)
        assert registry_value(ASSOCIATION+r'\shell\open\command') == f'"{app}\\BlitzCamera.exe" "%1"'
        assert registry_value(r'Software\Classes\.bcnproj') == 'BlitzCamera.Project'
        assert registry_value(UNINSTALL, 'DisplayVersion') == manifest['version']
        evidence.update(installed_files=len(manifest['files']), shortcuts=True, file_association=True, uninstall_entry=True)
        data = app/'output';data.mkdir(exist_ok=True)
        sentinel = data/'preserve-user-data.txt';sentinel.write_text('keep settings and cache', encoding='utf-8')
        first, second = run/'第一个项目.bcnproj', run/'第二个项目.bcnproj'
        project = read_project(app/'app/examples/eight-second.json')
        write_project(first, project);write_project(second, project)
        # The running-app guard must match the launcher's mutex even in Unicode paths.
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        key = hashlib.sha256(str(app).lower().encode('utf-8')).hexdigest().upper()[:24]
        mutex = kernel.CreateMutexW(None, False, 'Local\\BlitzCameraApp-'+key)
        assert mutex
        try:
            assert install('running-install.log') != 0, 'Installer replaced an active application'
        finally:
            kernel.CloseHandle(mutex)
        assert install('repair.log') == 0
        assert sentinel.read_text(encoding='utf-8') == 'keep settings and cache'
        evidence.update(running_app_blocked=True, repair_preserved_user_data=True)
        env = dict(os.environ, BLITZCAM_DATA_ROOT=str(app), BLITZCAM_PROFILE_ROOT=str(run/'account'), BLITZCAM_DESKTOP_SMOKE='1')
        service = subprocess.Popen([str(app/'BlitzCamera.exe'), str(first)], cwd=run, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        state_file = data/'workstation-service.json'
        deadline = time.monotonic()+20
        while not state_file.exists() and service.poll() is None and time.monotonic()<deadline:
            time.sleep(.05)
        assert state_file.exists(), 'Cold project launch did not start'
        service_state = json.loads(state_file.read_text(encoding='utf-8'))
        def state():
            with urllib.request.urlopen(service_state['url']+'api/state', timeout=3) as response:
                return json.load(response)
        initial = state()
        assert Path(initial['project_path']) == first
        assert initial['version'] == manifest['version']
        duplicate = subprocess.run([str(app/'BlitzCamera.exe'), str(second)], cwd=run, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        assert duplicate.returncode == 0
        switched = False
        while service.poll() is None and time.monotonic()<deadline:
            try:
                if state()['project_path'] == str(second):
                    switched = True
                    break
            except OSError:
                break
            time.sleep(.05)
        assert service.wait(timeout=45) == 0
        assert switched, 'Existing desktop did not open the requested project'
        smoke = json.loads(json.loads((data/'desktop-smoke.json').read_text(encoding='utf-8-sig')))
        assert all(smoke[name] for name in ('loaded', 'startup', 'timeline', 'webview'))
        assert json.loads(state_file.read_text(encoding='utf-8'))['pid'] == service_state['pid']
        evidence.update(cold_project_open=True, warm_project_open=True, one_backend=True, native_webview=smoke)
    finally:
        if uninstaller.exists():
            code = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                                   '/LOG='+str(run/'uninstall.log')], timeout=90).returncode
            assert code == 0, 'Uninstall failed; inspect acceptance directory'
    deadline = time.monotonic()+10
    while uninstaller.exists() and time.monotonic()<deadline:
        time.sleep(.1)
    assert not (app/'BlitzCamera.exe').exists()
    assert not any(p.exists() for p in shortcuts)
    assert registry_value(UNINSTALL, 'InstallLocation') is None
    assert registry_value(ASSOCIATION) is None
    assert registry_value(r'Software\Classes\.bcnproj') is None
    assert sentinel.read_text(encoding='utf-8') == 'keep settings and cache'
    assert read_project(first).to_dict() == project.to_dict()
    assert read_project(second).to_dict() == project.to_dict()
    evidence.update(uninstalled=True, user_data_preserved=True, projects_preserved=True, associations_and_shortcuts_removed=True)
    (report_root/'result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
