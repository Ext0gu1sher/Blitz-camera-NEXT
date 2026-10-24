"""Loopback workstation. Reading and explicit position playback have separate APIs."""

from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import webbrowser
from uuid import uuid4

from .profile import CameraError, SessionChanged
from .project import atomic_json, controls, edit_project, read_project, samples, validate_project, recycle_project
from .reader import CameraSession
from .playback import PositionPlayback
from . import __version__
from .terrain import TerrainStore
from .channels import track_controls
from .pose import angles_from_quaternion
from .replay_timeline import file_timeline, session_timeline, playback_window, replay_matches, replay_digest
from . import replay_launcher
from .paths import OUTPUT
from .replay_preview import ReplayPreview
from .editor_state import read_editor_state, write_editor_state, editor_state_path, validate_editor_state
from .settings import read_settings, save_settings, directory_path

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"


def read_recent():
    try:
        data = json.loads((OUTPUT/'recent-projects.json').read_text(encoding='utf-8'))
        return [e for e in data if isinstance(e, dict) and isinstance(e.get('path'), str)][:20]
    except (OSError, ValueError):
        return []


def record_recent(path):
    resolved = str(Path(path).resolve())
    entries = [e for e in read_recent() if str(Path(e['path']).resolve()) != resolved]
    entries.insert(0, {'path': resolved, 'last_opened': datetime.now(timezone.utc).isoformat()})
    try:
        atomic_json(OUTPUT/'recent-projects.json', entries[:20])
    except OSError:
        pass


def forget_recent(path):
    resolved = str(Path(path).resolve())
    atomic_json(OUTPUT/'recent-projects.json', [e for e in read_recent() if str(Path(e['path']).resolve()) != resolved])


def recent_listing():
    out = []
    for entry in read_recent():
        p = Path(entry['path'])
        item = {'path': entry['path'], 'name': p.stem, 'last_opened': entry.get('last_opened'),
                'exists': p.is_file(), 'size_bytes': None, 'shooting_mode': None, 'keyframes': None, 'replay': ''}
        if item['exists']:
            try:
                item['size_bytes'] = p.stat().st_size
                data = json.loads(p.read_text(encoding='utf-8'))
                item['shooting_mode'] = data.get('shooting_mode') or 'replay'
                tracks = data.get('camera_tracks')
                item['keyframes'] = len({k['time_sec'] for rows in tracks.values() for k in rows} if tracks
                                        else {k['time_sec'] for k in data.get('keyframes', [])})
                timeline = data.get('replay_timeline') or {}
                item['replay'] = Path(timeline['replay_file']).name if timeline.get('replay_file') else ''
            except (OSError, ValueError, KeyError):
                pass
        out.append(item)
    return out


def startup_project():
    for entry in read_recent():
        p = Path(entry['path'])
        if p.is_file():
            return p
    settings=read_settings(OUTPUT)
    if settings['project_directory']!=settings['default_project_directory']:
        return Path(settings['project_directory'])/'project.json'
    return OUTPUT/'project.json'


