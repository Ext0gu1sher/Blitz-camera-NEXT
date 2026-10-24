"""Bounded paused-replay FOV-only diagnostic; dry-run unless --execute.

Uses the already tested interface-FOV pair only, original range 54..64.
Never writes position, angles, shadow data, game code, or game files.
"""
import argparse
import ctypes as C
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
from restore_fov_1121_once import (
    CameraError,IncoherentSample,PROFILE_1121,CameraSession,AnimationProbe,
    battle_links,identity,validate_state,unchanged_pose,bracketed_capture)
from play_combined_1121_trial import StreamWriter

MAX_WRITES=302  # 60 identical writes, one 54 preparation, 241 ramp samples.


def encode_fov(value):
    if not math.isfinite(value) or not 54<=value<=64:
        raise CameraError('Diagnostic FOV must stay in the previously tested 54..64 range.')
    return struct.pack('<2f',value,value)


class FovOnlyWriter(StreamWriter):
    def commit_fov(self,value,guard):
        address=self.s.objects.spectator_controller+0x114
        try:
            data=encode_fov(value)
            if self.failed or self.h is None or self.calls>=MAX_WRITES:
                raise CameraError('Diagnostic is closed, failed or exhausted; no retry.')
            if set(self.expected)!={address} or len(self.expected[address])!=8:
                raise CameraError('Only the one FOV pair may be writable.')
            guard()
            if identity(self.k,self.h)!=self.process:
                raise CameraError('Process identity changed.')
            if self.s.memory.read(address,8)!=self.expected[address]:
                raise CameraError('Native or external FOV target changed; stop.')
            if not self.used:self.reserve();self.used=True
            self.journal({'intent':True,'call':self.calls+1,'address':hex(address),
                          'old_hex':self.expected[address].hex(),'new_hex':data.hex()})
            buf=C.create_string_buffer(data);count=C.c_size_t()
            self.calls+=1;started=time.perf_counter()
            ok=self.k.WriteProcessMemory(self.h,C.c_void_p(address),buf,8,C.byref(count))
            self.last_return=time.perf_counter()
            self.journal({'call':self.calls,'success':bool(ok),'bytes_written':count.value,
                          'fov':value,'started_monotonic':started,'returned_monotonic':self.last_return})
            if not ok or count.value!=8:
                raise CameraError('Incomplete FOV write; no retry or automatic rollback.')
            self.expected[address]=data
        except Exception:
            self.failed=True
            raise


