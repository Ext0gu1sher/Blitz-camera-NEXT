"""One cancellable preparation job; forward playback only, never native rewind."""
import time

from .profile import CameraError
from .reader import CameraSession
from .project import validate_project
from .replay_timeline import playback_window, session_timeline, replay_matches

ARRIVAL_TOLERANCE = .05
# A native seek can land just beyond the in-point on its ~0.1 s record grid.
PAST_INPOINT_TOLERANCE = .12


def stationary_project(camera, seconds, *, advance=None):
    """Temporary execution project. Authored keys and work area are untouched."""
    pose={k:camera[k] for k in ('position','quaternion','horizontal_fov_deg')}
    speed={'mode':'paused','camera_clock':'shooting'}
    if advance is not None:
        speed={'mode':'fixed','rate':advance/seconds,'camera_clock':'shooting'}
    return validate_project({'shooting_mode':'camera_only' if advance is None else 'replay',
                             'replay_speed':speed,
                             'keyframes':[{'time_sec':t,**pose} for t in (0,seconds)]})


def prepare_replay(manager, project, reference, locate_only, adopt_session,orientation_enabled=True,fov_enabled=True):
    target=project.replay_timeline['work_start_sec']
    pid=int(reference['session_id'].split(':')[0])
    session=None
    def phase(state,message,**extra):
        with manager.lock:
            manager.preparation={'state':state,'message':message,'target_time':target,
                                 'replay_controlled':False,**extra}
            if state.startswith('waiting_'):manager.preparation.update(progress=0.,elapsed=0.)
    def run_stage(trajectory,snapshot):
        manager._run(trajectory,snapshot,False,True,True)
        if manager.cancel.is_set():return False
        with manager.lock:result=dict(manager.value)
        if result['state']!='completed' or not result.get('hooks_detached'):
            raise CameraError(result.get('message') or '准备未完成，已停止。')
        return True
    try:
        deadline=time.monotonic()+300
        while not manager.cancel.is_set():
            if time.monotonic()>deadline:raise CameraError('等待定位超时，已取消。可重新点击准备播放。')
            try:
                if session is None:
                    session=CameraSession.connect(pid)
                    bound=project.replay_timeline.get('replay_file')
                    if bound:
                        actual=session_timeline(session)
                        if not replay_matches(project.replay_timeline,actual):
                            raise ValueError('当前游戏打开的回放与项目绑定不一致，请打开项目回放。')
                snapshot=session.capture(require_paused=False)
            except (CameraError,OSError) as exc:
                if session is not None:session.close();session=None
                phase('waiting_replay',f'等待回放稳定并切回自由镜头，随后自动继续。{exc}')
                manager.cancel.wait(.75);continue
            now=snapshot['replay']['time']
            if not snapshot['replay']['paused']:
                timeline=project.replay_timeline
                resume_here=not locate_only and target-ARRIVAL_TOLERANCE<=now<timeline['work_end_sec']
                message='请在游戏中暂停回放，随后从暂停时刻继续播放至出点。' if resume_here else f'请在游戏中暂停回放；已待命，将自动准备到 {target:.3f} 秒。'
                phase('waiting_replay',message,current_time=now,target_time=now if resume_here else target)
                manager.cancel.wait(.2);continue
            timeline=project.replay_timeline
            resume_here=not locate_only and target-ARRIVAL_TOLERANCE<=now<timeline['work_end_sec']
            if now>target+PAST_INPOINT_TOLERANCE and not resume_here:
                raise CameraError('游戏已到达或超过工作区出点，请先使用播放栏的实验性跳转；也可退出并重新打开回放。' if not locate_only else '游戏已越过入点，请先使用播放栏的实验性跳转；也可退出并重新打开回放。')
            gap=target-now
            if gap>ARRIVAL_TOLERANCE and not resume_here:
                # Leave a slow final approach: even a 150 ms game frame must not
                # overshoot the arrival tolerance and demand a manual rewind.
                advance=min(100.,gap-.5) if gap>1 else gap
                seconds=advance if gap>1 else max(.5,advance/.25)
                phase('advancing_replay',f'正在向前定位到入点 {target:.3f} 秒…',current_time=now)
                if not run_stage(stationary_project(snapshot['camera'],seconds,advance=advance),snapshot):return
                deadline=time.monotonic()+300
                continue
            if locate_only:
                pose=project.sample(now)
                camera={'position':pose.position,'quaternion':pose.quaternion,
                        'horizontal_fov_deg':pose.horizontal_fov_deg}
                phase('positioning',f'正在恢复入点 {target:.3f} 秒的构图…',current_time=now)
                if not run_stage(stationary_project(camera,.05),snapshot):return
                snapshot=session.capture(require_paused=True)
                if not adopt_session(session,snapshot):return
                session=None
                manager.update(state='completed',active=False,progress=1.,message=f'已定位到 {snapshot["replay"]["time"]:.3f} 秒并暂停。',replay_time=snapshot['replay']['time'])
            else:
                window=playback_window(project,snapshot)
                if not adopt_session(session,snapshot):return
                session=None
                with manager.lock:
                    manager._start_state(window,False,orientation_enabled,fov_enabled)
                    manager.preparation=None
                if not manager.cancel.is_set():manager._run(window,snapshot,False,orientation_enabled,fov_enabled)
            return
    except Exception as exc:
        manager.update(state='error',message=str(exc))
    finally:
        if session is not None:session.close()
        # Keep the job active through all intermediate native runs and detach.
        with manager.lock:
            manager.preparation=None
            manager.value['active']=False
            if manager.cancel.is_set() and manager.value.get('state')!='error':manager.value.update(state='stopped',message='已取消准备或播放。')
