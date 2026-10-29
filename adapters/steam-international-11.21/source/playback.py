"""Bounded full-camera playback. Connection/capture remain strictly read-only.

Only start() authorizes loading our version-locked DLL and installing instance
hooks. The worker owns a separate read session and always requests detachment.
"""
from copy import deepcopy
import ctypes as C
from datetime import datetime, timezone
import hashlib,json,math,struct,threading,time
from pathlib import Path

from .profile import CameraError,IncoherentSample,PROFILE_1121
from .reader import CameraSession
from .project import atomic_json
from .hook_layout import Config,Vec,Quat,Header,Event,PathPoint,CAP,MAX_POINTS,HEADER,RECORDS,POINTS,SPEED_POINTS,SHARED_SIZE,SpeedPoint,plain
from .pose import angles_from_quaternion
from .speed import validate_speed,playback_timing
from .replay_trial import signal_callback
from .hook_transport import Remote,pe_exports
from .hook_guards import (AnimationProbe,battle_links,guard_battle,controller_extra,
                          bracketed_capture,validate_snapshot,same_scene,check_path,segment_intersects,angle_difference)

NATIVE=Path(__file__).parent/'native'
DLL=NATIVE/'position_hook_1121.dll'
ERRORS={1:'工作台心跳中断',2:'已停止',3:'回放对象不可用',4:'客户端对象类型改变',
        5:'已退出回放或切换相机',6:'回放已播放、跳转或时钟改变',7:'镜头模式改变',
        8:'检测到手动镜头输入',9:'缩放或横滚发生变化',10:'镜头朝向发生变化',
        11:'相机投影发生变化',12:'实际朝向发生变化',13:'更新与绘制线程不一致',
        15:'阴影分区布局改变',16:'阴影相机不可用',17:'开始前摄像机状态发生变化',
        18:'游戏卡顿 请检查电脑占用',19:'游戏校正了位置目标，路径可能进入限制区域',
        20:'准备超时',21:'绘制入口被其他工具更改',22:'相机入口被其他工具更改',23:'镜头边界发生变化',24:'轨迹姿态或缩放超出已适配范围',25:'视口比例或缩放换算比例改变',26:'回放时钟或更新入口改变',27:'检测到其他播放速度或暂停控制',28:'场景时间与回放倍率不同步',29:'回放时间推进与倍率不符'}

def playback_progress(trajectory, config, header):
    """Use the last native camera position, including on an interrupted run."""
    elapsed=max(0.,min(config.duration,header.last_elapsed-config.approach_seconds))
    progress=elapsed/config.duration
    position=trajectory.end_time-progress*trajectory.duration if config.reverse else trajectory.start_time+progress*trajectory.duration
    raw=header.clock_raw if config.replay_mode else config.raw_time
    return dict(elapsed=elapsed,progress=progress,timeline_position=position,
                actual_replay_time=raw-config.origin,shooting_elapsed=header.shooting_elapsed,
                replay_elapsed=header.replay_elapsed,current_rate=header.current_rate,
                updates=header.updates,draws=header.draws)


