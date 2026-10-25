"""Build a relocatable Windows desktop ZIP from the trusted local runtimes.

No installers, external package scripts, game geometry or development toolchains
are included. Local asset conversion dependencies are bundled separately.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blitzcam import __version__


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(destination=None, project=None):
    destination = Path(destination or ROOT/'dist'/f'BlitzCamera-{__version__}').resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Build destination must be empty; choose a new folder to avoid stale release files')
    destination.mkdir(parents=True, exist_ok=True)
    app, runtime = destination/'app', destination/'runtime'
    runtime.mkdir(exist_ok=True)
    def copy(source, relative):
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    # Only application code and shipped web resources, never research/vendor trees.
    for source in (ROOT/'blitzcam').rglob('*'):
        rel = source.relative_to(ROOT)
        if not source.is_file() or '__pycache__' in source.parts:
            continue
        if source.suffix == '.py' or 'web' in rel.parts or 'preview_vendor' in rel.parts:
            copy(source, Path('app')/rel)
    # Asset conversion uses only NumPy, Pillow and imagecodecs' BCn decoder.
    # Include their licenses and DLL directories; never require machine pip.
    site = Path(sys.base_prefix)/'Lib/site-packages'
    for name in ('numpy','numpy.libs','PIL'):
        for source in (site/name).rglob('*'):
            if source.is_file() and not {'tests','__pycache__'}.intersection(source.parts):
                copy(source, Path('app/blitzcam/preview_runtime')/source.relative_to(site))
    for prefix in ('numpy-','pillow-'):
        for folder in site.glob(prefix+'*.dist-info'):
            for source in folder.rglob('*'):
                if source.is_file() and ('LICENSE' in source.name.upper() or 'licenses' in source.parts):
                    copy(source, Path('licenses')/source.relative_to(site))
    codec = ROOT/'blitzcam/preview_runtime'
    for source in codec.rglob('*'):
        if source.is_file() and (source.suffix=='.py' or source.name.startswith(('_bcn.','_imcd.','_shared')) or source.name=='imagecodecs-provenance.json' or source.name.upper().startswith('LICENSE') or 'licenses' in source.parts):
            copy(source, Path('app/blitzcam/preview_runtime')/source.relative_to(codec))
    copy(ROOT/'examples/eight-second.json', 'app/examples/eight-second.json')
    native = json.loads((ROOT/'blitzcam/native/position_hook_1121.json').read_text())
    hook = ROOT/'blitzcam/native'/native['dll']
    if sha(hook) != native['sha256']:
        raise ValueError('Hook hash mismatch')
    for source in (hook, ROOT/'blitzcam/native/position_hook_1121.json'):
        copy(source, Path('app/blitzcam/native')/source.name)
    seek_manifest = ROOT/'blitzcam/native/replay_seek_phase_trial_1121.json'
    seek = json.loads(seek_manifest.read_text(encoding='utf8'))
    seek_hook = seek_manifest.parent/seek['dll']
    if seek_hook.parent.resolve()!=seek_manifest.parent.resolve() or sha(seek_hook)!=seek['sha256']:
        raise ValueError('Experimental seek hook hash mismatch')
    for source in (seek_hook, seek_manifest):
        copy(source, Path('app/blitzcam/native')/source.name)
    camera_manifest = ROOT/'blitzcam/native/freecamera_switch_1121.json'
    camera = json.loads(camera_manifest.read_text(encoding='utf8'))
    camera_hook = camera_manifest.parent/camera['dll']
    if camera_hook.parent.resolve()!=camera_manifest.parent.resolve() or sha(camera_hook)!=camera['sha256']:
        raise ValueError('Free-camera hook hash mismatch')
    for source in (camera_hook, camera_manifest):
        copy(source, Path('app/blitzcam/native')/source.name)

    host_root = ROOT/'tools/overlay-runtime'
    host = json.loads((host_root/'host.json').read_text())
    if sha(host_root/host['executable']) != host['sha256']:
        raise ValueError('Desktop host hash mismatch')
    if host.get('icon_sha256') != sha(ROOT/'blitzcam/desktop/assets/BlitzCamera.ico'):
        raise ValueError('Desktop host icon is outdated; run tools/build_overlay.py first')
    for name in ('host.json', host['executable'], host['executable']+'.config',
                 'Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.Wpf.dll', 'WebView2Loader.dll'):
        copy(host_root/name, Path('app/tools/overlay-runtime')/name)

    # Copy this installed CPython and zip only its standard library. No pip/site
    # packages, registry installation, PATH entry or machine Python is required.
    python = Path(sys.base_prefix)
    if sys.version_info[:2] != (3, 11) or sys.maxsize < 2**32:
        raise ValueError('Build with the local 64-bit CPython 3.11 runtime')
    for name in ('python.exe', 'pythonw.exe', 'python311.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
        copy(python/name, Path('runtime')/name)
    for source in (python/'DLLs').iterdir():
        if source.suffix in ('.dll', '.pyd') and not source.name.startswith(('_test','_ctypes_test','_tkinter','tcl','tk')):
            copy(source, Path('runtime/DLLs')/source.name)
    excluded = {'site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'venv'}
    with zipfile.ZipFile(runtime/'python311.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in (python/'Lib').rglob('*.py'):
            rel = source.relative_to(python/'Lib')
            if not excluded.intersection(rel.parts):
                archive.write(source, rel.as_posix())
    (runtime/'python311._pth').write_text('python311.zip\nDLLs\n../app\n', encoding='ascii')
    copy(python/'LICENSE.txt', 'licenses/Python-LICENSE.txt')
    copy(ROOT/'tools/webview2-provenance.json', 'licenses/webview2-provenance.json')
    with zipfile.ZipFile(next((ROOT/'tools').glob('webview2-*.nupkg'))) as sdk:
        for name in sdk.namelist():
            if Path(name).name.lower() in ('license.txt', 'license.md', 'license'):
                (destination/'licenses'/('WebView2-'+Path(name).name)).write_bytes(sdk.read(name))

    csc = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    icon = ROOT/'blitzcam/desktop/assets/BlitzCamera.ico'
    subprocess.run([str(csc), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                    '/win32icon:'+str(icon),
                    '/out:'+str(destination/'BlitzCamera.exe'), str(ROOT/'blitzcam/desktop/DesktopLauncher.cs')], check=True)
    copy(icon, 'BlitzCamera.ico')
    copy(ROOT/'blitzcam/desktop/BlitzCameraOverlay.exe.config', 'BlitzCamera.exe.config')
    output = destination/'output'
    output.mkdir(exist_ok=True)
    seeded = None
    if project is not None and not (output/'project.json').exists():
        copy(Path(project), 'output/project.json')
        seeded = sha(output/'project.json')
    (destination/'使用说明.txt').write_text(
        f'Blitz Camera {__version__}\n\n'
        '请解压整个文件夹，然后双击 BlitzCamera.exe。无需安装 Python，也不会打开浏览器。\n'
        '完整工作台支持缩放和最大化；右上角可打开透明置顶悬浮窗。关闭工作台退出应用。\n'
        '左下方“项目 / 多机位”页签切换：新建机位建立独立空轨，右键机位可改名、复制、剪切或删除。\n'
        '选中的机位用于编辑、预览和游戏拍摄，各机位独立保存关键帧、工作区和速度曲线。\n'
        '机位列表支持 Ctrl+C / Ctrl+V / Ctrl+X，I/O 调整当前机位入出点。修改自动保存，每个项目最多 16 个机位。\n'
        '“卡点”页可启用 BPM 轨道，调整首拍、偏移与细分，拍点可定位和吸附；关闭后收起轨道并保留设置。\n'
        '主页自动发现默认项目文件夹本层的有效项目，并与最近打开记录合并；不会自动打开工程。\n'
        '重复双击会显示已运行的工作台。默认 Ctrl+Alt+F8 记录关键帧、Ctrl+Alt+F9 显隐悬浮窗，可在设置中换键。\n'
        '全局记录前先保存编辑器草稿；模式一使用编辑器播放头，模式二使用游戏当前暂停时刻。\n'
        '游戏最小化时自动隐藏悬浮窗，恢复后还原；手动隐藏的悬浮窗保持隐藏。\n'
        '项目默认保存在用户的“文档/Blitz-Camera-Project”；记录、设置、缓存和日志保存在 output，升级时保留此目录。不要只移动 EXE。\n'
        '需要 Windows 10/11 x64、.NET Framework 4.6.2 或更高，以及 Microsoft Edge WebView2 Runtime。\n'
        '此包不安装运行环境；若 WebView2 缺失会显示启动错误。\n'
        '请放到当前用户可写的文件夹；不要直接在压缩包中运行。\n'
        '跨电脑打开项目后，点击“在游戏中播放项目回放”；原位置不存在时选择本机的同一份回放。\n'
        '回放按文件内容核对，复制或改名后仍可关联；旧项目手动选择一次即可保存新位置和内容标识。\n'
        '启动进入主页，不自动创建项目。默认项目位置可在设置中修改；已有项目文件保持原位置。\n'
        '设置中的界面缩放提供 100%–200%；关键帧支持 Ctrl+X 剪切、Ctrl+C 复制和 Ctrl+V 粘贴。\n'
        '速度曲线下方提供缩放滑条和横向滚动条；Alt+滚轮缩放，滚轮平移，显示完整曲线按钮复位。\n'
        '模式二：载入回放预览，在真实地图中前后拖动时间轴；场景观察 / 镜头画面切换。\n'
        '编辑器预览从当前播放头播放到全片结束，不受工作区入点、出点限制。\n'
        '模式二自动读取比赛开始事件，此前禁止新增或移入摄像机关键帧；可在设置中手动覆盖赛前长度。\n'
        '若自动识别不可用，请先在设置中手动填写赛前片段长度；已有关键帧继续保留。\n'
        '记录预览镜头会将七项属性添加到播放头时刻，保存后沿用现有游戏轨迹播放。\n'
        '首次从本机 Steam 客户端转换地图和车辆，缓存至 output/replay-preview-cache。\n'
        '预览材质、特效和车辆显示重建不等于游戏最终画面；预览时间与游戏仍需对齐核对。\n'
        '游戏控制支持范围仍为已经核验的 Steam 国际版 11.21.0.1235。\n'
        '包内含解析所需车型元数据，不含游戏模型、地图、贴图。游戏内容权利属于其权利人。\n', encoding='utf-8-sig')
    files = sorted(p for p in destination.rglob('*') if p.is_file() and 'output' not in p.relative_to(destination).parts and p.name != 'manifest.json')
    manifest = {'version':__version__, 'platform':'windows-x64', 'python':sys.version,
                'built_at_utc':datetime.now(timezone.utc).isoformat(), 'entrypoint':'BlitzCamera.exe',
                'requirements':['Windows 10/11 x64','.NET Framework >= 4.6.2','Microsoft Edge WebView2 Runtime'],
                'data_directory':'output', 'seed_project_sha256':seeded,
                'native_hook_sha256':native['sha256'], 'desktop_host_sha256':host['sha256'],
                'application_icon_sha256':sha(icon),
                'files':{p.relative_to(destination).as_posix():sha(p) for p in files}}
    (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = destination.parent/(destination.name+'.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                z.write(p, (Path(destination.name)/p.relative_to(destination)).as_posix())
    archive.with_suffix('.zip.sha256.txt').write_text(f'{sha(archive)}  {archive.name}\n', encoding='ascii')
    print(json.dumps({'directory':str(destination), 'archive':str(archive), 'bytes':archive.stat().st_size, 'files':len(files), 'sha256':sha(archive)}))
    return destination


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--destination', type=Path)
    p.add_argument('--project', type=Path)
    args = p.parse_args()
    build(args.destination, args.project)
