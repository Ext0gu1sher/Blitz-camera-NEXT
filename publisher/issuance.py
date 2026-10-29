"""Preflight all recipients, then publish a complete auditable batch atomically."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.packages import API, digest, unbase64, read_signed
from blitzcam.offline_updater import write_json
from tools.publish_updates import seal_pro, signing_keys
from .master import read_json, read_master, version_key


def device_config(path):
    value = read_json(path, limit=64*1024)
    if not isinstance(value,dict) or value.get('format') != 'blitz-camera-device-v1' or type(value.get('api')) is not int or value['api'] != API:
        raise ValueError('配置格式不兼容，请从客户端重新导出。')
    public = unbase64(value.get('public_key'))
    if crypto.validate_public(public) != value.get('device'):
        raise ValueError('配置的设备标识与公钥不一致。')
    version_key(value.get('app_version'))
    if value.get('protection') not in ('tpm','windows-user'):
        raise ValueError('配置的密钥保护类型无效。')
    return {k:value[k] for k in ('format','api','app_version','device','public_key','protection')}


def preflight(master, configurations):
    manifest, files, checks = read_master(master)
    if not 1 <= len(configurations) <= 1000:
        raise ValueError('请选择 1 至 1000 份设备配置。')
    unique, duplicates = {}, []
    for path in configurations:
        value = device_config(path)
        if version_key(value['app_version']) < version_key(manifest['release']['host_min_version']):
            raise ValueError(Path(path).name + ' 的主程序版本过旧，请先升级并重新导出配置。')
        if value['device'] in unique:
            duplicates.append(str(path)); continue
        unique[value['device']] = (Path(path), value)
    return manifest, files, list(unique.values()), duplicates


def issue(master, configurations, output, key, trust, *, labels=None):
    manifest, files, recipients, duplicates = preflight(master, configurations)
    public, private = signing_keys(key, trust)
    root = Path(output).resolve(); root.mkdir(parents=True,exist_ok=True)
    batch_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:10]
    temporary = root/('.building-'+batch_id); temporary.mkdir()
    final = root/batch_id
    release, rows = manifest['release'], []
    try:
        for source, config in recipients:
            display = (labels or {}).get(config['device'], source.stem)
            label = re.sub(r'[^\w\-.\u4e00-\u9fff]+', '-', display).strip('.-')[:50] or 'device'
            filename = label+'-'+config['device'][:24]+'.bcupdate'
            destination = temporary/filename
            if destination.exists():
                raise ValueError('输出文件名冲突，请调整配置名称。')
            package = seal_pro(files, config, destination, version=release['version'], public=public, private=private,
                               game_sha256=release['client']['sha256'], notes=release['notes'],
                               metadata={'id':manifest['master_id'], 'adapter_id':release['adapter_id'],
                                         'host_min_version':release['host_min_version'], 'client':release['client']})
            verified, _ = read_signed(destination, trust)
            if verified['id'] != package['id']:
                raise ValueError('生成后的包验证失败。')
            rows.append({'config':source.name, 'name':display, 'device':config['device'], 'protection':config['protection'],
                         'filename':filename, 'package_id':package['id'], 'sha256':digest(destination.read_bytes()),
                         'bytes':destination.stat().st_size})
        report = {'format':'blitz-camera-issuance-v1','batch_id':batch_id,
                  'created_at':datetime.now(timezone.utc).isoformat(), 'master_id':manifest['master_id'],
                  'adapter_id':release['adapter_id'], 'version':release['version'], 'client':release['client'],
                  'signer':digest(public), 'recipients':rows, 'duplicates_skipped':len(duplicates), 'directory':str(final)}
        write_json(temporary/'batch.json', report)
        with (temporary/'分发清单.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer = csv.writer(stream); writer.writerow(['配置','设备标识','适配版本','分发文件','SHA-256','字节数'])
            for row in rows:
                # Neutralize spreadsheet formulas in user-supplied filenames.
                label = row['name']; label = "'"+label if label[:1] in ('=','+','-','@','\t','\r') else label
                writer.writerow([label,row['device'],release['version'],row['filename'],row['sha256'],row['bytes']])
        temporary.replace(final)
        return dict(report, directory=str(final))
    except BaseException:
        # Incomplete files remain clearly separated from deliverable batches.
        write_json(temporary/'FAILED.json', {'batch_id':batch_id,'completed':False,'message':'未完成的批次，请勿分发。'})
        raise
