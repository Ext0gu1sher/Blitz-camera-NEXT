"""One bounded 8-second A->B controller-target stream, paused 11.21 only.

Dry-run by default. Linear native yaw/pitch, XYZ and interface FOV share a
monotonic timeline. Native smoothing remains active: actual arrival is measured,
not assumed to occur at eight seconds. No injection or game function calls.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from restore_combined_1121_once import (
    CameraError, IncoherentSample, PROFILE_1121, CameraSession, AnimationProbe,
    MEMORY_BASIC_INFORMATION, atomic_json, identity, angle_difference,
    quaternion_from_angles, validate_snapshot, same_scene, compare_pre,
    trial_limits, battle_links, controller_extra, check_path, bracketed_capture,
    stage_guard, payloads, make_goal, observe)

DURATION=8.
HZ=30
MAX_BATCHES=int(DURATION*HZ)+1
MAX_CALLS=3*MAX_BATCHES


def target_at(a,b,seconds,lift=0.):
    if not math.isfinite(seconds):raise CameraError('Nonfinite timeline time.')
    if not math.isfinite(lift)or not 0<=lift<=2:raise CameraError('Path lift must be finite and within 0..2.')
    u=min(1.,max(0.,seconds/DURATION))
    def lerp(x,y):return x+(y-x)*u
    an,bn=a['native_controller'],b['native_controller']
    angles=[lerp(x,y)for x,y in zip(an['target_angles'],bn['target_angles'])]
    fov=lerp(an['current_interface_fov'],bn['current_interface_fov'])
    position=[lerp(x,y)for x,y in zip(a['camera']['position'],b['camera']['position'])]
    position[2]+=lift*math.sin(math.pi*u)if 0<u<1 else 0.
    return {'position':position,
        'target_angles':angles,'interface_fov':fov,
        'horizontal_fov_deg':fov*a['raw_camera']['fov_scale'],
        'quaternion':list(quaternion_from_angles(90-angles[0],-angles[1],0)),
        'planned_not_captured':True}


def near_start(a,s):
    validate_snapshot(s);same_scene(a,s)
    if (math.dist(a['camera']['position'],s['camera']['position'])>.01 or
        angle_difference(a['camera']['quaternion'],s['camera']['quaternion'])>.05 or
        abs(a['camera']['horizontal_fov_deg']-s['camera']['horizontal_fov_deg'])>.01):
        raise CameraError('Current camera is not at the saved A.')
    if (s['native_controller']['target_position']!=a['camera']['position'] or
        any(s['native_controller'][k]!=a['native_controller'][k]for k in
            ('target_angles','current_interface_fov','target_interface_fov'))):
        raise CameraError('Current controller targets do not equal saved A.')


class StreamWriter:
    """One handle, one non-resumable budget, three fixed data ranges per batch."""
    def __init__(self,session,process,expected,journal,reserve):
        self.s=session;self.process=process;self.expected=expected.copy()
        self.journal=journal;self.reserve=reserve;self.calls=0;self.batches=0
        self.used=False;self.failed=False;self.last_return=None
        self.k=C.WinDLL('kernel32',use_last_error=True);self.h=None
        k=self.k
        k.OpenProcess.argtypes,k.OpenProcess.restype=[W.DWORD,W.BOOL,W.DWORD],W.HANDLE
        k.CloseHandle.argtypes,k.CloseHandle.restype=[W.HANDLE],W.BOOL
        k.VirtualQueryEx.argtypes=[W.HANDLE,C.c_void_p,C.POINTER(MEMORY_BASIC_INFORMATION),C.c_size_t]
        k.VirtualQueryEx.restype=C.c_size_t
        k.WriteProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
        k.WriteProcessMemory.restype=W.BOOL

    def __enter__(self):
        self.h=self.k.OpenProcess(0x438,False,self.s.info.pid)
        if not self.h:raise CameraError(f'Cannot open bounded stream handle ({C.get_last_error()}).')
        try:
            if identity(self.k,self.h)!=self.process:raise CameraError('Process identity changed.')
            for address,data in self.expected.items():
                page=MEMORY_BASIC_INFORMATION()
                if not self.k.VirtualQueryEx(self.h,C.c_void_p(address),C.byref(page),C.sizeof(page)):
                    raise CameraError('Cannot query target page.')
                if(page.State!=0x1000 or page.Type!=0x20000 or page.Protect!=4 or address%4 or
                   address<int(page.BaseAddress)or address+len(data)>int(page.BaseAddress)+page.RegionSize):
                    raise CameraError('Target must fit an existing private RW page.')
            return self
        except Exception:
            self.__exit__(None,None,None);raise

    def __exit__(self,*args):
        if self.h:self.k.CloseHandle(self.h);self.h=None

    def commit(self,goal,guard):
        if self.failed or self.h is None or self.batches>=MAX_BATCHES:
            raise CameraError('Stream is closed, failed, or exhausted; it cannot resume.')
        parts=[]
        try:
            for name,offset,new in payloads(goal,'restore'):
                address=self.s.objects.spectator_controller+offset
                if self.s.memory.read(address,len(new))!=self.expected[address]:
                    raise CameraError('A previous controller target was changed externally.')
                parts.append({'name':name,'address':hex(address),'bytes':len(new),
                    'old_hex':self.expected[address].hex(),'new_hex':new.hex()})
            for i,p in enumerate(parts):
                if self.calls>=MAX_CALLS:raise CameraError('Write call budget exceeded.')
                if identity(self.k,self.h)!=self.process:raise CameraError('Process changed during stream.')
                guard(parts,i)
                if not self.used:self.reserve();self.used=True
                data=bytes.fromhex(p['new_hex']);buf=C.create_string_buffer(data);count=C.c_size_t()
                self.journal({'intent':True,'batch':self.batches,'stage':p['name'],'part':p})
                self.calls+=1;began=time.perf_counter()
                ok=self.k.WriteProcessMemory(self.h,C.c_void_p(int(p['address'],16)),buf,len(data),C.byref(count))
                returned=time.perf_counter();self.last_return=returned
                result={'batch':self.batches,'stage':p['name'],'call':self.calls,'api_success':bool(ok),
                    'bytes_written':count.value,'expected_bytes':len(data),
                    'windows_error':0 if ok else C.get_last_error(),
                    'call_started_monotonic':began,'returned_monotonic':returned}
                self.journal(result)
                if not ok or count.value!=len(data):raise CameraError('Incomplete stream write; no retry or rollback.')
                self.expected[int(p['address'],16)]=data
            self.batches+=1
        except Exception:
            self.failed=True;raise


def preflight(session,a,b,link,anim,lift=0.):
    validate_snapshot(a);validate_snapshot(b);same_scene(a,b)
    comparison=compare_pre(a,b,'restore',trial_limits(50.,60.))
    extra=controller_extra(session)
    boxes=check_path(session,extra,a['camera']['position'],b['camera']['position'])
    if lift:
        # A conservative envelope of the ENTIRE lifted curve, not point sampling.
        lo=[min(x,y)for x,y in zip(a['camera']['position'],b['camera']['position'])]
        hi=[max(x,y)for x,y in zip(a['camera']['position'],b['camera']['position'])];hi[2]+=lift
        if not all(x+.1<=v<=w<=y-.1 for x,v,w,y in zip(extra['bounds_min'],lo,hi,extra['bounds_max'])):
            raise CameraError('Lifted path envelope exceeds primary bounds.')
        if any(all(lo[i]<=box[i+3]and box[i]<=hi[i]for i in range(3))for box in boxes):
            raise CameraError('Lifted path envelope overlaps a known adjustment region.')
    rows=[];drops=0;began=time.perf_counter()
    while time.perf_counter()-began<4:
        try:
            snap,probe=bracketed_capture(session,link,anim);near_start(a,snap)
            now_extra=controller_extra(session)
            if now_extra!=extra:raise CameraError('Controller changed during preflight.')
            rows.append({'snapshot':snap,'animation':probe})
            if len(rows)>=60 and time.perf_counter()-began>=2:break
        except IncoherentSample:drops+=1
        time.sleep(.02)
    if len(rows)<60:raise CameraError('Insufficient stable preflight samples.')
    return {'comparison':comparison,'extra':extra,'position_regions':boxes,
        'valid_samples':len(rows),'dropped_samples':drops,'last':rows[-1]}


def sample_tracking(session,a,goal,link,anim):
    snap,probe=bracketed_capture(session,link,anim);same_scene(a,snap);validate_snapshot(snap,settled=False)
    return {'snapshot':snap,'animation':probe,'tracking':{
        'position_error':math.dist(goal['position'],snap['camera']['position']),
        'angle_error_deg':angle_difference(goal['quaternion'],snap['camera']['quaternion']),
        'fov_error_deg':abs(goal['horizontal_fov_deg']-snap['camera']['horizontal_fov_deg'])}}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--a',type=Path,required=True);ap.add_argument('--b',type=Path,required=True)
    ap.add_argument('--run-dir',type=Path,required=True);ap.add_argument('--budget',type=Path)
    ap.add_argument('--execute',action='store_true');ap.add_argument('--ui-replay-confirmed',action='store_true')
    ap.add_argument('--lift',type=float,default=0.)
    args=ap.parse_args()
    if not math.isfinite(args.lift)or not 0<=args.lift<=2:raise CameraError('Path lift must be finite and within 0..2.')
    args.run_dir.mkdir(parents=True,exist_ok=False)
    a,b=(json.loads(p.read_text(encoding='utf8'))for p in (args.a,args.b))
    report={'started_utc':datetime.now(timezone.utc).isoformat(),'duration_seconds':DURATION,
        'target_hz':HZ,'max_batches':MAX_BATCHES,'max_write_calls':MAX_CALLS,
        'interpolation':'linear XYZ base plus optional Z arch; linear native yaw/pitch and interface FOV; zero roll unchanged',
        'path_lift_units':args.lift,'lift_profile':'lift*sin(pi*u); exact original endpoints',
        'target_position_constant_speed':args.lift==0,
        'native_smoothing':'unchanged; target trajectory is distinct from actual rendered-camera trajectory',
        'source_sha256':{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest()for p in (args.a,args.b)},
        'write_attempts':0,'atomic':False,'frame_synchronized':False,'execution_requested':args.execute}
    writer=None
    def save():atomic_json(args.run_dir/'report.json',report)
    save()
    try:
        if args.execute and(not args.ui_replay_confirmed or args.budget is None):
            raise CameraError('Requires paused replay confirmation and one trial budget.')
        if args.budget and args.budget.exists():raise CameraError('This trial budget already exists.')
        with CameraSession.connect()as session:
            if session.profile!=PROFILE_1121:raise CameraError('Wrong exact build.')
            process=identity(session.memory.k,session.memory.handle);report['process_identity']=process
            for s in (a,b):
                captured=datetime.fromisoformat(s['captured_at_utc']).timestamp()
                if not(process['created_filetime']-116444736000000000)/1e7<=captured<=time.time()+1:
                    raise CameraError('Endpoint is not from the current process lifetime.')
            links=battle_links(session)
            if len(links)!=1:raise CameraError('No unique replay update chain.')
            link=links[0];anim=AnimationProbe(session);report['battle_link']=link
            pf=preflight(session,a,b,link,anim,args.lift);report['preflight']=pf;save()
            if not args.execute:
                report['status']='dry_run_passed';save();print(json.dumps({'status':report['status'],'comparison':pf['comparison']}));return 0
            expected={session.objects.spectator_controller+offset:data for name,offset,data in payloads(make_goal(a,'restore'),'restore')}
            def reserve():
                with args.budget.open('x',encoding='utf8')as f:
                    json.dump({'scope':'one A->B eight-second stream; no resume','process_identity':process,
                        'source_sha256':report['source_sha256'],'path_lift_units':args.lift,
                        'duration_seconds':DURATION,'max_batches':MAX_BATCHES,'max_calls':MAX_CALLS},f)
            with(args.run_dir/'writes.jsonl').open('x',encoding='utf8')as writes,(args.run_dir/'tracking.jsonl').open('x',encoding='utf8')as tracking:
                def journal(item):writes.write(json.dumps(item)+'\n');writes.flush()
                with StreamWriter(session,process,expected,journal,reserve)as writer:
                    # Check again after obtaining the handle, before starting the clock.
                    snap,probe=bracketed_capture(session,link,anim);near_start(a,snap)
                    began=time.perf_counter();report['stream_started_monotonic']=began;save()
                    drops=0;tracking_rows=[];scheduling=[]
                    for i in range(MAX_BATCHES):
                        deadline=began+i/HZ
                        remaining=deadline-time.perf_counter()
                        if remaining>0:time.sleep(remaining)
                        elapsed=time.perf_counter()-began
                        if elapsed-i/HZ>.15:raise CameraError('Stream scheduling stalled; no catch-up burst.')
                        t=min(DURATION,elapsed)if i<MAX_BATCHES-1 else DURATION
                        goal=target_at(a,b,t,args.lift)
                        writer.commit(goal,lambda parts,completed:stage_guard(session,a,link,anim,pf['extra'],parts,completed))
                        scheduling.append({'batch':i,'target_seconds':t,'last_write_seconds':writer.last_return-began})
                        try:
                            row=sample_tracking(session,a,goal,link,anim)
                            row.update(batch=i,target_seconds=t,target=goal,elapsed_seconds=time.perf_counter()-began)
                            tracking_rows.append(row);tracking.write(json.dumps(row,ensure_ascii=False)+'\n')
                        except IncoherentSample as exc:
                            drops+=1;tracking.write(json.dumps({'drop':str(exc),'batch':i,'target_seconds':t},ensure_ascii=False)+'\n')
                        tracking.flush()
                    report.update(write_attempts=writer.calls,completed_batches=writer.batches,
                        scheduling=scheduling,tracking_valid=len(tracking_rows),tracking_dropped=drops,
                        last_tracking=tracking_rows[-1]if tracking_rows else None)
                    save()
                    # Close write handle at the end of the target stream, then only read.
                goal=make_goal(b,'restore')
                report['observation']=observe(session,a,goal,'restore',link,anim,args.run_dir,writer.last_return)
                report['status']='completed'if report['observation']['return_and_hold_passed']else'endpoint_observed_failure'
                save();print(json.dumps({k:report[k]for k in ('status','write_attempts','completed_batches','tracking_valid','tracking_dropped')}))
                return 0 if report['status']=='completed'else 2
    except Exception as exc:
        report.update(status='stopped',error=f'{type(exc).__name__}: {exc}',
            write_attempts=writer.calls if writer else 0,completed_batches=writer.batches if writer else 0)
        save();print(report['error'],file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
