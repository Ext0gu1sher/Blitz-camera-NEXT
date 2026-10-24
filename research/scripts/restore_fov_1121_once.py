"""R3-F: one authorized 8-byte current/target interface-FOV restore, then RPM.

Dry run by default, independent of the workstation. No angle/position write,
injection, hook, remote call, protection change, thread suspension or retry.
Observed animation quiescence is not an engine-thread commit lock.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blitzcam.memory import MEMORY_BASIC_INFORMATION
from blitzcam.pose import quaternion_from_angles
from blitzcam.profile import CameraError, IncoherentSample, PROFILE_1121
from blitzcam.project import atomic_json
from blitzcam.reader import CameraSession
from prepare_restore_1121_readonly import battle_links, controller_extra
from probe_pose_fov_1121_readonly import AnimationProbe, structural_signature
# Guard/math helpers only: neither preceding experiment's writer is called.
from restore_yaw_pitch_1121_once import guard_battle, identity, angle_difference


def validate_state(s, *, projection_may_be_transitioning=False):
    if s['build']['sha256'] != PROFILE_1121.sha256 or not s['replay']['paused']:
        raise CameraError('R3-F requires the exact paused 11.21 build.')
    n, r, cam = s['native_controller'], s['raw_camera'], s['camera']
    if len(n['target_angles']) != 2 or len(n['smoothed_angles']) != 2:
        raise CameraError('Invalid native angle layout.')
    values = cam['position']+cam['quaternion']+[cam['horizontal_fov_deg']]
    values += n['target_angles']+n['smoothed_angles']+n['target_position']
    values += [n['native_roll_radians'],r['base_roll_deg'],r['aspect'],r['fov_scale'],
               n['current_interface_fov'],n['target_interface_fov'],r['interface_fov']]
    if not all(math.isfinite(v) for v in values):
        raise CameraError('Nonfinite camera/controller state.')
    if n['native_roll_radians'] != 0 or r['base_roll_deg'] != 0:
        raise CameraError('R3-F requires unchanged zero roll at both layers.')
    if max(abs(a-b) for a,b in zip(n['target_angles'],n['smoothed_angles'])) > .001:
        raise CameraError('Native angles are not settled.')
    q = quaternion_from_angles(90-n['target_angles'][0],-n['target_angles'][1],0)
    if angle_difference(q,cam['quaternion']) > .01:
        raise CameraError('Native angles do not match the rendered-camera direction.')
    if math.dist(n['target_position'],cam['position']) > .01:
        raise CameraError('Position has not settled.')
    if not 5 <= n['current_interface_fov'] <= 90 or not 5 <= n['target_interface_fov'] <= 90:
        raise CameraError('Interface FOV is outside the traced native range.')
    if r['fov_scale'] <= 0 or r['aspect'] <= 0:
        raise CameraError('Invalid projection scaling.')
    if abs(cam['horizontal_fov_deg']-r['interface_fov']*r['fov_scale']) > .0001:
        if projection_may_be_transitioning:
            raise IncoherentSample('Interface FOV and actual projection disagree during postwrite observation.')
        raise CameraError('Interface FOV and actual projection disagree.')


def unchanged_pose(saved, current):
    if saved['session_id'] != current['session_id'] or saved['addresses'] != current['addresses']:
        raise CameraError('Camera/replay identity changed.')
    if any(saved['replay'][k] != current['replay'][k] for k in ('time','origin','rate')):
        raise CameraError('Paused replay clock changed.')
    for key in ('target_position','target_angles','smoothed_angles','native_roll_radians'):
        if saved['native_controller'][key] != current['native_controller'][key]:
            raise CameraError('A position/orientation controller field changed.')
    for key in ('aspect','fov_scale','base_roll_deg','view'):
        if saved['raw_camera'][key] != current['raw_camera'][key]:
            raise CameraError('View or viewport/scaling changed.')
    if saved['camera']['position'] != current['camera']['position']:
        raise CameraError('Actual XYZ changed; no position restore is authorized.')
    angle = angle_difference(saved['camera']['quaternion'],current['camera']['quaternion'])
    if angle > .001:
        raise CameraError('Actual orientation changed; no angle restore is authorized.')
    return {'position_difference':0.,'orientation_difference_deg':angle}


def validate_pair(saved,current):
    for s in (saved,current):
        validate_state(s)
        n,r = s['native_controller'],s['raw_camera']
        if not (n['current_interface_fov']==n['target_interface_fov']==r['interface_fov']):
            raise CameraError('FOV has not settled.')
    result = unchanged_pose(saved,current)
    delta = abs(saved['camera']['horizontal_fov_deg']-current['camera']['horizontal_fov_deg'])
    if not 5 <= delta <= 15:
        raise CameraError(f'R3-F requires a visible 5..15 degree horizontal FOV change; actual {delta}.')
    result.update(horizontal_fov_difference_deg=delta,
        interface_fov_difference=abs(saved['native_controller']['current_interface_fov']-
                                     current['native_controller']['current_interface_fov']))
    return result


def bracketed_capture(session,link,animation):
    guard_battle(session,link)
    a = animation.observe()
    extra_a = controller_extra(session)
    snap = session.capture(require_paused=True)
    extra_b = controller_extra(session)
    b = animation.observe()
    if extra_a != extra_b or structural_signature(a) != structural_signature(b):
        raise IncoherentSample('Controller/animation structure changed around capture.')
    if not b['observed_quiescent']:
        raise CameraError('Known FOV animation/task path is not observationally quiescent.')
    n = snap['native_controller']
    if any(extra_b['input_bytes_10_2d']) or any(n['input_vector_80']) or any(n['input_vector_9c']):
        raise CameraError('Camera input has not been released.')
    return snap,b


def verify_live(session,saved,link,animation):
    snap,anim = bracketed_capture(session,link,animation)
    return snap,anim,validate_pair(saved,snap)


class OneFovWrite:
    def __init__(self):
        self.used = False

    def commit(self,session,saved,link,animation,expected_identity,journal,consume_budget):
        if self.used:
            raise CameraError('The single FOV-write attempt is already consumed.')
        k = C.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes,k.OpenProcess.restype = [W.DWORD,W.BOOL,W.DWORD],W.HANDLE
        k.CloseHandle.argtypes,k.CloseHandle.restype = [W.HANDLE],W.BOOL
        h = k.OpenProcess(0x438,False,session.info.pid)
        if not h:
            raise CameraError(f'Cannot open the one-shot FOV-write handle ({C.get_last_error()}).')
        try:
            if identity(k,h) != expected_identity:
                raise CameraError('Process creation identity changed.')
            address = session.objects.spectator_controller+0x114
            k.VirtualQueryEx.argtypes = [W.HANDLE,C.c_void_p,C.POINTER(MEMORY_BASIC_INFORMATION),C.c_size_t]
            k.VirtualQueryEx.restype = C.c_size_t
            region = MEMORY_BASIC_INFORMATION()
            if not k.VirtualQueryEx(h,C.c_void_p(address),C.byref(region),C.sizeof(region)):
                raise CameraError('Cannot inspect the FOV data range.')
            if (region.State!=0x1000 or region.Type!=0x20000 or region.Protect!=4 or
                address%4 or address<int(region.BaseAddress) or address+8>int(region.BaseAddress)+region.RegionSize):
                raise CameraError('FOV pair is not in one existing private RW range.')
            snap,anim,comparison = verify_live(session,saved,link,animation)
            n = saved['native_controller']
            payload = struct.pack('<2f',n['current_interface_fov'],n['target_interface_fov'])
            previous = session.memory.read(address,8)
            journal({'address':hex(address),'bytes':8,'old_hex':previous.hex(),'new_hex':payload.hex(),
                     'final_prewrite':snap,'animation':anim,'comparison':comparison})
            verify_live(session,saved,link,animation)
            if identity(k,h)!=expected_identity or session.memory.read(address,8)!=previous:
                raise CameraError('Identity or FOV fields changed immediately before commit.')
            k.WriteProcessMemory.argtypes = [W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
            k.WriteProcessMemory.restype = W.BOOL
            buf=C.create_string_buffer(payload);count=C.c_size_t()
            consume_budget()
            self.used=True
            call_start=time.perf_counter()
            ok=k.WriteProcessMemory(h,C.c_void_p(address),buf,8,C.byref(count))
            error=0 if ok else C.get_last_error()
            returned=time.perf_counter()
            return {'api_success':bool(ok),'bytes_written':count.value,'windows_error':error,
                    'write_attempts':1,'full_payload_written':bool(ok and count.value==8),
                    'call_started_monotonic':call_start,'returned_monotonic':returned}
        finally:
            k.CloseHandle(h)


def observe(session,saved,link,animation,outdir,returned):
    arrival=None;held=valid=dropped=0;hold_failed=False;failure=None;last=None
    max_angle=max_fov_hold=0.
    n=saved['native_controller']
    goal=struct.pack('<2f',n['current_interface_fov'],n['target_interface_fov'])
    with (outdir/'after.jsonl').open('x',encoding='utf8') as f:
        while time.perf_counter()-returned<8.5:
            s=None
            try:
                s,anim=bracketed_capture(session,link,animation)
                comparison=unchanged_pose(saved,s)
                max_angle=max(max_angle,comparison['orientation_difference_deg'])
                if session.memory.read(session.objects.spectator_controller+0x114,8)!=goal:
                    raise CameraError('Native FOV pair was overwritten after commit.')
                # Different native/FreeCamera/projection update stages are not a
                # frame-coherent success. Log/discard only this known mismatch;
                # identity, input, pose, target overwrite and animation errors
                # still stop immediately. The original time limit remains.
                validate_state(s,projection_may_be_transitioning=True)
                fov=abs(saved['camera']['horizontal_fov_deg']-s['camera']['horizontal_fov_deg'])
                now=time.perf_counter()-returned
                inside=fov<=.01 and s['raw_camera']['interface_fov']==n['current_interface_fov']
                if arrival is None and inside:arrival=now
                if arrival is not None:
                    held+=1;hold_failed=hold_failed or not inside;max_fov_hold=max(max_fov_hold,fov)
                last={'snapshot':s,'animation':anim,'metrics':{'elapsed_seconds_since_write_return':now,
                      'fov_error_deg':fov,'position_error':0.,'orientation_error_deg':comparison['orientation_difference_deg']}}
                f.write(json.dumps(last,ensure_ascii=False)+'\n');valid+=1
                if arrival is not None and now-arrival>=3 and held>=150:break
            except IncoherentSample as exc:
                dropped+=1;f.write(json.dumps({'drop':str(exc),'discarded_snapshot':s,
                    'elapsed_seconds_since_write_return':time.perf_counter()-returned})+'\n')
            except CameraError as exc:
                failure=str(exc);f.write(json.dumps({'stopped':failure,'failed_snapshot':s})+'\n');break
            time.sleep(.02)
    elapsed=time.perf_counter()-returned
    return {'fov_return_and_hold_passed':arrival is not None and arrival<=5 and elapsed-arrival>=3
            and held>=150 and not hold_failed and failure is None,
            'arrival_seconds_since_write_return':arrival,'elapsed_seconds_since_write_return':elapsed,
            'valid_samples':valid,'dropped_samples':dropped,'hold_valid_samples':held,
            'hold_failed':hold_failed,'failure':failure,'max_position_error':0.,
            'max_orientation_error_deg':max_angle,'max_hold_fov_error_deg':max_fov_hold,'last':last,
            'visual_match_verified':False,'frame_synchronized':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture',required=True,type=Path)
    ap.add_argument('--run-dir',required=True,type=Path)
    ap.add_argument('--budget-path',type=Path)
    ap.add_argument('--execute',action='store_true')
    ap.add_argument('--ui-replay-confirmed',action='store_true')
    args=ap.parse_args()
    args.run_dir.mkdir(parents=True,exist_ok=False)
    raw=args.capture.read_bytes();saved=json.loads(raw)
    report={'scope':'authorized one-shot R3-F current/target interface-FOV restore',
            'started_utc':datetime.now(timezone.utc).isoformat(),'capture':str(args.capture.resolve()),
            'capture_sha256':hashlib.sha256(raw).hexdigest(),'execution_requested':args.execute,
            'write_attempts':0,'frame_synchronized':False,'active_engine_root_verified':False,
            'supervision':'computer use plus guarded live readback'}
    def journal(v=None):
        if v is not None:report['prepared_write']=v
        atomic_json(args.run_dir/'report.json',report)
    writer=None;journal()
    try:
        validate_state(saved)
        if args.execute and (not args.ui_replay_confirmed or args.budget_path is None):
            raise CameraError('Execution needs current UI replay confirmation and a persistent attempt budget.')
        if args.budget_path is not None and args.budget_path.exists():
            raise CameraError('This FOV trial already consumed its persistent write budget.')
        with CameraSession.connect() as session:
            if session.profile!=PROFILE_1121:raise CameraError('Wrong exact build.')
            process=identity(session.memory.k,session.memory.handle);report['process_identity']=process
            captured=datetime.fromisoformat(saved['captured_at_utc']).timestamp()
            created=(process['created_filetime']-116444736000000000)/1e7
            if not created<=captured<=time.time()+1:raise CameraError('Reference timestamp/creation identity is invalid.')
            links=battle_links(session)
            if len(links)!=1:raise CameraError('No unique BattleController update chain.')
            link=links[0];report['battle_link']=link;animation=AnimationProbe(session)
            first=None;pre=[];drops=0;start=time.perf_counter()
            while time.perf_counter()-start<4:
                try:
                    snap,anim,comparison=verify_live(session,saved,link,animation)
                    if first is None:first=snap
                    if (first['camera']!=snap['camera'] or first['native_controller']!=snap['native_controller']):
                        raise CameraError('Camera/controller drifted during FOV preflight.')
                    pre.append({'snapshot':snap,'animation':anim})
                    if len(pre)>=100 and time.perf_counter()-start>=2:break
                except IncoherentSample:drops+=1
                time.sleep(.02)
            if len(pre)<100:raise CameraError('Not enough stable preflight samples.')
            with (args.run_dir/'before.jsonl').open('x',encoding='utf8') as f:
                for row in pre:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            report.update(before=snap,comparison=comparison,preflight_samples=len(pre),preflight_drops=drops);journal()
            if not args.execute:
                report['status']='dry_run_passed';journal()
                print(json.dumps({'status':report['status'],'comparison':comparison}));return 0
            def consume_budget():
                with args.budget_path.open('x',encoding='utf8') as f:
                    json.dump({'capture_sha256':report['capture_sha256'],'process_identity':process,
                               'prepared_write':report['prepared_write'],'utc':datetime.now(timezone.utc).isoformat()},f,ensure_ascii=False)
            writer=OneFovWrite()
            result=writer.commit(session,saved,link,animation,process,journal,consume_budget)
            report.update(write_result=result,write_attempts=1);journal()
            if not result['full_payload_written']:raise CameraError('Incomplete write; no retry/rollback.')
            report['observation']=observe(session,saved,link,animation,args.run_dir,result['returned_monotonic'])
            report['status']='completed' if report['observation']['fov_return_and_hold_passed'] else 'observed_failure'
            journal();print(json.dumps({k:v for k,v in report.items() if k in ('status','write_result','comparison')}))
            return 0 if report['status']=='completed' else 2
    except Exception as exc:
        report.update(status='stopped',error=f'{type(exc).__name__}: {exc}',write_attempts=int(writer.used) if writer else 0)
        journal();print(report['error'],file=sys.stderr);return 2


if __name__=='__main__':
    raise SystemExit(main())
