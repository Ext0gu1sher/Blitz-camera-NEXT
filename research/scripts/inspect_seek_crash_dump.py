"""Offline MINIDUMP reader. No process access, execution, network or symbols.
Reports exception registers, modules and EBP frames; stack scans are explicitly
candidate addresses, not an unwound call stack. x86 contexts only.
"""
import argparse,json,struct,re
from pathlib import Path

class Dump:
    def __init__(self,path):
        self.path=Path(path);self.data=self.path.read_bytes();d=self.data
        if d[:4]!=b'MDMP':raise ValueError('Not MINIDUMP')
        count,directory=struct.unpack_from('<2I',d,8)
        self.streams={}
        for i in range(count):
            kind,size,rva=struct.unpack_from('<3I',d,directory+12*i)
            self.streams[kind]=(rva,size)
        self.modules=[];rva,_=self.streams[4]
        for i in range(self.u32(rva)):
            at=rva+4+108*i;base,size,_,_,name=struct.unpack_from('<Q4I',d,at)
            n=self.u32(name);text=d[name+4:name+4+n].decode('utf-16le')
            self.modules.append(dict(base=base,size=size,path=text))
        self.ranges=[]
        if 5 in self.streams:
            rva,_=self.streams[5]
            for i in range(self.u32(rva)):
                start,size,loc=struct.unpack_from('<Q2I',d,rva+4+16*i)
                self.ranges.append((start,size,loc))
        if 9 in self.streams:
            rva,_=self.streams[9];n,loc=struct.unpack_from('<2Q',d,rva)
            for i in range(n):
                start,size=struct.unpack_from('<2Q',d,rva+16+16*i)
                self.ranges.append((start,size,loc));loc+=size
    def u32(self,at):return struct.unpack_from('<I',self.data,at)[0]
    def read(self,va,size):
        for start,n,off in self.ranges:
            if start<=va and va+size<=start+n:return self.data[off+va-start:off+va-start+size]
        raise ValueError(f'Memory absent: {va:#x}+{size:#x}')
    def address(self,va):
        for m in self.modules:
            if m['base']<=va<m['base']+m['size']:
                x={'address':hex(va),'module':Path(m['path']).name,'rva':hex(va-m['base'])}
                if x['module'].lower()=='wotblitz.exe':x['preferred_va']=hex(va-m['base']+0x400000)
                return x
        return {'address':hex(va),'module':None}
    def retained_exception_contexts(self):
        """Find retained x86 EXCEPTION_RECORD/CONTEXT pairs in captured stacks.

        This is a validated memory scan, not the dump's selected exception or
        a chronological exception trace. Require IP equality and sane x86 stack
        registers; keep the exact addresses so findings are independently checkable.
        """
        selected=self.inspect()['registers']
        esp=int(selected['esp'],16)
        result=[]
        for start,n,off in self.ranges:
            if not start<=esp<start+n:continue
            data=self.data[off:off+n]
            for match in re.finditer(re.escape(struct.pack('<I',0xc0000005)),data):
                at=match.start();ctx=at+80
                if ctx+204>len(data) or (start+at)%4:continue
                code,flags,linked,ip,count=struct.unpack_from('<5I',data,at)
                cf=struct.unpack_from('<I',data,ctx)[0]
                if count!=2 or cf&0xffff0000!=0x10000:continue
                names=('edi','esi','ebx','edx','ecx','eax','ebp','eip','cs','eflags','esp','ss')
                regs=dict(zip(names,struct.unpack_from('<12I',data,ctx+156)))
                if regs['eip']!=ip or regs['cs']!=0x23 or regs['ss']!=0x2b:continue
                if not start+ctx+204<=regs['esp']<=regs['ebp']<start+n:continue
                frames=[];ebp=regs['ebp'];seen=set()
                for i in range(45):
                    if ebp in seen or not regs['esp']<=ebp<start+n:break
                    seen.add(ebp)
                    try:prev,ret,*args=struct.unpack('<6I',self.read(ebp,24))
                    except ValueError:break
                    frames.append(dict(ebp=hex(ebp),return_address=self.address(ret),args=[hex(v)for v in args]))
                    if prev<=ebp:break
                    ebp=prev
                params=struct.unpack_from('<2I',data,at+20)
                result.append(dict(record_address=hex(start+at),context_address=hex(start+ctx),
                                   exception_code=hex(code),flags=hex(flags),linked_record=hex(linked),
                                   exception_ip=self.address(ip),parameters=[hex(v)for v in params],
                                   context_flags=hex(cf),registers={k:hex(v)for k,v in regs.items()},
                                   ebp_frames=frames,source='retained memory pair; not selected dump exception'))
        return result
    def inspect(self):
        rva,_=self.streams[6];tid=self.u32(rva);code=self.u32(rva+8)
        ip=struct.unpack_from('<Q',self.data,rva+24)[0];n=self.u32(rva+32)
        params=list(struct.unpack_from('<'+'Q'*min(n,15),self.data,rva+40))
        csize,crva=struct.unpack_from('<2I',self.data,rva+160)
        names=('edi','esi','ebx','edx','ecx','eax','ebp','eip','cs','eflags','esp','ss')
        flags=self.u32(crva)
        if flags&0xffff0000!=0x10000 or csize<204:raise ValueError('Expected x86 CONTEXT')
        regs=dict(zip(names,struct.unpack_from('<12I',self.data,crva+156)))
        frames=[];ebp=regs['ebp'];seen=set()
        for i in range(35):
            if ebp in seen or ebp<regs['esp'] or ebp>regs['esp']+0x100000:break
            seen.add(ebp)
            try:prev,ret,*args=struct.unpack('<6I',self.read(ebp,24))
            except ValueError:break
            frames.append(dict(ebp=hex(ebp),return_address=self.address(ret),args=[hex(v) for v in args]))
            if prev<=ebp:break
            ebp=prev
        candidates=[]
        for off in range(0,0x800,4):
            try:v=struct.unpack('<I',self.read(regs['esp']+off,4))[0]
            except ValueError:break
            addr=self.address(v)
            if addr['module']:
                candidates.append(dict(stack_offset=hex(off),**addr))
        return dict(path=str(self.path),thread=tid,exception_code=hex(code),exception_ip=self.address(ip),
                    parameters=[hex(v) for v in params],registers={k:hex(v) for k,v in regs.items()},
                    ebp_frames=frames,stack_candidates_not_unwound=candidates,
                    modules=[dict(base=hex(m['base']),size=hex(m['size']),path=m['path']) for m in self.modules])

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('dump');ap.add_argument('--out',required=True)
    a=ap.parse_args();d=Dump(a.dump);r=d.inspect();r['retained_exception_contexts']=d.retained_exception_contexts();Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in r.items() if k not in ('modules','stack_candidates_not_unwound')},ensure_ascii=False,indent=2))
