"""Verify the shipped desktop app in an isolated, relocated folder.

Native WebView2 renders offscreen with no focus, hotkeys, tray, game discovery,
camera connection, Hook execution or external browser launch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--preview-replay', type=Path)
    parser.add_argument('--overlay-visibility', action='store_true')
    args = parser.parse_args()
    tag=args.archive.stem.removeprefix('BlitzCamera-').replace('.','')
    report_root = ROOT/'output'/f'desktop-{tag}-acceptance'
    report_root.mkdir(exist_ok=True)
    relocated = Path(tempfile.mkdtemp(prefix='run-', dir=report_root))/'portable with spaces 中文'
    relocated.mkdir(exist_ok=True)
    with zipfile.ZipFile(args.archive) as archive:
        for name in archive.namelist():
            target = (relocated/name).resolve()
            if not target.is_relative_to(relocated.resolve()):
                raise ValueError('Archive path escaped destination')
        archive.extractall(relocated)
    app = relocated/args.archive.stem
    manifest = json.loads((app/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if hashlib.sha256((app/name).read_bytes()).hexdigest() != expected:
            raise AssertionError('Changed package file: '+name)
    env = dict(os.environ, BLITZCAM_DATA_ROOT=str(app), BLITZCAM_DESKTOP_SMOKE='1')
    if args.overlay_visibility:env['BLITZCAM_OVERLAY_SMOKE']='1'
    if args.preview_replay:
        env['BLITZCAM_PREVIEW_SMOKE']='1'
        from blitzcam.replay_timeline import file_timeline
        from blitzcam.pose import quaternion_from_angles
        from blitzcam.project import validate_project
        info=file_timeline(args.preview_replay)
        # Replace only the isolated extracted test project's data. The user's
        # source and delivered package project remain untouched.
        data={'shooting_mode':'replay','timing':'keyframes',
              'replay_timeline':{'time_basis':'replay','duration_sec':info['duration_sec'], 'work_start_sec':40,'work_end_sec':80,'replay_file':info['replay_file']},
              'keyframes':[{'time_sec':t,'position':p,'quaternion':list(quaternion_from_angles(a,-10,0)),'horizontal_fov_deg':z}for t,p,a,z in [(40,[150,100,60],-130,70),(80,[-20,30,50],-90,50)]]}
        (app/'output/project.json').write_text(json.dumps(validate_project(data).to_dict()),encoding='utf-8')
    original = ROOT/'output/project.json'
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    probe = subprocess.run([str(app/'runtime/python.exe'), '-B', '-c',
        "import json,sys,hashlib;from blitzcam.project import read_project;from blitzcam.channels import track_controls;"
        "from blitzcam.playback import compile_positions,NATIVE;from blitzcam.paths import OUTPUT;"
        "p=read_project(OUTPUT/'project.json');m=json.loads((NATIVE/'position_hook_1121.json').read_text());"
        "assert hashlib.sha256((NATIVE/m['dll']).read_bytes()).hexdigest()==m['sha256'];"
        "rows=compile_positions(p);print(json.dumps({'sys_path':sys.path,'version':sys.version,'channels':list(track_controls(p)),"
        "'compiled_pose_points':len(rows),'dll_verified':True}))"],
        cwd=relocated, env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
    if probe.returncode:
        raise AssertionError(probe.stderr)
    probe_result = json.loads(probe.stdout)
    if args.preview_replay:
        codec = subprocess.run([str(app/'runtime/python.exe'),'-B','-c',
            # The pinned codec requires input >128 bytes. Use a real 32x32
            # constant-red BC1 texture, rather than an undersized probe.
            "from blitzcam.preview_assets import dependencies;dependencies();import imagecodecs;"
            "a=imagecodecs.bcn_decode(bytes.fromhex('00f8000000000000')*64,1,shape=(32,32,4));"
            "assert a.shape==(32,32,4) and (a==[255,0,0,255]).all()"],cwd=relocated,env=env,capture_output=True,text=True,timeout=15)
        if codec.returncode:raise AssertionError(codec.stderr)
    print('Portable runtime and full-pose compile passed', flush=True)
    service = subprocess.Popen([str(app/'BlitzCamera.exe')], cwd=relocated, env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    state_file = app/'output/workstation-service.json'
    deadline = time.monotonic()+15
    while not state_file.exists() and service.poll() is None and time.monotonic()<deadline:
        time.sleep(.05)
    if not state_file.exists():
        raise AssertionError('Desktop service did not start')
    initial_service = json.loads(state_file.read_text(encoding='utf-8-sig'))
    # A second launch signals the original window instead of creating a backend.
    second = subprocess.run([str(app/'BlitzCamera.exe')], cwd=relocated, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
    if second.returncode or json.loads(state_file.read_text(encoding='utf-8-sig'))['pid'] != initial_service['pid']:
        raise AssertionError('Duplicate launch created a second backend')
    try:
        code = service.wait(timeout=240 if args.preview_replay else 45)
    except subprocess.TimeoutExpired:
        # Retain all evidence. Never terminate other desktop/game processes.
        raise AssertionError('Desktop did not finish; inspect isolated output logs')
    smoke_file = app/'output/desktop-smoke.json'
    if not smoke_file.is_file():
        errors = {p.name:p.read_text(encoding='utf-8') for p in (app/'output').glob('*error.txt')}
        raise AssertionError({'code':code, 'errors':errors, 'log':(app/'output/desktop-service.log').read_text(encoding='utf-8')})
    smoke = json.loads(json.loads(smoke_file.read_text(encoding='utf-8-sig')))
    if code != 0 or not all(smoke[k] for k in ('loaded','startup','timeline','webview')):
        raise AssertionError({'code':code, 'smoke':smoke})
    actions = json.loads((app/'output/desktop-actions.json').read_text(encoding='utf-8-sig'))
    if not all(actions.values()):
        raise AssertionError(actions)
    exported = json.loads((app/'output/desktop-export.json').read_text(encoding='utf-8-sig'))
    # Older example projects omit optional defaults that native export expands.
    # Compare their loaded contents rather than treating defaults as an edit.
    from blitzcam.project import read_project
    saved = read_project(app/'output/project.json').to_dict()
    if exported != saved:
        raise AssertionError('Native export changed the project')
    status = json.loads((app/'output/overlay-status.json').read_text(encoding='utf-8-sig'))
    if not status['workbench']['ready'] or status['gameFound']:
        raise AssertionError(status)
    state = json.loads((app/'output/workstation-service.json').read_text(encoding='utf-8-sig'))
    import urllib.request
    try:
        urllib.request.urlopen(state['url']+'api/state',timeout=1)
    except OSError:
        pass
    else:
        raise AssertionError('Backend remained active after desktop closed')
    if hashlib.sha256(original.read_bytes()).hexdigest() != before:
        raise AssertionError('Original project changed')
    report = {'package':str(args.archive.resolve()), 'package_sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),
              'version':manifest['version'], 'runtime_probe':probe_result,
              'native_webview':smoke, 'native_actions':actions, 'duplicate_launch_reused_backend':True,
              'backend_exited':True, 'source_project_unchanged':before,
              'relocated_directory':str(app), 'scope':'offscreen native desktop; no game access or Hook execution'}
    if args.overlay_visibility:
        overlay=json.loads((app/'output/desktop-overlay-smoke.json').read_text(encoding='utf-8-sig'))
        if not all(overlay[k] for k in ('hidePreservedWorkbench','revealPassed','collapsePassed','positiveCaptureSize')) or overlay['cycles']<3:raise AssertionError(overlay)
        report['overlay_visibility']=overlay
    if args.preview_replay:
        preview=json.loads((app/'output/desktop-preview-smoke.json').read_text(encoding='utf-8-sig'))
        actual=json.loads(json.loads(preview['result']))
        if not actual.get('ready') or not actual.get('backwardStable') or not actual['diagnostics']['visible'] or actual['diagnostics']['triangles']<=0:
            raise AssertionError(preview)
        report['replay_preview']=actual
    (report_root/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