def shadow_state(session,pointer):
    if session.memory.u32(session.objects.render+0x8c)!=pointer:
        raise CameraError('ShadowPass link changed.')
    a=session.memory.read(pointer,0x5e0)
    b=session.memory.read(pointer,0x5e0)
    if a!=b:raise IncoherentSample('Shadow state changed between reads.')
    if struct.unpack_from('<I',a,0)[0]!=session.live(0x375b100):
        raise CameraError('ShadowPass type changed.')
    n=struct.unpack_from('<I',a,0x294)[0]
    if not 1<=n<=4:raise CameraError('Unsupported shadow cascade count.')
    width=list(struct.unpack_from('<4f',a,0x550))[:n]
    step=list(struct.unpack_from('<4f',a,0x560))[:n]
    resolution=struct.unpack_from('<f',a,0x5dc)[0]
    if not all(math.isfinite(v) and v>0 for v in width+step+[resolution]):
        raise CameraError('Invalid shadow coverage values.')
    return {'cached_projection':list(struct.unpack_from('<16f',a,0x380)),
            'resource_dirty':a[0x319],'count':n,
            'texture_extent':list(struct.unpack_from('<2I',a,0x274)),
            'resolution':resolution,'coverage_width':width,'texel_step':step}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--execute',action='store_true')
    ap.add_argument('--budget',type=Path)
    args=ap.parse_args()
    args.run_dir.mkdir(parents=True,exist_ok=False)
    report={'started_utc':datetime.now(timezone.utc).isoformat(),'execute':args.execute,
            'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'max_calls':MAX_WRITES,'write_range':'SpectatorCameraController +0x114, 8 bytes only',
            'scope':'same paused replay; unchanged XYZ/yaw/pitch; FOV64 repeated then 54->64',
            'frame_synchronized':False,'write_calls':0,'drops':0}
    writer=None
    def save():
        (args.run_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    save()
    try:
        if args.execute and (args.budget is None or args.budget.exists()):
            raise CameraError('Execution requires a fresh diagnostic budget.')
        with CameraSession.connect()as s:
            if s.profile!=PROFILE_1121:raise CameraError('Wrong exact executable build.')
            process=identity(s.memory.k,s.memory.handle)
            links=battle_links(s)
            if len(links)!=1:raise CameraError('No unique replay update link.')
            link=links[0];anim=AnimationProbe(s)
            reference,_=bracketed_capture(s,link,anim);validate_state(reference)
            n=reference['native_controller'];r=reference['raw_camera']
            if not(n['current_interface_fov']==n['target_interface_fov']==r['interface_fov']==64):
                raise CameraError('Expected stationary current B with interface FOV64.')
            sh=s.memory.u32(s.objects.render+0x8c)
            first_shadow=shadow_state(s,sh)
            report.update(process_identity=process,reference=reference,shadow_address=hex(sh),first_shadow=first_shadow)
            began=time.perf_counter()
            rows=[]
            def guard():
                snap,_=bracketed_capture(s,link,anim)
                validate_state(snap,projection_may_be_transitioning=True)
                unchanged_pose(reference,snap)
                if s.memory.u32(s.objects.render+0x8c)!=sh:raise CameraError('Shadow link changed.')
            with (args.run_dir/'samples.jsonl').open('x',encoding='utf8')as samples:
                def sample(phase):
                    try:
                        snap=s.capture(require_paused=True)
                        validate_state(snap,projection_may_be_transitioning=True)
                        unchanged_pose(reference,snap)
                        ss=shadow_state(s,sh)
                        row={'phase':phase,'elapsed':time.perf_counter()-began,
                             'fov':snap['raw_camera']['interface_fov'],
                             'controller_fov':snap['native_controller']['current_interface_fov'],
                             'projection':snap['raw_camera']['projection'],'shadow':ss,
                             'xyz':snap['camera']['position'],'quaternion':snap['camera']['quaternion'],
                             'replay':snap['replay']}
                        rows.append(row);samples.write(json.dumps(row)+'\n');samples.flush()
                    except IncoherentSample as e:
                        report['drops']+=1
                        samples.write(json.dumps({'phase':phase,'drop':str(e),'elapsed':time.perf_counter()-began})+'\n')
                def until(deadline,phase):
                    while time.perf_counter()<deadline:
                        sample(phase);time.sleep(.005)
                until(began+3,'baseline')
                guard()
                if len(rows)<100:raise CameraError('Insufficient stable baseline.')
                if not args.execute:
                    report.update(status='dry_run_passed',valid_samples=len(rows));save();return 0
                def reserve():
                    with args.budget.open('x',encoding='utf8')as f:
                        json.dump({'process':process,'source_sha256':report['source_sha256'],
                                   'max_calls':MAX_WRITES,'bytes_per_call':8,'range':report['write_range']},f)
                with (args.run_dir/'writes.jsonl').open('x',encoding='utf8')as writes:
                    def journal(x):writes.write(json.dumps(x)+'\n');writes.flush()
                    expected={s.objects.spectator_controller+0x114:encode_fov(64)}
                    with FovOnlyWriter(s,process,expected,journal,reserve)as writer:
                        start=time.perf_counter()
                        for i in range(60):
                            deadline=start+i/30;until(deadline,'identical_resubmission')
                            if time.perf_counter()-deadline>.15:raise CameraError('Schedule stalled.')
                            writer.commit_fov(64,guard);sample('identical_resubmission')
                        until(start+2,'identical_resubmission')
                        writer.commit_fov(54,guard)
                        until(time.perf_counter()+2,'prepare_54')
                        start=time.perf_counter()
                        for i in range(241):
                            deadline=start+i/30;until(deadline,'fov_ramp_30hz')
                            if time.perf_counter()-deadline>.15:raise CameraError('Schedule stalled.')
                            writer.commit_fov(54+10*i/240,guard);sample('fov_ramp_30hz')
                    # Writer handle closed before final observation.
                    until(time.perf_counter()+3,'settled_64')
                guard()
                final=s.capture(require_paused=True);unchanged_pose(reference,final)
                if final['raw_camera']['interface_fov']!=64:raise CameraError('Final FOV is not original 64.')
                report.update(status='completed',write_calls=writer.calls,valid_samples=len(rows),final=final)
                save();print(json.dumps({k:report[k]for k in ('status','write_calls','valid_samples','drops')}));return 0
    except Exception as e:
        report.update(status='stopped',error=f'{type(e).__name__}: {e}',write_calls=writer.calls if writer else 0)
        save();print(report['error'],file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
