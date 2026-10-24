"""Build the Windows overlay with the installed .NET Framework compiler.

Only the official, version-pinned Microsoft WebView2 NuGet package is downloaded.
No administrator install or game access is needed.
"""
import base64
import hashlib
import gzip
import io
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.3912.50'
PACKAGE = f'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{VERSION}/microsoft.web.webview2.{VERSION}.nupkg'


def build():
    output = ROOT / 'tools' / 'overlay-runtime'
    output.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'tools' / f'webview2-{VERSION}.nupkg'
    if not archive.exists():
        print('Downloading official Microsoft WebView2 SDK ' + VERSION, flush=True)
        raw = urllib.request.urlopen(PACKAGE, timeout=45).read()
        def document(url):
            data = urllib.request.urlopen(url, timeout=20).read()
            return json.loads(gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data)
        registration = document(f'https://api.nuget.org/v3/registration5-gz-semver2/microsoft.web.webview2/{VERSION}.json')
        catalog = document(registration['catalogEntry'])
        expected = catalog['packageHash']
        if base64.b64encode(hashlib.sha512(raw).digest()).decode() != expected:
            raise RuntimeError('NuGet package SHA-512 does not match')
        archive.write_bytes(raw)
        (ROOT / 'tools' / 'webview2-provenance.json').write_text(json.dumps({
            'version': VERSION, 'source': PACKAGE, 'sha256': hashlib.sha256(raw).hexdigest(),
            'sha512': expected,
        }, indent=2) + '\n', encoding='utf-8')
    provenance = json.loads((ROOT / 'tools' / 'webview2-provenance.json').read_text())
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != provenance['sha256']:
        raise RuntimeError('Cached WebView2 package hash does not match')
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        def put(name, data):
            target = output/name
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
        for name in ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.Wpf.dll'):
            put(name, package.read('lib/net462/' + name))
        put('WebView2Loader.dll', package.read('runtimes/win-x64/native/WebView2Loader.dll'))
    source = ROOT/'blitzcam/desktop/OverlayHost.cs'
    icon = ROOT/'blitzcam/desktop/assets/BlitzCamera.ico'
    filename = 'BlitzCameraOverlay.'+hashlib.sha256(source.read_bytes()+icon.read_bytes()).hexdigest()[:12]+'.exe'
    framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
    references = ['WindowsBase.dll', 'PresentationCore.dll', 'PresentationFramework.dll',
                  'System.Xaml.dll', 'System.dll', 'System.Core.dll', 'System.Drawing.dll',
                  'System.Windows.Forms.dll', 'System.Web.Extensions.dll']
    args = [str(framework/'csc.exe'), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
            '/out:' + str(output/filename), '/win32icon:'+str(icon), '/resource:'+str(icon)+',BlitzCamera.Icon']
    for name in references:
        path = framework / name
        if not path.exists():
            path = framework / 'WPF' / name
        args.append('/reference:' + str(path))
    for name in ('Core', 'Wpf'):
        args.append('/reference:' + str(output/f'Microsoft.Web.WebView2.{name}.dll'))
    args.append(str(source))
    subprocess.run(args, check=True)
    shutil.copyfile(ROOT/'blitzcam/desktop/BlitzCameraOverlay.exe.config', output/(filename+'.config'))
    (output/'host.json').write_text(json.dumps({'executable':filename,'sha256':hashlib.sha256((output/filename).read_bytes()).hexdigest(),
                                               'icon_sha256':hashlib.sha256(icon.read_bytes()).hexdigest()}))
    print(output/filename)


if __name__ == '__main__':
    build()
