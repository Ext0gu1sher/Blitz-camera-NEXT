"""Add a materialized virtual observer to the audited dual-team prototype."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from analyze_dual_replay import read_replay, arena_body
from make_dual_replay_trial import framing, raw_record
from make_observer_replay_trial import fields, message, varint

SOURCE_SHA='545baef29f7c174d041a39bb6571138e84b68022592953aaedbe70dd0851e5c8'
TICK_V2_SHA='2e681b23158ffef93a7304da2b860822fa9f7bc88e27bda401c029646306eb69'
NEW=0x70000001
DBID=2147483001
NAME=b'ReplayCamera'


def add_roster(body,old):
    out=bytearray();changed=0;count=0;kept=[]
    for f,w,v,raw in fields(body):
        if (f,w)!=(1,2):out.extend(raw);continue
        rows=[];extra=None
        for g,x,row,encoded in fields(v):
            assert (g,x)==(1,2)
            vf=list(fields(row));scalars={a:c for a,b,c,_ in vf if b==0}
            assert scalars[1]!=NEW and scalars[7]!=DBID
            rows.append(encoded);kept.append(encoded);count+=1
            if scalars[1]==old:
                assert scalars.get(14,0)==0
                extra=b''.join(varint(a<<3)+varint(NEW if a==1 else DBID) if a in (1,7)
                    else message(3,NAME) if a==3 else r for a,b,c,r in vf)
                extra+=varint(14<<3)+varint(2);changed+=1
        assert extra is not None
        out.extend(message(1,b''.join(rows)+message(1,extra)))
    assert changed==1 and count==16
    newrows=[]
    for f,w,v,raw in fields(out):
        if (f,w)==(1,2):newrows.extend(encoded for g,x,row,encoded in fields(v))
    assert newrows[:-1]==kept
    return bytes(out)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);args=ap.parse_args()
    folder=args.folder;source=folder/'dual-team-merged.wotbreplay';r=read_replay(source)
    assert r['sha256'] in (SOURCE_SHA,TICK_V2_SHA) and r['recorder']['eid']==13073154
    old=r['recorder']['eid'];header,terminal=framing(r['data'])
    output=[];provenance=[];changes=[];insertions=[]
    for i,(k,t,p) in enumerate(r['records']):
        altered=p
        if k==8 and len(p)>=14 and struct.unpack_from('<II',p)==(r['avatar'],48):
            subtype,body=arena_body(p)
            if subtype==1:
                body=add_roster(body,old)
                argv=b'\x01\xff'+len(body).to_bytes(3,'little')+body
                altered=p[:8]+struct.pack('<I',len(argv))+argv
        elif k==1:
            assert len(p)==130 and struct.unpack_from('<I',p,36)[0]==len(p)-40
            assert p[40]==2 and struct.unpack_from('<I',p,41)[0]==old
            altered=p[:41]+struct.pack('<I',NEW)+p[45:]
        if altered!=p:changes.append(dict(input_index=i,output_index=len(output),kind=k))
        output.append((k,t,altered));provenance.append(i)
        if k in (33,5) and len(p)>=4 and struct.unpack_from('<I',p)[0]==old:
            ghost=struct.pack('<I',NEW)+p[4:]
            if k==33:assert len(p)==12
            else:
                assert struct.unpack_from('<H',p,4)[0]==2 and struct.unpack_from('<I',p,38)[0]==len(p)-42
                name_size=p[57];assert p[58:58+name_size]==r['meta']['playerName'].encode()
                ghost=bytearray(ghost[:57]+bytes([len(NAME)])+NAME+ghost[58+name_size:])
                struct.pack_into('<I',ghost,38,len(ghost)-42)
                ghost=bytes(ghost)
            insertions.append(dict(output_index=len(output),kind=k,raw=t))
            output.append((k,t,ghost));provenance.append(None)
    assert [x['kind'] for x in changes]==[8,1] and [x['kind'] for x in insertions]==[33,5]
    data=bytearray(header+b''.join(raw_record(*x) for x in output)+terminal)
    struct.pack_into('<I',data,4,len(data)-8)
    reverted=bytearray(header+b''.join(raw_record(*r['records'][i]) for i in provenance if i is not None)+terminal)
    struct.pack_into('<I',reverted,4,len(reverted)-8)
    assert bytes(reverted)==r['data']
    target=folder/('dual-team-observer-tick-v2.wotbreplay' if r['sha256']==TICK_V2_SHA else 'dual-team-observer.wotbreplay');assert not target.exists()
    with zipfile.ZipFile(source) as src,zipfile.ZipFile(target,'x') as dst:
        dst.comment=src.comment
        for info in src.infolist():dst.writestr(info,data if info.filename=='data.wotreplay' else src.read(info))
    got=read_replay(target)
    assert len(got['roster'])==17 and got['roster'][NEW]['observer']==2
    assert {k:v for k,v in got['roster'].items() if k!=NEW}==r['roster']
    with zipfile.ZipFile(source) as src,zipfile.ZipFile(target) as dst:
        assert dst.testzip() is None
        assert all(src.read(n)==dst.read(n) for n in src.namelist() if n!='data.wotreplay')
    manifest=dict(source=str(source.resolve()),source_sha256=r['sha256'],trial=str(target.resolve()),trial_sha256=got['sha256'],
        original_vehicle=old,virtual_observer=NEW,virtual_dbid=DBID,original_roster_rows_preserved=16,
        existing_observers_preserved=2,observer_rows_added=1,extra_vehicle_materialized=True,added_packets=2,
        changes=changes,insertions=insertions,exact_reverse_verified=True,original_metadata_preserved=True,
        terminal_record_preserved=True,client_acceptance='not tested')
    (folder/'observer-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    config=dict(output=str(folder.resolve()),inputs=[dict(label='observer',path=str(target.resolve()))])
    (folder/'decode-observer-config.json').write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
