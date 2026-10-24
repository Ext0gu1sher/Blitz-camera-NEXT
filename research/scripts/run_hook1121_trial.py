"""Version-locked per-instance camera Hook trial. Default is READ-ONLY preflight.

Execution loads ONLY the locally built and hashed research/native/hook1121.dll.
No inline patches, global vtable edits, debug privilege, or game-file changes.
Detached DLL deliberately stays resident to avoid unloading a prefetched callback.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime,timezone
import hashlib,json,math,struct,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from blitzcam.reader import CameraSession
from blitzcam.profile import PROFILE_1121,CameraError,IncoherentSample
from prepare_restore_1121_readonly import battle_links,controller_extra
from restore_position_1121_once import identity
from probe_pose_fov_1121_readonly import AnimationProbe
from restore_combined_1121_once import validate_snapshot,same_scene,check_path,bracketed_capture

INTS='magic size base battle owner context player scene scene_owner replay_controller game_camera camera spectator render shadow battle_vft update_vft shadow_vft context_vft player_vft camera_vft spectator_vft render_vft scene_vft scene_owner_vft replay_vft game_vft player_secondary_vft set_position set_direction refresh'.split()
class Vec(C.Structure):
    _pack_=4
    _fields_=[(x,C.c_float)for x in ('x','y','z')]
class Config(C.Structure):
    _pack_=4
    _fields_=[(n,C.c_uint32)for n in INTS]+[(n,C.c_float)for n in ('raw_time','origin','fov')]+[('angles',C.c_float*2),('projection',C.c_float*16)]+[(n,Vec)for n in ('direction','setter_direction','a','b')]
class Event(C.Structure):
    _pack_=4
    _fields_=[('commit',C.c_int32)]+[(n,C.c_uint32)for n in ('kind','thread','stage','updates','draws')]+[('qpc',C.c_int64),('elapsed',C.c_double),('dt',C.c_float)]+[(n,Vec)for n in ('position','goal','direction')]+[('fov',C.c_float),('angles',C.c_float*2),('view',C.c_float*16),('projection',C.c_float*16),('width',C.c_float*3),('step',C.c_float*3),('shadow_projection',(C.c_float*16)*3),('shadow_vp',(C.c_float*16)*3)]

def plain(value):
    if isinstance(value,C.Array):return[plain(x)for x in value]
    if isinstance(value,Vec):return[value.x,value.y,value.z]
    if isinstance(value,C.Structure):return{n:plain(getattr(value,n))for n,*_ in value._fields_}
    return value
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check_layout(layout):
    if C.sizeof(Config)!=layout['config_size']or C.sizeof(Event)!=layout['event_size']:
        raise CameraError('C/Python structure size mismatch.')
def pe_exports(path):
    b=Path(path).read_bytes();p=struct.unpack_from('<I',b,0x3c)[0];o=p+24
    if struct.unpack_from('<H',b,p+4)[0]!=0x14c:raise CameraError('Hook DLL must be x86.')
    secs=[]
    for i in range(struct.unpack_from('<H',b,p+6)[0]):
        q=o+struct.unpack_from('<H',b,p+20)[0]+40*i
        vs,r,rs,ro=struct.unpack_from('<4I',b,q+8);secs.append((r,rs,ro))
    def off(r):
        for v,n,k in secs:
            if v<=r<v+n:return k+r-v
        raise CameraError('Bad PE file RVA.')
    u=lambda r:struct.unpack_from('<I',b,off(r))[0]
    er,esz=struct.unpack_from('<II',b,o+96);q=off(er)
    nf,nn,fs,ns,ords=struct.unpack_from('<5I',b,q+20);result={}
    for i in range(nn):
        v=off(u(ns+4*i));name=b[v:b.index(0,v)].decode('ascii')
        index=struct.unpack_from('<H',b,off(ords+2*i))[0];result[name]=u(fs+4*index)
    return result

class Remote:
    def __init__(self,s,journal):
        self.s=s;self.k=C.WinDLL('kernel32',use_last_error=True);self.h=None;self.journal=journal;self.detach_address=None
        k=self.k
        k.OpenProcess.argtypes,k.OpenProcess.restype=[W.DWORD,W.BOOL,W.DWORD],W.HANDLE
        k.CloseHandle.argtypes,k.CloseHandle.restype=[W.HANDLE],W.BOOL
        k.WriteProcessMemory.argtypes,k.WriteProcessMemory.restype=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)],W.BOOL
        k.VirtualAllocEx.argtypes,k.VirtualAllocEx.restype=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,W.DWORD],C.c_void_p
        k.VirtualFreeEx.argtypes,k.VirtualFreeEx.restype=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD],W.BOOL
        k.CreateRemoteThread.argtypes,k.CreateRemoteThread.restype=[W.HANDLE,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p,W.DWORD,C.c_void_p],W.HANDLE
        k.WaitForSingleObject.argtypes,k.WaitForSingleObject.restype=[W.HANDLE,W.DWORD],W.DWORD
        k.GetExitCodeThread.argtypes,k.GetExitCodeThread.restype=[W.HANDLE,C.POINTER(W.DWORD)],W.BOOL
        k.K32EnumProcessModulesEx.argtypes,k.K32EnumProcessModulesEx.restype=[W.HANDLE,C.POINTER(W.HMODULE),W.DWORD,C.POINTER(W.DWORD),W.DWORD],W.BOOL
        k.K32GetModuleFileNameExW.argtypes,k.K32GetModuleFileNameExW.restype=[W.HANDLE,W.HMODULE,W.LPWSTR,W.DWORD],W.DWORD
    def __enter__(self):
        self.h=self.k.OpenProcess(0x43a,False,self.s.info.pid)
        if not self.h:raise CameraError(f'Hook trial access denied ({C.get_last_error()}).')
        if identity(self.k,self.h)!=identity(self.s.memory.k,self.s.memory.handle):self.__exit__();raise CameraError('Process identity mismatch.')
        return self
    def __exit__(self,*_):
        if self.h:
            # Detach while the handle is still open, including exception exits.
            # The DLL stays resident; the watchdog is an independent fallback.
            try:
                if self.detach_address:
                    self.call(self.detach_address,0,'supervisor exit detachment')
            except Exception as e:
                self.journal({'action':'exit_detachment_error','error':str(e)})
            finally:
                self.k.CloseHandle(self.h);self.h=None
    def write(self,address,data,label):
        buf=C.create_string_buffer(data);n=C.c_size_t()
        self.journal({'action':'write_intent','address':hex(address),'size':len(data),'label':label,'sha256':hashlib.sha256(data).hexdigest()})
        ok=self.k.WriteProcessMemory(self.h,C.c_void_p(address),buf,len(data),C.byref(n))
        if not ok or n.value!=len(data):raise CameraError('Incomplete Hook configuration write; no retry.')
    def call(self,address,param,label):
        self.journal({'action':'remote_thread','label':label,'entry':hex(address),'argument':hex(param)})
        h=self.k.CreateRemoteThread(self.h,None,0,C.c_void_p(address),C.c_void_p(param),0,None)
        if not h:raise CameraError(f'Cannot start the authorized Hook operation ({C.get_last_error()}).')
        try:
            if self.k.WaitForSingleObject(h,8000)!=0:raise CameraError('Hook thread did not finish; outcome unknown.')
            code=W.DWORD()
            if not self.k.GetExitCodeThread(h,C.byref(code)):raise CameraError('No Hook thread exit code.')
            self.journal({'action':'remote_thread_return','label':label,'code':code.value})
            return code.value
        finally:self.k.CloseHandle(h)
    def modules(self):
        a=(W.HMODULE*1024)();n=W.DWORD()
        if not self.k.K32EnumProcessModulesEx(self.h,a,C.sizeof(a),C.byref(n),1)or n.value>C.sizeof(a):raise CameraError('Cannot enumerate x86 modules.')
        result={}
        for m in a[:n.value//C.sizeof(W.HMODULE)]:
            p=C.create_unicode_buffer(32768)
            if self.k.K32GetModuleFileNameExW(self.h,m,p,len(p)):result[Path(p.value).name.lower()]=(int(m),p.value)
        return result
    def export(self,module,name,depth=0):
        if depth>5:raise CameraError('Export forwarder cycle.')
        modules=self.modules();entry=modules.get(module.lower())
        if not entry:raise CameraError('Required system DLL not loaded.')
        base=entry[0];m=self.s.memory;head=m.read(base,0x1000);nt=struct.unpack_from('<I',head,0x3c)[0]
        if struct.unpack_from('<H',head,nt+4)[0]!=0x14c:raise CameraError('Export source is not x86.')
        r,size=struct.unpack_from('<2I',head,nt+24+96);d=m.read(base+r,40)
        _,nn,fs,ns,ords=struct.unpack_from('<5I',d,20)
        for i in range(nn):
            p=base+m.u32(base+ns+4*i);s=m.read(p,256).split(b'\0',1)[0].decode('ascii')
            if s!=name:continue
            idx=struct.unpack('<H',m.read(base+ords+2*i,2))[0];value=m.u32(base+fs+4*idx)
            if r<=value<r+size:
                forward=m.read(base+value,256).split(b'\0',1)[0].decode('ascii');dll,symbol=forward.rsplit('.',1)
                return self.export(dll+'.dll',symbol,depth+1)
            return base+value
        raise CameraError('Verified export not found.')
    def load(self,dll):
        if dll.name.lower()in self.modules():raise CameraError('Trial DLL is already loaded; do not reuse a one-shot trial.')
        data=(str(dll.resolve())+'\0').encode('utf-16le');p=self.k.VirtualAllocEx(self.h,None,len(data),0x3000,4)
        if not p:raise CameraError('Cannot allocate the DLL path.')
        self.write(p,data,'owned temporary DLL path')
        result=self.call(self.export('kernel32.dll','LoadLibraryW'),p,'LoadLibraryW of locally built Hook DLL')
        # Only free the path after the loading thread has completed.
        self.k.VirtualFreeEx(self.h,C.c_void_p(p),0,0x8000)
        if not result:raise CameraError('Hook DLL did not load.')
        module=self.modules().get(dll.name.lower())
        if not module or module[0]!=result or Path(module[1]).resolve()!=dll.resolve():raise CameraError('Loaded Hook identity mismatch.')
        return result

def configuration(s,snap,a,b,link):
    c=Config();o=s.objects;c.magic=0x31484342;c.size=C.sizeof(Config);c.base=s.info.base
    for n in ('context','player','scene','replay_controller','game_camera','render'):setattr(c,n,getattr(o,n))
    c.scene_owner=o.scene_controller;c.camera=o.free_camera;c.spectator=o.spectator_controller
    c.battle=int(link['battle_controller'],16);c.owner=int(link['owner_at_150'],16);c.shadow=s.memory.u32(o.render+0x8c)
    c.battle_vft=s.live(0x37f8f70);c.update_vft=s.live(0x37f8fb0);c.shadow_vft=s.live(0x375b100)
    for field,kind in [('context_vft','AvatarContextReplay'),('player_vft','ReplayPlayer'),('camera_vft','FreeCamera'),('spectator_vft','SpectatorCameraController'),('render_vft','RenderSystem'),('scene_vft','GameScene'),('scene_owner_vft','GameSceneController'),('replay_vft','ReplayCameraController'),('game_vft','GameCamera')]:setattr(c,field,s.vft[kind])
    c.player_secondary_vft=s.live(PROFILE_1121.replay_secondary_vft)
    c.set_position=s.live(0xa95710);c.set_direction=s.live(0xa92b80);c.refresh=s.live(0xa7aee0)
    c.raw_time=snap['replay']['raw_time'];c.origin=snap['replay']['origin'];c.fov=snap['raw_camera']['interface_fov']
    c.angles[:]=snap['native_controller']['target_angles'];c.projection[:]=snap['raw_camera']['projection']
    c.direction=Vec(*snap['raw_camera']['direction']);c.setter_direction=Vec(*snap['native_controller']['direction_scaled'])
    c.a=Vec(*a['camera']['position']);c.b=Vec(*b['camera']['position']);return c

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run-dir',required=True,type=Path);ap.add_argument('--execute',action='store_true');ap.add_argument('--dll',type=Path,default=ROOT/'research/native/hook1121.dll')
    args=ap.parse_args();args.run_dir.mkdir(parents=True,exist_ok=False)
    dll=args.dll.resolve();layout=json.loads((dll.parent/'hook1121-layout.json').read_text());check_layout(layout)
    report={'started_utc':datetime.now(timezone.utc).isoformat(),'execution_requested':args.execute,'dll_sha256':sha(dll),'layout':layout,'position_only':True,'dll_unloaded':False,'movement_started':False,'hooks_detached':False}
    def save(): (args.run_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    def journal(x):
        with(args.run_dir/'operations.jsonl').open('a',encoding='utf8')as f:f.write(json.dumps(x)+'\n')
    remote=None;base=None;g=None;exports=pe_exports(dll);save()
    try:
        a=json.loads((ROOT/'output/combined-trajectory-20261019/a.json').read_text(encoding='utf8'))
        b=json.loads((ROOT/'output/combined-trajectory-20261019/b.json').read_text(encoding='utf8'))
        with CameraSession.connect()as s:
            if s.profile!=PROFILE_1121:raise CameraError('Wrong exact executable hash.')
            links=battle_links(s)
            if len(links)!=1:raise CameraError('No unique replay update object.')
            anim=AnimationProbe(s);reference=None;count=0;began=time.perf_counter()
            while time.perf_counter()-began<4:
                try:snap,_=bracketed_capture(s,links[0],anim);validate_snapshot(snap)
                except IncoherentSample:continue
                same_scene(a,snap);same_scene(b,snap)
                if math.dist(snap['camera']['position'],b['camera']['position'])>.01:raise CameraError('Start must be original B.')
                if reference and(math.dist(snap['camera']['position'],reference['camera']['position'])>.001 or snap['replay']!=reference['replay']):raise CameraError('Camera/replay changed in preflight.')
                reference=snap;count+=1
                if count>=100 and time.perf_counter()-began>=2:break
                time.sleep(.02)
            if count<100:raise CameraError('Insufficient stable paused samples.')
            if reference['raw_camera']['interface_fov']!=64:raise CameraError('Expected original B interface FOV64.')
            extra=controller_extra(s);boxes=check_path(s,extra,a['camera']['position'],b['camera']['position'])
            lo=[min(x,y)for x,y in zip(a['camera']['position'],b['camera']['position'])]
            hi=[max(x,y)for x,y in zip(a['camera']['position'],b['camera']['position'])];hi[2]+=2
            if not all(x+.1<=v<=w<=y-.1 for x,v,w,y in zip(extra['bounds_min'],lo,hi,extra['bounds_max'])):raise CameraError('Path exceeds primary bounds.')
            if any(all(lo[i]<=box[i+3]and box[i]<=hi[i]for i in range(3))for box in boxes):raise CameraError('Path overlaps known native adjustment volume.')
            cfg=configuration(s,reference,a,b,links[0]);report.update(preflight_samples=count,reference=reference,config=plain(cfg),process=identity(s.memory.k,s.memory.handle))
            report['plan']='observe forwarding for 4 s; fixed B heading/FOV: B->A 8 s with original +2 sin(pi*u) arch; hold 3 s; A->B same 8 s; hold 3 s; restore both original vptrs'
            save()
            if not args.execute:report['status']='read_only_preflight_passed';save();print(report['status']);return 0
            # Preserve exact source and binary used, without modifying the installed game.
            for p in (dll,dll.parent/'hook1121.c',Path(__file__),dll.parent/'hook1121-layout.json'):
                (args.run_dir/p.name).write_bytes(p.read_bytes())
            with Remote(s,journal)as remote:
                base=remote.load(dll);g=base+exports['g_shared'];report['loaded_module_base']=hex(base);report['shared_address']=hex(g);save()
                remote.write(g,bytes(cfg),'owned Hook configuration')
                remote.write(g+layout['heartbeat'],struct.pack('<I',remote.k.GetTickCount()&0xffffffff),'owned watchdog')
                remote.detach_address=base+exports['HookDetach@4']
                code=remote.call(base+exports['HookAttach@4'],0,'atomic per-instance vptr installation')
                report['attach_result']=code;save()
                if code:raise CameraError(f'HookAttach rejected configuration ({code}).')
                started=time.perf_counter();armed_local=False
                def header():
                    raw=s.memory.read(g+layout['command'],layout['records']-layout['command'])
                    return {k:struct.unpack_from('<i',raw,v-layout['command'])[0]for k,v in layout.items()if k in ('status','error','updates','draws','events','active','position_applies','detach_mask')}
                with(args.run_dir/'monitor.jsonl').open('x')as out:
                    while time.perf_counter()-started<34:
                        remote.write(g+layout['heartbeat'],struct.pack('<I',remote.k.GetTickCount()&0xffffffff),'owned watchdog')
                        state=header();out.write(json.dumps({'elapsed':time.perf_counter()-started,**state})+'\n');out.flush()
                        if state['status']in(-1,4):break
                        if not armed_local and time.perf_counter()-started>=4:
                            if state['updates']<50 or state['draws']<50 or state['position_applies']:
                                raise CameraError('Observe-only Hook did not forward both phases without camera writes.')
                            tids=struct.unpack('<2i',s.memory.read(g+288,8))
                            if not tids[0]or tids[0]!=tids[1]:raise CameraError('Camera update and shadow Draw are on different/unobserved threads.')
                            report['observe_only']=state;report['thread_ids']=tids;report['movement_started']=True;save()
                            remote.write(g+layout['command'],struct.pack('<i',1),'arm single bounded position experiment');armed_local=True
                            print('Hook forwarding verified; position trajectory started',flush=True)
                        time.sleep(.1)
                if header()['status']not in(-1,4):remote.call(base+exports['HookDetach@4'],0,'explicit trial timeout detachment')
                time.sleep(.25);report['final_hook_state']=header()
                report['hooks_detached']=(report['final_hook_state']['detach_mask']==3 and s.memory.u32(cfg.battle+0x128)==cfg.update_vft and s.memory.u32(cfg.shadow)==cfg.shadow_vft)
                n=min(report['final_hook_state']['events'],8192)
                raw=s.memory.read(g+layout['records'],n*C.sizeof(Event));(args.run_dir/'events.bin').write_bytes(raw)
                with(args.run_dir/'events.jsonl').open('x')as f:
                    for i in range(n):
                        e=Event.from_buffer_copy(raw,i*C.sizeof(Event))
                        if e.commit==i+1:f.write(json.dumps(plain(e))+'\n')
                report['final_camera']=s.capture(require_paused=True)
                report['status']='completed'if report['hooks_detached']and not report['final_hook_state']['error']and armed_local else 'stopped'
                save();print(json.dumps({'status':report['status'],'hook':report['final_hook_state'],'hooks_detached':report['hooks_detached']}));return 0 if report['status']=='completed'else 2
    except Exception as e:
        report.update(status='stopped',error=f'{type(e).__name__}: {e}');save();print(report['error'],file=sys.stderr)
        # The in-process watchdog also detaches if this supervisor cannot continue.
        if remote and remote.h and base:
            try:report['exception_detach_result']=remote.call(base+exports['HookDetach@4'],0,'exception detachment');save()
            except Exception as cleanup:report['cleanup_error']=str(cleanup);save()
        return 2

if __name__=='__main__':raise SystemExit(main())
