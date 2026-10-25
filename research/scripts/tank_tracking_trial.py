"""Isolated TankVisual tracking trial. Inspect by default; --execute runs a clip.

Requires the supported 11.21 local replay, paused in free camera. This CLI uses
the existing bounded playback supervisor with an experimental DLL in output/.
It does not modify the workstation project, production driver, or game files.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam import playback
from blitzcam.hook_layout import Vec, Header, HEADER, plain
from blitzcam.hook_transport import Remote, pe_exports
from blitzcam.pose import quaternion_from_angles
from blitzcam.profile import CameraError, PROFILE_1121
from blitzcam.project import atomic_json, validate_project
from blitzcam.reader import CameraSession
from blitzcam.replay_timeline import session_timeline

OUT = ROOT/'output/tank-tracking-experiment'
CAP = 4096


class TrackConfig(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_uint32) for n in ('magic','size','visual','transform','eid','preset','lag_frames','phase')]+[
        ('distance',C.c_float),('height',C.c_float),('anchor',C.c_float*3),
        ('orbit_degrees',C.c_float),('smooth_seconds',C.c_float)]


class TrackEvent(C.Structure):
    _pack_ = 4
    _fields_ = [(n,C.c_uint32) for n in ('commit','kind','updates','valid')]+[
        ('raw_time',C.c_float),('root',Vec),('anchor',Vec),('used_anchor',Vec),('matrix',C.c_float*16)]


def target_snapshot(s, visual):
    m=s.memory;transform=m.u32(visual+0x3c)
    if (m.u32(visual)!=s.live(0x3713afc) or m.u32(visual+0x14)!=s.objects.scene or
        m.u32(transform)!=s.live(0x3724564) or m.u32(transform+8)!=visual):
        raise CameraError('TankVisual scene/transform ownership changed.')
    a=m.read(transform+0x60,64);b=m.read(transform+0x60,64)
    if a!=b:raise CameraError('Target transform changed during read.')
    matrix=list(struct.unpack('<16f',a))
    if not all(math.isfinite(x) for x in matrix):raise CameraError('Invalid target matrix.')
    return dict(eid=m.u32(visual+0x58),visual=visual,transform=transform,matrix=matrix,position=matrix[12:15])


def targets(s):
    m=s.memory;pattern=re.compile(re.escape(struct.pack('<I',s.live(0x3713afc))))
    rows=[]
    for start,length in m.regions():
        for address in range(start,start+length,1024*1024):
            try:data=m.read(address,min(1024*1024,start+length-address))
            except CameraError:continue
            for match in pattern.finditer(data):
                visual=address+match.start()
                if visual%4:continue
                try:rows.append(target_snapshot(s,visual))
                except CameraError:pass
    return rows


def anchor_at(matrix, local):
    return [matrix[12+j]+sum(local[i]*matrix[i*4+j] for i in range(3)) for j in range(3)]


def initial_pose(target, args, fov):
    m=target['matrix'];heading=math.atan2(m[5],m[4])
    angle=heading+(math.pi/2 if args.preset=='side' else math.pi)
    p=[m[12]+math.cos(angle)*args.distance,m[13]+math.sin(angle)*args.distance,m[14]+args.height]
    a=anchor_at(m,args.anchor);d=[y-x for x,y in zip(p,a)]
    yaw=math.degrees(math.atan2(d[1],d[0]));pitch=math.degrees(math.atan2(d[2],math.hypot(*d[:2])))
    return dict(position=p,quaternion=quaternion_from_angles(yaw,pitch,0),horizontal_fov_deg=fov)


def project_pixel(point, view, projection, width=1920, height=1080):
    q=[sum(point[i]*view[i*4+j] for i in range(3))+view[12+j] for j in range(4)]
    clip=[sum(q[i]*projection[i*4+j] for i in range(4)) for j in range(4)]
    if clip[3]<=1e-6:return None
    return [clip[0]/clip[3]*width/2,-clip[1]/clip[3]*height/2]


def stats(values):
    if not values:return None
    a=sorted(values)
    return dict(count=len(a),median=a[len(a)//2],p95=a[max(0,math.ceil(len(a)*.95)-1)],max=a[-1])


def measure(camera_events, target_events, width=1920, height=1080):
    targets_by_id={e['commit']:e for e in target_events}
    errors=[];stale=[];phase=[];movement=[];frames=[];last=None;updates={}
    invalid=unmatched=behind=0
    for cam in camera_events:
        target=targets_by_id.get(cam['commit'])
        if not target:
            unmatched+=1;continue
        if not target['valid']:
            invalid+=1;continue
        if cam['kind']==1:updates[cam['updates']]=target
        if cam['stage']!=2 or cam['kind']!=2:continue
        xy=project_pixel(target['anchor'],cam['view'],cam['projection'],width,height)
        if xy is None:
            behind+=1;continue
        errors.append(math.hypot(*xy))
        update=updates.get(cam['updates'])
        if update:phase.append(math.dist(update['anchor'],target['anchor']))
        if last and last['updates']!=target['updates']:
            previous_xy=project_pixel(last['anchor'],cam['view'],cam['projection'],width,height)
            if previous_xy:stale.append(math.hypot(*previous_xy))
            movement.append(math.dist(last['root'],target['root']))
        frames.append(dict(commit=cam['commit'],raw_time=cam['raw_time'],error_px=errors[-1],
                           root=target['root'],anchor=target['anchor']))
        last=target
    return dict(metric='TankVisual anchor projected through camera matrices at shadow draw entry',
                viewport=[width,height],center_error_px=stats(errors),
                previous_draw_target_error_px=stats(stale),update_to_draw_target_delta_m=stats(phase),
                target_motion_per_draw_m=stats(movement),invalid=invalid,unmatched=unmatched,
                behind_camera=behind,frames=frames,
                caveat='Matrix measurement, not image-space feature tracking or final presented-frame verification.')


def require_idle():
    service=ROOT/'output/workstation-service.json'
    if service.exists():
        url=json.loads(service.read_text(encoding='utf8'))['url'].rstrip('/')
        # Refuse an unknown/busy workstation state rather than fighting its hook.
        with urllib.request.urlopen(url+'/api/state',timeout=5) as r:state=json.load(r)
        if state['playback']['active'] or not state['playback'].get('hooks_detached',True):
            raise CameraError('Stop workstation playback before the isolated trial.')


def run(args):
    if not .5<=args.seconds<=12 or not .0625<=args.rate<=1:raise ValueError('Clip: 0.5–12 replay seconds, rate 1/16–1.')
    if not 3<=args.distance<=100 or not -30<=args.height<=30:raise ValueError('Invalid camera offset.')
    if not 0<=args.smooth<=2 or not abs(args.orbit_speed)<=90 or any(not math.isfinite(x) or abs(x)>10 for x in args.anchor):raise ValueError('Invalid tracking parameters.')
    if args.stop_after is not None and not .1<=args.stop_after<=30:raise ValueError('Stop-after must be 0.1–30 wall-clock seconds after playback begins.')
    require_idle()
    s=CameraSession.connect()
    try:
        if s.profile!=PROFILE_1121:raise CameraError('Exact 11.21 build required.')
        snap=s.capture();timeline=session_timeline(s);rows=targets(s)
        recorder=s.memory.u32(s.memory.u32(s.objects.context+0x1ac)+0xc)
        eid=args.eid if args.eid is not None else recorder
        selected=[row for row in rows if row['eid']==eid]
        if len(selected)!=1:raise CameraError(f'Need one scene-bound target for entity {eid}; found {len(selected)}.')
        target=selected[0]
        summary=dict(clock=snap['replay'],source=timeline,selected=target,
                     available=[dict(eid=x['eid'],position=x['position']) for x in rows])
        if not args.execute:
            print(json.dumps(summary,ensure_ascii=False,indent=2));return
        config=TrackConfig(magic=0x31544b42,size=C.sizeof(TrackConfig),visual=target['visual'],
                           transform=target['transform'],eid=eid,preset=['chase','side','orbit'].index(args.preset),
                           lag_frames=args.lag_frames,phase=int(args.phase=='scene'),distance=args.distance,height=args.height,
                           anchor=(C.c_float*3)(*args.anchor),orbit_degrees=args.orbit_speed,smooth_seconds=args.smooth)
        start=snap['replay']['time'];end=start+args.seconds
        if end>timeline['duration_sec']:raise CameraError('Clip extends past replay end.')
        pose=initial_pose(target,args,args.fov if args.fov is not None else snap['camera']['horizontal_fov_deg'])
        trajectory=validate_project(dict(keyframes=[dict(time_sec=t,**pose) for t in (start,end)],
            position_interpolation='linear',shooting_mode='replay',
            replay_timeline={**timeline,'time_basis':'replay','work_start_sec':start,'work_end_sec':end},
            replay_speed=dict(mode='fixed',rate=args.rate,camera_clock='replay')))
        before=hashlib.sha256(Path(timeline['replay_file']).read_bytes()).hexdigest()
        native=OUT/'native';manifest=json.loads((native/'position_hook_1121.json').read_text())
        current_source=(ROOT/'blitzcam/native/position_hook_1121.c').read_text()
        if manifest['production_source_sha256']!=hashlib.sha256(current_source.encode()).hexdigest():raise CameraError('Rebuild experiment against current production source.')
        extension=(ROOT/'research/native/tank_tracking_1121.h').read_text()
        if manifest['extension_sha256']!=hashlib.sha256(extension.encode()).hexdigest():raise CameraError('Rebuild experiment against current tracking extension.')
        if C.sizeof(TrackConfig)!=60 or C.sizeof(TrackEvent)!=120:raise CameraError('Tracking ABI changed; review native layout.')
        captures=[]
        capture_status={'dropped':0,'scene_hook_detached':None}
        class TrialRemote(Remote):
            def load(self,dll):
                base=super().load(dll);exports=pe_exports(dll)
                shared=base+exports['g_shared'];h=Header.from_buffer_copy(self.s.memory.read(shared+HEADER,C.sizeof(Header)))
                if h.active or h.status not in (0,4,-1):raise CameraError('Experiment still active.')
                self.tracking_address=base+exports['g_tracking']
                self.tracking_shared=shared;self.tracking_cursor=0
                self.write_bounds=(self.tracking_address,self.tracking_address+C.sizeof(config)+CAP*C.sizeof(TrackEvent))
                self.write(self.tracking_address,bytes(config)+bytes(CAP*C.sizeof(TrackEvent)),'owned tracking config and inactive log')
                self.write_bounds=None
                return base
            def drain_tracking(self):
                end=Header.from_buffer_copy(self.s.memory.read(self.tracking_shared+HEADER,C.sizeof(Header))).events
                begin=max(self.tracking_cursor,end-CAP)
                capture_status['dropped']+=begin-self.tracking_cursor
                self.tracking_cursor=begin
                for i in range(begin,end):
                    address=self.tracking_address+C.sizeof(config)+(i%CAP)*C.sizeof(TrackEvent)
                    row=TrackEvent.from_buffer_copy(self.s.memory.read(address,C.sizeof(TrackEvent)))
                    if row.commit!=i+1 or self.s.memory.u32(address)!=i+1:break
                    captures.append(plain(row));self.tracking_cursor=i+1
            def write(self,address,data,label):
                super().write(address,data,label)
                if hasattr(self,'tracking_shared') and label=='owned watchdog':self.drain_tracking()
            def __exit__(self,*exc):
                super().__exit__(*exc)
                if getattr(self,'tracking_address',None):
                    capture_status['scene_hook_detached']=self.s.memory.u32(self.s.objects.scene)==self.s.vft['GameScene']
                    if not capture_status['scene_hook_detached']:
                        raise CameraError('Experimental scene hook did not detach.')
                    self.drain_tracking()
        original_native,original_remote=playback.NATIVE,playback.Remote
        playback.NATIVE=native;playback.Remote=TrialRemote
        driver=playback.PositionPlayback(OUT/'runs')
        try:
            require_idle();driver.start(trajectory,snap)
            began=None;stop_sent=False
            while driver.thread.is_alive():
                driver.thread.join(.1)
                if driver.state()['state']=='playing' and began is None:began=time.monotonic()
                if args.stop_after is not None and began is not None and not stop_sent and time.monotonic()-began>=args.stop_after:
                    driver.stop();stop_sent=True
        except BaseException:
            driver.stop(wait=True);raise
        finally:
            playback.NATIVE=original_native;playback.Remote=original_remote
        state=driver.state();folder=Path(state['run_path'])
        if capture_status['scene_hook_detached'] is False:state['hooks_detached']=False
        atomic_json(folder/'tracking-targets.json',sorted(captures,key=lambda x:x['commit']))
        events_path=folder/'events.jsonl'
        camera_events=[json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        measurement=measure(camera_events,captures)
        report=dict(experiment='tank-tracking-v1',settings=vars(args),source=timeline,
                    selected=target,config=plain(config),state=state,measurement=measurement,capture=capture_status,
                    input_replay_unchanged=before==hashlib.sha256(Path(timeline['replay_file']).read_bytes()).hexdigest())
        atomic_json(folder/'tracking-report.json',report)
        print(json.dumps(dict(run=str(folder),state=state['state'],message=state['message'],
                              hooks_detached=state['hooks_detached'],measurement={k:v for k,v in measurement.items() if k!='frames'}),ensure_ascii=False,indent=2))
        accepted=('completed','stopped') if args.stop_after is not None else ('completed',)
        if state['state'] not in accepted or not state['hooks_detached']:raise CameraError('Trial did not complete; inspect saved report.')
    finally:s.close()


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true');p.add_argument('--eid',type=int)
    p.add_argument('--preset',choices=['chase','side','orbit'],default='chase')
    p.add_argument('--seconds',type=float,default=4);p.add_argument('--rate',type=float,default=1)
    p.add_argument('--distance',type=float,default=15);p.add_argument('--height',type=float,default=6)
    p.add_argument('--anchor',type=float,nargs=3,default=[0,0,1.5]);p.add_argument('--fov',type=float)
    p.add_argument('--orbit-speed',type=float,default=15);p.add_argument('--smooth',type=float,default=0)
    p.add_argument('--lag-frames',type=int,choices=[0,1],default=0,help='Deliberate stale-target control experiment')
    p.add_argument('--phase',choices=['update','scene'],default='scene',help='Compare early camera update with post-scene evaluation')
    p.add_argument('--stop-after',type=float,help='Exercise cancellation after this many wall-clock seconds of linked playback')
    return p


if __name__=='__main__':run(parser().parse_args())
