# Static PE inspection only. Reads the installed executable, never loads or executes it.

from pathlib import Path
import struct,re
b=Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\wotblitz.exe').read_bytes()
nt=struct.unpack_from('<I',b,0x3c)[0];op=nt+24
base=struct.unpack_from('<I',b,op+28)[0]
ns=struct.unpack_from('<H',b,nt+6)[0];osz=struct.unpack_from('<H',b,nt+20)[0]
sec=[(b[op+osz+i*40:op+osz+i*40+8].rstrip(b'\0').decode(),*struct.unpack_from('<4I',b,op+osz+i*40+8)) for i in range(ns)]
def off(va):
 r=va-base
 for name,vs,rva,rs,raw in sec:
  if rva<=r<rva+rs:return raw+r-rva
 raise ValueError(hex(va))
def va(o):
 for name,vs,rva,rs,raw in sec:
  if raw<=o<raw+rs:return base+rva+o-raw
 raise ValueError(hex(o))
def u(v):return struct.unpack_from('<I',b,off(v))[0]
def refs(v):return [va(m.start()) for m in re.finditer(re.escape(struct.pack('<I',v)),b)]
def name(td):
 o=off(td)+8;return b[o:b.index(b'\0',o)].decode('ascii','replace')
def td(s):return va(b.index(s.encode()+b'\0')-8)
def rtti(s):
 t=td(s);print('\nTYPE',s,'TypeDescriptor',hex(t))
 for r in refs(t):
  col=r-12
  try:
   sig,delta,cd,t0,ch=struct.unpack_from('<5I',b,off(col))
   if sig==0 and delta<0x1000 and cd==0 and 0x3600000<=ch<0x4100000:
    sig1,attr,n,arr=struct.unpack_from('<4I',b,off(ch))
    if n>40 or n==0:continue
    print('COL',hex(col),'subobject',hex(delta),'hierarchy',[(name(u(u(arr+i*4))),hex(u(u(arr+i*4)+8))) for i in range(n)])
    for rr in refs(col):
     vf=rr+4
     fun=[]
     for i in range(32):
      v=u(vf+i*4)
      if not base+0x1000<=v<base+0x321cf2a:break
      fun.append(hex(v))
     if fun:print('VFT',hex(vf),'slots',fun,'xrefs',list(map(hex,refs(vf)))[:15])
  except (ValueError,struct.error):pass

