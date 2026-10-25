"""Verify v2 provenance, server-tick ownership, coverage and observer isolation."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import struct
import zipfile

from analyze_dual_replay import read_replay
from make_dual_replay_trial import EXPECTED, ENTITY_KINDS, framing
from make_dual_tick_trial import tick_index


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);args=ap.parse_args()
    folder=args.folder;original=folder.parent
    audit=json.loads((original/'audit.json').read_text(encoding='utf8'))
    a,b=[read_replay(v['path']) for v in audit['inputs']]
    assert (a['sha256'],b['sha256'])==EXPECTED
    manifest=json.loads((folder/'merged-manifest.json').read_text())
    om=json.loads((folder/'observer-manifest.json').read_text())
    merged=read_replay(manifest['trial']);observer=read_replay(om['trial'])
    assert merged['sha256']==manifest['trial_sha256'] and observer['sha256']==om['trial_sha256']
    targets={eid for eid,v in a['roster'].items() if v['team']==1 and not v['observer']}
    selected=lambda k,p:k in ENTITY_KINDS and int.from_bytes(p[:4],'little') in targets
    ticks=[tick_index(r['records'])[1] for r in (a,b,merged)]
    starts=tick_index(a['records'])[2];last=manifest['donor_last_tick']
    provenance=json.loads((folder/'merged-provenance.json').read_text())
    assert len(provenance['output_source_indices'])==len(merged['records'])
    seen=[[],[]]
    for j,((k,t,p),(source,i)) in enumerate(zip(merged['records'],provenance['output_source_indices'])):
        sk,st,sp=(a,b)[source]['records'][i]
        assert (k,p)==(sk,sp) and ticks[2][j]==ticks[source][i]
        assert t==(st if source==0 else starts[ticks[1][i]][1])
        seen[source].append(i)
    removed={i for i,(k,t,p) in enumerate(a['records']) if selected(k,p) and ticks[0][i]<=last}
    assert removed==set(provenance['removed_a_indices'])
    assert seen[0]==[i for i in range(len(a['records'])) if i not in removed]
    assert seen[1]==[i for i,(k,t,p) in enumerate(b['records']) if selected(k,p)]
    for r in (merged,observer):
        assert framing(r['data'])[1]==framing(a['data'])[1]
        assert all(x[1]<=y[1] for x,y in zip(r['records'],r['records'][1:]))
        with zipfile.ZipFile(a['path']) as src,zipfile.ZipFile(r['path']) as dst:
            assert dst.testzip() is None
            assert all(src.read(n)==dst.read(n) for n in src.namelist() if n!='data.wotreplay')
    participant=lambda r:[row for row in r['records'] if row[0] in ENTITY_KINDS and int.from_bytes(row[2][:4],'little') in a['roster']]
    assert participant(merged)==participant(observer)
    old=read_replay(original/'dual-team-merged.wotbreplay')
    oldticks=tick_index(old['records'])[1]
    oldprov=json.loads((original/'merged-provenance.json').read_text())['output_source_indices']
    olddiff=Counter(oldticks[j]-ticks[1][i] for j,(source,i) in enumerate(oldprov) if source==1 and old['records'][j][0]==10)
    playback=json.loads((folder/'observer-playback.json').read_text())
    assert len(playback['vehicles'])==14
    start=a['battle_start']['battle_start_raw_sec'];end=next(p['raw'] for p in a['periods'] if p['values'][1]==4)
    rows=[]
    for v in playback['vehicles']:
        alive_end=min(end,v['death_t'] if v['death_t'] is not None else end)
        cv=v['coverage'];known=sum(max(0,min(alive_end,cv[i+1])-max(start,cv[i])) for i in range(0,len(cv),2))
        assert known>=alive_end-start-.05
        moves=[(t,struct.unpack_from('<3f',p,12)) for k,t,p in merged['records'] if k==10 and int.from_bytes(p[:4],'little')==v['eid']]
        times=[t for t,pos in moves if start<=t<=alive_end]
        gap=max((y-x for x,y in zip(times,times[1:])),default=0)
        assert gap<.5
        row=dict(eid=v['eid'],alive_seconds=alive_end-start,known_seconds=known,max_motion_gap=gap)
        if v['team']==1 and alive_end>manifest['donor_last_tick_time']:
            before=max((r for r in moves if r[0]<=manifest['donor_last_tick_time']),key=lambda r:r[0])
            after=min((r for r in moves if r[0]>manifest['donor_last_tick_time']),key=lambda r:r[0])
            row['handoff']=dict(seconds=after[0]-before[0],distance=math.dist(before[1],after[1]))
            assert row['handoff']['seconds']<.3 and row['handoff']['distance']<2
        rows.append(row)
    result=dict(passed=True,source_payloads_preserved=True,source_a_nonreplaced_stream_identical=True,
        all_donor_packets_keep_original_server_tick=True,observer_participant_packets_identical=True,
        all_14_alive_intervals_covered=True,metadata_results_terminal_preserved=True,
        v1_donor_movement_tick_delta=dict(olddiff),v1_wrong_tick_movements=sum(n for d,n in olddiff.items() if d),
        v2_wrong_tick_movements=0,rows=rows)
    (folder/'tick-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


if __name__=='__main__':main()
