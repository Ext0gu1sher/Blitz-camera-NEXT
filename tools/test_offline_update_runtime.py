"""Real portable runtime -> external updater -> native desktop restart, offline.

Creates only isolated copies under output. No running user app is closed and
no game is accessed. Test releases are never put in the distribution folder.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

from blitzcam.packages import digest, read_signed
from blitzcam.offline_updater import write_json
from tools.publish_updates import build_app, signing_keys

ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, seconds=60):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError('Timed out waiting for isolated update; preserve output for diagnostics')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--package', type=Path, help='Verify an actual signed release update instead of a synthetic one')
    args = parser.parse_args()
    report_dir = Path(tempfile.mkdtemp(prefix='runtime-', dir=ROOT/'output/deployment-development'))
    base, target = report_dir/'portable with spaces 中文', report_dir/'target'
    shutil.copytree(args.baseline, base)
    if args.package:
        package = args.package.resolve()
        signed, _ = read_signed(package, ROOT/'blitzcam/package-trust.json')
        assert signed['kind'] == 'app'
        manifest = signed['target_manifest']
    else:
        shutil.copytree(args.baseline, target)
        public, private = signing_keys(ROOT/'output/publisher/publisher.dpapi', ROOT/'blitzcam/package-trust.json')
        manifest = json.loads((target/'manifest.json').read_text(encoding='utf-8'))
        manifest['version'] = '0.9.6-beta.update-test'
        init = target/'app/blitzcam/__init__.py'
        init.write_text('__version__ = "0.9.6-beta.update-test"\n', encoding='utf-8')
        manifest['files']['app/blitzcam/__init__.py'] = digest(init.read_bytes())
        write_json(target/'manifest.json', manifest)
        package = report_dir/'test.bcupdate'
        build_app(base, target, package, public=public, private=private, notes='Isolated runtime update test')
    env = dict(os.environ, BLITZCAM_DATA_ROOT=str(base), BLITZCAM_INSTALL_ROOT=str(base), BLITZCAM_DESKTOP_SMOKE='1', BLITZCAM_PROFILE_ROOT=str(report_dir/'account'))
    fixture = base/'output/project.json'
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_bytes((base/'app/examples/eight-second.json').read_bytes())
    preserved = base/'output/preserved-user-data.txt'
    preserved.write_bytes(b'user data survives deployment')
    def open_fixture(service):
        request = urllib.request.Request(service['url']+'api/projects/open',
                    data=json.dumps({'path':str(fixture)}).encode(), headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert json.load(response)['ok']
    # The first desktop closes itself after native smoke assertions. Updater
    # must wait for the old launcher and service instead of replacing live files.
    launcher = subprocess.Popen([str(base/'BlitzCamera.exe')], cwd=base, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    service_file = base/'output/workstation-service.json'
    wait_for(service_file.is_file, 20)
    state = json.loads(service_file.read_text(encoding='utf-8-sig'))
    open_fixture(state)
    runner = report_dir/'install.py'
    runner.write_text(
        "from pathlib import Path\nimport json,sys\nfrom blitzcam.deployment import Deployment\n"
        "root=Path(sys.argv[1]);d=Deployment(root/'output',root=root)\n"
        "item=d.inspect(sys.argv[2])\n"
        "result=d.install(item['token'],pids=[int(sys.argv[3]),int(sys.argv[4])])\n"
        "print(json.dumps(result))\n", encoding='utf-8')
    operation = subprocess.run([str(base/'runtime/python.exe'), '-X','utf8','-B',str(runner), str(base), str(package),
                                str(launcher.pid), str(state['pid'])], cwd=base, env=env,
                               capture_output=True, text=True, encoding='utf-8', timeout=40)
    if operation.returncode:
        raise AssertionError(operation.stderr)
    launcher.wait(timeout=45)
    # WebView's smoke download intentionally does not overwrite an existing
    # destination. Preserve the first run's export before the restarted host
    # performs its own export to the same smoke-only filename.
    for name in ('desktop-export.json', 'desktop-actions.json'):
        previous = base/'output'/name
        if previous.exists():
            previous.replace(base/'output'/('before-update-' + name))
    result_file = base/'output/deployment/last-result.json'
    wait_for(result_file.is_file)
    result = json.loads(result_file.read_text(encoding='utf-8'))
    assert result['ok'], result
    def restarted():
        try:
            current = json.loads(service_file.read_text(encoding='utf-8-sig'))
            return current if current['version'] == manifest['version'] else None
        except (OSError, ValueError):
            return None
    new_service = wait_for(restarted, 30)
    open_fixture(new_service)
    from blitzcam.offline_updater import wait_processes
    wait_processes([new_service['pid']], timeout=45)
    actual = json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    assert actual['version'] == manifest['version']
    assert all(digest((base/n).read_bytes()) == h for n,h in actual['files'].items())
    smoke = json.loads(json.loads((base/'output/desktop-smoke.json').read_text(encoding='utf-8-sig')))
    assert smoke['loaded'] and smoke['startup'] and smoke['webview']
    actions = json.loads((base/'output/desktop-actions.json').read_text(encoding='utf-8-sig'))
    assert all(actions.values()), actions
    assert preserved.read_bytes() == b'user data survives deployment'
    report = {'waited_for_old_app': True, 'update_completed': True, 'native_restart': True,
              'all_target_hashes_verified': True, 'delta_bytes': package.stat().st_size,
              'package_sha256': digest(package.read_bytes()), 'actual_release': bool(args.package),
              'target': str(base), 'version': new_service['version'], 'native_actions': actions}
    write_json(report_dir/'result.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