class Workstation:
    def __init__(self, project_path):
        self.project_path = Path(project_path).resolve()
        self.project = read_project(self.project_path if self.project_path.exists() else ROOT/"examples/eight-second.json")
        self.lock, self.stop = threading.RLock(), threading.Event()
        self.session, self.sample = None, None
        self.replay_info = None
        self._keyframe_metadata_cache = {}
        self.replay_launch = {"state": "idle", "message": "可先打开游戏和回放后连接，也可从这里选择回放启动。"}
        self.replay_process = None
        self.connection = {"state": "disconnected", "message": "离线模式 · 可编辑与预演。连接只读取当前暂停的回放。"}
        self.generation = 0
        self.project_revision = 0
        self.editor_state = read_editor_state(OUTPUT, self.project_path)
        self.terrain = TerrainStore()
        self.replay_preview = ReplayPreview()
        self.selected_time = self.project.keyframes[0].time_sec
        self.desktop_process = None
        self.playback = PositionPlayback(OUTPUT/'playback-runs')
        if self.project_path.exists():
            record_recent(self.project_path)
        self.poller = threading.Thread(target=self._poll, daemon=True); self.poller.start()

    def state(self):
        with self.lock:
            return deepcopy({"connection": self.connection, "sample": self.sample,
                             "replay_info": self.replay_info,
                             "replay_launch": self.replay_launch,
                             "keyframe_guard": self.keyframe_guard(),
                             "replay_keyframe_start_seconds": read_settings(OUTPUT)['replay_keyframe_start_seconds'],
                             "project": self.project.to_dict(), "keyframe_controls": controls(self.project),
                             "camera_track_controls": track_controls(self.project),
                             "project_path": str(self.project_path), "project_name": self.project_path.stem,
                             "playback": self.playback.state(),
                             "version": __version__, "project_revision": self.project_revision,
                             "ui": {"selected_time": self.selected_time},
                             "editor_state": self.editor_state,
                             "capabilities": {"read_capture": True, "offline_preview": True,
                                              "game_write": True, "game_restore": False,
                                              "position_playback": True, "orientation_playback": True,
                                              "replay_speed": True, "linked_playback": True, "fov_playback": True, "fixed_orientation_fov": False}})

    def connect(self):
        with self.lock:
            if self.replay_launch['state'] in ('choosing', 'launching'):
                raise CameraError('请先完成回放文件选择与启动。')
            if self.connection["state"] == "connecting":
                return
            self.disconnect(); self.generation += 1; generation = self.generation
            self.connection = {"state": "connecting", "message": "核验客户端构建与回放相机引用…"}
        def worker():
            session = None
            source_error = None
            try:
                session = CameraSession.connect(); sample = session.capture()
                try: replay_info = session_timeline(session)
                except Exception as exc:
                    replay_info = None; source_error = str(exc)
            except Exception as exc:
                if session is not None:
                    session.close()
                with self.lock:
                    if generation == self.generation:
                        self.connection = {"state": "error", "message": str(exc)}
                return
            with self.lock:
                if generation != self.generation:
                    session.close(); return
                self.session, self.sample = session, sample
                launch = self.replay_launch
                source_warning = None
                # Reconnecting after a reader invalidation must recheck the
                # source and replace the old status with this attempt's result.
                if launch['state'] in ('launched', 'invalidated'):
                    try:
                        verification = replay_launcher.verify_launch_source(session.memory.info, launch, replay_info, source_error)
                        replay_info = {**launch['info'], **replay_info,
                                       'source':'blitz_camera', 'verification': verification['verification']}
                        launch.pop('source_error', None)
                        launch.update(state='launched', verified=True, source_state='verified', **verification,
                                      message='已核对本次打开的回放文件 · 只读连接。')
                    except replay_launcher.ReplaySourceUnavailable as exc:
                        # Opening a file is a request; it is not evidence that an
                        # existing game accepted it. Keep the independently valid
                        # camera, without promoting the selected file to verified.
                        source_warning = '当前回放文件暂未识别；请等待回放加载稳定后重新连接。'
                        launch.update(state='launched', verified=False, source_state='unavailable', source_error=str(exc),
                                      message='镜头已连接。' + source_warning)
                    except CameraError as exc:
                        if replay_info and replay_info.get('verification') == 'runtime_replay':
                            # Users may open a different replay themselves. A
                            # past Open request does not own the current client.
                            self.replay_launch = {'state':'idle', 'verified':False,
                                                  'message':'已连接游戏中当前打开的回放。'}
                        else:
                            launch.update(verified=False, message=str(exc))
                            session.close()
                            self.session, self.sample = None, None
                            self.connection = {'state':'error', 'message':launch['message']}
                            return
                elif replay_info is None:
                    source_warning = '当前回放文件暂未识别；请等待回放加载稳定后重新连接。'
                self.replay_info = replay_info
                timeline = self.project.replay_timeline
                if (replay_info and timeline and timeline.get('replay_file') and
                        replay_matches(timeline, replay_info)):
                    try:
                        self._bind_opened_replay(replay_info)
                    except (ValueError, OSError):
                        pass  # A read-only connection can still be used if saving fails.
                self.connection = {"state": "connected", "message": "已匹配回放自由镜头对象链 · 只读", "discovery": session.discovery_stats}
                if source_warning:
                    self.connection.update(source_warning=source_warning, source_error=source_error)
                    self.connection['message'] += '；' + source_warning
        threading.Thread(target=worker, daemon=True).start()

    def open_project_replay(self):
        with self.lock:
            timeline = deepcopy(self.project.replay_timeline)
            if not timeline or not timeline.get('replay_file'):
                raise CameraError('当前项目尚未绑定回放，请先载入回放。')
            return self.open_replay(timeline['replay_file'], expected_replay=timeline)

    def open_replay(self, path=None, *, recovery_guard=None, expected_replay=None):
        if path is not None and (not isinstance(path, str) or not path.strip() or len(path) > 32768):
            raise ValueError('回放文件路径无效。')
        with self.lock:
            if recovery_guard is not None and not recovery_guard():return False
            if self.playback.state()['active']:
                raise CameraError('请先停止镜头接管，再打开回放。')
            if self.replay_launch['state'] in ('choosing', 'launching'):
                raise CameraError('回放选择或启动尚未完成。')
            launch_id = uuid4().hex
            project_directory = self.project_path.parent
            project_revision = self.project_revision
            self.replay_launch = {'id': launch_id, 'state': 'choosing', 'verified': False,
                                  'message': '请选择本地回放文件…' if path is None else '正在检查回放文件…'}
        def worker():
            try:
                executable = replay_launcher.locate_client()
                selected = replay_launcher.choose_replay() if path is None else Path(path)
                if expected_replay is not None and selected is not None and not selected.is_file():
                    # A project and its replay can travel together. Only choose
                    # a nearby file automatically when its saved hash matches.
                    nearby = project_directory/selected.name
                    if (expected_replay.get('replay_sha256') and nearby.is_file() and
                            replay_matches(expected_replay, {'replay_file': str(nearby)})):
                        selected = nearby
                    else:
                        with self.lock:
                            self.replay_launch['message'] = '回放位置已改变，请选择这台电脑上的同一份回放。'
                        selected = replay_launcher.choose_replay()
                if selected is None:
                    with self.lock:
                        self.replay_launch.update(state='cancelled', message='已取消选择，游戏和项目未改变。')
                    return
                info = {**file_timeline(selected), 'source': 'blitz_camera', 'launch_id': launch_id}
                if (expected_replay is not None and
                        (expected_replay.get('replay_sha256') or Path(expected_replay['replay_file']).is_file()) and
                        not replay_matches(expected_replay, info)):
                    raise ValueError('所选文件与项目保存的回放内容不同，请选择同一份回放。')
                with self.lock:
                    if self.stop.is_set():
                        return
                    if recovery_guard is not None and not recovery_guard():
                        self.replay_launch.update(state='cancelled', message='连接或项目已改变，已取消自动重新启动。')
                        return
                    if self.playback.state()['active']:
                        raise CameraError('镜头接管仍在运行，请先停止。')
                    if expected_replay is not None and project_revision != self.project_revision:
                        raise CameraError('项目已改变，请重新打开当前项目的回放。')
                    self.replay_launch.update(state='launching', info=info, message='正在启动游戏并打开所选回放…')
                    self.disconnect()
                    process = replay_launcher.launch_replay(executable, info['replay_file'])
                    self.replay_process = process
                    self.replay_info = info
                    self.replay_launch.update(state='launched', pid=process.pid, executable=str(executable),
                        message='已启动所选回放。进入游戏后切到自由镜头并暂停，再点击连接回放。')
                    try:
                        self._bind_opened_replay(info)
                    except (ValueError, OSError) as exc:
                        self.replay_launch['message'] += f' 时间轴未改动：{exc} 连接后可从当前属性新建动画。'
            except Exception as exc:
                with self.lock:
                    self.replay_launch.update(state='error', message=str(exc))
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _bind_opened_replay(self, info):
        """Bind source/length only; preserve every authored camera timestamp."""
        data = deepcopy(self.project.to_dict())
        duration = info['duration_sec']
        timeline = deepcopy(self.project.replay_timeline) or {
            'time_basis': 'replay', 'work_start_sec': 0, 'work_end_sec': min(8, duration)}
        timeline.update(duration_sec=duration, replay_file=info['replay_file'])
        for name in ('battle_start_sec', 'battle_start_raw_sec', 'replay_origin_sec', 'battle_start_status', 'battle_start_reason'):
            timeline.pop(name, None)
            if name in info:
                timeline[name] = info[name]
        if info.get('replay_sha256'):
            timeline['replay_sha256'] = info['replay_sha256']
        else:
            timeline.pop('replay_sha256', None)
        if timeline['work_end_sec'] > duration:
            timeline.update(work_start_sec=0, work_end_sec=min(8, duration))
        from .replay_timeline import replay_keyframe_guard
        guard = replay_keyframe_guard(timeline, read_settings(OUTPUT), info)
        if guard['enabled'] and guard['start_sec'] is not None and timeline['work_start_sec'] < guard['start_sec'] < duration:
            if self.project.replay_speed['mode'] == 'curve' and not data['replay_speed'].get('time_range') and self.project.replay_timeline:
                data['replay_speed']['time_range'] = {'start_sec': self.project.replay_timeline['work_start_sec'], 'end_sec': self.project.replay_timeline['work_end_sec']}
            length = timeline['work_end_sec'] - timeline['work_start_sec']
            timeline['work_start_sec'] = guard['start_sec']
            if timeline['work_end_sec'] <= timeline['work_start_sec']:
                timeline['work_end_sec'] = min(duration, timeline['work_start_sec'] + length)
        data['replay_timeline'] = timeline
        project = validate_project(data)
        if project.to_dict() != self.project.to_dict():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            atomic_json(OUTPUT/'project-history'/f'{stamp}.json', self.project.to_dict())
            self.set_project(project)

    def disconnect(self):
        self.playback.stop(wait=True)
        with self.lock:
            self.generation += 1
            if self.session:
                self.session.close()
            self.session, self.sample = None, None
            self.replay_info = None
            self.replay_launch['verified'] = False
            self.connection = {"state": "disconnected", "message": "已断开实机读取，离线项目仍可编辑。"}

    def _poll(self):
        while not self.stop.wait(0.2):
            with self.lock:
                if self.session is None or self.playback.state().get('preparing_replay'):
                    continue
                try:
                    self.sample = self.session.capture(require_paused=False)
                    self.connection["message"] = "已匹配回放自由镜头对象链 · 只读"
                    if self.connection.get('source_warning'):
                        self.connection['message'] += '；' + self.connection['source_warning']
                except SessionChanged as exc:
                    if self.playback.state().get('replay_recovery_pending'):
                        # Leave the seek's exit-only observer alive while Windows
                        # finishes tearing down a crashing process. An explicit
                        # reconnect/disconnect still cancels that observer.
                        self.sample = None
                        self.connection.update(state='error', message=str(exc))
                        continue
                    self.disconnect()
                    if self.replay_launch.get('info'):
                        self.replay_launch.update(verified=False, state='invalidated',
                            message='回放对象已改变，本次文件关联已失去核对。请退出游戏后从 Blitz Camera 重新打开回放。')
                    self.connection = {"state": "error", "message": str(exc)}
                except CameraError as exc:
                    self.sample = None; self.connection["message"] = str(exc)
                except Exception as exc:
                    self.disconnect()
                    self.connection = {"state": "error", "message": f"读取已停止：{exc}"}

    def check_revision(self, expected):
        if expected is not None and (type(expected) is not int or expected != self.project_revision):
            raise ValueError('项目已在其他窗口更新，请载入最新项目后重试。')

    def select_keyframe(self, time_sec):
        with self.lock:
            if isinstance(time_sec, bool) or not isinstance(time_sec, (int, float)) or not math.isfinite(time_sec):
                raise ValueError('请选择有效关键帧时间。')
            if not any(k.time_sec == time_sec for k in self.project.keyframes):
                raise ValueError('该关键帧时刻已不存在，请刷新项目。')
            self.selected_time = time_sec

    def set_project(self, project, expected_revision=None):
        with self.lock:
            self.check_revision(expected_revision)
            if self.playback.state()['active']:
                raise CameraError('运镜期间请先停止，再编辑或记录属性关键帧。')
            self.validate_keyframe_edit(project)
            self._remember_replay_identity(project)
            atomic_json(self.project_path, project.to_dict())
            self.project = project
            self.project_revision += 1
            if not any(k.time_sec == self.selected_time for k in project.keyframes):
                self.selected_time = project.keyframes[0].time_sec

    def _keyframe_metadata(self, timeline):
        if not timeline or not timeline.get('replay_file'):
            return None
        path = Path(timeline['replay_file'])
        try:
            stat = path.stat()
            key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, timeline.get('replay_sha256'))
        except OSError:
            return None
        if key not in self._keyframe_metadata_cache:
            try:
                info = file_timeline(path)
                if timeline.get('replay_sha256') and info['replay_sha256'] != timeline['replay_sha256']:
                    info = {'battle_start_status': 'unavailable', 'battle_start_sec': None,
                            'battle_start_reason': '回放文件内容已改变，请重新选择同一份回放，或在设置中手动填写赛前片段长度。'}
            except (OSError, ValueError):
                info = {'battle_start_status': 'unavailable', 'battle_start_sec': None,
                        'battle_start_reason': '无法解析回放的比赛开始事件，请在设置中手动填写赛前片段长度。'}
            self._keyframe_metadata_cache = {key: info}
        return self._keyframe_metadata_cache[key]

    def keyframe_guard(self, timeline=None):
        from .replay_timeline import replay_keyframe_guard
        if self.project.shooting_mode == 'camera_only' and timeline is None:
            return {'enabled': False, 'start_sec': None, 'source': 'camera_only', 'status': 'disabled', 'message': ''}
        timeline = timeline if timeline is not None else self.project.replay_timeline
        return replay_keyframe_guard(timeline, read_settings(OUTPUT), self._keyframe_metadata(timeline))

    def validate_keyframe_edit(self, project):
        from .replay_timeline import validate_new_keyframes
        validate_new_keyframes(self.project, project, read_settings(OUTPUT), self._keyframe_metadata(project.replay_timeline))

    def check_capture_time(self, when):
        guard = self.keyframe_guard()
        if guard['enabled'] and (guard['start_sec'] is None or when < guard['start_sec'] - 1e-6):
            raise ValueError(guard['message'])

    def capture_hotkey(self):
        with self.lock:
            timeline = (self.editor_state or {}).get('timeline') or {}
            when = timeline.get('playhead', self.selected_time) if self.project.shooting_mode == 'camera_only' else 0
            self.capture(when)
            return {'ok': True, 'time_sec': self.selected_time, 'project_revision': self.project_revision}

    @staticmethod
    def _remember_replay_identity(project):
        timeline = project.replay_timeline
        if timeline and timeline.get('replay_file') and not timeline.get('replay_sha256'):
            try:
                timeline['replay_sha256'] = replay_digest(timeline['replay_file'])
            except OSError:
                pass  # Legacy projects may need the user to select a local copy.

    def _switch_to(self, path, project, *, remember=True):
        self.project_path = Path(path).resolve()
        self.project = project
        self.project_revision += 1
        self.selected_time = project.keyframes[0].time_sec
        self.editor_state = read_editor_state(OUTPUT, self.project_path) if remember else None
        if remember:
            record_recent(self.project_path)

    def save_editor_state(self, path, value, draft=None, expected_revision=None):
        with self.lock:
            if not isinstance(path, str) or Path(path).resolve() != self.project_path:
                raise ValueError('项目已切换，未保存旧项目的编辑器状态。')
            value = validate_editor_state(value)
            if draft is not None:
                if not isinstance(draft, dict):
                    raise ValueError('自动保存草稿格式无效。')
                project = edit_project(draft)
                if self.playback.state()['active']:
                    raise CameraError('运镜期间请先停止，再编辑或记录属性关键帧。')
                self.validate_keyframe_edit(project)
                # View state is independent of stale project drafts, but an
                # actual project write failure must not replace the last view.
                if expected_revision is not None and (type(expected_revision) is not int or expected_revision != self.project_revision):
                    self.editor_state = write_editor_state(OUTPUT, self.project_path, value)
                    self.check_revision(expected_revision)
                self.set_project(project, expected_revision)
            self.editor_state = write_editor_state(OUTPUT, self.project_path, value)
            return self.project_revision

    def open_project(self, path):
        path = Path(path).resolve()
        if self.playback.state()['active']:
            raise CameraError('运镜期间请先停止，再切换项目。')
        project = read_project(path)
        with self.lock:
            self._switch_to(path, project)

    def new_project_file(self, name):
        if not isinstance(name, str):
            raise ValueError('请输入项目名称。')
        safe = ''.join(c for c in name.strip() if c not in '<>:"/\\|?*' and c not in '\r\n').strip(' .')
        if not safe:
            raise ValueError('项目名称无效。')
        directory = Path(read_settings(OUTPUT)['project_directory'])
        directory.mkdir(parents=True, exist_ok=True)
        path = (directory/(safe+'.json')).resolve()
        if path.parent != directory.resolve() or path.exists():
            raise ValueError('同名项目已存在，请换一个名称。')
        data = read_project(ROOT/"examples/eight-second.json").to_dict()
        data['shooting_mode'] = 'replay'
        project = validate_project(data)
        with self.lock:
            if self.playback.state()['active']:
                raise CameraError('运镜期间请先停止，再切换项目。')
            atomic_json(path, project.to_dict())
            self._switch_to(path, project)
        return str(path)

    def delete_project(self, path, expected_revision=None):
        if not isinstance(path, str) or not path.strip() or '\0' in path:
            raise ValueError('项目文件路径无效。')
        target = Path(path).resolve()
        with self.lock:
            self.check_revision(expected_revision)
            if self.playback.state()['active']:
                raise CameraError('请先停止运镜，再删除项目。')
            if self.replay_launch['state'] in ('choosing', 'launching'):
                raise CameraError('请先完成回放选择与启动，再删除项目。')
            known = any(Path(item['path']).resolve() == target for item in read_recent())
            if not known or target.suffix.lower() != '.json' or not target.is_file():
                raise ValueError('该项目已不在最近列表或文件不存在，请刷新列表。')
            current = target == self.project_path
            if current:
                # Prepare an unsaved workspace before touching the current file.
                # It stays out of Recents until the user actually saves an edit.
                directory = Path(read_settings(OUTPUT)['project_directory'])
                blank_path = directory/'未命名.json'
                index = 2
                while blank_path.exists() or blank_path == target:
                    blank_path = directory/f'未命名 {index}.json'
                    index += 1
                data = read_project(ROOT/'examples/eight-second.json').to_dict()
                data['shooting_mode'] = 'replay'
                blank = validate_project(data)
            if not recycle_project(target):
                return {'cancelled': True}
            if current:
                self._switch_to(blank_path, blank, remember=False)
            forget_recent(target)
            try:
                editor_state_path(OUTPUT, target).unlink(missing_ok=True)
            except OSError:
                pass  # View state cleanup must not misreport a completed deletion.
            return {'ok': True, 'deleted_path': str(target)}

    def save_project_as(self, path):
        path = Path(path).resolve()
        if path.suffix.lower() != '.json':
            path = path.with_suffix('.json')
        with self.lock:
            if self.playback.state()['active']:
                raise CameraError('运镜期间请先停止，再保存项目。')
            self._remember_replay_identity(self.project)
            atomic_json(path, self.project.to_dict())
            if self.editor_state is not None:
                write_editor_state(OUTPUT, path, self.editor_state)
            self._switch_to(path, self.project)
        return str(path)

    def capture(self, time_sec, replace_existing=False, name="", expected_revision=None):
        with self.lock:
            self.check_revision(expected_revision)
            if self.playback.state()['active']:raise CameraError('请先停止运镜，再记录属性关键帧。')
            if isinstance(time_sec,bool)or not isinstance(time_sec,(int,float))or not math.isfinite(time_sec):raise ValueError('关键帧时间需为有限数值。')
            if not isinstance(replace_existing, bool):
                raise ValueError("是否允许替换属性关键帧必须为布尔值。")
            if self.session is None:
                raise CameraError("请先连接已暂停的回放自由镜头。")
            project = self.project.to_dict()
            snapshot = None
            if self.project.shooting_mode != 'camera_only' and self.project.replay_timeline is not None:
                snapshot = self.session.capture(require_paused=True)
                time_sec = snapshot['replay']['time']
            self.check_capture_time(time_sec)
            matches = [i for i, f in enumerate(project["keyframes"]) if f["time_sec"] == time_sec]
            if matches and not replace_existing:
                raise ValueError("该时刻已有属性关键帧。勾选“允许替换同一时刻的属性关键帧”后再记录。")
            if snapshot is None:
                snapshot = self.session.capture(require_paused=True)
            camera = snapshot["camera"]
            keyframe = {"time_sec": time_sec, "name": name, **{k: camera[k] for k in ("position", "quaternion", "horizontal_fov_deg")}}
            if matches and not name:
                keyframe["name"] = project["keyframes"][matches[0]].get("name", "")
            if matches:
                project["keyframes"][matches[0]] = keyframe
            else:
                project["keyframes"].append(keyframe)
                project["keyframes"].sort(key=lambda f: f["time_sec"])
            if 'camera_tracks' in project:
                for channel in ('x','y','z','yaw','pitch','roll','zoom'):
                    rows = project['camera_tracks'][channel]
                    rows[:] = [row for row in rows if row['time_sec'] != time_sec]
                    values = (*camera['position'], camera['yaw_deg'], camera['pitch_deg'], camera['roll_deg'], camera['horizontal_fov_deg'])
                    rows.append({'time_sec':time_sec, 'value':values[('x','y','z','yaw','pitch','roll','zoom').index(channel)]})
                    rows.sort(key=lambda row:row['time_sec'])
            validated = validate_project(project)
            capture_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
            atomic_json(OUTPUT/'captures'/capture_name, snapshot)
            self.set_project(validated); self.sample = snapshot
            self.selected_time = time_sec
            return snapshot

    def new_project(self, expected_revision=None):
        with self.lock:
            self.check_revision(expected_revision)
            if self.playback.state()['active']:raise CameraError('请先停止运镜。')
            if self.session is None:raise CameraError('请先连接暂停的回放。')
            snapshot=self.session.capture(require_paused=True)
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            atomic_json(OUTPUT/'project-history'/f'{stamp}.json',self.project.to_dict())
            timeline=self.project.replay_timeline
            if self.replay_info and (self.replay_info.get('verification') == 'runtime_replay' or
                    (self.replay_launch.get('verified') and self.replay_info.get('source') == 'blitz_camera')):
                timeline={'time_basis':'replay', 'duration_sec':self.replay_info['duration_sec'],
                          'replay_file':self.replay_info['replay_file']}
                if self.replay_info.get('replay_sha256'):
                    timeline['replay_sha256'] = self.replay_info['replay_sha256']
                for name in ('battle_start_sec', 'battle_start_raw_sec', 'replay_origin_sec', 'battle_start_status', 'battle_start_reason'):
                    if name in self.replay_info:
                        timeline[name] = self.replay_info[name]
            mode=self.project.shooting_mode
            when=snapshot['replay']['time'] if timeline and mode != 'camera_only' else 0
            if mode != 'camera_only':
                from .replay_timeline import replay_keyframe_guard
                guard = replay_keyframe_guard(timeline, read_settings(OUTPUT), self._keyframe_metadata(timeline))
                if guard['enabled'] and (guard['start_sec'] is None or when < guard['start_sec'] - 1e-6):
                    raise ValueError(guard['message'])
            if timeline:
                timeline=deepcopy(timeline)
                timeline.update(work_start_sec=when, work_end_sec=min(timeline['duration_sec'],when+8))
            self.set_project(validate_project({'keyframes':[{'time_sec':when,**{k:snapshot['camera'][k]for k in ('position','quaternion','horizontal_fov_deg')}}], 'position_interpolation':'smooth', 'replay_timeline':timeline, 'shooting_mode':mode, 'replay_speed':self.project.replay_speed}))
            atomic_json(OUTPUT/'captures'/f'{stamp}.json',snapshot)
            self.sample=snapshot

    def retime(self, seconds, expected_revision=None):
        with self.lock:
            self.check_revision(expected_revision)
            if self.project.shooting_mode != 'camera_only' and self.project.replay_timeline:
                raise ValueError('属性关键帧已绑定对局绝对时间，请在完整工作台设置入点与出点；改变工作区间不会重排属性关键帧时间。')
            if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<.5 or (self.project.shooting_mode != 'camera_only' and seconds>120):
                raise ValueError('轨迹时长需为 0.5–120 秒。')
            if len(self.project.keyframes)<2 or self.project.duration<=0:
                raise ValueError('请先保存至少两个不同时刻的属性关键帧。')
            data=self.project.to_dict()
            selected=next((i for i,k in enumerate(self.project.keyframes) if k.time_sec==self.selected_time),0)
            start=self.project.start_time;duration=self.project.duration
            for frame in data['keyframes']:
                frame['time_sec']=start+(frame['time_sec']-start)/duration*seconds
            for rows in data.get('camera_tracks', {}).values():
                for frame in rows:
                    frame['time_sec']=start+(frame['time_sec']-start)/duration*seconds
            self.set_project(validate_project(data),expected_revision)
            self.selected_time=self.project.keyframes[selected].time_sec

    def play(self, reverse=False, orientation_enabled=True, fov_enabled=True, speed_only=False, seconds=8, expected_revision=None, mode='auto'):
        with self.lock:
            self.check_revision(expected_revision)
            if mode not in ('current','prepare','locate','auto'):raise ValueError('未知播放方式。')
            if type(reverse)is not bool or type(orientation_enabled)is not bool or type(fov_enabled)is not bool or type(speed_only)is not bool:raise ValueError('播放选项需为布尔值。')
            if self.session is None:raise CameraError('请先连接暂停的回放自由镜头。')
            timeline=self.project.replay_timeline
            if self.project.shooting_mode=='replay' and timeline and timeline.get('replay_file'):
                actual=session_timeline(self.session)
                if not replay_matches(timeline,actual):
                    raise CameraError('当前游戏打开的回放与项目绑定不一致，请打开项目回放。')
                from .replay_timeline import validate_work_start
                validate_work_start(timeline, read_settings(OUTPUT), self._keyframe_metadata(timeline))
            reference=None
            # Older workbench pages still send "prepare" after the separate
            # continue button was removed. Both names use the merged play action.
            automatic=mode in ('auto','prepare')
            if automatic:
                mode='current'
                if self.project.shooting_mode=='replay' and self.project.replay_timeline and not speed_only and not reverse:
                    reference=self.session.capture(require_paused=False)
                    timeline=self.project.replay_timeline
                    now=reference['replay']['time']
                    in_range=timeline and timeline['work_start_sec']-.05<=now<timeline['work_end_sec']
                    if not reference['replay']['paused'] or not in_range:mode='prepare'
            if mode!='current' and self.project.shooting_mode=='replay' and not speed_only:
                if reverse:raise ValueError('入点准备只支持正向播放。')
                if reference is None:reference=self.session.capture(require_paused=False)
                generation=self.generation
                def adopt_session(session,snapshot):
                    while not self.playback.cancel.is_set():
                        if not self.lock.acquire(timeout=.1):continue
                        try:
                            if generation!=self.generation or self.stop.is_set():return False
                            if self.session is not None:self.session.close()
                            self.session,self.sample=session,snapshot
                            self.connection={'state':'connected','message':'已重新核验自由镜头，回放准备完成。','discovery':session.discovery_stats}
                            return True
                        finally:self.lock.release()
                    return False
                if mode=='locate':
                    revision=self.project_revision
                    bound=self.project.replay_timeline.get('replay_file')
                    seek_cancel=None
                    def recovery_guard():
                        return (not self.stop.is_set() and self.playback.cancel is seek_cancel and
                                not seek_cancel.is_set() and
                                generation==self.generation and revision==self.project_revision and
                                bound and self.project.replay_timeline.get('replay_file')==bound)
                    def reopen_replay():
                        with self.lock:
                            if not recovery_guard():return False
                            # The successful seek may already have adopted a new
                            # reader of this same process. Retire it before the
                            # asynchronous launcher yields to the normal poller.
                            if not invalidate_session():return False
                            return self.open_replay(bound,recovery_guard=recovery_guard)
                    def invalidate_session():
                        while not self.playback.cancel.is_set():
                            if not self.lock.acquire(timeout=.1):continue
                            try:
                                if generation!=self.generation or self.stop.is_set():return False
                                if self.session is not None:self.session.close()
                                self.session,self.sample=None,None
                                self.connection={'state':'disconnected','message':'实验性跳转正在重建回放，完成后将重新识别自由镜头。'}
                                return True
                            finally:self.lock.release()
                        return False
                    self.playback.seek(self.project,reference,adopt_session,invalidate_session,reopen_replay)
                    seek_cancel=self.playback.cancel
                else:
                    self.playback.prepare(self.project,reference,False,adopt_session,orientation_enabled,fov_enabled)
                return
            if reference is None:reference=self.session.capture(require_paused=True)
            project=self.project
            if type(speed_only)is not bool:raise ValueError('固定镜头选项需为布尔值。')
            if speed_only:
                if self.project.shooting_mode == 'camera_only':raise ValueError('仅镜头运动模式不控制对局播放速度。')
                if self.project.replay_speed['mode']=='paused':raise ValueError('请先选择固定倍率或速度曲线。')
                if isinstance(seconds,bool)or not isinstance(seconds,(int,float))or not math.isfinite(seconds)or not .5<=seconds<=120:raise ValueError('拍摄时长需为 0.5–120 秒。')
                speed=deepcopy(self.project.replay_speed);speed['camera_clock']='shooting'
                pose={k:reference['camera'][k]for k in ('position','quaternion','horizontal_fov_deg')}
                project=validate_project({'keyframes':[{'time_sec':0,**pose},{'time_sec':seconds,**pose}], 'replay_speed':speed})
            if not speed_only:
                project=playback_window(project,reference,reverse)
            self.playback.start(project,reference,reverse,orientation_enabled,fov_enabled)

    def close(self):
        self.stop.set(); self.replay_preview.close(); self.disconnect(); self.poller.join(timeout=2)


