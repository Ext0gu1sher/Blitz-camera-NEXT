"""Read-only disk research for the exact 11.21 replay time implementation.

Only this analysis process is used by the existing non-invasive disassembler.
No process discovery, game attachment, DLL loading or runtime writes.
"""
import argparse, contextlib, hashlib, json, re, struct
from pathlib import Path
from inspect_build import PE

EXE=Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\wotblitz.exe')
EXPECTED='5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608'
OUT=Path(__file__).resolve().parents[1]/'builds/11.21.0.1235'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--scan',action='store_true');ap.add_argument('--calls',nargs='*',default=[])
    ap.add_argument('--blocks',nargs='*',default=[]);ap.add_argument('--out',required=True);a=ap.parse_args()
    pe=PE(EXE);digest=hashlib.sha256(pe.data).hexdigest()
    if digest!=EXPECTED:raise RuntimeError('Client hash changed; this analysis is build-locked.')
    result={'file':str(EXE),'sha256':digest,'base':hex(pe.base),'date':'2026-10-19','calls':{},'strings':[]}
    if a.scan:
        for match in re.finditer(rb'[ -~]{5,}',pe.data):
            s=match.group().decode()
            if re.search(r'(Replay.*(Speed|TimeWarp|Rewind|FastForward|Pause|Playback)|replay.*(speed|Speed|TimeWarp|timeWarp|Playback|playback)|Rewind(Start|Finish)|FastForward(Start|Finish))',s):
                va=pe.va(match.start());result['strings'].append({'va':hex(va),'text':s,'refs':[hex(x) for x in pe.refs(va)]})
    for t in a.calls:
        target=int(t,0);sites=[]
        for section in pe.sections:
            if not section['flags']&0x20000000:continue
            raw=section['raw'];data=pe.data[raw:raw+section['size']]
            for m in re.finditer(b'\xe8',data):
                i=m.start()
                if i+5<=len(data)and(pe.va(raw+i)+5+struct.unpack_from('<i',data,i+1)[0])&0xffffffff==target:sites.append(hex(pe.va(raw+i)))
        result['calls'][hex(target)]={'candidate_direct_calls':sites,'absolute_refs':[hex(x) for x in pe.refs(target)]}
    if a.blocks:
        from disassemble_local_bytes import dis,ck,meth,cl
        try:
            with (OUT/a.out).open('w',encoding='utf8')as f,contextlib.redirect_stdout(f):
                print(json.dumps({k:result[k]for k in ('file','sha256','base','date')}))
                for block in a.blocks:
                    va,count=block.split(':');print('\nBLOCK',va);dis(int(va,0),int(count))
        finally:ck(meth(cl,25)(cl))
    else:(OUT/a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(str(OUT/a.out))
    if not a.blocks:print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
