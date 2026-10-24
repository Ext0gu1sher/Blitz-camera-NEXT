"""Authorized R3-Y experiment: one 8-byte native target-angle write, then RPM.

Dry run by default. Separate from the camera workstation. No injection, hooks,
remote calls, protection changes, thread suspension, retry or automatic undo.
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
# Pure helper reuse only; never instantiate/call the R1 position writer.
from restore_position_1121_once import identity, angle_difference


def validate_pair(saved, current):
    for s in (saved, current):
        if s['build']['sha256'] != PROFILE_1121.sha256 or not s['replay']['paused']:
            raise CameraError('R3-Y requires the exact paused 11.21 build.')
        n, r = s['native_controller'], s['raw_camera']
        values = s['camera']['position']+s['camera']['quaternion']+[s['camera']['horizontal_fov_deg']]
        values += n['target_angles']+n['smoothed_angles']+[n['native_roll_radians'],
            n['current_interface_fov'],n['target_interface_fov'],r['base_roll_deg'],r['aspect'],r['fov_scale']]
        if len(n['target_angles']) != 2 or not all(math.isfinite(v) for v in values):
            raise CameraError('Invalid angle/reference state.')
        if abs(n['target_angles'][1]) > 80 or abs(n['target_angles'][0]) > 1e6:
            raise CameraError('Avoid pitch extremes or excessive accumulated yaw in R3-Y.')
        if n['native_roll_radians'] != 0 or r['base_roll_deg'] != 0:
            raise CameraError('This yaw/pitch-only trial requires both roll layers to be zero.')
        if max(abs(a-b) for a,b in zip(n['target_angles'],n['smoothed_angles'])) > .001:
            raise CameraError('Native orientation has not settled.')
        expected = quaternion_from_angles(90-n['target_angles'][0],-n['target_angles'][1],0)
        if angle_difference(expected,s['camera']['quaternion']) > .01:
            raise CameraError('Native target angles do not match the settled camera orientation.')
        if not (n['current_interface_fov']==n['target_interface_fov']==r['interface_fov']):
            raise CameraError('Interface FOV is not settled.')
    if saved['session_id'] != current['session_id'] or saved['addresses'] != current['addresses']:
        raise CameraError('Camera/replay identity changed.')
    if any(saved['replay'][k] != current['replay'][k] for k in ('time','origin','rate')):
        raise CameraError('Replay clock changed.')
    distance = math.dist(saved['camera']['position'],current['camera']['position'])
    fov = abs(saved['camera']['horizontal_fov_deg']-current['camera']['horizontal_fov_deg'])
    if distance > .01 or fov > .01:
        raise CameraError('R3-Y requires unchanged XYZ and FOV.')
    for key in ('aspect','fov_scale'):
        if saved['raw_camera'][key] != current['raw_camera'][key]:
            raise CameraError('Viewport/FOV scale changed.')
    for key in ('current_interface_fov','target_interface_fov','target_position'):
        if saved['native_controller'][key] != current['native_controller'][key]:
            raise CameraError('A non-angle controller target changed.')
    a,b = saved['native_controller']['target_angles'],current['native_controller']['target_angles']
    dy,dp = abs(a[0]-b[0]),abs(a[1]-b[1])
    if not 10 <= dy <= 45 or not 3 <= dp <= 15 or math.floor(a[0]/360)!=math.floor(b[0]/360):
        raise CameraError(f'R3-Y bounds: yaw 10..45°, pitch 3..15°, same accumulated turn; actual {dy:.6f}/{dp:.6f}.')
    return {'position_difference':distance,'fov_difference_deg':fov,
            'native_yaw_difference_deg':dy,'native_pitch_difference_deg':dp,
            'orientation_difference_deg':angle_difference(saved['camera']['quaternion'],current['camera']['quaternion'])}


def guard_battle(session, link):
    session._guard()
    p,owner = int(link['battle_controller'],16),int(link['owner_at_150'],16)
    for address,value in ((p,session.live(0x37f8f70)),(p+0x128,session.live(0x37f8fb0)),
        (p+0x120,session.objects.context),(p+0x150,owner),(owner+0x68,session.objects.spectator_controller)):
        if session.memory.u32(address) != value:
            raise CameraError('Battle-controller update chain changed.')


def verify_live(session, saved, link, animation):
    guard_battle(session,link)
    before = animation.observe()
    extra_a = controller_extra(session)
    snap = session.capture(require_paused=True)
    extra_b = controller_extra(session)
    after = animation.observe()
    if extra_a != extra_b or structural_signature(before) != structural_signature(after):
        raise IncoherentSample('Controller/animation changed across capture.')
    if not after['observed_quiescent']:
        raise CameraError('Known animation/task path is not observationally quiescent.')
    n = snap['native_controller']
    if any(extra_b['input_bytes_10_2d']) or any(n['input_vector_80']) or any(n['input_vector_9c']):
        raise CameraError('Camera input is not released.')
    if math.dist(n['target_position'],snap['camera']['position'])>.01:
        raise CameraError('Position has not settled.')
    return snap,after,validate_pair(saved,snap)


class OneAngleWrite:
    def __init__(self):
        self.used = False

    def commit(self, session, saved, link, animation, expected_identity, journal, consume_budget):
        if self.used:
            raise CameraError('The single angle-write attempt is already consumed.')
        k = C.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes,k.OpenProcess.restype=[W.DWORD,W.BOOL,W.DWORD],W.HANDLE
        k.CloseHandle.argtypes,k.CloseHandle.restype=[W.HANDLE],W.BOOL
        h = k.OpenProcess(0x438,False,session.info.pid)
        if not h:
            raise CameraError(f'Cannot open the one-shot angle-write handle ({C.get_last_error()}).')
        try:
            if identity(k,h) != expected_identity:
                raise CameraError('Process creation identity changed.')
            address = session.objects.spectator_controller+0x58
            k.VirtualQueryEx.argtypes=[W.HANDLE,C.c_void_p,C.POINTER(MEMORY_BASIC_INFORMATION),C.c_size_t]
            k.VirtualQueryEx.restype=C.c_size_t
            region = MEMORY_BASIC_INFORMATION()
            if not k.VirtualQueryEx(h,C.c_void_p(address),C.byref(region),C.sizeof(region)):
                raise CameraError('Cannot inspect target-angle data range.')
            if (region.State!=0x1000 or region.Type!=0x20000 or region.Protect!=4 or
                address%4 or address<int(region.BaseAddress) or address+8>int(region.BaseAddress)+region.RegionSize):
                raise CameraError('Target angles are not in one existing private RW range.')
            snap,anim,comparison = verify_live(session,saved,link,animation)
            payload = struct.pack('<2f',*saved['native_controller']['target_angles'])
            previous = session.memory.read(address,8)
            journal({'address':hex(address),'bytes':8,'old_hex':previous.hex(),'new_hex':payload.hex(),
                     'final_prewrite':snap,'animation':anim,'comparison':comparison})
            verify_live(session,saved,link,animation)
            if identity(k,h)!=expected_identity or session.memory.read(address,8)!=previous:
                raise CameraError('Identity or angle target changed immediately before commit.')
            k.WriteProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
            k.WriteProcessMemory.restype=W.BOOL
            buf=C.create_string_buffer(payload);count=C.c_size_t()
            # Persist the budget before calling Windows. Any later exception forbids retry.
            consume_budget()
            self.used=True
            ok=k.WriteProcessMemory(h,C.c_void_p(address),buf,8,C.byref(count))
            return {'api_success':bool(ok),'bytes_written':count.value,
                    'windows_error':0 if ok else C.get_last_error(),'write_attempts':1,
                    'full_payload_written':bool(ok and count.value==8)}
        finally:
            k.CloseHandle(h)


def observe(session,saved,link,outdir):
    began=time.perf_counter();arrival=None;held=valid=dropped=0;hold_failed=False;failure=None
    peak_position=peak_fov=peak_hold_angle=0.;last=None
    goal=struct.pack('<2f',*saved['native_controller']['target_angles'])
    with (outdir/'after.jsonl').open('x',encoding='utf8') as f:
        while time.perf_counter()-began<8.5:
            try:
                guard_battle(session,link)
                s=session.capture(require_paused=True)
                if (s['session_id']!=saved['session_id'] or s['addresses']!=saved['addresses'] or
                    any(s['replay'][k]!=saved['replay'][k] for k in ('time','origin','rate'))):
                    raise CameraError('Replay/camera identity or clock changed after commit.')
                if session.memory.read(session.objects.spectator_controller+0x58,8)!=goal:
                    raise CameraError('Native target angles were overwritten after commit.')
                pos=math.dist(saved['camera']['position'],s['camera']['position'])
                angle=angle_difference(saved['camera']['quaternion'],s['camera']['quaternion'])
                fov=abs(saved['camera']['horizontal_fov_deg']-s['camera']['horizontal_fov_deg'])
                peak_position=max(peak_position,pos);peak_fov=max(peak_fov,fov)
                if pos>.01 or fov>.01 or s['native_controller']['native_roll_radians']!=0 or s['raw_camera']['base_roll_deg']!=0:
                    raise CameraError('A non-angle camera component changed after commit.')
                now=time.perf_counter()-began
                inside=angle<=.05
                if arrival is None and inside:arrival=now
                if arrival is not None:
                    held+=1;hold_failed=hold_failed or not inside;peak_hold_angle=max(peak_hold_angle,angle)
                last={'snapshot':s,'metrics':{'elapsed_seconds':now,'angle_error_deg':angle,'position_error':pos,'fov_error_deg':fov}}
                f.write(json.dumps(last,ensure_ascii=False)+'\n');valid+=1
                if arrival is not None and now-arrival>=3 and held>=150:break
            except IncoherentSample as exc:
                dropped+=1;f.write(json.dumps({'drop':str(exc),'elapsed_seconds':time.perf_counter()-began},ensure_ascii=False)+'\n')
            except CameraError as exc:
                failure=str(exc);f.write(json.dumps({'stopped':failure})+'\n');break
            time.sleep(.02)
    elapsed=time.perf_counter()-began
    return {'orientation_return_and_hold_passed':arrival is not None and arrival<=5 and
            elapsed-arrival>=3 and held>=150 and not hold_failed and failure is None,
            'arrival_seconds':arrival,'elapsed_seconds':elapsed,'valid_samples':valid,'dropped_samples':dropped,
            'hold_valid_samples':held,'hold_failed':hold_failed,'failure':failure,
            'max_position_error':peak_position,'max_fov_error_deg':peak_fov,
            'max_hold_angle_error_deg':peak_hold_angle,'last':last,
            'visual_match_verified':False,'frame_synchronized':False,'nonzero_roll_restore_verified':False}


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
    report={'scope':'authorized one-shot R3-Y yaw/pitch target restore','started_utc':datetime.now(timezone.utc).isoformat(),
            'capture':str(args.capture.resolve()),'capture_sha256':hashlib.sha256(raw).hexdigest(),
            'execution_requested':args.execute,'write_attempts':0,'frame_synchronized':False,
            'active_engine_root_verified':False,'supervision':'computer use plus guarded live readback'}
    def journal(v=None):
        if v is not None:report['prepared_write']=v
        atomic_json(args.run_dir/'report.json',report)
    writer=None;journal()
    try:
        if args.execute and (not args.ui_replay_confirmed or args.budget_path is None):
            raise CameraError('Execution needs current UI replay confirmation and a persistent attempt budget.')
        if args.budget_path is not None and args.budget_path.exists():
            raise CameraError('This reference trial already consumed its persistent write budget.')
        with CameraSession.connect() as session:
            if session.profile!=PROFILE_1121:raise CameraError('Wrong exact build.')
            process=identity(session.memory.k,session.memory.handle);report['process_identity']=process
            captured=datetime.fromisoformat(saved['captured_at_utc']).timestamp()
            created=(process['created_filetime']-116444736000000000)/1e7
            if not created<=captured<=time.time()+1:raise CameraError('Reference capture timestamp/creation identity is invalid.')
            links=battle_links(session)
            if len(links)!=1:raise CameraError('No unique BattleController update chain.')
            link=links[0];report['battle_link']=link;animation=AnimationProbe(session)
            first=None;pre=[];drops=0;start=time.perf_counter()
            while time.perf_counter()-start<4:
                try:
                    snap,anim,comparison=verify_live(session,saved,link,animation)
                    if first is None:first=snap
                    if (math.dist(first['camera']['position'],snap['camera']['position'])>.001 or
                        angle_difference(first['camera']['quaternion'],snap['camera']['quaternion'])>.001):
                        raise CameraError('Pose drifted during preflight.')
                    pre.append({'snapshot':snap,'animation':anim})
                    if len(pre)>=100 and time.perf_counter()-start>=2:break
                except IncoherentSample:drops+=1
                time.sleep(.02)
            if len(pre)<100:raise CameraError('Not enough stable preflight samples.')
            with (args.run_dir/'before.jsonl').open('x',encoding='utf8') as f:
                for row in pre:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            report.update(before=snap,comparison=comparison,preflight_samples=len(pre),preflight_drops=drops);journal()
            if not args.execute:
                report['status']='dry_run_passed';journal();print(json.dumps({'status':report['status'],'comparison':comparison}));return 0
            def consume_budget():
                with args.budget_path.open('x',encoding='utf8') as f:
                    json.dump({'capture_sha256':report['capture_sha256'],'process_identity':process,
                               'prepared_write':report['prepared_write'],'utc':datetime.now(timezone.utc).isoformat()},f,ensure_ascii=False)
            writer=OneAngleWrite()
            result=writer.commit(session,saved,link,animation,process,journal,consume_budget)
            report.update(write_result=result,write_attempts=1);journal()
            if not result['full_payload_written']:raise CameraError('Incomplete write; no retry/rollback.')
            report['observation']=observe(session,saved,link,args.run_dir)
            report['status']='completed' if report['observation']['orientation_return_and_hold_passed'] else 'observed_failure'
            journal();print(json.dumps({k:v for k,v in report.items() if k in ('status','write_result','comparison')}))
            return 0 if report['status']=='completed' else 2
    except Exception as exc:
        report.update(status='stopped',error=f'{type(exc).__name__}: {exc}',write_attempts=int(writer.used) if writer else 0)
        journal();print(report['error'],file=sys.stderr);return 2


if __name__=='__main__':
    raise SystemExit(main())
