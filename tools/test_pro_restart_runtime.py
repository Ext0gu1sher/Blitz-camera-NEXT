"""Real NEXT desktop -> encrypted Pro activation -> automatic restart and intro.

Uses an isolated portable copy and disposable Windows key. Never accesses a game.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.deployment import Deployment
from blitzcam.offline_updater import wait_processes, write_json
from blitzcam.packages import digest
from publisher.issuance import issue
from tools.test_offline_update_runtime import wait_for

ROOT = Path(__file__).resolve().parents[1]


def main(cleanup):
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--master', type=Path, required=True)
    args = parser.parse_args()
    parent = ROOT/'output/pro-restart-acceptance'; parent.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    app = run/'portable with spaces 中文'; shutil.copytree(args.package, app)
    profile = run/'account'
    key_name = 'BlitzCamera-Pro-Restart-Test-'+uuid4().hex
    provider = 'Microsoft Software Key Storage Provider'
    public = crypto.device_public(key_name, provider, create=True)
    def delete_key():
        with crypto.device_key(key_name, provider) as (dll, key):
            crypto._check(crypto._fn(dll, 'NCryptDeleteKey', [crypto.HANDLE, crypto.U32])(key, 0), '清理测试密钥')
            key.value = 0
    cleanup.callback(delete_key)
    write_json(profile/'device.json', {'key_name':key_name,'provider':provider,'device':digest(public)})
    manager = Deployment(app/'output', root=app, profile_root=profile, trust=app/'app/blitzcam/package-trust.json')
    config = profile/'device.bcconfig'; manager.export_config(config)
    issued = issue(args.master, [config], run/'issued', ROOT/'output/publisher/publisher.dpapi', manager.trust)
    package = Path(issued['directory'])/issued['recipients'][0]['filename']
    env = dict(os.environ, BLITZCAM_INSTALL_ROOT=str(app), BLITZCAM_DATA_ROOT=str(app),
               BLITZCAM_PROFILE_ROOT=str(profile), BLITZCAM_DESKTOP_SMOKE='1')
    fixture = app/'output/project.json'
    fixture.write_bytes((app/'app/examples/eight-second.json').read_bytes())
    preserved = app/'output/preserved-user-data.txt'; preserved.write_bytes(b'preserved during Pro restart')
    state_file = app/'output/workstation-service.json'
    def request(state, route, value=None, raw=False):
        req = urllib.request.Request(state['url']+route,
                  data=None if value is None else json.dumps(value).encode(),
                  headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8') if raw else json.load(response)
    def open_project(state): request(state,'api/projects/open',{'path':str(fixture)})
    def service_after(previous=None):
        try:
            value=json.loads(state_file.read_text(encoding='utf-8-sig'))
            return value if value['pid'] != previous else None
        except (OSError,ValueError): return None
    def preserve_smoke(label):
        for name in ('desktop-smoke.json','desktop-actions.json','desktop-export.json'):
            path=app/'output'/name
            if path.exists(): path.replace(app/'output'/(label+'-'+name))
    first = subprocess.Popen([str(app/'BlitzCamera.exe')], cwd=app, env=env,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    initial=wait_for(service_after,20)
    assert request(initial,'api/state')['edition']=='next'
    open_project(initial)
    runner=run/'install.py'
    runner.write_text('''import json,sys
from pathlib import Path
from blitzcam.deployment import Deployment
from blitzcam.device_store import shared_profile_root
root=Path(sys.argv[1]); d=Deployment(root/'output',root=root,profile_root=shared_profile_root())
preview=d.inspect(sys.argv[2]); assert preview['restart']
result=d.install(preview['token'],pids=[int(p) for p in sys.argv[3:]],restart_pro=True)
assert result['restart'] and d.restart_pending
print(json.dumps({'result':result,'intro':d.startup_state()['intro_token']}))
''',encoding='utf-8')
    result=subprocess.run([str(app/'runtime/python.exe'),'-X','utf8','-B',str(runner),str(app),str(package),
                           str(first.pid),str(initial['pid'])],cwd=run,env=env,
                          capture_output=True,text=True,encoding='utf-8',timeout=30)
    (run/'install.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    assert result.returncode==0,result.stderr
    installation=json.loads(result.stdout); token=installation['intro']; assert token
    first.wait(timeout=45); assert first.returncode==0
    preserve_smoke('before-upgrade')
    restarted=wait_for(lambda:service_after(initial['pid']),30)
    assert request(restarted,'api/state')['edition']=='pro'
    html=request(restarted,'',raw=True)
    assert 'data-pro-intro="'+token+'"' in html
    open_project(restarted)
    wait_processes([restarted['pid']],timeout=45)
    smoke=json.loads(json.loads((app/'output/desktop-smoke.json').read_text(encoding='utf-8-sig')))
    assert smoke['loaded'] and smoke['startup'] and smoke['webview'] and 'Pro' in smoke['version'],smoke
    assert not (profile/'pro-intro.json').exists(), 'Completed native intro was not acknowledged'
    preserve_smoke('first-pro')
    daily=subprocess.Popen([str(app/'BlitzCamera.exe')],cwd=app,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    subsequent=wait_for(lambda:service_after(restarted['pid']),20)
    assert 'data-pro-intro=""' in request(subsequent,'',raw=True)
    assert request(subsequent,'api/state')['edition']=='pro'
    open_project(subsequent); daily.wait(timeout=45); assert daily.returncode==0
    assert preserved.read_bytes()==b'preserved during Pro restart'
    manifest=json.loads((app/'manifest.json').read_text(encoding='utf-8'))
    assert all(digest((app/name).read_bytes())==sha for name,sha in manifest['files'].items())
    report={'version':manifest['version'],'package':str(args.package.resolve()),'report_directory':str(run),
            'signed_encrypted_activation':True,'waited_for_original_exit':True,'automatic_native_restart':True,
            'first_intro_in_restarted_html':True,'native_first_intro_completed':True,'daily_intro_not_repeated':True,
            'user_data_preserved':True,'application_files_unchanged':True,'game_access':False,
            'service_pids':[initial['pid'],restarted['pid'],subsequent['pid']]}
    write_json(run/'result.json',report); print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    with ExitStack() as cleanup: main(cleanup)
