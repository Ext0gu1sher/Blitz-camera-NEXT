"""Independent complete camera timelines stored alongside the active trajectory."""
from copy import deepcopy
import hashlib
import json
import re

MAX_CAMERAS = 16


def _text(value, label, identifier=False):
    if not isinstance(value, str) or not value.strip() or len(value) > (64 if identifier else 80):
        raise ValueError(f'{label}需为 1–{64 if identifier else 80} 个字符。')
    if identifier and not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError(f'{label}格式无效。')
    return value.strip()


def camera_settings(project):
    result = {key: deepcopy(getattr(project, key)) for key in ('replay_speed', 'easing', 'position_interpolation')}
    if project.replay_timeline:
        result['work_range'] = {key: project.replay_timeline[key] for key in ('work_start_sec', 'work_end_sec')}
    return result


def camera_project(project, camera):
    from .project import validate_project
    data = project.to_dict()
    data.pop('multicam', None)
    data['camera_tracks'] = deepcopy(camera.get('camera_tracks'))
    data['keyframes'] = deepcopy(camera.get('keyframes', []))
    for key in ('replay_speed', 'easing', 'position_interpolation'):
        if key in camera:
            data[key] = deepcopy(camera[key])
    if 'work_range' in camera:
        work = camera['work_range']
        if not isinstance(work, dict) or set(work) != {'work_start_sec', 'work_end_sec'} or not data.get('replay_timeline'):
            raise ValueError('机位工作区格式无效。')
        data['replay_timeline'] = {**data['replay_timeline'], **work}
    return validate_project(data)


def _migrate(value):
    """Flatten the previous prototype without discarding any camera."""
    shots = value.get('shots')
    if not isinstance(shots, list) or not shots or len(shots) > 32:
        raise ValueError('旧版多机位数据格式无效。')
    result = {'version': 2, 'active_camera_id': None, 'cameras': []}
    seen = set()
    for shot in shots:
        if not isinstance(shot, dict) or not isinstance(shot.get('cameras'), list) or not shot['cameras']:
            raise ValueError('旧版多机位数据格式无效。')
        sid = _text(shot.get('id'), '旧版分组标识', True)
        if sid in seen:
            raise ValueError('旧版分组标识不能重复。')
        seen.add(sid)
        ids = set()
        for source in shot['cameras']:
            if not isinstance(source, dict):
                raise ValueError('机位格式无效。')
            cid = _text(source.get('id'), '机位标识', True)
            if cid in ids:
                raise ValueError('机位标识不能重复。')
            ids.add(cid)
            identity = hashlib.sha256((sid + '/' + cid).encode()).hexdigest()[:32]
            camera = {**deepcopy(source), 'id': identity,
                      'work_range': {'work_start_sec': shot.get('start_sec'), 'work_end_sec': shot.get('end_sec')}}
            if len(shots) > 1:
                camera['name'] = (str(shot.get('name', '')) + ' · ' + str(source.get('name', '')))[:80]
            result['cameras'].append(camera)
            if sid == value.get('active_shot_id') and cid == shot.get('active_camera_id'):
                result['active_camera_id'] = identity
        if shot.get('active_camera_id') not in ids:
            raise ValueError('旧版当前机位不存在。')
    if len(result['cameras']) > MAX_CAMERAS:
        raise ValueError('旧版项目超过 16 个机位，无法自动转换；原文件未修改。')
    return result


def validate_multicam(value, project):
    from .channels import track_controls
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] not in (1, 2):
        raise ValueError('多机位数据格式无效。')
    if value['version'] == 1:
        value = _migrate(value)
    cameras = value.get('cameras')
    if not isinstance(cameras, list) or len(cameras) > MAX_CAMERAS:
        raise ValueError('每个项目最多支持 16 个机位。')
    active = value.get('active_camera_id')
    if cameras:
        active = _text(active, '当前机位标识', True)
    elif active is not None or project.keyframes:
        raise ValueError('无机位时不能包含当前机位或关键帧。')
    result = {'version': 2, 'active_camera_id': active, 'cameras': []}
    ids = set()
    slots = set()
    for source in cameras:
        if not isinstance(source, dict):
            raise ValueError('机位格式无效。')
        camera = {'id': _text(source.get('id'), '机位标识', True), 'name': _text(source.get('name'), '机位名称')}
        if camera['id'] in ids:
            raise ValueError('机位标识不能重复。')
        ids.add(camera['id'])
        slot = source.get('slot')
        if slot is not None:
            if type(slot) is not int or not 0 <= slot < MAX_CAMERAS:
                raise ValueError('机位槽位需为 0–15 的整数。')
            if slot in slots:
                raise ValueError('机位槽位不能重复。')
            slots.add(slot)
            camera['slot'] = slot
        checked = project if camera['id'] == active else camera_project(project, source)
        camera.update(camera_tracks=track_controls(checked), keyframes=checked.to_dict()['keyframes'], **camera_settings(checked))
        result['cameras'].append(camera)
    if cameras and active not in ids:
        raise ValueError('当前机位不存在。')
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 1800000:
        raise ValueError('多机位项目过大，请减少机位或关键帧。')
    return result


def alternatives(project):
    value = getattr(project, 'multicam', None)
    return {c['id']: camera_project(project, c) for c in value['cameras']} if value else {}
