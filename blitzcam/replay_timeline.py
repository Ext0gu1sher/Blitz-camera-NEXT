"""Absolute replay timestamps and bounded playback windows. No game writes."""
from copy import deepcopy
import hashlib
import math
import json
import zipfile
from pathlib import Path


def validate_timeline(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('time_basis') != 'replay':
        raise ValueError('时间轴需使用对局绝对时间。')
    result = {'time_basis':'replay'}
    if 'starter_keyframes_pending' in value:
        if type(value['starter_keyframes_pending']) is not bool:
            raise ValueError('默认关键帧初始化标记无效。')
        if value['starter_keyframes_pending']:
            result['starter_keyframes_pending'] = True
    for name in ('duration_sec','work_start_sec','work_end_sec'):
        x = value.get(name)
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not 0 <= x <= 3600:
            raise ValueError('全片长度和工作区间需为 0–3600 秒的有效时间。')
        result[name] = float(x)
    if not 0 <= result['work_start_sec'] < result['work_end_sec'] <= result['duration_sec']:
        raise ValueError('工作区间需满足：0 ≤ 入点 < 出点 ≤ 全片长度。')
    if 'replay_file' in value:
        if not isinstance(value['replay_file'],str) or len(value['replay_file']) > 32768:
            raise ValueError('回放文件路径无效。')
        result['replay_file'] = value['replay_file']
    if 'replay_sha256' in value:
        digest = value['replay_sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdefABCDEF' for c in digest):
            raise ValueError('回放文件内容标识无效。')
        result['replay_sha256'] = digest.lower()
    for name in ('battle_start_sec', 'battle_start_raw_sec', 'replay_origin_sec'):
        if name in value:
            x = value[name]
            if x is not None and (isinstance(x, bool) or not isinstance(x, (int, float))
                                  or not math.isfinite(x) or not 0 <= x <= 3600):
                raise ValueError('比赛开始时间需为 0–3600 秒的有效时间。')
            result[name] = float(x) if x is not None else None
    if 'battle_start_status' in value:
        if value['battle_start_status'] not in ('identified', 'unavailable'):
            raise ValueError('比赛开始事件识别状态无效。')
        result['battle_start_status'] = value['battle_start_status']
    if 'battle_start_reason' in value:
        reason = value['battle_start_reason']
        if not isinstance(reason, str) or len(reason) > 2048:
            raise ValueError('比赛开始事件说明无效。')
        result['battle_start_reason'] = reason
    return result


def replay_digest(path):
    """Content identity survives copying, renaming and filesystem timestamps."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def replay_matches(bound, actual):
    """Prefer content; keep path matching only for legacy, unreadable sources."""
    expected = bound.get('replay_sha256')
    if not expected:
        try:
            expected = replay_digest(bound['replay_file'])
        except OSError:
            pass
    if expected:
        observed = actual.get('replay_sha256')
        if not observed:
            try:
                observed = replay_digest(actual['replay_file'])
            except OSError:
                return False
        return expected == observed
    return Path(bound['replay_file']).resolve() == Path(actual['replay_file']).resolve()


def file_timeline(path):
    """Read bounded metadata and the explicit BATTLE event, then hash the file."""
    from .replay_events import replay_battle_start
    path = Path(path)
    if path.suffix.lower() != '.wotbreplay' or not path.is_file():
        raise ValueError('请选择有效的 .wotbreplay 回放文件。')
    try:
        with zipfile.ZipFile(path) as archive:
            entries = [e for e in archive.infolist() if e.filename == 'meta.json']
            if len(entries)!=1 or entries[0].file_size>65536 or entries[0].flag_bits & 1:
                raise ValueError('回放元数据不存在或超过读取上限。')
            with archive.open(entries[0]) as stream:
                raw=stream.read(65537)
            if len(raw)>65536:
                raise ValueError('回放元数据超过读取上限。')
            meta=json.loads(raw.decode('utf-8-sig'))
            start = replay_battle_start(archive, meta.get('version', '') if isinstance(meta, dict) else '')
    except zipfile.BadZipFile as exc:
        raise ValueError('回放文件不是可读取的回放压缩包，或元数据已损坏。') from exc
    duration=meta.get('battleDuration') if isinstance(meta,dict) else None
    if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 0<duration<=3600:
        raise ValueError('回放未提供有效的 battleDuration，需手动设置全片长度。')
    if start['battle_start_sec'] is not None and start['battle_start_sec'] > duration:
        start.update(battle_start_status='unavailable', battle_start_sec=None,
                     battle_start_reason='比赛开始事件超出回放长度，请在设置中手动填写赛前片段长度。')
    return {**start, 'duration_sec':float(duration),'replay_file':str(path.resolve()),'replay_sha256':replay_digest(path),'name':path.name,
            'source':'replay_metadata','version':str(meta.get('version',''))}


def replay_keyframe_guard(timeline, settings, metadata=None):
    """Resolve an editor-clock boundary from a saved event or manual setting."""
    from .settings import keyframe_start_seconds
    if not timeline or not timeline.get('replay_file'):
        return {'enabled': False, 'start_sec': None, 'source': 'unbound', 'status': 'unbound', 'message': ''}
    manual = keyframe_start_seconds((settings or {}).get('replay_keyframe_start_seconds'))
    if manual is not None:
        return {'enabled': True, 'start_sec': manual, 'source': 'manual', 'status': 'manual',
                'message': f'比赛开始：{manual:.3f} 秒（手动）；此前不能设置入点或添加、移动摄像机关键帧。'}
    info = metadata if metadata is not None else timeline
    start = info.get('battle_start_sec')
    if (info.get('battle_start_status') == 'identified' and not isinstance(start, bool)
            and isinstance(start, (float, int)) and math.isfinite(start) and 0 <= start <= 3600):
        return {'enabled': True, 'start_sec': float(start), 'source': 'replay_event', 'status': 'identified',
                'message': f'已从回放读取比赛开始：{start:.3f} 秒；此前不能设置入点或添加、移动摄像机关键帧。'}
    return {'enabled': True, 'start_sec': None, 'source': 'unavailable', 'status': 'unavailable',
            'message': info.get('battle_start_reason') or '未识别到比赛开始事件，请在设置中手动填写赛前片段长度后设置入点或添加关键帧。'}


def validate_work_start(timeline, settings, metadata=None):
    guard = replay_keyframe_guard(timeline, settings, metadata)
    if not guard['enabled']:
        return
    if guard['start_sec'] is None:
        raise ValueError('比赛开始时间尚未解析，请在设置中填写赛前片段长度后设置入点。')
    if timeline['work_start_sec'] < guard['start_sec'] - 1e-6:
        raise ValueError(f'入点不能早于比赛开始（{guard["start_sec"]:.3f} 秒）。')


def validate_new_keyframes(previous, candidate, settings, metadata=None):
    """Validate changed in-points and new camera times; retain legacy data."""
    if candidate.shooting_mode == 'camera_only':
        return
    old_timeline, timeline = previous.replay_timeline, candidate.replay_timeline
    # Old projects may contain an early range. Preserve unrelated edits while
    # requiring every newly authored in-point to respect the current boundary.
    if timeline and (not old_timeline or timeline['work_start_sec'] != old_timeline['work_start_sec']):
        validate_work_start(timeline, settings, metadata)
    from .channels import track_controls
    guard = replay_keyframe_guard(candidate.replay_timeline, settings, metadata)
    if not guard['enabled']:
        return
    old, new = track_controls(previous), track_controls(candidate)
    for channel, rows in new.items():
        existing = {row['time_sec'] for row in old[channel]}
        for row in rows:
            when = row['time_sec']
            if when not in existing and (guard['start_sec'] is None or when < guard['start_sec'] - 1e-6):
                raise ValueError(guard['message'])


def session_timeline(session):
    # Prefer the file actually owned by ReplayPlayer. Steam handoffs and opening
    # a replay inside an existing client need not leave a filename in argv.
    from .replay_map import launch_replay_path
    from .replay_launcher import ReplaySourceUnavailable
    from .replay_source import supports_runtime_source, runtime_replay_source
    from .profile import CameraError
    try:
        if supports_runtime_source(session):
            before = runtime_replay_source(session)
            result = file_timeline(before.path)
            if (runtime_replay_source(session) != before or
                    result['version'] not in (before.version, before.client_version)):
                raise ValueError('读取期间当前回放文件已变化，请重新连接。')
            return {**result, 'source':'runtime_replay', 'verification':'runtime_replay'}
        return {**file_timeline(launch_replay_path(session.memory)), 'source':'launch_argument'}
    except (OSError, ValueError, CameraError) as exc:
        raise ReplaySourceUnavailable('暂时无法读取游戏当前的回放文件。请待回放加载稳定后重新连接。'
                                      f' 读取原因：{exc}') from exc


class PlaybackWindow:
    """Keep global evaluation intact while compiling only the selected interval."""
    def __init__(self, source, start, end):
        from .trajectory import Keyframe
        self.source, self.start_time, self.end_time = source, start, end
        self.duration=end-start
        self.replay_speed=deepcopy(source.replay_speed)
        self.replay_timeline=source.replay_timeline
        self.shooting_mode=source.shooting_mode
        times=sorted({start,end,*[t for t in source.keyframe_times() if start<t<end]})
        self.keyframes=tuple(Keyframe(t,source.sample(t)) for t in times)
    def keyframe_times(self): return [k.time_sec for k in self.keyframes]
    def sample(self,time): return self.source.sample(time)
    def to_dict(self): return {**self.source.to_dict(),'playback_window':{'start_sec':self.start_time,'end_sec':self.end_time}}


def playback_window(project, reference, reverse=False):
    from .profile import CameraError
    from .speed import mean_rate, schedule_time
    if project.shooting_mode == 'camera_only':
        # Independent wall clock. Never consult the replay timestamp or work area.
        window=PlaybackWindow(project,0.,project.end_time)
        window.replay_speed={**window.replay_speed,'mode':'paused','camera_clock':'shooting'}
        return window
    t=project.replay_timeline
    if t is None:
        return project
    if reverse and project.replay_speed['mode']!='paused':
        raise CameraError('对局时间绑定时不能倒放战斗；可使用离线预演，或在暂停运镜模式倒序播放。')
    start,end=t['work_start_sec'],t['work_end_sec']
    now=reference['replay']['time']
    if project.replay_speed['mode']!='paused':
        # Start from the actual paused timestamp, never shift authored keys to it.
        if not start-.05<=now<end:
            raise CameraError(f'当前回放 {now:.3f} 秒不在工作区间 {start:.3f}–{end:.3f} 秒内。入点前可直接播放；到达出点后请先跳转到入点。')
        start=now
    if 0<end-start<.5:
        raise ValueError('距离工作区出点不足 0.5 秒，剩余区间太短，无法续播。')
    if not .5<=end-start<=120:
        raise ValueError('整场回放可编辑；单次播放工作区间需为 0.5–120 秒。')
    window=PlaybackWindow(project,start,end)
    speed=project.replay_speed
    if speed['mode']!='paused' and speed['camera_clock']=='replay':
        bounds=speed.get('time_range') if speed['mode']=='curve' else None
        original=bounds['start_sec'] if bounds else t['work_start_sec']
        original_end=bounds['end_sec'] if bounds else end
        total=(original_end-original)/mean_rate(speed)
        offset=schedule_time(speed,start,original,original_end)
        finish=schedule_time(speed,end,original,original_end)
        window.speed_schedule=(total,offset)
        window.shooting_seconds=finish-offset
    return window
