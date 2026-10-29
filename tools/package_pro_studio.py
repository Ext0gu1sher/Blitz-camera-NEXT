"""Build the maintainer-only Windows app from the existing offline runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from publisher import __version__


def build(runtime=None, output=None):
    runtime = Path(runtime or ROOT/'dist/BlitzCamera-0.9.6-beta-release/runtime').resolve()
    output = Path(output or ROOT/'dist'/('BlitzCameraProStudio-'+__version__)).resolve()
    if not (runtime/'python.exe').is_file():
        raise ValueError('需要现有便携客户端的 runtime 文件夹；也可通过 --runtime 指定。')
    # Explicit allowlist: no source adapters, device configs or publisher keys.
    output.mkdir(parents=True, exist_ok=True)
    packaged = set()
    def copy(source, target):
        target = Path(target); target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target); packaged.add(target)
    app = output/'app'; app.mkdir(exist_ok=True)
    for source in runtime.rglob('*'):
        if source.is_file(): copy(source,output/'runtime'/source.relative_to(runtime))
    (output/'runtime/python311._pth').write_text('python311.zip\nDLLs\n../app\n',encoding='ascii')
    for name in ('__init__.py','packages.py','package_crypto.py','offline_updater.py','package-trust.json'):
        target = app/'blitzcam'/name; target.parent.mkdir(exist_ok=True)
        copy(ROOT/'blitzcam'/name,target)
    (app/'tools').mkdir(exist_ok=True)
    (app/'tools/__init__.py').write_text('',encoding='ascii')
    packaged.add(app/'tools/__init__.py')
    copy(ROOT/'tools/publish_updates.py',app/'tools/publish_updates.py')
    publisher = app/'publisher'; publisher.mkdir(exist_ok=True)
    for source in (ROOT/'publisher').rglob('*'):
        relative = source.relative_to(ROOT/'publisher')
        if source.is_file() and (len(relative.parts)==1 and source.suffix=='.py' or relative.parts[0] in ('schema','web')):
            copy(source,publisher/relative)
    dependencies = ROOT/'tools/overlay-runtime'
    for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.Wpf.dll','WebView2Loader.dll'):
        copy(dependencies/name,output/name)
    framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
    icon = ROOT/'blitzcam/desktop/assets/BlitzCamera.ico'
    command = [str(framework/'csc.exe'),'/nologo','/target:winexe','/platform:x64','/optimize+',
               '/out:'+str(output/'ProStudio.exe'),'/win32icon:'+str(icon)]
    for name in ('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll','System.Xaml.dll',
                 'System.dll','System.Core.dll','System.Drawing.dll','System.Windows.Forms.dll','System.Web.Extensions.dll'):
        path = framework/name
        if not path.exists(): path = framework/'WPF'/name
        command.append('/reference:'+str(path))
    for name in ('Core','Wpf'): command.append('/reference:'+str(output/f'Microsoft.Web.WebView2.{name}.dll'))
    command.append(str(ROOT/'publisher/desktop/ProStudio.cs'))
    subprocess.run(command,check=True)
    copy(ROOT/'blitzcam/desktop/BlitzCameraOverlay.exe.config',output/'ProStudio.exe.config')
    copy(icon,output/'ProStudio.ico')
    licenses = output/'licenses'; licenses.mkdir(exist_ok=True)
    for name in ('Python-LICENSE.txt','WebView2-LICENSE.txt','webview2-provenance.json'):
        copy(runtime.parent/'licenses'/name,licenses/name)
    defaults = {'key_path':str(ROOT/'output/publisher/publisher.dpapi'),
                'trust_path':'app/blitzcam/package-trust.json',
                'recipe_path':str(ROOT/'adapters/steam-international-11.21/adapter.json'),
                'master_hint':str(ROOT/'output/pro-masters/steam-international-11.21-r1.bcpro'),
                'output_dir':str(ROOT/'output/pro-distribution')}
    (output/'defaults.json').write_text(json.dumps(defaults,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'使用说明.txt').write_text(
        'Blitz Camera Pro Studio '+__version__+'（内部制作工具）\n\n'
        '双击 ProStudio.exe。系统需要 Microsoft Edge WebView2；无需 Python 安装或联网。\n'
        '本机已预设现有发布密钥、适配清单与母包路径。移动工具或换电脑后，请在发布设置中重新选择路径。\n\n'
        '常规发包：导入 .bcpro 母包 → 导入用户从客户端导出的 .bcconfig → 勾选用户 → 生成加密升级包。\n'
        '把各用户对应的 .bcupdate 单独发给本人。batch.json 和分发清单.csv 用于自己留档。\n'
        '版本更新：完成适配与验证，更新 adapter.json 和修订号 → 在制作母包页生成新的 .bcpro。\n'
        '新版本继续使用原来的用户配置；设备或 Windows 用户密钥变化时需重新导出。\n\n'
        '.bcpro 是未加密的内部母包，包含完整适配实现，不要交给最终用户。\n'
        '工具不包含发布私钥。换电脑前在发布设置中导出带口令的密钥备份。\n'
        'data 文件夹保存母包库、公开配置和历史；更换工具版本时保留它。\n'
        '设备绑定阻止直接复制使用，不能保证对运行时逆向分析的绝对防护。\n',encoding='utf-8-sig')
    # Archive only the files produced here. Mutable data and any accidental
    # credentials dropped beside the executable must never enter the ZIP.
    permitted = {'ProStudio.exe','ProStudio.exe.config','ProStudio.ico','defaults.json','使用说明.txt',
                 'Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.Wpf.dll','WebView2Loader.dll'}
    files = sorted(packaged | {output/name for name in permitted})
    if any(p.suffix.lower() in ('.dpapi','.bcsecret','.bcconfig','.bcpro') for p in files):
        raise ValueError('制作工具归档意外包含私有数据。')
    archive = output.parent/(output.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as stream:
        for path in sorted(files): stream.write(path,path.relative_to(output).as_posix())
    result = {'executable':str(output/'ProStudio.exe'),'archive':str(archive),'files':len(files),
              'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--runtime'); parser.add_argument('--output')
    args = parser.parse_args(); build(args.runtime,args.output)
