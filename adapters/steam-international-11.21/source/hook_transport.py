"""Windows x86 DLL transport, used only after an explicit game-play request.
Adapted from the bounded 11.21 trial; no game-file modifications.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib,struct,time
from pathlib import Path
from .profile import CameraError

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

def relocated_code(path,base):
    """Expected executable sections of our x86 DLL, after HIGHLOW relocations."""
    b=Path(path).read_bytes();pe=struct.unpack_from('<I',b,0x3c)[0];o=pe+24
    if struct.unpack_from('<HH',b,pe+4)[0]!=0x14c or struct.unpack_from('<H',b,o)[0]!=0x10b:raise CameraError('Hook image is not PE32 x86.')
    preferred=struct.unpack_from('<I',b,o+28)[0];delta=(base-preferred)&0xffffffff;sections=[]
    for i in range(struct.unpack_from('<H',b,pe+6)[0]):
        q=o+struct.unpack_from('<H',b,pe+20)[0]+40*i
        vs,r,rs,ro=struct.unpack_from('<4I',b,q+8);flags=struct.unpack_from('<I',b,q+36)[0]
        sections.append((r,vs,rs,ro,flags))
    def off(r):
        for va,vs,rs,ro,flags in sections:
            if va<=r<va+rs:return ro+r-va
        raise CameraError('Bad relocation RVA.')
    code={r:bytearray(b[ro:ro+min(vs,rs)]+b'\0'*max(0,vs-rs))for r,vs,rs,ro,flags in sections if flags&0x20000000}
    rr,rn=struct.unpack_from('<2I',b,o+96+5*8);cur=rr
    while cur<rr+rn:
        q=off(cur);page,size=struct.unpack_from('<2I',b,q)
        if size<8 or size%2 or cur+size>rr+rn:raise CameraError('Bad relocation block.')
        for j in range((size-8)//2):
            entry=struct.unpack_from('<H',b,q+8+j*2)[0];kind=entry>>12;rva=page+(entry&4095)
            for start,data in code.items():
                if start<=rva<start+len(data) and kind:
                    if kind!=3 or rva+4>start+len(data):raise CameraError('Unsupported executable relocation.')
                    n=rva-start;struct.pack_into('<I',data,n,(struct.unpack_from('<I',data,n)[0]+delta)&0xffffffff)
        cur+=size
    if not code:raise CameraError('No executable Hook sections.')
    return code

def verify_module_code(memory,base,dll):
    for rva,expected in relocated_code(dll,base).items():
        if memory.read(base+rva,len(expected))!=expected:
            raise CameraError('已驻留的工具代码与构建文件不一致，拒绝复用；请重启游戏后连接。')


class Remote:
    def __init__(self,s,journal):
        self.s=s;self.k=C.WinDLL('kernel32',use_last_error=True);self.h=None;self.journal=journal;self.detach_address=None;self.detach_probe=None;self.write_bounds=None
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
                    if self.detach_probe:
                        deadline=time.monotonic()+2
                        while not self.detach_probe():
                            if time.monotonic()>=deadline:
                                raise CameraError('Hook detachment has not completed.')
                            time.sleep(.02)
            except Exception as e:
                self.journal({'action':'exit_detachment_error','error':str(e)})
            finally:
                self.k.CloseHandle(self.h);self.h=None
    def write(self,address,data,label):
        bounds=self.write_bounds
        if bounds and not(bounds[0]<=address and address+len(data)<=bounds[1]):raise CameraError('写入超出已校验的工具共享数据范围。')
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
        existing=self.modules().get(dll.name.lower())
        if existing:
            if Path(existing[1]).resolve()!=dll.resolve():raise CameraError('同名 Hook 来自其他位置，已停止。')
            verify_module_code(self.s.memory,existing[0],dll)
            return existing[0]
        data=(str(dll.resolve())+'\0').encode('utf-16le');p=self.k.VirtualAllocEx(self.h,None,len(data),0x3000,4)
        if not p:raise CameraError('Cannot allocate the DLL path.')
        self.write(p,data,'owned temporary DLL path')
        result=self.call(self.export('kernel32.dll','LoadLibraryW'),p,'LoadLibraryW of locally built Hook DLL')
        # Only free the path after the loading thread has completed.
        self.k.VirtualFreeEx(self.h,C.c_void_p(p),0,0x8000)
        if not result:raise CameraError('Hook DLL did not load.')
        module=self.modules().get(dll.name.lower())
        if not module or module[0]!=result or Path(module[1]).resolve()!=dll.resolve():raise CameraError('Loaded Hook identity mismatch.')
        verify_module_code(self.s.memory,result,dll)
        return result
