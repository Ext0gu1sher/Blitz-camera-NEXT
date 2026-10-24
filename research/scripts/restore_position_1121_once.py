"""Manually supervised R1 experiment: one 12-byte target-position write, then read only.

Not imported by the workstation. Default operation is a dry run. No injection,
remote calls, protection changes, thread suspension, retries, or automatic undo.
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
from blitzcam.profile import CameraError, IncoherentSample, PROFILE_1121
from blitzcam.project import atomic_json
from blitzcam.reader import CameraSession
from prepare_restore_1121_readonly import battle_links, controller_extra


def angle_difference(a, b):
    na, nb = math.sqrt(sum(x*x for x in a)), math.sqrt(sum(x*x for x in b))
    if not na or not nb:
        raise CameraError('Invalid orientation.')
    dot = min(1., abs(sum(x*y for x,y in zip(a,b))/(na*nb)))
    return math.degrees(2*math.acos(dot))


def validate_pair(saved, current, max_distance=3.):
    if not math.isfinite(max_distance) or not .5 <= max_distance <= 25:
        raise CameraError('The supervised displacement ceiling must be between 0.5 and 25 world units.')
    for snap in (saved, current):
        if snap['build']['sha256'] != PROFILE_1121.sha256:
            raise CameraError('Capture build does not match the exact supported client.')
        if not snap['replay']['paused']:
            raise CameraError('Replay must remain paused.')
        values = snap['camera']['position'] + snap['camera']['quaternion'] + [snap['camera']['horizontal_fov_deg']]
        if not all(math.isfinite(v) for v in values):
            raise CameraError('Non-finite target or camera state.')
    if saved['session_id'] != current['session_id'] or saved['addresses'] != current['addresses']:
        raise CameraError('Saved capture belongs to another camera/replay identity.')
    if saved['replay']['time'] != current['replay']['time'] or saved['replay']['origin'] != current['replay']['origin']:
        raise CameraError('Replay time/origin changed since capture.')
    distance = math.dist(saved['camera']['position'], current['camera']['position'])
    angle = angle_difference(saved['camera']['quaternion'], current['camera']['quaternion'])
    fov = abs(saved['camera']['horizontal_fov_deg']-current['camera']['horizontal_fov_deg'])
    if not .5 <= distance <= max_distance:
        raise CameraError(f'R1 distance must be 0.5–{max_distance:g} world units; actual {distance:.6f}.')
    if angle > .05 or fov > .01:
        raise CameraError(f'R1 requires unchanged orientation/FOV; angle {angle:.6f}°, FOV {fov:.6f}°.')
    return {'distance': distance, 'orientation_difference_deg': angle, 'fov_difference_deg': fov}


def identity(kernel, handle):
    kernel.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)]*4
    kernel.GetProcessTimes.restype = W.BOOL
    kernel.GetProcessId.argtypes, kernel.GetProcessId.restype = [W.HANDLE], W.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = W.BOOL
    times = [W.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(C.byref(t) for t in times)):
        raise CameraError(f'Cannot verify process creation time ({C.get_last_error()}).')
    path = C.create_unicode_buffer(32768); size = W.DWORD(len(path))
    if not kernel.QueryFullProcessImageNameW(handle,0,path,C.byref(size)):
        raise CameraError('Cannot verify process path.')
    created = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
    return {'pid': int(kernel.GetProcessId(handle)), 'created_filetime': created,
            'path': str(Path(path.value).resolve())}


def verify_live(session, saved, link, max_distance=3.):
    session._guard()
    p = int(link['battle_controller'],16); owner = int(link['owner_at_150'],16)
    mem = session.memory
    for address, value in [(p,session.live(0x37f8f70)),(p+0x128,session.live(0x37f8fb0)),
                           (p+0x120,session.objects.context),(p+0x150,owner),
                           (owner+0x68,session.objects.spectator_controller)]:
        if mem.u32(address) != value:
            raise CameraError('Battle-controller update chain changed.')
    before = controller_extra(session)
    snap = session.capture(require_paused=True)
    after = controller_extra(session)
    if before != after:
        raise CameraError('Controller changed during preflight.')
    if any(after['input_bytes_10_2d']) or any(snap['native_controller']['input_vector_80']) or any(snap['native_controller']['input_vector_9c']):
        raise CameraError('Release camera input before the experiment.')
    if math.dist(after['target_position'],snap['camera']['position']) > .01:
        raise CameraError('Native camera is still settling.')
    if snap['native_controller']['current_interface_fov'] != snap['native_controller']['target_interface_fov']:
        raise CameraError('FOV has not settled.')
    if not all(lo+.1 <= x <= hi-.1 for lo,x,hi in zip(after['bounds_min'],saved['camera']['position'],after['bounds_max'])):
        raise CameraError('Saved position is outside or too near the primary bounds.')
    # Inspect the additional 24-byte position regions traversed by the native updater.
    begin,end = (int(x,16) for x in after['position_boxes_begin_end'])
    if end < begin or (end-begin)%24 or end-begin > 24*128:
        raise CameraError('Unrecognized position-region list.')
    boxes = [list(struct.unpack('<6f',mem.read(p,24))) for p in range(begin,end,24)]
    for box in boxes:
        if not all(math.isfinite(x) for x in box) or any(box[i]>box[i+3] for i in range(3)):
            raise CameraError('Invalid position-region bounds.')
        a,b = saved['camera']['position'], snap['camera']['position']
        # A small near-linear path needs to avoid a region that could raise its Z.
        for t in [i/20 for i in range(21)]:
            v=[x+(y-x)*t for x,y in zip(a,b)]
            if all(box[i]<=v[i]<=box[i+3] for i in range(3)) and v[2]<box[5]-.01:
                raise CameraError('The return segment enters a native position-adjustment region.')
    return snap, {**after,'position_regions':boxes}, validate_pair(saved,snap,max_distance)


class OneTargetWrite:
    """One-shot budget is consumed even when Windows reports a failed/partial write."""
    def __init__(self):
        self.used = False

    def commit(self, session, saved, link, expected_identity, before_attempt, max_distance=3.):
        if self.used:
            raise CameraError('This experiment has already consumed its one write attempt.')
        k = C.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.argtypes, k.OpenProcess.restype = [W.DWORD,W.BOOL,W.DWORD],W.HANDLE
        k.CloseHandle.argtypes, k.CloseHandle.restype = [W.HANDLE],W.BOOL
        # QUERY_INFORMATION | VM_READ | VM_WRITE | VM_OPERATION; never debug privilege.
        handle = k.OpenProcess(0x438,False,session.info.pid)
        if not handle:
            raise CameraError(f'Cannot open the one-shot data-write handle ({C.get_last_error()}).')
        try:
            if identity(k,handle) != expected_identity:
                raise CameraError('Process identity changed before the write.')
            address = session.objects.spectator_controller+0xac
            k.VirtualQueryEx.argtypes = [W.HANDLE,C.c_void_p,C.POINTER(MEMORY_BASIC_INFORMATION),C.c_size_t]
            k.VirtualQueryEx.restype = C.c_size_t
            region = MEMORY_BASIC_INFORMATION()
            if not k.VirtualQueryEx(handle,C.c_void_p(address),C.byref(region),C.sizeof(region)):
                raise CameraError('Cannot inspect target data protection.')
            if (region.State != 0x1000 or region.Type != 0x20000 or region.Protect != 4 or
                address%4 or address+12 > int(region.BaseAddress)+region.RegionSize):
                raise CameraError('Target is not one existing private read/write data range.')
            snap, extra, comparison = verify_live(session,saved,link,max_distance)
            payload = struct.pack('<3f',*saved['camera']['position'])
            previous = session.memory.read(address,12)
            before_attempt({'address':hex(address),'bytes':12,'old_hex':previous.hex(),'new_hex':payload.hex(),
                            'final_prewrite':snap,'extra':extra,'comparison':comparison})
            # Recheck identity/mode after journaling. This still is not an atomic game-thread fence.
            verify_live(session,saved,link,max_distance)
            if session.memory.read(address,12) != previous:
                raise CameraError('Target position changed immediately before commit.')
            k.WriteProcessMemory.argtypes = [W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
            k.WriteProcessMemory.restype = W.BOOL
            buffer = C.create_string_buffer(payload); count = C.c_size_t()
            self.used = True
            ok = k.WriteProcessMemory(handle,C.c_void_p(address),buffer,12,C.byref(count))
            return {'api_success':bool(ok),'bytes_written':count.value,
                    'windows_error':0 if ok else C.get_last_error(),'write_attempts':1,
                    'full_payload_written':bool(ok and count.value==12)}
        finally:
            k.CloseHandle(handle)


def observe(session, saved, run_dir):
    started = time.perf_counter(); arrival = None; held = 0; hold_failed = False
    attempts = valid = dropped = 0; max_errors = dict(eye_error=0.,rotation_error=0.,vp_error=0.)
    last = None; failure = None
    with (run_dir/'after.jsonl').open('x',encoding='utf-8') as out:
        while time.perf_counter()-started < 8.5:
            attempts += 1
            try:
                snap = session.capture(require_paused=True)
                now=time.perf_counter()-started
                error=math.dist(saved['camera']['position'],snap['camera']['position'])
                angle=angle_difference(saved['camera']['quaternion'],snap['camera']['quaternion'])
                fov=abs(saved['camera']['horizontal_fov_deg']-snap['camera']['horizontal_fov_deg'])
                metrics={'elapsed_seconds':now,'position_error':error,'angle_error_deg':angle,'fov_error_deg':fov}
                if snap['replay']['time'] != saved['replay']['time']:
                    raise CameraError('Replay time changed after commit.')
                inside=error<=.01 and angle<=.05 and fov<=.01
                if arrival is None and inside:
                    arrival=now
                if arrival is not None:
                    if not inside: hold_failed=True
                    held += 1
                for k in max_errors: max_errors[k]=max(max_errors[k],snap['quality'][k])
                last={'snapshot':snap,'metrics':metrics}; valid += 1
                out.write(json.dumps(last,ensure_ascii=False,separators=(',',':'))+'\n')
                if arrival is not None and now-arrival>=3 and held>=150:
                    break
            except IncoherentSample as exc:
                dropped += 1
                out.write(json.dumps({'drop':str(exc),'elapsed_seconds':time.perf_counter()-started},ensure_ascii=False)+'\n')
            except CameraError as exc:
                failure=str(exc); break
            time.sleep(.02)
    elapsed=time.perf_counter()-started
    passed=(arrival is not None and arrival<=5 and elapsed-arrival>=3 and held>=150 and not hold_failed and failure is None)
    return {'position_return_and_hold_passed':passed,'arrival_seconds':arrival,'elapsed_seconds':elapsed,
            'attempts':attempts,'valid_samples':valid,'dropped_samples':dropped,'hold_valid_samples':held,
            'hold_failed':hold_failed,'failure':failure,'max_matrix_errors':max_errors,'last':last,
            'visual_match_verified':False,'frame_synchronized':False,'full_pose_restore_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',required=True,type=Path)
    parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--manual-replay-confirmed',action='store_true')
    parser.add_argument('--max-distance',type=float,default=3.)
    args=parser.parse_args()
    args.run_dir.mkdir(parents=True,exist_ok=False)
    raw=args.capture.read_bytes(); saved=json.loads(raw)
    report={'started_at_utc':datetime.now(timezone.utc).isoformat(),'capture_path':str(args.capture.resolve()),
            'capture_sha256':hashlib.sha256(raw).hexdigest(),'execution_requested':args.execute,
            'scope':'one-shot supervised R1 target-position experiment','write_attempts':0,
            'max_distance_client_units':args.max_distance,
            'active_engine_root_verified':False,'frame_synchronized':False}
    def journal(value=None):
        if value is not None: report['prepared_write']=value
        atomic_json(args.run_dir/'report.json',report)
    journal()
    writer=None
    try:
        with CameraSession.connect() as session:
            if session.profile != PROFILE_1121:
                raise CameraError('Only the exact verified 11.21 build is allowed.')
            process=identity(session.memory.k,session.memory.handle)
            report['process_identity']=process
            captured=datetime.fromisoformat(saved['captured_at_utc']).timestamp()
            created=(process['created_filetime']-116444736000000000)/10000000
            if captured<created or captured>time.time()+1:
                raise CameraError('Saved capture predates this process or has an invalid timestamp.')
            links=battle_links(session)
            if len(links)!=1:
                raise CameraError('Cannot confirm a unique battle-controller update chain.')
            report['battle_link']=links[0]
            first=None
            for _ in range(100):
                snap,extra,comparison=verify_live(session,saved,links[0],args.max_distance)
                if first is None: first=snap
                if math.dist(first['camera']['position'],snap['camera']['position'])>.001:
                    raise CameraError('Camera moved during the two-second preflight.')
                time.sleep(.02)
            report.update(before=snap,preflight_extra=extra,comparison=comparison)
            journal()
            if not args.execute:
                report['status']='dry_run_passed'; journal(); print(json.dumps(report['comparison'])); return 0
            if not args.manual_replay_confirmed:
                raise CameraError('Manual local-replay confirmation is required for the supervised trial.')
            writer=OneTargetWrite()
            result=writer.commit(session,saved,links[0],process,journal,args.max_distance)
            report['write_result']=result; report['write_attempts']=1; journal()
            if not result['full_payload_written']:
                raise CameraError('Write was incomplete; no retry or automatic undo will be performed.')
            report['observation']=observe(session,saved,args.run_dir)
            report['status']='completed' if report['observation']['position_return_and_hold_passed'] else 'observed_failure'
            journal()
            print(json.dumps({'status':report['status'],'write_result':result,'observation':{k:v for k,v in report['observation'].items() if k!='last'}},ensure_ascii=False))
            return 0 if report['status']=='completed' else 2
    except Exception as exc:
        if writer is not None:
            report['write_attempts']=int(writer.used)
        report['status']='stopped'; report['error']=f'{type(exc).__name__}: {exc}'; journal()
        print(report['error'],file=sys.stderr); return 2


if __name__=='__main__':
    raise SystemExit(main())