def compile_positions(trajectory):
    """Offline full-pose table, with exact knot times; sampled in game updates."""
    independent=getattr(trajectory,'shooting_mode',None)=='camera_only'
    if len(trajectory.keyframes)<2 or trajectory.duration<=0 or (not independent and not .5<=trajectory.duration<=120):
        raise ValueError('游戏内播放需要至少两个不同时刻的属性关键帧，总时长为 0.5–120 秒。')
    duration=C.c_float(trajectory.duration).value
    times={0.,duration}
    if independent:
        # Allocate per key interval, not per second. Long holds cost no more than
        # short ones. Refine where the native linear table differs from evaluator.
        from .trajectory import quaternion_slerp as slerp
        knots=sorted({trajectory.start_time,trajectory.end_time,*trajectory.keyframe_times()})
        pending=[(a,b) for a,b in zip(knots,knots[1:])]
        times.update(C.c_float(t-trajectory.start_time).value for t in knots)
        while pending:
            a,b=pending.pop();pa,pb=trajectory.sample(a),trajectory.sample(b)
            split=False
            for u in (.25,.5,.75):
                actual=trajectory.sample(a+(b-a)*u)
                pos=tuple(x+(y-x)*u for x,y in zip(pa.position,pb.position))
                rotation=slerp(pa.quaternion,pb.quaternion,u)
                if math.dist(actual.position,pos)>.002 or angle_difference(actual.quaternion,rotation)>.01 or abs(actual.horizontal_fov_deg-(pa.horizontal_fov_deg+(pb.horizontal_fov_deg-pa.horizontal_fov_deg)*u))>.002:
                    split=True;break
            if split:
                m=(a+b)/2;fm=C.c_float(m-trajectory.start_time).value
                if len(times)>=MAX_POINTS or not C.c_float(a-trajectory.start_time).value<fm<C.c_float(b-trajectory.start_time).value:
                    raise ValueError('轨迹超出当前采样精度或点数容量，请减少过密或剧烈变化的关键帧。')
                times.add(fm);pending.extend(((a,m),(m,b)))
    else:
        times.update(C.c_float(i/120).value for i in range(1,math.ceil(duration*120)) if i/120<duration)
    times.update(C.c_float(t-trajectory.start_time).value for t in trajectory.keyframe_times())
    times=sorted(times)
    # Native interpolation requires strictly increasing float times, already
    # ensured by the set above. Grid samples and work-area boundaries may lie
    # less than a microsecond from an authored key without being invalid keys.
    if len(times)>MAX_POINTS:
        raise ValueError('轨迹采样点数超出容量，请缩短区间或减少剧烈变化的关键帧。')
    rows=[]
    knots={C.c_float(t-trajectory.start_time).value:k.pose for t,k in zip(trajectory.keyframe_times(),trajectory.keyframes)}
    for t in times:
        p=knots.get(t) or trajectory.sample(trajectory.start_time+t/duration*trajectory.duration)
        rows.append(PathPoint(t,Vec(*p.position),Quat(*p.quaternion),p.horizontal_fov_deg))
    return rows,duration

def config_for(s,snap,link,rows,duration,reverse,extra,orientation_enabled=True,fov_enabled=True):
    c=Config();o=s.objects;c.magic=0x33484342;c.size=C.sizeof(Config);c.base=s.info.base
    for n in ('context','player','scene','replay_controller','game_camera','render'):setattr(c,n,getattr(o,n))
    c.scene_owner=o.scene_controller;c.camera=o.free_camera;c.spectator=o.spectator_controller
    c.battle=int(link['battle_controller'],16);c.owner=int(link['owner_at_150'],16);c.shadow=s.memory.u32(o.render+0x8c)
    c.battle_vft=s.live(0x37f8f70);c.update_vft=s.live(0x37f8fb0);c.shadow_vft=s.live(0x375b100)
    for field,kind in [('context_vft','AvatarContextReplay'),('player_vft','ReplayPlayer'),('camera_vft','FreeCamera'),('render_vft','RenderSystem'),('scene_vft','GameScene'),('scene_owner_vft','GameSceneController'),('replay_vft','ReplayCameraController'),('game_vft','GameCamera')]:setattr(c,field,s.vft[kind])
    c.spectator_vft=s.vft[s.controller_kind]
    c.player_secondary_vft=s.live(PROFILE_1121.replay_secondary_vft)
    c.set_position=s.live(0xa95710);c.set_direction=s.live(0xa92b80);c.refresh=s.live(0xa7aee0)
    c.set_fov=s.live(0x15eaf10);c.fov_scale=snap['raw_camera']['fov_scale'];c.aspect=snap['raw_camera']['aspect']
    c.start_roll=snap['raw_camera']['base_roll_deg'];c.start_quaternion=Quat(*snap['camera']['quaternion'])
    c.orientation_enabled=orientation_enabled;c.fov_enabled=fov_enabled
    c.raw_time=snap['replay']['raw_time'];c.origin=snap['replay']['origin'];c.fov=snap['raw_camera']['interface_fov']
    c.angles[:]=snap['native_controller']['target_angles'];c.projection[:]=snap['raw_camera']['projection']
    c.direction=Vec(*snap['raw_camera']['direction']);c.setter_direction=Vec(*snap['native_controller']['direction_scaled'])
    c.b=Vec(*snap['camera']['position']);c.point_count=len(rows);c.reverse=reverse;c.duration=duration
    c.lower=Vec(*extra['bounds_min']);c.upper=Vec(*extra['bounds_max'])
    target=rows[-1 if reverse else 0]
    distance=math.dist(plain(target.position),snap['camera']['position'])
    rotation=angle_difference(plain(target.quaternion),snap['camera']['quaternion']) if orientation_enabled else 0
    fov_delta=abs(target.horizontal_fov-snap['camera']['horizontal_fov_deg']) if fov_enabled else 0
    c.approach_seconds=0 if distance<.001 and rotation<.001 and fov_delta<.001 else min(3.,max(1.,distance/30,rotation/90,fov_delta/30))
    validate_channels(c,rows)
    return c

