"""Exercise production HWND stacking using transparent offscreen fixtures only."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main(baseline=False):
    runtime = ROOT / 'tools/overlay-runtime'
    report = ROOT / 'output/overlay-visibility-acceptance'
    report.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'output') as folder:
        root = Path(folder)
        framework = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319')
        args = [str(framework / 'csc.exe'), '/nologo', '/target:exe', '/platform:x64',
                '/main:OverlayVisibilityProbe', '/out:' + str(root / 'probe.exe'),
                '/resource:' + str(ROOT / 'blitzcam/desktop/assets/BlitzCamera.ico') + ',BlitzCamera.Icon']
        for name in ('WindowsBase', 'PresentationCore', 'PresentationFramework', 'System.Xaml',
                     'System', 'System.Core', 'System.Drawing', 'System.Windows.Forms', 'System.Web.Extensions'):
            path = framework / (name + '.dll')
            if not path.exists():
                path = framework / 'WPF' / (name + '.dll')
            args.append('/reference:' + str(path))
        for name in ('Core', 'Wpf'):
            dll = runtime / f'Microsoft.Web.WebView2.{name}.dll'
            args.append('/reference:' + str(dll))
            shutil.copyfile(dll, root / dll.name)
        args.extend([str(ROOT / 'blitzcam/desktop/OverlayHost.cs'),
                     str(ROOT / 'tools/overlay_visibility_probe.cs')])
        subprocess.run(args, check=True)
        probe = subprocess.run([str(root / 'probe.exe'), str(root)] + (['--baseline'] if baseline else []),
                               capture_output=True, text=True, encoding='utf-8', timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        if probe.stdout.strip():
            result = json.loads(probe.stdout)
            (report / ('baseline.json' if baseline else 'result.json')).write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False))
        if probe.returncode:
            raise AssertionError(probe.stderr)


if __name__ == '__main__':
    main('--baseline' in sys.argv)
