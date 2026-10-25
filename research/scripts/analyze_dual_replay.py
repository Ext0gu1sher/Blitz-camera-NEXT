"""Read-only pair audit: identity, shared-event clocks, and lifecycle coverage.

All input bytes are preserved. No game process or replay launch is involved.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam.replay_clock import replay_records, origin_from_data
from blitzcam.replay_events import battle_start_from_data, _varint
from make_observer_replay_trial import fields


def arena_body(p):
    assert len(p) >= 14 and struct.unpack_from('<I', p, 8)[0] == len(p)-12
    subtype, at = _varint(p, 12)
    length = p[at]
    at += 1
    if length == 255:
        length = int.from_bytes(p[at:at+3], 'little')
        at += 3
    assert at+length == len(p)
    return subtype, p[at:]


def read_replay(path):
    raw = Path(path).read_bytes()
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        meta = json.loads(z.read('meta.json'))
        data = z.read('data.wotreplay')
    assert struct.unpack_from('<II', data) == (0x12345678, len(data)-8)
    records = [(k, t, bytes(p)) for k,t,p in replay_records(data)]
    roster, avatar, periods = {}, None, []
    for k,t,p in records:
        if k != 8 or len(p)<14 or struct.unpack_from('<I',p,4)[0] != 48:
            continue
        sub, body = arena_body(p)
        if sub == 1:
            assert not roster
            avatar = struct.unpack_from('<I',p)[0]
            for f,w,v,_ in fields(body):
                if (f,w)!=(1,2):
                    continue
                for f,w,row,_ in fields(v):
                    assert (f,w)==(1,2)
                    values = {a:c for a,b,c,_ in fields(row)}
                    eid=values[1]
                    roster[eid] = dict(eid=eid, dbid=values[7], name=values[3].decode(),
                        team=values[4], observer=values.get(14,0), vehicle=values[2].hex())
        elif sub == 3:
            for f,w,v,_ in fields(body):
                if (f,w)==(3,2):
                    values={a:(struct.unpack('<d',c)[0] if b==1 else c) for a,b,c,_ in fields(v) if b in (0,1)}
                    periods.append(dict(raw=t, values=values))
    me = [r for r in roster.values() if str(r['dbid'])==str(meta['dbid'])]
    assert len(me)==1
    origin = origin_from_data(data)
    return dict(path=str(Path(path).resolve()),sha256=hashlib.sha256(raw).hexdigest(),meta=meta,
        data=data,records=records,roster=roster,avatar=avatar,recorder=me[0],origin=origin,
        battle_start=battle_start_from_data(data,meta['version']),periods=periods,
        last_clock=max(t for k,t,p in records))


def quantiles(values):
    v=sorted(values)
    if not v:return None
    return {str(q):v[round((len(v)-1)*q)] for q in (0,.05,.25,.5,.75,.95,1)}


def anchor_index(replay):
    out=defaultdict(list)
    for k,t,p in replay['records']:
        if t<10 or len(p)<4:
            continue
        eid=struct.unpack_from('<I',p)[0]
        label=None
        key=p
        if k==8 and eid==replay['avatar'] and len(p)>=14 and struct.unpack_from('<I',p,4)[0]==48:
            sub,_=arena_body(p)
            if sub in (3,6,8,9,12,13):
                label=f'arena-{sub}'
                key=p[4:]
        elif eid in replay['roster'] and k in (7,8,10):
            label=f'vehicle-{k}'
        if label:
            out[(label,key)].append(t)
    return out


def coverage(replay):
    events=defaultdict(list)
    for k,t,p in replay['records']:
        if k in (4,5,10,33) and len(p)>=4:
            eid=struct.unpack_from('<I',p)[0]
            if eid in replay['roster']:
                events[eid].append((k,t,p))
    result=[]
    for eid,vehicle in replay['roster'].items():
        ev=events[eid];moves=[t for k,t,p in ev if k==10];counts=Counter(k for k,t,p in ev)
        gaps=[];left=None;segments=[];entered=None
        for k,t,p in ev:
            if k==4:
                left=t
                if entered is not None:
                    segments.append([entered,t]);entered=None
            elif k==5:
                if left is not None:
                    gaps.append([left,t,sum(left<mt<t for mt in moves)]);left=None
                if entered is None:entered=t
        if entered is not None:segments.append([entered,replay['last_clock']])
        result.append(dict(**vehicle,creates=counts[5],exits=counts[4],motion_count=len(moves),
            motion_begin=min(moves) if moves else None,motion_end=max(moves) if moves else None,
            presence=segments,gaps=gaps,position_payload_sizes=dict(Counter(len(p) for k,t,p in ev if k==10))))
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('a',type=Path);ap.add_argument('b',type=Path)
    ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    a,b=read_replay(args.a),read_replay(args.b)
    assert all(a['meta'][k]==b['meta'][k] for k in ('arenaUniqueId','mapName','version'))
    assert a['roster']==b['roster']
    assert a['recorder']['team']!=b['recorder']['team']
    ia,ib=anchor_index(a),anchor_index(b)
    anchors=[]
    for (label,p),ta in ia.items():
        tb=ib.get((label,p),[])
        if len(ta)==len(tb)==1:
            anchors.append(dict(kind=label,a=ta[0],b=tb[0],a_minus_b=ta[0]-tb[0],payload_sha256=hashlib.sha256(p).hexdigest()))
    groups={kind:[x for x in anchors if x['kind']==kind] for kind in sorted(set(x['kind'] for x in anchors))}
    summaries={kind:dict(count=len(rows),offset_quantiles=quantiles([r['a_minus_b'] for r in rows])) for kind,rows in groups.items()}
    info=[]
    for r in (a,b):
        info.append({k:r[k] for k in ('path','sha256','meta','avatar','recorder','origin','battle_start','periods','last_clock')}
                    |dict(packet_counts=dict(Counter(k for k,t,p in r['records'])),coverage=coverage(r)))
    report=dict(same_arena=True,identical_roster=True,opposing_recorders=True,inputs=info,anchor_summaries=summaries)
    (args.out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (args.out/'clock-anchors.json').write_text(json.dumps(anchors,indent=2)+'\n')
    config=dict(output=str(args.out.resolve()),inputs=[dict(label=label,path=r['path']) for label,r in zip(('a','b'),(a,b))])
    (args.out/'decode-config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(inputs=[{k:r[k] for k in ('recorder','origin','battle_start','periods','last_clock')} for r in (a,b)],anchors=summaries),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