def make_handler(workstation):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"BlitzCameraLab/{__version__}"

        def log_message(self, *_):
            pass

        def _allowed(self):
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in {f"http://{h}" for h in allowed}

        def _send(self, status, data, content_type="application/json; charset=utf-8", download=False):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' blob:; img-src 'self' data: blob:; frame-ancestors 'none'")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="blitz-camera-path.json"')
            try:
                self.end_headers(); self.wfile.write(data)
            except ConnectionError:
                # A hidden/closed WebView can cancel its in-flight read.
                pass

        def do_GET(self):
            if not self._allowed():
                self._send(403, {"error": "仅允许本机同源访问。"}); return
            path = urlsplit(self.path).path
            if path == '/favicon.ico':
                self._send(204, b'', 'image/x-icon'); return
            if path == "/api/state":
                self._send(200, workstation.state()); return
            if path == '/api/settings':
                self._send(200, read_settings(OUTPUT)); return
            if path == "/api/export":
                self._send(200, workstation.state()["project"], download=True); return
            if path == "/api/projects/recent":
                self._send(200, {"projects": recent_listing()}); return
            if path == '/api/preview/state':
                self._send(200, workstation.replay_preview.snapshot()); return
            if path.startswith('/api/preview/replay/') or path.startswith('/api/preview/asset/'):
                try:
                    identity = path.rsplit('/', 1)[-1]
                    if path.startswith('/api/preview/replay/'):
                        content, kind = workstation.replay_preview.replay_bytes(identity), 'application/octet-stream'
                    else:
                        p = workstation.replay_preview.asset_path(identity)
                        content = p.read_bytes()
                        kind = {'.glb':'model/gltf-binary','.json':'application/json','.webp':'image/webp'}.get(p.suffix,'application/octet-stream')
                    self._send(200, content, kind)
                except (ValueError, OSError) as exc:
                    self._send(400, {'error':str(exc)})
                return
            if path.startswith('/vendor/'):
                # A dedicated shipped resource subtree; never resolve arbitrary
                # workstation/client paths and never follow traversal/symlinks.
                relative = Path(path.removeprefix('/'))
                candidate = (WEB/relative).resolve()
                vendor = (WEB/'vendor').resolve()
                if vendor in candidate.parents and candidate.is_file() and candidate.suffix in ('.js','.wasm','.json'):
                    kind = {'.js':'text/javascript; charset=utf-8','.wasm':'application/wasm','.json':'application/json'}[candidate.suffix]
                    self._send(200, candidate.read_bytes(), kind); return
                self._send(404, {'error':'预览资源不存在。'}); return
            if path.startswith('/api/terrain/'):
                try:
                    self._send(200, workstation.terrain.load(path.removeprefix('/api/terrain/')))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    self._send(400, {'error': str(exc)})
                return
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/startup.css": ("startup.css", "text/css; charset=utf-8"),
                      "/startup.js": ("startup.js", "text/javascript; charset=utf-8"),
                      "/number-field.js": ("number-field.js", "text/javascript; charset=utf-8"),
                      "/number-field.css": ("number-field.css", "text/css; charset=utf-8"),
                      "/preview-guides.js": ("preview-guides.js", "text/javascript; charset=utf-8"),
                      "/overlay": ("overlay.html", "text/html; charset=utf-8"),
                      "/overlay.js": ("overlay.js", "text/javascript; charset=utf-8"),
                      "/overlay.css": ("overlay.css", "text/css; charset=utf-8"),
                      "/overlay-controls.css": ("overlay-controls.css", "text/css; charset=utf-8"),
                      "/overlay-preview.js": ("overlay-preview.js", "text/javascript; charset=utf-8"),
                      "/preview-time.js": ("preview-time.js", "text/javascript; charset=utf-8"),
                      "/keyframe-clipboard.js": ("keyframe-clipboard.js", "text/javascript; charset=utf-8"),
                      "/replay-preview.js": ("replay-preview.js", "text/javascript; charset=utf-8"),
                      "/replay-preview-core.js": ("replay-preview-core.js", "text/javascript; charset=utf-8"),
                      "/replay-effects.js": ("replay-effects.js", "text/javascript; charset=utf-8"),
                      "/replay-effects-core.js": ("replay-effects-core.js", "text/javascript; charset=utf-8"),
                      "/curve-core.js": ("curve-core.js", "text/javascript; charset=utf-8"),
                      "/replay-preview-worker.js": ("replay-preview-worker.js", "text/javascript; charset=utf-8"),
                      "/replay-preview.css": ("replay-preview.css", "text/css; charset=utf-8"),
                      "/timeline.js": ("timeline.js", "text/javascript; charset=utf-8"),
                       "/speed-editor.js": ("speed-editor.js", "text/javascript; charset=utf-8"),
                      "/timeline.css": ("timeline.css", "text/css; charset=utf-8"),
                      "/replay-open.css": ("replay-open.css", "text/css; charset=utf-8"),
                      "/terrain-preview.js": ("terrain-preview.js", "text/javascript; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/editor-session.js": ("editor-session.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                name, content_type = assets[path]
                self._send(200, (WEB/name).read_bytes(), content_type); return
            self._send(404, {"error": "页面不存在。"})

        def do_POST(self):
            if not self._allowed():
                self._send(403, {"error": "仅允许本机同源访问。"}); return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._send(415, {"error": "请求需使用 JSON。"}); return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2*1024*1024:
                    raise ValueError("请求大小无效。")
                data = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("请求需为对象。")
                path = urlsplit(self.path).path
                if path == "/api/connect": workstation.connect()
                elif path == '/api/settings':
                    with workstation.lock:
                        settings=save_settings(OUTPUT,data)
                    self._send(200,settings); return
                elif path == '/api/settings/directory':
                    initial=data.get('initial') or read_settings(OUTPUT)['project_directory']
                    try: initial=directory_path(initial)
                    except ValueError: initial=Path(read_settings(OUTPUT)['project_directory'])
                    selected=replay_launcher.choose_directory(initial)
                    self._send(200,{'cancelled':True} if selected is None else {'path':str(selected)}); return
                elif path == '/api/replay/open': workstation.open_replay(data.get('path'))
                elif path == '/api/replay/open_project': workstation.open_project_replay()
                elif path == '/api/replay/timeline':
                    info=file_timeline(data.get('path',''))
                    self._send(200, info); return
                elif path == '/api/preview/select':
                    selected = data.get('path')
                    if selected is None:
                        selected = replay_launcher.choose_replay()
                    if selected is None:
                        self._send(200, {'cancelled':True}); return
                    if not isinstance(selected, (str, Path)):
                        raise ValueError('回放路径无效。')
                    self._send(200, workstation.replay_preview.select(selected)); return
                elif path == '/api/preview/prepare':
                    workstation.replay_preview.prepare(data.get('source_id'), data.get('map_id'), data.get('tank_ids'))
                elif path == "/api/disconnect": workstation.disconnect()
                elif path == "/api/capture": workstation.capture(data["time_sec"], data.get("replace_existing", False), data.get("name", ""), data.get("expected_revision"))
                elif path == '/api/capture/hotkey':
                    self._send(200, workstation.capture_hotkey()); return
                elif path == "/api/project/new": workstation.new_project(data.get("expected_revision"))
                elif path == "/api/ui/selection": workstation.select_keyframe(data["time_sec"])
                elif path == '/api/ui/editor':
                    revision = workstation.save_editor_state(data.get('project_path'), data.get('value'), data.get('draft'), data.get('expected_revision'))
                    self._send(200, {'ok': True, 'project_revision': revision}); return
                elif path == "/api/desktop/open":
                    from .desktop import open_overlay
                    with workstation.lock:
                        workstation.desktop_process = open_overlay(f'http://127.0.0.1:{self.server.server_address[1]}/', workstation.desktop_process)
                elif path == "/api/desktop/workbench":
                    from .desktop import open_overlay
                    with workstation.lock:
                        workstation.desktop_process = open_overlay(f'http://127.0.0.1:{self.server.server_address[1]}/', workstation.desktop_process, view='workbench')
                elif path == "/api/playback/start": workstation.play(data.get('reverse',False),data.get('orientation_enabled',True),data.get('fov_enabled',True),data.get('speed_only',False),data.get('seconds',8),data.get('expected_revision'),data.get('mode','auto'))
                elif path == "/api/project/retime": workstation.retime(data['seconds'],data.get('expected_revision'))
                elif path == "/api/playback/pause": workstation.playback.pause(data.get("paused",True))
                elif path == "/api/playback/stop": workstation.playback.stop()
                elif path == "/api/projects/open":
                    selected = data.get('path')
                    if selected is None:
                        selected = replay_launcher.choose_project(Path(read_settings(OUTPUT)['project_directory']))
                        if selected is None:
                            self._send(200, {'cancelled': True}); return
                    workstation.open_project(selected)
                    self._send(200, {'ok': True, 'path': str(workstation.project_path)}); return
                elif path == "/api/projects/new":
                    self._send(200, {'ok': True, 'path': workstation.new_project_file(data.get('name'))}); return
                elif path == "/api/projects/save_as":
                    selected = replay_launcher.save_project(workstation.project_path.stem,Path(read_settings(OUTPUT)['project_directory']))
                    if selected is None:
                        self._send(200, {'cancelled': True}); return
                    self._send(200, {'ok': True, 'path': workstation.save_project_as(selected)}); return
                elif path == "/api/projects/forget":
                    forget_recent(data.get('path'))
                elif path == "/api/projects/delete":
                    self._send(200, workstation.delete_project(data.get('path'), data.get('expected_revision'))); return
                elif path == "/api/project": workstation.set_project(validate_project(data["project"]), data.get("expected_revision"))
                elif path == "/api/project/edit":
                    with workstation.lock:
                        data.setdefault("arc_tolerance", workstation.project.arc_tolerance)
                        data.setdefault('replay_timeline', workstation.project.replay_timeline)
                        data.setdefault('shooting_mode', workstation.project.shooting_mode)
                        if 'camera_track_controls' not in data and hasattr(workstation.project, 'camera_tracks'):
                            raise ValueError('项目包含独立参数轨道，请在主时间轴编辑，或导入完整项目。')
                        workstation.set_project(edit_project(data), data.get("expected_revision"))
                        self._send(200, {"ok": True, **workstation.state()}); return
                elif path == "/api/sample":
                    with workstation.lock:
                        workstation.check_revision(data.get('expected_revision'))
                        trajectory = workstation.project
                        revision = workstation.project_revision
                    points = samples(trajectory, data.get("rate_hz", 30))
                    self._send(200, {"samples": points, "length": trajectory.length, "duration": trajectory.duration,
                                     "project_revision":revision,"keyframe_times":trajectory.keyframe_times()}); return
                elif path in ("/api/sample/draft", "/api/evaluate"):
                    # Offline edits are evaluated without saving or touching the game.
                    trajectory = edit_project(data)
                    with workstation.lock:
                        workstation.validate_keyframe_edit(trajectory)
                    if path == "/api/evaluate":
                        when = data['time_sec']
                        pose = trajectory.sample(when)
                        if hasattr(trajectory, 'children'):
                            values = {name: child.sample(when) for name, child in trajectory.children.items()}
                        else:
                            angles = angles_from_quaternion(pose.quaternion)
                            values = dict(zip(('x','y','z','yaw','pitch','roll','zoom'),
                                              (*pose.position, angles['yaw_deg'], angles['pitch_deg'], angles['roll_deg'], pose.horizontal_fov_deg)))
                        self._send(200, {"pose":pose.to_dict(), "values":values}); return
                    points = samples(trajectory, data.get("rate_hz", 60))
                    self._send(200, {"samples":points, "length":trajectory.length, "duration":trajectory.duration,
                                     "keyframe_times":trajectory.keyframe_times(), "keyframe_controls":controls(trajectory)}); return
                else:
                    self._send(404, {"error": "操作不存在。"}); return
                self._send(200, {"ok": True})
            except (ValueError, KeyError, TypeError, CameraError, OSError) as exc:
                self._send(400, {"error": str(exc)})

    return Handler


def serve(project_path=None, port=0, open_browser=True, desktop=False, desktop_view='overlay', exit_with_desktop=False):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    workstation = Workstation(project_path or startup_project())
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(workstation))
    except Exception:
        workstation.close(); raise
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    service_file = OUTPUT/'workstation-service.json'
    atomic_json(service_file, {'url':url, 'pid':os.getpid(), 'version':__version__, 'project_path':str(workstation.project_path)})
    print(f"Blitz Camera Lab {__version__} — {url}", flush=True)
    print("仅本机访问；连接只读取游戏，游戏内播放才接管位置。关闭服务会请求停止运镜。", flush=True)
    if open_browser: webbrowser.open(url)
    if desktop:
        from .desktop import open_overlay
        try:
            workstation.desktop_process = open_overlay(url, view=desktop_view)
        except Exception:
            workstation.close(); server.server_close(); raise
        if exit_with_desktop:
            # A host crash also relinquishes camera control through close().
            # The host process is the first instance on this newly bound port.
            host = workstation.desktop_process
            def monitor_host():
                host.wait()
                server.shutdown()
            threading.Thread(target=monitor_host, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        workstation.close(); server.server_close()
