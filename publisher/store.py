"""Local library of immutable masters and reusable public device configs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from blitzcam.offline_updater import write_json
from blitzcam.packages import digest
from .master import inspect_master, create_master, read_json
from .issuance import device_config, preflight, issue
from tools.publish_updates import signing_keys, backup_key, restore_key


class Studio:
    def __init__(self, data, defaults=None):
        self.data = Path(data).resolve(); self.data.mkdir(parents=True,exist_ok=True)
        self.defaults = defaults or {}

    def settings(self):
        value = dict(self.defaults)
        path = self.data/'settings.json'
        if path.exists(): value.update(read_json(path))
        return value

    def save_settings(self, values):
        allowed = ('key_path','trust_path','output_dir','recipe_path','master_hint')
        current = self.settings()
        for key,value in values.items():
            if key not in allowed or not isinstance(value,str) or len(value)>2000:
                raise ValueError('设置字段无效。')
            current[key] = value
        write_json(self.data/'settings.json', current)
        return current

    def index(self, name):
        path = self.data/(name+'.json')
        return read_json(path, limit=64*1024*1024) if path.exists() else []

    def master_path(self, identity):
        if not re.fullmatch('[0-9a-f]{64}', str(identity)):
            raise ValueError('母包标识无效。')
        return self.data/'masters'/(identity+'.bcpro')

    def config_path(self, identity):
        if not re.fullmatch('[0-9a-f]{64}', str(identity)):
            raise ValueError('设备标识无效。')
        return self.data/'devices'/(identity+'.bcconfig')

    def import_master(self, path):
        value = inspect_master(path)
        current = self.index('masters')
        if any(m['adapter_id']==value['adapter_id'] and m['version']==value['version'] and m['master_id']!=value['master_id'] for m in current):
            raise ValueError('同一适配版本已存在不同内容。请增加修订号后重新制作，避免混淆已发出的包。')
        target = self.master_path(value['master_id']); target.parent.mkdir(exist_ok=True)
        if Path(path).resolve() != target:
            temporary = target.with_name('.import-'+uuid4().hex)
            try:
                shutil.copyfile(path, temporary)
                snapshot = inspect_master(temporary)
                if snapshot['sha256'] != value['sha256']:
                    raise ValueError('读取期间母包发生变化，请重新导入。')
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        value['path'] = str(target)
        value['imported_at'] = datetime.now(timezone.utc).isoformat()
        current = [m for m in current if m['master_id'] != value['master_id']]
        write_json(self.data/'masters.json', [value,*current])
        return value

    def import_configs(self, paths):
        if not isinstance(paths,list) or not 1<=len(paths)<=1000:
            raise ValueError('请选择 1 至 1000 份配置。')
        # Validate the whole selection before modifying the public-key library.
        parsed = [(Path(p),device_config(p)) for p in paths]
        current = {d['device']:d for d in self.index('devices')}
        for path,value in parsed:
            target = self.config_path(value['device']); target.parent.mkdir(exist_ok=True)
            write_json(target,value)
            current[value['device']] = {'device':value['device'],'name':path.stem,
                                       'app_version':value['app_version'],'protection':value['protection']}
        write_json(self.data/'devices.json', list(current.values()))
        return list(current.values())

    def issue(self, identity, devices):
        if not isinstance(devices,list) or len(devices)!=len(set(devices)):
            raise ValueError('设备选择无效。')
        known = {d['device']:d for d in self.index('devices')}
        if any(d not in known for d in devices):
            raise ValueError('选中的设备已从配置库移除。')
        settings = self.settings()
        master = self.master_path(identity)
        report = issue(master, [self.config_path(d) for d in devices], settings['output_dir'],
                       settings['key_path'], settings['trust_path'], labels={d:known[d]['name'] for d in devices})
        # Keep recipient names in the batch and local history, not the signed
        # executable package. Outputs can be mapped back even after source edits.
        write_json(self.data/'history.json', [report,*self.index('history')])
        return report

    def state(self):
        settings = self.settings()
        if not self.index('masters') and settings.get('master_hint') and Path(settings['master_hint']).is_file():
            self.import_master(settings['master_hint'])
        return {'settings':settings, 'masters':self.index('masters'), 'devices':self.index('devices'),
                'history':self.index('history')[:100]}

    def dispatch(self, action, value):
        if action=='state': return self.state()
        if action=='settings': return self.save_settings(value)
        if action=='import_master': return self.import_master(value['path'])
        if action=='import_configs': return self.import_configs(value['paths'])
        if action=='inspect': return inspect_master(self.master_path(value['master_id']))
        if action=='create':
            result = create_master(value['recipe'],value['output'])
            return self.import_master(result['path'])
        if action=='check':
            m,_,devices,duplicates = preflight(self.master_path(value['master_id']),[self.config_path(d) for d in value['devices']])
            settings = self.settings(); public,_ = signing_keys(settings['key_path'],settings['trust_path'])
            return {'count':len(devices),'version':m['release']['version'],'signer':digest(public),'duplicates':len(duplicates)}
        if action=='issue': return self.issue(value['master_id'],value['devices'])
        if action=='remove_device':
            identity = value['device']; self.config_path(identity)
            rows = [d for d in self.index('devices') if d['device']!=identity]
            write_json(self.data/'devices.json',rows)
            return rows
        if action=='verify_key':
            settings = self.settings(); public,_ = signing_keys(settings['key_path'],settings['trust_path'])
            return {'signer':digest(public),'message':'发布密钥可用，与当前客户端公钥一致。'}
        if action=='backup_key':
            settings = self.settings(); backup_key(settings['key_path'],settings['trust_path'],value['path'],value['password'])
            return {'message':'加密备份已保存，请将口令与备份分开保管。'}
        if action=='restore_key':
            settings = self.settings(); restore_key(value['path'],settings['key_path'],settings['trust_path'],value['password'])
            return {'message':'发布密钥已恢复。'}
        raise ValueError('不支持的制作工具操作。')
