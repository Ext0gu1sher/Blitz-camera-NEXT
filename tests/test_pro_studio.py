"""Maintainer master/issuance contract tests; no game process is accessed."""
import base64
from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.offline_updater import write_json
from blitzcam.packages import ADAPTER_MODULES, canonical, decrypt_pro, digest, read_signed, read_zip, zip_bytes
from publisher.master import collect, create_master, inspect_master, read_master, validate_payload, validate_release, version_key
from publisher.issuance import device_config, issue, preflight
from publisher.store import Studio
from tools.publish_updates import seal_pro

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT/'adapters/steam-international-11.21/adapter.json'


class MasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release, cls.files, cls.evidence, _ = collect(RECIPE)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.master = self.root/'master.bcpro'
        create_master(RECIPE,self.master)

    def test_deterministic_contents_and_identity(self):
        other = self.root/'second.bcpro'; create_master(RECIPE,other)
        self.assertEqual(self.master.read_bytes(),other.read_bytes())
        manifest,files,checks = read_master(other)
        self.assertEqual(files,self.files)
        self.assertEqual(len(files),20)
        self.assertFalse(checks['executed_adapter'])
        self.assertEqual(checks['native_architecture'],'x86')
        self.assertEqual(manifest['release'],self.release)
        self.assertEqual(inspect_master(other)['master_id'],inspect_master(self.master)['master_id'])

    def test_does_not_overwrite_existing_master(self):
        before = self.master.read_bytes()
        with self.assertRaisesRegex(ValueError,'已存在'): create_master(RECIPE,self.master)
        self.assertEqual(before,self.master.read_bytes())

    def test_interrupted_master_write_does_not_publish_partial_file(self):
        target=self.root/'new-master.bcpro'
        with patch('publisher.master.os.fsync',side_effect=OSError('simulated write failure')),self.assertRaises(OSError):
            create_master(RECIPE,target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.master-*')))

    def test_recipe_missing_or_ambiguous_fields(self):
        original = json.loads(RECIPE.read_text(encoding='utf-8'))
        for change in ({'unexpected':1},{'format':'v2'},{'evidence':[]}):
            recipe = dict(original,source_root=str(ROOT/'blitzcam')); recipe.update(change)
            path = self.root/'adapter.json'; write_json(path,recipe)
            with self.subTest(change=change), self.assertRaises(ValueError): collect(path)

    def test_release_required_fields_architecture_and_api(self):
        for key,value in [('adapter_api',2),('adapter_api',True),('entrypoints',{}),('host_min_version','banana'),
                          ('adapter_id','../unsafe'),('validation',{'level':'unknown','summary':'test'})]:
            release = deepcopy(self.release); release[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_release(release)
        release = deepcopy(self.release); release['client']['architecture']='x64'
        with self.assertRaises(ValueError): validate_release(release)

    def test_version_order(self):
        versions=['0.9.5','0.9.6-alpha','0.9.6-beta','0.9.6-beta2','0.9.6-rc','0.9.6','0.9.7','0.10.0','1.0.0']
        self.assertEqual(sorted(versions,key=version_key),versions)

    def test_missing_modules_and_incompatible_imports(self):
        for name in ADAPTER_MODULES:
            files=dict(self.files); del files[name+'.py']
            with self.subTest(name=name), self.assertRaises(ValueError): validate_payload(files)
        for suffix in (b'\nfrom .future_host import something\n',b'\nimport blitzcam.reader\n',b'\nfrom .. import reader\n',b'\nsyntax!error!\n'):
            files=dict(self.files); files['reader.py']+=suffix
            with self.subTest(suffix=suffix), self.assertRaises(ValueError): validate_payload(files)

    def test_entrypoint_contract(self):
        files=dict(self.files); files['reader.py']=b'class CameraSession: pass\n'
        with self.assertRaisesRegex(ValueError,'入口方法'): validate_payload(files)

    def test_native_hash_architecture_and_orphan(self):
        dll = next(n for n in self.files if n.endswith('.dll'))
        files=dict(self.files); files[dll]=b'bad'
        with self.assertRaisesRegex(ValueError,'哈希'): validate_payload(files)
        native=next(n for n,b in self.files.items() if n.endswith('.json') and json.loads(b)['dll']==Path(dll).name)
        files[native]=canonical(dict(json.loads(files[native]),sha256=digest(files[dll])))
        with self.assertRaisesRegex(ValueError,'PE'): validate_payload(files)
        files=dict(self.files); files['native/orphan.dll']=files[dll]
        with self.assertRaisesRegex(ValueError,'未被'): validate_payload(files)
        files=dict(self.files); data=bytearray(files[dll]); offset=int.from_bytes(data[60:64],'little'); data[offset+4:offset+6]=b'\x64\x86'; files[dll]=bytes(data)
        files[native]=canonical(dict(json.loads(files[native]),sha256=digest(files[dll])))
        with self.assertRaisesRegex(ValueError,'x86'): validate_payload(files)

    def test_rejects_missing_referenced_native_manifest(self):
        files=dict(self.files)
        native=next(n for n in files if n.endswith('.json')); dll=json.loads(files.pop(native))['dll']; files.pop('native/'+dll)
        with self.assertRaisesRegex(ValueError,'清单未包含'): validate_payload(files)

    def test_master_content_tamper_extra_and_identity(self):
        original=read_zip(self.master)
        for name in ('payload/reader.py','evidence/validation.json','extra'):
            files=dict(original); files[name]=b'tampered'; self.master.write_bytes(zip_bytes(files))
            with self.subTest(name=name),self.assertRaises(ValueError): read_master(self.master)
        files=dict(original); manifest=json.loads(files['manifest.json']); manifest['master_id']='f'*64
        files['manifest.json']=canonical(manifest); self.master.write_bytes(zip_bytes(files))
        with self.assertRaisesRegex(ValueError,'身份'): read_master(self.master)

    def test_checks_do_not_execute_adapter(self):
        marker=self.root/'must-not-exist.txt'
        files=dict(self.files); files['reader.py']+=('\n__import__("pathlib").Path('+repr(str(marker))+').write_text("executed")\n').encode()
        validate_payload(files)
        with patch('publisher.master.collect',return_value=(self.release,files,self.evidence,validate_payload(files))):
            create_master(RECIPE,self.root/'sideeffect.bcpro')
        inspect_master(self.root/'sideeffect.bcpro')
        self.assertFalse(marker.exists())

    def test_library_same_version_conflict_and_snapshot(self):
        studio=Studio(self.root/'data'); first=studio.import_master(self.master)
        release=deepcopy(self.release); release['notes']+=' changed'
        with patch('publisher.master.collect',return_value=(release,self.files,self.evidence,validate_payload(self.files))):
            create_master(RECIPE,self.root/'changed.bcpro')
        with self.assertRaisesRegex(ValueError,'修订号'): studio.import_master(self.root/'changed.bcpro')
        self.master.unlink()
        self.assertEqual(inspect_master(studio.master_path(first['master_id']))['sha256'],first['sha256'])
        self.assertEqual(len(studio.state()['masters']),1)

    def test_snapshot_read_failure_preserves_library(self):
        studio=Studio(self.root/'data'); first=studio.import_master(self.master)
        def changed_copy(source,destination): Path(destination).write_bytes(b'changed during import')
        with patch('publisher.store.shutil.copyfile',side_effect=changed_copy),self.assertRaises(ValueError): studio.import_master(self.master)
        self.assertEqual(inspect_master(studio.master_path(first['master_id']))['sha256'],first['sha256'])
        self.assertFalse(list((studio.data/'masters').glob('.import-*')))


@unittest.skipUnless(os.name=='nt','Uses Windows CNG and DPAPI')
class IssuanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public,cls.private=crypto.generate_publisher(); cls.devices=[]; cls.configs=[]
        for _ in range(2):
            name='BlitzCamera-Studio-Test-'+uuid4().hex; provider='Microsoft Software Key Storage Provider'
            public=crypto.device_public(name,provider,create=True)
            cls.devices.append({'key_name':name,'provider':provider,'device':digest(public)})
            cls.configs.append({'format':'blitz-camera-device-v1','api':1,'app_version':'0.9.6-beta','device':digest(public),
                                'public_key':base64.b64encode(public).decode(),'protection':'windows-user'})

    @classmethod
    def tearDownClass(cls):
        for device in cls.devices:
            with crypto.device_key(device['key_name'],device['provider']) as (dll,key):
                crypto._check(crypto._fn(dll,'NCryptDeleteKey',[crypto.HANDLE,crypto.U32])(key,0),'清理测试密钥'); key.value=0

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup); self.root=Path(temporary.name)
        self.master=self.root/'master.bcpro'; create_master(RECIPE,self.master)
        self.trust=self.root/'trust.json'; write_json(self.trust,{'keys':{digest(self.public):base64.b64encode(self.public).decode()}})
        self.key=self.root/'publisher.dpapi'; self.key.write_bytes(crypto.protect_local(self.private))
        self.paths=[]
        for n,config in enumerate(self.configs):
            path=self.root/('用户'+str(n+1)+'.bcconfig'); write_json(path,config); self.paths.append(path)
        self.output=self.root/'batches'

    def batch(self, **kwargs): return issue(self.master,self.paths,self.output,self.key,self.trust,**kwargs)

    def test_real_device_encryption_and_wrong_recipient(self):
        report=self.batch(); self.assertEqual(len(report['recipients']),2)
        _,expected,_=read_master(self.master)
        for n,row in enumerate(report['recipients']):
            package=Path(report['directory'])/row['filename']; manifest,cipher=read_signed(package,self.trust)
            self.assertEqual(decrypt_pro(manifest,cipher,self.devices[n]),expected)
            self.assertEqual(manifest['source_master']['id'],report['master_id'])
            self.assertEqual(row['sha256'],digest(package.read_bytes()))
            self.assertNotIn(b'class CameraSession',cipher)
            with self.assertRaisesRegex(ValueError,'不匹配'): decrypt_pro(manifest,cipher,self.devices[1-n])
        self.assertNotEqual(report['recipients'][0]['sha256'],report['recipients'][1]['sha256'])
        self.assertEqual(json.loads((Path(report['directory'])/'batch.json').read_text(encoding='utf-8')),report)

    def test_same_device_reissuance_uses_fresh_randomness(self):
        first=self.batch(); second=self.batch()
        self.assertNotEqual(first['batch_id'],second['batch_id'])
        self.assertNotEqual(first['recipients'][0]['sha256'],second['recipients'][0]['sha256'])
        self.assertEqual(first['master_id'],second['master_id'])

    def test_duplicate_configs_collapsed(self):
        _,_,devices,duplicates=preflight(self.master,[*self.paths,self.paths[0]])
        self.assertEqual(len(devices),2); self.assertEqual(len(duplicates),1)

    def test_old_client_rejected_before_output(self):
        write_json(self.paths[1],dict(self.configs[1],app_version='0.9.5'))
        with self.assertRaisesRegex(ValueError,'过旧'): self.batch()
        self.assertFalse(self.output.exists())

    def test_invalid_config_rejected_before_output(self):
        for change in ({'device':'f'*64},{'api':True},{'public_key':'bad'},{'protection':'unknown'}):
            write_json(self.paths[1],dict(self.configs[1],**change))
            with self.subTest(change=change),self.assertRaises(ValueError): self.batch()
            self.assertFalse(self.output.exists())

    def test_identity_mismatch_rejected_before_output(self):
        other,_=crypto.generate_publisher(); write_json(self.trust,{'keys':{digest(other):base64.b64encode(other).decode()}})
        with self.assertRaisesRegex(ValueError,'不匹配'): self.batch()
        self.assertFalse(self.output.exists())

    def test_incomplete_batch_never_published(self):
        calls=0
        def fail_second(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2: raise OSError('simulated disk failure')
            return seal_pro(*args,**kwargs)
        with patch('publisher.issuance.seal_pro',side_effect=fail_second),self.assertRaises(OSError): self.batch()
        dirs=list(self.output.iterdir()); self.assertEqual(len(dirs),1)
        self.assertTrue(dirs[0].name.startswith('.building-')); self.assertTrue((dirs[0]/'FAILED.json').exists())
        self.assertFalse((dirs[0]/'batch.json').exists())

    def test_names_retained_and_csv_formula_neutralized(self):
        report=self.batch(labels={self.devices[0]['device']:'=1+2',self.devices[1]['device']:'张三'})
        self.assertTrue(report['recipients'][1]['filename'].startswith('张三-'))
        with (Path(report['directory'])/'分发清单.csv').open(encoding='utf-8-sig',newline='') as stream: rows=list(csv.reader(stream))
        self.assertEqual(rows[1][0],"'=1+2"); self.assertEqual(rows[2][0],'张三')

    def test_library_reuse_across_restart_and_source_removed(self):
        data=self.root/'library'; defaults={'key_path':str(self.key),'trust_path':str(self.trust),'output_dir':str(self.output)}
        studio=Studio(data,defaults); master=studio.import_master(self.master); studio.import_configs([str(p) for p in self.paths]); studio.save_settings(defaults)
        self.master.unlink()
        for path in self.paths: path.unlink()
        resumed=Studio(data); devices=[d['device'] for d in resumed.state()['devices']]
        report=resumed.issue(master['master_id'],devices)
        self.assertEqual(report['recipients'][0]['name'],'用户1')
        self.assertEqual(len(Studio(data).state()['history']),1)
        resumed.dispatch('remove_device',{'device':devices[0]})
        with self.assertRaises(ValueError): resumed.issue(master['master_id'],devices)

    def test_configuration_import_is_all_validated_before_changes(self):
        studio=Studio(self.root/'library'); self.paths[1].write_text('{}')
        with self.assertRaises(ValueError): studio.import_configs([str(p) for p in self.paths])
        self.assertFalse((studio.data/'devices').exists())

    def test_existing_portable_096_client_imports_new_master_package(self):
        runtime=ROOT/'dist/BlitzCamera-0.9.6-beta-release/runtime/python.exe'
        if not runtime.exists(): self.skipTest('Existing 0.9.6 portable baseline is not available')
        report=self.batch(); package=Path(report['directory'])/report['recipients'][0]['filename']
        devicefile=self.root/'device.json'; write_json(devicefile,self.devices[0])
        script='''import json,sys
from pathlib import Path
from blitzcam import __version__
from blitzcam.deployment import Deployment
from blitzcam.game_backend import GameBackend
from blitzcam.offline_updater import write_json
root=Path(sys.argv[4]); manager=Deployment(root/'output',root=root,trust=Path(sys.argv[2]))
write_json(manager.directory/'device.json',json.loads(Path(sys.argv[3]).read_text()))
preview=manager.inspect(sys.argv[1]); result=manager.install(preview['token'])
assert result['edition']=='pro'
assert hasattr(GameBackend(manager).module('playback'),'PositionPlayback')
print(json.dumps({'version':__version__,'edition':result['edition']}))
'''
        result=subprocess.run([str(runtime),'-X','utf8','-B','-c',script,str(package),str(self.trust),str(devicefile),str(self.root/'client')],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'version':'0.9.6-beta','edition':'pro'})


if __name__=='__main__': unittest.main()
