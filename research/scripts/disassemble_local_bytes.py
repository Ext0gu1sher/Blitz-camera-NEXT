# Static disassembly helper. Maps bytes read-write (not executable) ONLY inside this Python process.
# DbgEng attaches non-invasively ONLY to os.getpid(); it never attaches to the game.
# Call dis(preferred_va, count), then ck(meth(cl,25)(cl)) before exit.

import ctypes as C, uuid, os, struct, pathlib
from ctypes import wintypes as W
class GUID(C.Structure): _fields_=[('v',C.c_ubyte*16)]
def guid(s): return GUID((C.c_ubyte*16).from_buffer_copy(uuid.UUID(s).bytes_le))
def meth(o,i,*args):
 return C.WINFUNCTYPE(C.c_long,C.c_void_p,*args)(C.cast(o,C.POINTER(C.POINTER(C.c_void_p))).contents[i])
def ck(r):
 if r<0: raise RuntimeError(hex(r&0xffffffff))
f=pathlib.Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\wotblitz.exe').read_bytes()
u16=lambda x:struct.unpack_from('<H',f,x)[0]; u32=lambda x:struct.unpack_from('<I',f,x)[0]
pe=u32(0x3c); opt=pe+24; base=u32(opt+28); size=u32(opt+56)
k=C.WinDLL('kernel32',use_last_error=True); k.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,W.DWORD,W.DWORD]; k.VirtualAlloc.restype=C.c_void_p
p=k.VirtualAlloc(base,size,0x3000,4)
assert p==base,(p,base,C.get_last_error())
C.memmove(base,f,u32(opt+60))
for i in range(u16(pe+6)):
 s=opt+u16(pe+20)+i*40; va,sz,raw=struct.unpack_from('<III',f,s+12)
 C.memmove(base+va,f[raw:raw+sz],sz)
dbg=C.WinDLL(r'C:\Windows\System32\dbgeng.dll'); dbg.DebugCreate.argtypes=[C.POINTER(GUID),C.POINTER(C.c_void_p)]; dbg.DebugCreate.restype=C.c_long
cl=C.c_void_p(); co=C.c_void_p(); ck(dbg.DebugCreate(C.byref(guid('27fe5639-8407-4f47-8364-ee118fb08ac8')),C.byref(cl))); ck(meth(cl,0,C.POINTER(GUID),C.POINTER(C.c_void_p))(cl,C.byref(guid('5182e668-105e-416e-ad92-24ef800424ba')),C.byref(co)))
ck(meth(cl,12,C.c_ulonglong,W.ULONG,W.ULONG)(cl,0,os.getpid(),5));ck(meth(co,93,W.ULONG,W.ULONG)(co,0,5000));ck(meth(co,48,W.ULONG)(co,0x14c))
def dis(va,count=20):
 buf=C.create_string_buffer(512); n=W.ULONG(); e=C.c_ulonglong()
 for _ in range(count):
  ck(meth(co,26,C.c_ulonglong,W.ULONG,C.c_void_p,W.ULONG,C.POINTER(W.ULONG),C.POINTER(C.c_ulonglong))(co,va,0,buf,len(buf),C.byref(n),C.byref(e)))
  print(buf.value.decode().strip()); va=e.value

