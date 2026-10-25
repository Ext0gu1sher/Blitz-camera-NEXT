"""Independent acceptance checks against both source archives and WASM output."""
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

from analyze_dual_replay import read_replay
from make_dual_replay_trial import framing, raw_record, EXPECTED


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);args=ap.parse_args()
    folder=args.folder
    audit=json.loads((folder/'audit.json').read_text(encoding='utf8'))
    manifest=json.loads((folder/'merged-manifest.json').read_text(encoding='utf8'))
    a,b=[read_replay(v['path']) for v in audit['inputs']]
    assert (a['sha256'],b['sha256'])==EXPECTED
    merged=read_replay(manifest['trial'])
    observer_info=json.loads((folder/'observer-manifest.json').read_text())
    observer=read_replay(observer_info['trial'])
    assert merged['sha256']==manifest['trial_sha256'] and observer['sha256']==observer_info['trial_sha256']
    provenance=json.loads((folder/'merged-provenance.json').read_text())
    assert len(merged['records'])==len(provenance['output_source_indices'])
    seen=[set(),set()];sources=[a,b]
    for (k,t,p),(source,index) in zip(merged['records'],provenance['output_source_indices']):
        assert index not in seen[source];seen[source].add(index)
        sk,st,sp=sources[source]['records'][index]
        expected=st if source==0 else max(0.,st+manifest['donor_clock_offset'])
        expected=struct.unpack('<f',struct.pack('<f',expected))[0]
        assert (k,t,p)==(sk,expected,sp)
        if source==1:
            assert k in manifest['entity_packet_kinds'] and struct.unpack_from('<I',p)[0] in manifest['donor_vehicle_ids']
    removed=set(provenance['removed_a_indices'])
    assert seen[0].isdisjoint(removed) and seen[0]|removed==set(range(len(a['records'])))
    for source in (merged,observer):
        assert all(source['records'][i-1][1]<=source['records'][i][1] for i in range(1,len(source['records'])))
        assert framing(source['data'])[1]==framing(a['data'])[1]
        with zipfile.ZipFile(source['path']) as z,zipfile.ZipFile(a['path']) as za:
            assert z.testzip() is None
            assert all(z.read(n)==za.read(n) for n in ('meta.json','battle_results.dat'))
    pa,pb,pm,po=[json.loads((folder/f'{tag}-playback.json').read_text()) for tag in ('a','b','merged','observer')]
    assert len(pm['vehicles'])==len(po['vehicles'])==14
    assert po==pm, 'Adding the virtual observer changed participant playback'
    start=a['battle_start']['battle_start_raw_sec']
    end=next(p['raw'] for p in a['periods'] if p['values'][1]==4)
    rows=[]
    for v in pm['vehicles']:
        va=next(x for x in pa['vehicles'] if x['eid']==v['eid'])
        alive_end=min(end,v['death_t'] if v['death_t'] is not None else end)
        def covered(obj):
            c=obj['coverage']
            return sum(max(0,min(alive_end,c[i+1])-max(start,c[i])) for i in range(0,len(c),2))
        before,after=covered(va),covered(v)
        moves=[(t,struct.unpack_from('<3f',p,12)) for k,t,p in merged['records']
               if k==10 and len(p)==49 and struct.unpack_from('<I',p)[0]==v['eid']]
        assert all(all(math.isfinite(x) for x in pos) for t,pos in moves)
        times=[t for t,pos in moves if start<=t<=alive_end]
        max_gap=max((y-x for x,y in zip(times,times[1:])),default=0)
        assert after>=alive_end-start-.05 and max_gap<.5
        row=dict(eid=v['eid'],name=v['nickname'],team=v['team'],alive_seconds=alive_end-start,
                 original_known_seconds=before,merged_known_seconds=after,gained_seconds=after-before,
                 max_motion_gap_alive=max_gap)
        if v['team']==2:
            assert v==va
        elif alive_end>manifest['donor_cutoff_raw']:
            beforep=max((r for r in moves if r[0]<=manifest['donor_cutoff_raw']),key=lambda r:r[0])
            afterp=min((r for r in moves if r[0]>manifest['donor_cutoff_raw']),key=lambda r:r[0])
            row['handoff']=dict(before=beforep,after=afterp,seconds=afterp[0]-beforep[0],distance=math.dist(beforep[1],afterp[1]))
            assert row['handoff']['seconds']<.3 and row['handoff']['distance']<2
        rows.append(row)
    result=dict(passed=True,battle_start_raw=start,battle_end_raw=end,rows=rows,
        gained_vehicle_seconds=sum(r['gained_seconds'] for r in rows),all_14_alive_intervals_covered=True,
        source_a_team_playback_identical=True,observer_participant_playback_identical=True,
        every_merged_packet_has_verified_provenance=True,all_source_payloads_preserved=True,
        metadata_results_terminal_preserved=True,originals_unchanged=True,
        max_alive_motion_gap=max(r['max_motion_gap_alive'] for r in rows))
    (folder/'merged-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


if __name__=='__main__':main()
