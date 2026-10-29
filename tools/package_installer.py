"""Build a per-user Windows installer from a verified portable release.

Requires Inno Setup 6.7+, its Chinese translation and Microsoft's signed
Evergreen bootstrapper. No runtime/development dependencies are downloaded here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(package, compiler=None, installer_id=None, output=None):
    package = Path(package).resolve()
    manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    runtime = ROOT/'tools/installer-runtime'
    compiler = Path(compiler or runtime/'inno/ISCC.exe').resolve()
    language = runtime/'ChineseSimplified.isl'
    bootstrapper = runtime/'MicrosoftEdgeWebview2Setup.exe'
    provenance = json.loads((ROOT/'tools/installer-provenance.json').read_text(encoding='utf-8'))
    for file in (language, bootstrapper):
        if sha(file) != provenance[file.name]['sha256']:
            raise ValueError('Installer dependency hash mismatch: '+file.name)
    if not compiler.is_file():
        raise ValueError('Install Inno Setup or pass --compiler')
    output = Path(output or ROOT/'dist').resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for name, digest in {**manifest['files'], 'manifest.json': sha(package/'manifest.json')}.items():
        source = (package/name).resolve()
        if not source.is_relative_to(package) or 'output' in Path(name).parts or sha(source) != digest:
            raise ValueError('Invalid release file: '+name)
        relative = Path(name)
        dest = '{app}' if relative.parent == Path('.') else '{app}\\'+str(relative.parent)
        files.append(f'Source: "{source}"; DestDir: "{dest}"; Flags: ignoreversion')
    payload = output/(package.name+'-payload.iss')
    payload.write_text('\n'.join(files)+'\n', encoding='utf-8-sig')
    args = [str(compiler), '/Qp', '/DPackageDir='+str(package), '/DAppVersion='+manifest['version'],
            '/DOutputDir='+str(output), '/DPayloadList='+str(payload), '/DLanguageFile='+str(language),
            '/DBootstrapper='+str(bootstrapper)]
    if installer_id:
        args.append('/DInstallerId='+installer_id)
    subprocess.run([*args, str(ROOT/'tools/installer.iss')], check=True)
    installer = output/f"BlitzCamera-{manifest['version']}-Setup.exe"
    installer.with_suffix('.exe.sha256.txt').write_text(f'{sha(installer)}  {installer.name}\n', encoding='ascii')
    report = {'installer': str(installer), 'sha256': sha(installer), 'bytes': installer.stat().st_size,
              'version': manifest['version'], 'package_manifest_sha256': sha(package/'manifest.json'),
              'files': len(files), 'dependencies': provenance, 'signed': False}
    installer.with_suffix('.build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return installer


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--compiler', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--installer-id')
    args = parser.parse_args()
    build(args.package, args.compiler, args.installer_id, args.output)