def validate_channels(c,rows):
    for row in rows:
        if c.orientation_enabled and abs(angles_from_quaternion(plain(row.quaternion))['pitch_deg'])>80:
            raise CameraError('轨迹俯仰需在 -80° 至 80° 内，请避开垂直极点。')
        if c.fov_enabled and not 5<=row.horizontal_fov/c.fov_scale<=90:
            raise CameraError(f'当前视口的缩放需为 {5*c.fov_scale:.2f}°–{90*c.fov_scale:.2f}°。')

def check_positions(s,extra,c,rows):
    points=[plain(p.position)for p in rows]
    start=plain(c.b);target=points[-1 if c.reverse else 0]
    # Include the approach in the same bounds/known-volume checks.
    if c.approach_seconds:
        approach=[]
        for i in range(121):
            u=i/120;u=u*u*(3-2*u)
            p=[a+(b-a)*u for a,b in zip(start,target)]
            if math.dist(start,target)>.001:p[2]+=2*math.sin(math.pi*u)
            approach.append(p)
        points=approach+points
    boxes=check_path(s,extra,start,start)
    for p in points:
        if not all(math.isfinite(v)and lo+.1<=v<=hi-.1 for v,lo,hi in zip(p,extra['bounds_min'],extra['bounds_max'])):
            raise CameraError('轨迹越过自由镜头边界，请调整位置属性关键帧或路径形状。')
    # Approach ends at the reverse endpoint; don't introduce an artificial chord
    # from there to the forward table's first point.
    segments=list(zip([plain(p.position)for p in rows],[plain(p.position)for p in rows][1:]))
    if c.approach_seconds:segments+=list(zip(approach,approach[1:]))
    if any(segment_intersects(a,b,box)for a,b in segments for box in boxes):
        raise CameraError('轨迹穿过已知镜头限制区域，请抬高或绕开该段。')

