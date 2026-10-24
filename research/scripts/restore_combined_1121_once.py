"""Bounded paused-replay R3-C experiment, dry-run by default.

prepare-displacement: one 12-byte target-XYZ write, 5 world units sideways.
restore: three separate writes, target angles / XYZ / interface-FOV, 28 bytes.
Not atomic; no injection, hooks, game calls, thread suspension, retry or undo.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from blitzcam.memory import MEMORY_BASIC_INFORMATION
from blitzcam.pose import quaternion_from_angles
from blitzcam.profile import CameraError,IncoherentSample,PROFILE_1121
from blitzcam.project import atomic_json
from blitzcam.reader import CameraSession
from prepare_restore_1121_readonly import battle_links,controller_extra
from probe_pose_fov_1121_readonly import AnimationProbe
from restore_fov_1121_once import bracketed_capture
from restore_yaw_pitch_1121_once import guard_battle,identity,angle_difference


def validate_snapshot(s,settled=True):
    n,r,c=s['native_controller'],s['raw_camera'],s['camera']
    if s['build']['sha256']!=PROFILE_1121.sha256 or not s['replay']['paused']:
        raise CameraError('Requires the exact paused 11.21 build.')
    if len(n['target_angles'])!=2 or len(n['smoothed_angles'])!=2:
        raise CameraError('Unexpected native angle layout.')
    values=c['position']+c['quaternion']+n['target_position']+n['target_angles']+n['smoothed_angles']
    values += [c['horizontal_fov_deg'],n['current_interface_fov'],n['target_interface_fov'],
               n['native_roll_radians'],r['base_roll_deg'],r['interface_fov'],r['aspect'],r['fov_scale']]
    if not all(math.isfinite(x)for x in values):raise CameraError('Nonfinite camera state.')
    if n['native_roll_radians']!=0 or r['base_roll_deg']!=0:
        raise CameraError('This experiment does not change roll; both layers must stay zero.')
    if abs(n['target_angles'][0])>1e6 or abs(n['target_angles'][1])>80:
        raise CameraError('Avoid excessive accumulated yaw or pitch extremes.')
    if not all(5<=n[k]<=90 for k in ('current_interface_fov','target_interface_fov')):
        raise CameraError('Native FOV outside the traced range.')
    if r['aspect']<=0 or r['fov_scale']<=0:raise CameraError('Invalid viewport/scaling.')
    if abs(c['horizontal_fov_deg']-r['interface_fov']*r['fov_scale'])>.0001:
        kind=CameraError if settled else IncoherentSample
        raise kind('Interface FOV and projection are from inconsistent update stages.')
    q=quaternion_from_angles(90-n['smoothed_angles'][0],-n['smoothed_angles'][1],0)
    if angle_difference(q,c['quaternion'])>.01:
        kind=CameraError if settled else IncoherentSample
        raise kind('Native smoothed angles and Camera direction are from inconsistent update stages.')
    if settled:
        if max(abs(a-b)for a,b in zip(n['target_angles'],n['smoothed_angles']))>.001:
            raise CameraError('Angles are not settled.')
        if math.dist(n['target_position'],c['position'])>.01:
            raise CameraError('Position is not settled.')
        if not(n['current_interface_fov']==n['target_interface_fov']==r['interface_fov']):
            raise CameraError('FOV is not settled.')


def same_scene(saved,s):
    if saved['session_id']!=s['session_id'] or saved['addresses']!=s['addresses']:
        raise CameraError('Replay/camera identity changed.')
    if any(saved['replay'][k]!=s['replay'][k]for k in ('time','origin','rate')) or not s['replay']['paused']:
        raise CameraError('Paused replay time or rate changed.')
    if any(saved['raw_camera'][k]!=s['raw_camera'][k]for k in ('aspect','fov_scale','base_roll_deg')):
        raise CameraError('Viewport/scaling/base roll changed.')
    if s['native_controller']['native_roll_radians']!=saved['native_controller']['native_roll_radians']:
        raise CameraError('Native roll changed.')


def make_goal(saved,operation):
    validate_snapshot(saved)
    position=list(saved['camera']['position'])
    if operation=='prepare-displacement':
        dx,dy,_=saved['raw_camera']['direction'];length=math.hypot(dx,dy)
        if length<.1:raise CameraError('Reference direction is unsuitable for a sideways displacement.')
        position=[position[0]+5*dy/length,position[1]-5*dx/length,position[2]]
        position=list(struct.unpack('<3f',struct.pack('<3f',*position)))
    elif operation!='restore':raise CameraError('Unknown operation.')
    return {'position':position,'target_angles':saved['native_controller']['target_angles'],
            'interface_fov':saved['native_controller']['current_interface_fov'],
            'horizontal_fov_deg':saved['camera']['horizontal_fov_deg'],
            'quaternion':saved['camera']['quaternion'],
            'planned_not_captured':operation=='prepare-displacement'}


def payloads(goal,operation):
    xyz=('position',0xac,struct.pack('<3f',*goal['position']))
    if operation=='prepare-displacement':return [xyz]
    if operation!='restore':raise CameraError('Unknown operation.')
    return [('angles',0x58,struct.pack('<2f',*goal['target_angles'])),xyz,
            ('fov',0x114,struct.pack('<2f',goal['interface_fov'],goal['interface_fov']))]


def trial_limits(max_distance=25.,max_yaw=45.):
    if not(math.isfinite(max_distance)and .5<=max_distance<=50 and
           math.isfinite(max_yaw)and 10<=max_yaw<=60):
        raise CameraError('Trial limits must be finite: distance .5..50 and yaw 10..60.')
    return {'max_distance':float(max_distance),'max_yaw':float(max_yaw)}


def compare_pre(saved,s,operation,limits=None):
    limits=trial_limits(**(limits or {}))
    validate_snapshot(s);same_scene(saved,s)
    distance=math.dist(saved['camera']['position'],s['camera']['position'])
    angle=angle_difference(saved['camera']['quaternion'],s['camera']['quaternion'])
    fov=abs(saved['camera']['horizontal_fov_deg']-s['camera']['horizontal_fov_deg'])
    a,b=saved['native_controller']['target_angles'],s['native_controller']['target_angles']
    dy,dp=abs(a[0]-b[0]),abs(a[1]-b[1])
    if operation=='prepare-displacement':
        if distance>.001 or angle>.001 or fov>.0001 or a!=b:
            raise CameraError('Reference pose changed before the planned displacement.')
    elif not(.5<=distance<=limits['max_distance'] and 10<=dy<=limits['max_yaw'] and 3<=dp<=15 and 5<=fov<=15 and
             math.floor(a[0]/360)==math.floor(b[0]/360)):
        raise CameraError(f'Combined trial bounds not met: XYZ={distance}, yaw={dy}, pitch={dp}, FOV={fov}.')
    return {'position_difference':distance,'orientation_difference_deg':angle,
            'native_yaw_difference_deg':dy,'native_pitch_difference_deg':dp,'horizontal_fov_difference_deg':fov}


def segment_intersects(a,b,box):
    lo,hi=0.,1.
    for i in range(3):
        d=b[i]-a[i]
        if d==0:
            if not box[i]<=a[i]<=box[i+3]:return False
        else:
            x,y=sorted(((box[i]-a[i])/d,(box[i+3]-a[i])/d))
            lo,hi=max(lo,x),min(hi,y)
            if lo>hi:return False
    return True


def check_path(session,extra,start,end):
    for point in (start,end):
        if not all(math.isfinite(v)for v in point)or not all(lo+.1<=v<=hi-.1 for lo,v,hi in
                zip(extra['bounds_min'],point,extra['bounds_max'])):
            raise CameraError('Path endpoint outside or too near primary bounds.')
    begin,finish=(int(x,16)for x in extra['position_boxes_begin_end'])
    if finish<begin or (finish-begin)%24 or finish-begin>128*24:
        raise CameraError('Unexpected native position-region list.')
    boxes=[]
    for address in range(begin,finish,24):
        box=list(struct.unpack('<6f',session.memory.read(address,24)))
        if not all(math.isfinite(x)for x in box)or any(box[i]>box[i+3]for i in range(3)):
            raise CameraError('Invalid position-adjustment region.')
        if segment_intersects(start,end,box):
            raise CameraError('Return segment intersects a native position-adjustment region.')
        boxes.append(box)
    return boxes


def verify_pre(session,saved,operation,goal,link,animation,limits=None):
    extra_a=controller_extra(session)
    snap,anim=bracketed_capture(session,link,animation)
    extra=controller_extra(session)
    if extra_a!=extra:raise IncoherentSample('Bounds/controller changed around preflight capture.')
    comparison=compare_pre(saved,snap,operation,limits)
    boxes=check_path(session,extra,snap['camera']['position'],goal['position'])
    return snap,anim,comparison,{**extra,'position_regions':boxes}


def stage_guard(session,saved,link,animation,initial_extra,parts,completed):
    guard_battle(session,link)
    clock=session._clock()
    if not clock['paused']or any(clock[k]!=saved['replay'][k]for k in ('time','origin','rate')):
        raise CameraError('Replay changed between bounded write stages.')
    extra=controller_extra(session);n=session._native_controller();r=session._camera()
    if any(extra['input_bytes_10_2d'])or any(n['input_vector_80'])or any(n['input_vector_9c']):
        raise CameraError('Camera input appeared between write stages.')
    if n['native_roll_radians']!=0 or r['base_roll_deg']!=0 or any(
            r[k]!=saved['raw_camera'][k]for k in ('aspect','fov_scale')):
        raise CameraError('Roll or viewport changed between write stages.')
    for key in ('bounds_min','bounds_max','position_boxes_begin_end','scene_related_pointer_08'):
        if extra[key]!=initial_extra[key]:raise CameraError('Native bounds/owner changed between write stages.')
    if not animation.observe()['observed_quiescent']:
        raise CameraError('Known animation/task path became busy between stages.')
    for i,p in enumerate(parts):
        expected=bytes.fromhex(p['new_hex']if i<completed else p['old_hex'])
        if session.memory.read(int(p['address'],16),p['bytes'])!=expected:
            raise CameraError('A completed or pending target changed between stages.')


class BoundedWriteSequence:
    def __init__(self):
        self.used=False;self.attempts=0;self.results=[]

    def commit(self,session,saved,operation,goal,link,animation,expected_identity,journal,reserve,progress,limits=None):
        if self.used:raise CameraError('This sequence already consumed its one trial budget.')
        k=C.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes,k.OpenProcess.restype=[W.DWORD,W.BOOL,W.DWORD],W.HANDLE
        k.CloseHandle.argtypes,k.CloseHandle.restype=[W.HANDLE],W.BOOL
        h=k.OpenProcess(0x438,False,session.info.pid)
        if not h:raise CameraError(f'Cannot open bounded data-write handle ({C.get_last_error()}).')
        try:
            if identity(k,h)!=expected_identity:raise CameraError('Process creation identity changed.')
            k.VirtualQueryEx.argtypes=[W.HANDLE,C.c_void_p,C.POINTER(MEMORY_BASIC_INFORMATION),C.c_size_t]
            k.VirtualQueryEx.restype=C.c_size_t
            parts=[]
            for name,offset,data in payloads(goal,operation):
                address=session.objects.spectator_controller+offset
                region=MEMORY_BASIC_INFORMATION()
                if not k.VirtualQueryEx(h,C.c_void_p(address),C.byref(region),C.sizeof(region)):
                    raise CameraError('Cannot inspect target data range.')
                if(region.State!=0x1000 or region.Type!=0x20000 or region.Protect!=4 or address%4 or
                   address<int(region.BaseAddress)or address+len(data)>int(region.BaseAddress)+region.RegionSize):
                    raise CameraError('Each target must fit one existing private RW range.')
                parts.append({'name':name,'address':hex(address),'bytes':len(data),
                    'old_hex':session.memory.read(address,len(data)).hex(),'new_hex':data.hex()})
            snap,anim,comparison,extra=verify_pre(session,saved,operation,goal,link,animation,limits)
            journal({'parts':parts,'final_prewrite':snap,'animation':anim,'comparison':comparison,'extra':extra})
            verify_pre(session,saved,operation,goal,link,animation,limits)
            k.WriteProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
            k.WriteProcessMemory.restype=W.BOOL
            reserve();self.used=True
            for i,p in enumerate(parts):
                progress({'next_stage':p['name'],'attempts':self.attempts,'results':self.results})
                if identity(k,h)!=expected_identity:raise CameraError('Process changed between write stages.')
                stage_guard(session,saved,link,animation,extra,parts,i)
                data=bytes.fromhex(p['new_hex']);buffer=C.create_string_buffer(data);count=C.c_size_t()
                self.attempts+=1
                began=time.perf_counter()
                ok=k.WriteProcessMemory(h,C.c_void_p(int(p['address'],16)),buffer,len(data),C.byref(count))
                error=0 if ok else C.get_last_error();returned=time.perf_counter()
                item={'stage':p['name'],'address':p['address'],'api_success':bool(ok),'bytes_written':count.value,
                      'expected_bytes':len(data),'windows_error':error,'call_started_monotonic':began,
                      'returned_monotonic':returned,'full_payload_written':bool(ok and count.value==len(data))}
                self.results.append(item)
                progress({'completed_stage':p['name'],'attempts':self.attempts,'results':self.results})
                if not item['full_payload_written']:break
            return {'write_attempts':self.attempts,'results':self.results,
                'all_stages_fully_written':len(self.results)==len(parts)and all(x['full_payload_written']for x in self.results),
                'returned_monotonic':self.results[-1]['returned_monotonic']if self.results else None,
                'atomic':False}
        finally:k.CloseHandle(h)


def observe(session,saved,goal,operation,link,animation,outdir,returned):
    valid=dropped=held=0;arrival=None;hold_failed=False;failure=None;last=None
    peak_hold={'position_error':0.,'angle_error_deg':0.,'fov_error_deg':0.}
    maxima={'eye_error':0.,'rotation_error':0.,'vp_error':0.}
    all_targets=payloads(goal,'restore')
    with(outdir/'after.jsonl').open('x',encoding='utf8')as f:
        while time.perf_counter()-returned<8.5:
            snap=None
            try:
                snap,anim=bracketed_capture(session,link,animation)
                same_scene(saved,snap)
                for name,offset,data in all_targets:
                    if session.memory.read(session.objects.spectator_controller+offset,len(data))!=data:
                        raise CameraError(f'Native {name} target was overwritten after commit.')
                validate_snapshot(snap,settled=False)
                metrics={'position_error':math.dist(goal['position'],snap['camera']['position']),
                    'angle_error_deg':angle_difference(goal['quaternion'],snap['camera']['quaternion']),
                    'fov_error_deg':abs(goal['horizontal_fov_deg']-snap['camera']['horizontal_fov_deg'])}
                if operation=='prepare-displacement'and(metrics['angle_error_deg']>.001 or metrics['fov_error_deg']>.0001):
                    raise CameraError('Planned XYZ displacement changed orientation or FOV.')
                now=time.perf_counter()-returned
                inside=metrics['position_error']<=.01 and metrics['angle_error_deg']<=.05 and metrics['fov_error_deg']<=.01
                inside=inside and snap['raw_camera']['interface_fov']==goal['interface_fov']
                if arrival is None and inside:arrival=now
                if arrival is not None:
                    held+=1;hold_failed=hold_failed or not inside
                    for key in peak_hold:peak_hold[key]=max(peak_hold[key],metrics[key])
                for key in maxima:maxima[key]=max(maxima[key],snap['quality'][key])
                metrics['elapsed_seconds_since_last_write_return']=now
                last={'snapshot':snap,'animation':anim,'metrics':metrics}
                f.write(json.dumps(last,ensure_ascii=False)+'\n');valid+=1
                if arrival is not None and now-arrival>=3 and held>=150:break
            except IncoherentSample as exc:
                dropped+=1;f.write(json.dumps({'drop':str(exc),'discarded_snapshot':snap,
                    'elapsed_seconds_since_last_write_return':time.perf_counter()-returned})+'\n')
            except CameraError as exc:
                failure=str(exc);f.write(json.dumps({'stopped':failure,'failed_snapshot':snap})+'\n');break
            time.sleep(.02)
    elapsed=time.perf_counter()-returned
    return {'return_and_hold_passed':arrival is not None and arrival<=5 and elapsed-arrival>=3 and held>=150
            and not hold_failed and failure is None,'arrival_seconds_since_last_write_return':arrival,
            'elapsed_seconds_since_last_write_return':elapsed,'valid_samples':valid,'dropped_samples':dropped,
            'hold_valid_samples':held,'hold_failed':hold_failed,'failure':failure,'max_hold_errors':peak_hold,
            'max_matrix_residuals':maxima,'last':last,'visual_match_verified':False,'frame_synchronized':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture',type=Path,required=True);ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--operation',choices=['prepare-displacement','restore'],default='restore')
    ap.add_argument('--budget-path',type=Path);ap.add_argument('--execute',action='store_true')
    ap.add_argument('--max-distance',type=float,default=25.)
    ap.add_argument('--max-yaw',type=float,default=45.)
    ap.add_argument('--ui-replay-confirmed',action='store_true');args=ap.parse_args()
    limits=trial_limits(args.max_distance,args.max_yaw)
    args.run_dir.mkdir(parents=True,exist_ok=False)
    raw=args.capture.read_bytes();saved=json.loads(raw)
    report={'scope':'authorized bounded paused-replay combined trial','operation':args.operation,
        'started_utc':datetime.now(timezone.utc).isoformat(),'capture':str(args.capture.resolve()),
        'capture_sha256':hashlib.sha256(raw).hexdigest(),'execution_requested':args.execute,
        'write_attempts':0,'atomic':False,'frame_synchronized':False,'active_engine_root_verified':False,
        'trial_limits':limits}
    def journal(prepared=None):
        if prepared is not None:report['prepared_write']=prepared
        atomic_json(args.run_dir/'report.json',report)
    writer=None;journal()
    try:
        goal=make_goal(saved,args.operation);report['goal']=goal
        if args.execute and(not args.ui_replay_confirmed or args.budget_path is None):
            raise CameraError('Execution requires UI replay confirmation and an exclusive trial budget.')
        if args.budget_path is not None and args.budget_path.exists():
            raise CameraError('This operation already reserved/consumed its persistent budget.')
        with CameraSession.connect()as session:
            if session.profile!=PROFILE_1121:raise CameraError('Wrong exact build.')
            process=identity(session.memory.k,session.memory.handle);report['process_identity']=process
            captured=datetime.fromisoformat(saved['captured_at_utc']).timestamp()
            if not(process['created_filetime']-116444736000000000)/1e7<=captured<=time.time()+1:
                raise CameraError('Reference timestamp/creation identity is invalid.')
            links=battle_links(session)
            if len(links)!=1:raise CameraError('No unique BattleController update chain.')
            link=links[0];report['battle_link']=link;animation=AnimationProbe(session)
            first=None;rows=[];drops=0;began=time.perf_counter()
            while time.perf_counter()-began<4:
                try:
                    snap,anim,comparison,extra=verify_pre(session,saved,args.operation,goal,link,animation,limits)
                    if first is None:first=snap
                    if first['camera']!=snap['camera']or first['native_controller']!=snap['native_controller']:
                        raise CameraError('Pose/controller drifted during preflight.')
                    rows.append({'snapshot':snap,'animation':anim})
                    if len(rows)>=100 and time.perf_counter()-began>=2:break
                except IncoherentSample:drops+=1
                time.sleep(.02)
            if len(rows)<100:raise CameraError('Not enough stable preflight samples.')
            with(args.run_dir/'before.jsonl').open('x',encoding='utf8')as f:
                for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            report.update(before=snap,comparison=comparison,preflight_samples=len(rows),preflight_drops=drops,preflight_extra=extra)
            journal()
            if not args.execute:
                report['status']='dry_run_passed';journal()
                print(json.dumps({'status':report['status'],'comparison':comparison,'goal':goal}));return 0
            def reserve():
                with args.budget_path.open('x',encoding='utf8')as f:
                    json.dump({'capture_sha256':report['capture_sha256'],'operation':args.operation,'trial_limits':limits,
                        'process_identity':process,'prepared_write':report['prepared_write']},f,ensure_ascii=False)
            def progress(value):
                report['write_progress']=value;journal()
            writer=BoundedWriteSequence()
            result=writer.commit(session,saved,args.operation,goal,link,animation,process,journal,reserve,progress,limits)
            report.update(write_result=result,write_attempts=writer.attempts);journal()
            if not result['all_stages_fully_written']:raise CameraError('Incomplete sequence; no retry or rollback.')
            report['observation']=observe(session,saved,goal,args.operation,link,animation,args.run_dir,result['returned_monotonic'])
            report['status']='completed'if report['observation']['return_and_hold_passed']else'observed_failure'
            journal();print(json.dumps({k:report[k]for k in('status','operation','comparison','write_result')}))
            return 0 if report['status']=='completed'else 2
    except Exception as exc:
        report.update(status='stopped',error=f'{type(exc).__name__}: {exc}',
                      write_attempts=writer.attempts if writer else 0,
                      completed_write_results=writer.results if writer else [])
        journal();print(report['error'],file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
