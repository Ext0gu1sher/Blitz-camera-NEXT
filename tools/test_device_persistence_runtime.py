"""Cold portable processes: export, close, receive, import, reopen elsewhere."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.offline_updater import write_json
from blitzcam.packages import digest
from tools.publish_updates import build_pro

ROOT=Path(__file__).resolve().parents[1]


def main():
    report=Path(tempfile.mkdtemp(prefix='persistence-',dir=ROOT/'output'))
    baseline=ROOT/'dist/BlitzCamera-0.9.6-beta.1'
    public,private=crypto.generate_publisher()
    name='BlitzCamera-'+uuid4().hex;provider='Microsoft Software Key Storage Provider'
    device_public=crypto.device_public(name,provider,create=True)
    device={'key_name':name,'provider':provider,'device':digest(device_public)}
    profile=report/'account';config=report/'exported-before-close.bcconfig';package=report/'arrived-later.bcupdate'
    env=dict(os.environ,BLITZCAM_PROFILE_ROOT=str(profile),BLITZCAM_DESKTOP_SMOKE='1')
    def api(service,path,value=None):
        request=urllib.request.Request(service['url']+path,data=None if value is None else json.dumps(value).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    def copy(label):
        target=report/label;shutil.copytree(baseline,target)
        write_json(target/'app/blitzcam/package-trust.json',{'keys':{digest(public):base64.b64encode(public).decode()}})
        (target/'output/project.json').write_bytes((target/'app/examples/eight-second.json').read_bytes())
        return target
    def operation(target,action):
        script='''import json,sys
from pathlib import Path
from blitzcam.deployment import Deployment
from blitzcam.device_store import shared_profile_root
d=Deployment(Path(sys.argv[1])/'output',root=sys.argv[1],profile_root=shared_profile_root())
if sys.argv[2]=='export': print(json.dumps(d.export_config(sys.argv[3])))
else:
 p=d.inspect(sys.argv[3]);print(json.dumps(d.install(p['token'])))
'''
        command=[str(target/'runtime/python.exe'),'-X','utf8','-B','-c',script,str(target),action,str(config if action=='export' else package)]
        completed=subprocess.run(command,env=env,cwd=target,capture_output=True,text=True,encoding='utf-8',check=True,timeout=30)
        return json.loads(completed.stdout)
    def native(target,edition,label):
        for filename in ('workstation-service.json','desktop-export.json','desktop-actions.json','desktop-smoke.json'):
            (target/'output'/filename).unlink(missing_ok=True)
        child_env=dict(env,BLITZCAM_DATA_ROOT=str(target),BLITZCAM_INSTALL_ROOT=str(target))
        process=subprocess.Popen([str(target/'BlitzCamera.exe')],cwd=target,env=child_env,creationflags=subprocess.CREATE_NO_WINDOW)
        statefile=target/'output/workstation-service.json';deadline=time.monotonic()+20
        while not statefile.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        service=json.loads(statefile.read_text(encoding='utf-8-sig'))
        state=api(service,'api/state');assert state['edition']==edition,(label,state['edition'])
        api(service,'api/projects/open',{'path':str(target/'output/project.json')})
        process.wait(timeout=45);assert process.returncode==0
        smoke=json.loads(json.loads((target/'output/desktop-smoke.json').read_text(encoding='utf-8-sig')))
        assert smoke['startup'] and smoke['loaded'] and smoke['webview'],smoke
        try: api(service,'api/state')
        except OSError: pass
        else: raise AssertionError('service did not stop')
        return {'stage':label,'edition':edition,'service_pid':service['pid'],'native_rendered':True,'closed':True}
    try:
        first,second=copy('original portable'),copy('another folder 中文')
        write_json(first/'output/deployment/device.json',device)
        assert operation(first,'export')['ok']
        stages=[native(first,'next','export then close')]
        # The package is made only after the original native app is fully gone.
        os.utime(config,(1000000000,1000000000))
        build_pro(ROOT/'blitzcam',config,package,version='11.21-persistence-test',public=public,private=private,
                  game_sha256='5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608')
        for path in (first/'output/deployment/device.json',profile/'device.json',profile/'devices'/(device['device']+'.json')):path.unlink()
        assert operation(second,'install')['edition']=='pro'  # no second export
        stages.append(native(second,'pro','import elsewhere then open'))
        stages.append(native(second,'pro','close then reopen'))
        stages.append(native(first,'pro','return to original entry'))
        result={'ok':True,'no_reexport':True,'lost_metadata_recovered_from_existing_key':True,
                'same_device':json.loads((profile/'device.json').read_text())['device']==device['device'],'stages':stages,'directory':str(report)}
        write_json(report/'result.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        with crypto.device_key(name,provider) as (dll,key):
            crypto._check(crypto._fn(dll,'NCryptDeleteKey',[crypto.HANDLE,crypto.U32])(key,0),'清理测试密钥');key.value=0


if __name__=='__main__':main()