class PositionPlayback:
    def __init__(self,output):
        self.pause_request=None;self.output=Path(output);self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None;self.cached_link=None;self.preparation=None
        self.value={'state':'idle','active':False,'message':'暂停回放后可播放镜头轨迹。','progress':0.,'hooks_detached':True}
    def state(self):
        with self.lock:
            value=deepcopy(self.value)
            if self.preparation:
                value.update(self.preparation,active=True,preparing_replay=True)
                if self.cancel.is_set():value.update(state='stopping',message='正在取消准备…')
            return value
    def update(self,**values):
        with self.lock:self.value.update(values)
    def _start_state(self,trajectory,reverse,orientation_enabled,fov_enabled):
        self.value={'state':'preparing','active':True,'message':'正在核验回放、路径与镜头…','progress':0.,'reverse':reverse,'duration':trajectory.duration,'timeline_start':trajectory.start_time,'timeline_end':trajectory.end_time,'hooks_detached':True,'orientation_enabled':orientation_enabled,'fov_enabled':fov_enabled,'replay_controlled':trajectory.replay_speed['mode']!='paused'}
    def prepare(self,project,reference,locate_only,adopt_session,orientation_enabled=True,fov_enabled=True):
        from .replay_preparation import prepare_replay
        from .replay_timeline import playback_window
        if project.shooting_mode!='replay' or not project.replay_timeline:raise ValueError('请先设置回放工作区间。')
        if reference['build']['sha256']!=PROFILE_1121.sha256:raise CameraError('当前客户端构建不支持回放准备。')
        if not locate_only:
            timeline=project.replay_timeline;now=reference['replay']['time']
            begin=now if timeline['work_start_sec']-.05<=now<timeline['work_end_sec'] else timeline['work_start_sec']
            window=playback_window(project,{'replay':{'time':begin}})
            compile_positions(window);playback_timing(window,validate_speed(window.replay_speed))
        with self.lock:
            if self.thread and self.thread.is_alive():raise CameraError('已有准备或播放正在进行，请先停止。')
            self.cancel=threading.Event();self.pause_request=None
            self.value={'state':'preparing','active':True,'message':'正在准备入点…','progress':0.,'hooks_detached':True}
            self.preparation={'state':'waiting_replay','message':'正在检查回放时刻…','target_time':project.replay_timeline['work_start_sec'],'replay_controlled':False}
            self.thread=threading.Thread(target=prepare_replay,args=(self,project,deepcopy(reference),locate_only,adopt_session,orientation_enabled,fov_enabled),daemon=True)
            self.thread.start()
    def seek(self,project,reference,adopt_session,invalidate_session,reopen_replay=None):
        from .replay_seek import seek_replay
        if project.shooting_mode!='replay' or not project.replay_timeline:raise ValueError('请先设置回放工作区间。')
        if reference['build']['sha256']!=PROFILE_1121.sha256 or not reference['replay']['paused']:
            raise CameraError('实验性跳转需要已适配的暂停回放自由镜头。')
        with self.lock:
            if self.thread and self.thread.is_alive():raise CameraError('已有准备或播放正在进行，请先停止。')
            self.cancel=threading.Event();self.pause_request=None
            self.value={'state':'preparing','active':True,'message':'正在准备实验性跳转…','progress':0.,'hooks_detached':True}
            self.preparation={'state':'seeking_replay','message':'正在准备实验性跳转…','target_time':project.replay_timeline['work_start_sec'],'replay_controlled':False}
            self.thread=threading.Thread(target=seek_replay,args=(self,project,deepcopy(reference),adopt_session,invalidate_session,reopen_replay),daemon=True)
            self.thread.start()
    def start(self,trajectory,reference,reverse=False,orientation_enabled=True,fov_enabled=True):
        if type(reverse)is not bool:raise ValueError('播放方向需为布尔值。')
        if type(orientation_enabled)is not bool or type(fov_enabled)is not bool:raise ValueError('朝向和缩放参数需为布尔值。')
        if reference['build']['sha256']!=PROFILE_1121.sha256 or not reference['replay']['paused']:
            raise CameraError('游戏播放仅支持已适配的 11.21 暂停回放自由镜头。')
        if len(trajectory.keyframes)<2 or trajectory.duration<=0 or (trajectory.shooting_mode != 'camera_only' and not .5<=trajectory.duration<=120):
            raise ValueError('需要至少两个不同时刻的属性关键帧，总时长为 0.5–120 秒。')
        speed=validate_speed(trajectory.replay_speed);playback_timing(trajectory,speed)
        with self.lock:
            if self.thread and self.thread.is_alive():raise CameraError('已有运镜正在准备或播放，请先停止。')
            self.cancel=threading.Event();self.pause_request=None
            self._start_state(trajectory,reverse,orientation_enabled,fov_enabled)
            self.thread=threading.Thread(target=self._run,args=(trajectory,deepcopy(reference),reverse,orientation_enabled,fov_enabled),daemon=True);self.thread.start()
    def pause(self,paused=True):
        if type(paused)is not bool:raise ValueError('暂停状态需为布尔值。')
        with self.lock:
            if self.preparation or not self.value.get('active') or not self.value.get('replay_controlled') or self.value.get('state') not in ('playing','paused'):
                raise CameraError('请等待联动播放开始后再暂停或继续。')
            self.pause_request=paused
    def stop(self,wait=False):
        self.cancel.set()
        with self.lock:
            if self.value['active']:self.value.update(state='stopping',message='正在停止并交还镜头…')
            worker=self.thread
        if wait and worker and worker is not threading.current_thread():worker.join(timeout=10)
    def _run(self,trajectory,reference,reverse,orientation_enabled=True,fov_enabled=True):
        run=self.output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');run.mkdir(parents=True)
        report={'position_only':not(orientation_enabled or fov_enabled),'orientation_enabled':orientation_enabled,'fov_enabled':fov_enabled,'reverse':reverse,'project':trajectory.to_dict(),'hooks_detached':True,'dll_resident':False}
        def journal(row):
            with(run/'operations.jsonl').open('a',encoding='utf8')as f:f.write(json.dumps(row)+'\n')
        cfg=None;g=None;driver=None;s=None;last_read=0;event_file=None
        try:
            rows,duration=compile_positions(trajectory)
            speed=validate_speed(trajectory.replay_speed);play_seconds,schedule_seconds,schedule_offset=playback_timing(trajectory,speed)
            controlled=speed['mode']!='paused';mask=7 if controlled else 3
            if self.cancel.is_set():return
            manifest=json.loads((NATIVE/'position_hook_1121.json').read_text())
            dll=NATIVE/manifest['dll']
            if dll.parent.resolve()!=NATIVE.resolve()or not dll.name.startswith('position_hook_1121.')or dll.suffix!='.dll':raise CameraError('Hook 文件名不匹配。')
            if hashlib.sha256(dll.read_bytes()).hexdigest()!=manifest['sha256']:raise CameraError('Hook 文件校验失败，请重新构建本工具。')
            if manifest['config_size']!=C.sizeof(Config)or manifest['event_size']!=C.sizeof(Event)or manifest['records']!=RECORDS or manifest['points']!=POINTS or manifest.get('speed_points')!=SPEED_POINTS or manifest.get('shared_size')!=SHARED_SIZE or manifest.get('path_point_size')!=C.sizeof(PathPoint) or manifest.get('speed_point_size')!=C.sizeof(SpeedPoint):
                raise CameraError('Hook 数据布局不匹配。')
            exports=pe_exports(dll);pid=int(reference['session_id'].split(':')[0])
            s=CameraSession.connect(pid)
            if s.profile!=PROFILE_1121:raise CameraError('此构建不支持位置 Hook。')
            key=(s.info.pid,s.objects.context,s.objects.free_camera)
            link=None
            if self.cached_link and self.cached_link[0]==key:
                try:guard_battle(s,self.cached_link[1]);link=self.cached_link[1]
                except CameraError:pass
            if link is None:
                links=battle_links(s)
                if len(links)!=1:raise CameraError('未找到唯一回放相机更新入口。')
                link=links[0];self.cached_link=(key,link)
            anim=AnimationProbe(s);first=None;count=0;deadline=time.monotonic()+3
            while count<8 and time.monotonic()<deadline:
                if self.cancel.is_set():return
                try:snap,_=bracketed_capture(s,link,anim)
                except IncoherentSample:continue
                validate_snapshot(snap);same_scene(reference,snap)
                if first and(math.dist(snap['camera']['position'],first['camera']['position'])>.001 or snap['native_controller']['target_angles']!=first['native_controller']['target_angles']):raise CameraError('镜头还在移动，请松开按键并停稳。')
                first=snap;count+=1;self.cancel.wait(.03)
            if count<8:raise CameraError('镜头暂未稳定，未接管。')
            extra=controller_extra(s);cfg=config_for(s,first,link,rows,duration,reverse,extra,orientation_enabled,fov_enabled);check_positions(s,extra,cfg,rows)
            cfg.replay_mode={'paused':0,'fixed':1,'curve':2}[speed['mode']];cfg.camera_clock=int(speed['camera_clock']=='replay')
            cfg.play_seconds=play_seconds;cfg.initial_rate=first['replay']['rate'];cfg.speed_smooth=int(speed['interpolation']=='smooth')
            cfg.schedule_seconds=schedule_seconds;cfg.schedule_offset=schedule_offset
            speed_rows=[SpeedPoint.from_key(f) for f in speed['keyframes']]
            if speed['mode']=='fixed':speed_rows=[SpeedPoint(0,speed['rate']),SpeedPoint(1,speed['rate'])]
            cfg.speed_count=len(speed_rows)
            if controlled:
                cb=signal_callback(s);cfg.functor=cb['functor'];cfg.functor_vft=cb['functor_vft'];cfg.tick_entry=cb['tick_entry']
                cfg.notify_entry=s.live(0x140ec00);cfg.pause_entry=s.live(0x1402000)
                if s.memory.read(s.objects.scene+0x2a4,1)!=b'\x01' or s.memory.read(s.objects.scene+0x2a8,4)!=b'\0'*4:raise CameraError('暂停场景时间缩放未就绪。')
            report.update(replay_speed=speed,shooting_duration=play_seconds)
            report.update(reference=first,config=plain(cfg),point_count=len(rows),dll_sha256=manifest['sha256'])
            self.update(fixed_camera=first['camera'],replay_time=first['replay']['time'],approach_seconds=cfg.approach_seconds,run_path=str(run),schedule_seconds=schedule_seconds,schedule_offset=schedule_offset,shooting_duration=play_seconds)
            if self.cancel.is_set():return
            with Remote(s,journal)as driver:
                base=driver.load(dll);g=base+exports['g_shared'];report.update(dll_resident=True,module_base=hex(base),shared_address=hex(g))
                old=Header.from_buffer_copy(s.memory.read(g+HEADER,C.sizeof(Header)))
                if old.status not in(0,4,-1)or old.active or s.memory.u32(cfg.battle+0x128)!=cfg.update_vft or s.memory.u32(cfg.shadow)!=cfg.shadow_vft:
                    raise CameraError('上次镜头接管尚未撤下，未重复安装。')
                driver.write_bounds=(g,g+SHARED_SIZE)
                driver.write(g,bytes(cfg),'owned Hook configuration')
                driver.write(g+HEADER,bytes(Header()),'owned inactive Hook counters')
                driver.write(g+POINTS,b''.join(bytes(p)for p in rows),'owned immutable camera trajectory')
                driver.write(g+SPEED_POINTS,b''.join(bytes(p)for p in speed_rows),'owned immutable replay rate curve')
                driver.write(g+HEADER+Header.heartbeat.offset,struct.pack('<I',driver.k.GetTickCount()&0xffffffff),'owned watchdog')
                driver.detach_address=base+exports['HookDetach@4']
                def detach_complete():
                    header=Header.from_buffer_copy(s.memory.read(g+HEADER,C.sizeof(Header)))
                    return not header.active and s.memory.u32(cfg.battle+0x128)==cfg.update_vft and s.memory.u32(cfg.shadow)==cfg.shadow_vft and (not controlled or s.memory.u32(cfg.functor+0x10)==cfg.tick_entry)
                driver.detach_probe=detach_complete
                code=driver.call(base+exports['HookAttach@4'],0,'install camera instance hooks')
                if code:raise CameraError(f'Hook 拒绝当前状态（{code}）。')
                report['hooks_detached']=False;self.update(hooks_detached=False,message='正在确认相机更新与绘制…')
                begin=time.monotonic();armed=False;stop_sent=False;event_file=(run/'events.jsonl').open('w',encoding='utf8')
                while time.monotonic()-begin<(600 if controlled else duration+cfg.approach_seconds+12):
                    driver.write(g+HEADER+Header.heartbeat.offset,struct.pack('<I',driver.k.GetTickCount()&0xffffffff),'owned watchdog')
                    h=Header.from_buffer_copy(s.memory.read(g+HEADER,C.sizeof(Header)))
                    # Snapshot committed ring entries before slots can wrap.
                    end=h.events;last_read=max(last_read,end-CAP)
                    for i in range(last_read,end):
                        addr=g+RECORDS+(i%CAP)*C.sizeof(Event);raw=s.memory.read(addr,C.sizeof(Event));e=Event.from_buffer_copy(raw)
                        if e.commit!=i+1 or s.memory.u32(addr)!=i+1:break
                        event_file.write(json.dumps(plain(e))+'\n');last_read=i+1
                    event_file.flush()
                    if h.status in(-1,4):break
                    if self.cancel.is_set()and not stop_sent:
                        driver.call(driver.detach_address,0,'user stop');stop_sent=True
                    elif controlled and self.pause_request is not None and armed:
                        with self.lock: pause=self.pause_request;self.pause_request=None
                        driver.write(g+HEADER+Header.command.offset,struct.pack('<i',3 if pause else 4),'pause linked playback' if pause else 'resume linked playback')
                    elif not armed and not self.cancel.is_set()and h.updates>=10 and h.draws>=10:
                        if h.update_tid!=h.draw_tid or h.position_applies:raise CameraError('相机与绘制阶段核对失败。')
                        driver.write(g+HEADER+Header.command.offset,struct.pack('<i',1),'start position trajectory');armed=True
                    if armed and not stop_sent:
                        playing=h.last_elapsed>=cfg.approach_seconds and (not controlled or bool(h.clock_started))
                        channels='位置'+(' · 朝向'if orientation_enabled else'')+(' · 缩放'if fov_enabled else'')
                        self.update(state=('paused' if controlled and h.clock_started and h.clock_paused else 'playing')if playing else'positioning',message=('联动播放已暂停' if controlled and h.clock_started and h.clock_paused else f'{channels} 轨迹播放中')if playing else'正在恢复轨迹起始构图…',replay_controlled=controlled,**playback_progress(trajectory,cfg,h))
                    self.cancel.wait(.08)if not self.cancel.is_set()else time.sleep(.02)
                report['final_header']=plain(h)
                driver.call(driver.detach_address,0,'finish position playback')
                until=time.monotonic()+2
                while time.monotonic()<until:
                    h=Header.from_buffer_copy(s.memory.read(g+HEADER,C.sizeof(Header)))
                    if h.detach_mask==mask and not h.active:break
                    time.sleep(.02)
                detached=h.detach_mask==mask and s.memory.u32(cfg.battle+0x128)==cfg.update_vft and s.memory.u32(cfg.shadow)==cfg.shadow_vft
                report.update(hooks_detached=detached,final_header=plain(h),user_stopped=self.cancel.is_set(),clock_restored=bool(h.clock_restored))
                # Publish final counters before raising an error: the preceding
                # UI poll may have occurred several frames before interruption.
                self.update(**playback_progress(trajectory,cfg,h),native_error=int(h.error))
                if controlled and not h.clock_restored:raise CameraError('无法确认回放倍率恢复，请退出回放后重新连接。')
                if not detached:raise CameraError('尚未确认镜头入口已恢复，请退出回放后重新连接。')
                try:report['final_camera']=s.capture(require_paused=True)
                except CameraError:pass
                if h.error:raise CameraError(ERRORS.get(h.error,f'Hook 检查停止（{h.error}）'))
                if not self.cancel.is_set()and h.last_elapsed<duration+cfg.approach_seconds:raise CameraError('运镜超时，已撤下镜头接管。')
                elapsed=max(0.,min(duration,h.last_elapsed-cfg.approach_seconds))
                self.update(state='stopped'if self.cancel.is_set()else'completed',message='已停止，镜头已交还手动控制。'if self.cancel.is_set()else'播放完成，镜头已交还手动控制。',hooks_detached=True,elapsed=elapsed,shooting_elapsed=h.shooting_elapsed,replay_elapsed=h.replay_elapsed,current_rate=h.current_rate,clock_restored=bool(h.clock_restored),progress=elapsed/duration if self.cancel.is_set()else 1.)
        except Exception as exc:
            report['error']=str(exc);self.update(state='error',message=str(exc))
        finally:
            if event_file:event_file.close()
            if s:
                if cfg and g:
                    try:
                        h=Header.from_buffer_copy(s.memory.read(g+HEADER,C.sizeof(Header)))
                        report['hooks_detached']=not h.active and s.memory.u32(cfg.battle+0x128)==cfg.update_vft and s.memory.u32(cfg.shadow)==cfg.shadow_vft and (not controlled or s.memory.u32(cfg.functor+0x10)==cfg.tick_entry)
                        report['final_header']=plain(h)
                    except CameraError:report['hooks_detached']=False
                s.close()
            if self.cancel.is_set()and self.value['state']in('preparing','stopping'):
                self.update(state='stopped',message='已取消准备，镜头未继续运动。')
            report['finished_utc']=datetime.now(timezone.utc).isoformat();atomic_json(run/'report.json',report)
            self.update(active=False,hooks_detached=report['hooks_detached'],run_path=str(run))
