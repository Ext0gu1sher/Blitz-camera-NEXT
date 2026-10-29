"""Real CNG regression for delayed delivery, folder changes and restarts."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.deployment import Deployment
from blitzcam.device_store import shared_profile_root
from blitzcam.offline_updater import write_json
from blitzcam.packages import digest
from tools.publish_updates import build_pro

ROOT=Path(__file__).resolve().parents[1]
HASH='5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608'


@unittest.skipUnless(os.name=='nt','Windows CNG')
class DevicePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public,cls.private=crypto.generate_publisher();cls.devices=[]
        for _ in range(2):
            name='BlitzCamera-'+uuid4().hex;provider='Microsoft Software Key Storage Provider'
            public=crypto.device_public(name,provider,create=True)
            cls.devices.append({'device':digest(public),'key_name':name,'provider':provider})

    @staticmethod
    def delete_key(value):
        with crypto.device_key(value['key_name'],value['provider']) as (dll,key):
            crypto._check(crypto._fn(dll,'NCryptDeleteKey',[crypto.HANDLE,crypto.U32])(key,0),'清理测试密钥');key.value=0

    @classmethod
    def tearDownClass(cls):
        for value in cls.devices: cls.delete_key(value)

    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.profile=self.root/'account';self.trust=self.root/'trust.json'
        write_json(self.trust,{'keys':{digest(self.public):base64.b64encode(self.public).decode()}})
        self.first=self.manager('first')
        write_json(self.first.directory/'device.json',self.devices[0])
        self.config=self.root/'original.bcconfig';self.first.export_config(self.config)
        self.package=self.root/'original.bcupdate';self.make(self.package,'11.21-r1')

    def manager(self, name, *, profile=None):
        root=self.root/name
        return Deployment(root/'output',root=root,trust=self.trust,profile_root=profile or self.profile)

    def make(self,path,version):
        return build_pro(ROOT/'blitzcam',self.config,path,version=version,public=self.public,private=self.private,game_sha256=HASH)

    def install(self,manager,path=None):
        selected=manager.inspect(path or self.package);return manager.install(selected['token'])

    def test_close_wait_deliver_to_another_folder_without_exporting_again(self):
        os.utime(self.config,(1000000000,1000000000))
        reopened=self.manager('second')
        self.assertFalse(reopened.enabled)
        with patch.object(reopened,'export_config',side_effect=AssertionError('must not export again')):
            self.assertEqual(self.install(reopened)['edition'],'pro')
        third=self.manager('third')
        self.assertTrue(third.enabled)
        self.assertEqual(third.manifest['version'],'11.21-r1')
        next_config=self.root/'next.bcconfig';third.export_config(next_config)
        self.assertEqual(json.loads(next_config.read_text(encoding='utf-8')),json.loads(self.config.read_text(encoding='utf-8')))

    def test_native_key_recovery_without_any_json_registration(self):
        for p in (self.profile/'device.json',self.profile/'devices'/(self.devices[0]['device']+'.json'),self.first.directory/'device.json'): p.unlink()
        reopened=self.manager('new-install')
        self.assertFalse((reopened.directory/'device.json').exists())
        original=crypto.device_public
        def no_creation(name,provider,**kw):
            self.assertFalse(kw.get('create',False),'recovery must not rotate device keys')
            return original(name,provider,**kw)
        with patch.object(crypto,'device_public',side_effect=no_creation): self.install(reopened)
        self.assertTrue(self.manager('after-recovery').enabled)
        self.assertEqual(reopened.device()[0]['device'],self.devices[0]['device'])

    def test_legacy_activation_migrates_and_survives_local_folder_data_loss(self):
        write_json(self.first.directory/'device.json',self.devices[0])
        (self.first.directory/'active.bcupdate').write_bytes(self.package.read_bytes())
        migrated=self.manager('first');self.assertTrue(migrated.enabled)
        for name in ('device.json','active.bcupdate'): (self.first.directory/name).unlink()
        self.assertTrue(self.manager('third').enabled)

    def test_old_install_cannot_replace_newer_shared_activation(self):
        newer=self.root/'new.bcupdate';self.make(newer,'11.21-r2');self.install(self.first,newer)
        oldroot=self.root/'old/output/deployment';write_json(oldroot/'device.json',self.devices[0])
        (oldroot/'active.bcupdate').write_bytes(self.package.read_bytes())
        self.assertEqual(self.manager('old').manifest['version'],'11.21-r2')

    def test_broken_shared_activation_does_not_resurrect_local_stale_package(self):
        self.install(self.first)
        (self.profile/'active.bcupdate').write_bytes(b'broken')
        reopened=self.manager('first')
        self.assertFalse(reopened.enabled);self.assertTrue(reopened.error)

    def test_old_configuration_can_be_imported_without_rotating_export_identity(self):
        other=self.root/'other-account';write_json(other/'device.json',self.devices[1])
        manager=self.manager('other',profile=other)
        self.install(manager)
        self.assertEqual(manager.device()[0],self.devices[1])
        self.assertEqual(manager.manifest['device'],self.devices[0]['device'])
        self.assertTrue(self.manager('reopen-other',profile=other).enabled)

    def test_missing_private_key_is_rejected_without_generating_new_identity(self):
        manager=self.manager('foreign',profile=self.root/'foreign-account')
        with patch.object(crypto,'stored_key_names',return_value=[]),self.assertRaisesRegex(ValueError,'当前 Windows 用户'):
            manager.inspect(self.package)
        self.assertFalse((manager.profile/'device.json').exists())
        self.assertFalse((manager.profile/'active.bcupdate').exists())

    def test_export_identity_recovers_stable_key_after_metadata_loss(self):
        manager=self.manager('fresh',profile=self.root/'stable-account')
        cfg=self.root/'stable.bcconfig';manager.export_config(cfg);value=manager.device()[0]
        self.addCleanup(self.delete_key,value)
        (manager.profile/'device.json').unlink();(manager.profile/'devices'/(value['device']+'.json')).unlink()
        reopened=self.manager('moved',profile=manager.profile)
        reopened.export_config(self.root/'stable-again.bcconfig')
        self.assertEqual(reopened.device()[0],value)

    def test_profile_path_is_independent_of_install_and_supports_test_override(self):
        with patch.dict(os.environ,{'BLITZCAM_PROFILE_ROOT':str(self.profile)}):
            self.assertEqual(shared_profile_root(),self.profile)
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'local')}):
            with patch.dict(os.environ):
                os.environ.pop('BLITZCAM_PROFILE_ROOT',None)
                self.assertEqual(shared_profile_root(),self.root/'local/BlitzCamera/deployment')


if __name__=='__main__':unittest.main()
