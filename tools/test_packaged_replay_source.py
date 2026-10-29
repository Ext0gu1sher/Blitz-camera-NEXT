"""Verify host/adapter replay reads in the shipped runtime, using archived bytes only."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from tools.verify_desktop_package import activate_test_pro

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import ctypes as C
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch
import blitzcam
from blitzcam.deployment import Deployment
from blitzcam.device_store import shared_profile_root
from blitzcam.game_backend import GameBackend
from blitzcam.profile import BuildProfile, CameraError
from blitzcam.replay_launcher import ReplaySourceUnavailable
from blitzcam.replay_timeline import file_timeline, replay_matches, session_timeline

root = Path(sys.argv[1])
assert Path(blitzcam.__file__).resolve().is_relative_to(root/'app')
deployment = Deployment(root/'output', root=root, profile_root=shared_profile_root())
assert deployment.enabled
backend = GameBackend(deployment)
reader, profile = backend.module('reader'), backend.module('profile')
class Memory:
    def __init__(self, data):
        self.info = SimpleNamespace(base=data['base'],pid=1,path=Path('fixture.exe'))
        self.profile = profile.PROFILE_1121
        self.blocks = {int(k):bytes.fromhex(v) for k,v in data['blocks'].items()}
    def read(self, address, size):
        for start, data in self.blocks.items():
            if start <= address and address+size <= start+len(data):
                return data[address-start:address-start+size]
        raise CameraError('Outside archived bytes')
    def u32(self,address): return struct.unpack('<I',self.read(address,4))[0]
    def regions(self): return [(a,len(b)) for a,b in self.blocks.items()]
cases=[]
for fixture in json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')):
    session = reader.CameraSession(Memory(fixture));session.discover()
    assert not isinstance(session.profile, BuildProfile)
    with patch.object(C,'WinDLL',side_effect=AssertionError('Unexpected process argument query')):
        actual=session_timeline(session)
        assert actual['verification']=='runtime_replay'
        assert replay_matches(file_timeline(fixture['replay']),actual)
        assert not replay_matches({'replay_file':'different.wotbreplay','replay_sha256':'b'*64},actual)
        # A changed owning pointer must still fail, without weakening the file checks.
        player=session.objects.player
        for address,raw in session.memory.blocks.items():
            if address<=player+0xE8 and player+0xF0<=address+len(raw):
                raw=bytearray(raw);raw[player+0xE8-address:player+0xF0-address]=bytes(8)
                session.memory.blocks[address]=bytes(raw);break
        try: session_timeline(session)
        except ReplaySourceUnavailable: pass
        else: raise AssertionError('Changed file owner was accepted')
    cases.append({'controller':fixture['controller'],'pointer_owner':fixture['pointer_owner'],
                  'verification':actual['verification'],'wrong_file_rejected':True,'changed_owner_rejected':True})
print(json.dumps({'app_version':blitzcam.__version__,'adapter_version':deployment.manifest['version'],
                  'master_id':deployment.manifest['source_master']['id'],'cases':cases,'game_access':False}))
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('package',type=Path)
    parser.add_argument('--master',type=Path,required=True)
    parser.add_argument('--source-host',action='store_true',help='Overlay changed host files in the isolated copy only')
    args=parser.parse_args()
    report_root=ROOT/'output/packaged-replay-source-acceptance';report_root.mkdir(exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix='run-',dir=report_root))
    app=run/'portable with spaces 中文';shutil.copytree(args.package,app)
    changed=[]
    if args.source_host:
        for name in ('replay_timeline.py','replay_source.py','replay_map.py','replay_launcher.py'):
            shutil.copyfile(ROOT/'blitzcam'/name,app/'app/blitzcam'/name)
            changed.append(name)
    sys.path.insert(0,str(ROOT/'tests'))
    from test_replay_source import source_fixture
    import zipfile
    replay=run/'手动回放.wotbreplay'
    with zipfile.ZipFile(replay,'w') as archive:
        archive.writestr('meta.json',json.dumps({'version':'11.21.0','battleDuration':253.12938}))
    fixtures=[]
    for controller in ('CinemaCameraController','SpectatorCameraController'):
        for pointer_owner in (False,True):
            session=source_fixture(replay,controller,pointer_owner=pointer_owner)
            fixtures.append({'controller':controller,'pointer_owner':pointer_owner,'replay':str(replay),
                             'base':session.memory.info.base,
                             'blocks':{str(a):b.hex() for a,b in session.memory.blocks.items()}})
    fixture_path=run/'fixtures.json';fixture_path.write_text(json.dumps(fixtures),encoding='utf-8')
    probe=run/'probe.py';probe.write_text(PROBE,encoding='utf-8')
    with ExitStack() as cleanup:
        activation=activate_test_pro(args.master,app,run/'account',cleanup)
        env=dict(os.environ,BLITZCAM_INSTALL_ROOT=str(app),BLITZCAM_DATA_ROOT=str(app),BLITZCAM_PROFILE_ROOT=str(run/'account'))
        result=subprocess.run([str(app/'runtime/python.exe'),'-X','utf8','-B',str(probe),str(app),str(fixture_path)],
                              cwd=run,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        (run/'probe.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:
            raise AssertionError('Packaged replay verification failed: '+str(run/'probe.log')+'\n'+result.stderr)
        value=json.loads(result.stdout)
        assert value['master_id']==activation['master_id']
        report={**value,'source_host_overlay':changed,'package':str(args.package.resolve()),'report_directory':str(run)}
        (run/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
