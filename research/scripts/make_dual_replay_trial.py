"""Exact-pair, offline-only replay fusion prototype with provenance.

Own-team entity streams come from each recorder. The longer A replay supplies
the tail, only after proving all donor vehicles are still materialized in A.
No client files, original archives, or process state are changed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import struct
import zipfile

from analyze_dual_replay import read_replay, coverage

EXPECTED = ('09becd67a9c7525069a6d0f718e6157d374bc459ea5a567b689fe9cd4f557924',
            'b13fad2ef39bf89c547e288e3e44a8d8cbfab1fa8e8a642b8d3a9b6d0faf1ba6')
ENTITY_KINDS = {4,5,7,8,10,33}


def raw_record(k,t,p):
    return struct.pack('<IIf',len(p),k,t)+p


def framing(data):
    at=12
    for _ in range(2):at+=1+data[at]
    at+=1
    header=data[:at]
    while at+12<=len(data):
        n,k,t=struct.unpack_from('<IIf',data,at)
        end=at+12+n
        assert end<=len(data)
        if k==0xffffffff:
            assert end==len(data)
            return header,data[at:]
        at=end
    raise ValueError('Missing terminal record')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);args=ap.parse_args()
    folder=args.folder
    audit=json.loads((folder/'audit.json').read_text(encoding='utf8'))
    a,b=[read_replay(v['path']) for v in audit['inputs']]
    assert (a['sha256'],b['sha256'])==EXPECTED and a['roster']==b['roster']
    assert a['recorder']['team']==2 and b['recorder']['team']==1
    anchors=json.loads((folder/'clock-anchors.json').read_text())
    events=[r for r in anchors if r['kind'].startswith('arena-')]
    assert len(events)>=300
    offset=statistics.median(r['a_minus_b'] for r in events)
    residuals=sorted(abs(r['a_minus_b']-offset) for r in events)
    assert residuals[round(.95*(len(residuals)-1))]<.025 and max(residuals)<.15
    cutoff=b['last_clock']+offset
    targets={eid for eid,v in a['roster'].items() if v['team']==1 and v['observer']==0}
    assert len(targets)==7
    for row in coverage(a):
        if row['eid'] in targets:
            assert any(start<=cutoff<=end for start,end in row['presence']),row
    for row in coverage(b):
        if row['eid'] in targets:
            assert row['creates']==1 and row['exits']==0
    def selected(k,p):
        return k in ENTITY_KINDS and len(p)>=4 and struct.unpack_from('<I',p)[0] in targets
    output=[];removed=[];added=[]
    for i,(k,t,p) in enumerate(a['records']):
        if selected(k,p) and t<=cutoff:
            removed.append(i)
        else:
            # Source A tie ordering is unchanged; donor initialization follows
            # source A's complete zero-time initialization prefix.
            output.append((t,0,i,k,p))
    for i,(k,t,p) in enumerate(b['records']):
        if selected(k,p):
            corrected=max(0.,t+offset)
            assert corrected<=cutoff+1e-6
            output.append((corrected,1,i,k,p));added.append(i)
    output.sort(key=lambda r:r[:3])
    header,terminal=framing(a['data'])
    altered=bytearray(header+b''.join(raw_record(k,t,p) for t,source,i,k,p in output)+terminal)
    struct.pack_into('<I',altered,4,len(altered)-8)
    # Verify every kept packet preserves its source payload and order. All
    # mutations are clock translation of donor headers and global length.
    kept=[(k,t,p) for t,source,i,k,p in output if source==0]
    removed_set=set(removed)
    assert kept==[r for i,r in enumerate(a['records']) if i not in removed_set]
    target=folder/'dual-team-merged.wotbreplay'
    assert not target.exists()
    with zipfile.ZipFile(a['path']) as src,zipfile.ZipFile(target,'x') as dst:
        dst.comment=src.comment
        for info in src.infolist():dst.writestr(info,altered if info.filename=='data.wotreplay' else src.read(info))
    merged=read_replay(target)
    assert merged['roster']==a['roster'] and merged['meta']==a['meta']
    assert len(merged['records'])==len(output)
    for got,(t,source,i,k,p) in zip(merged['records'],output):
        assert got==(k,struct.unpack('<f',struct.pack('<f',t))[0],p)
    for row in coverage(merged):
        if not row['observer']:
            assert row['creates']==1 and row['exits']==0,row
    with zipfile.ZipFile(target) as trial,zipfile.ZipFile(a['path']) as src:
        assert trial.testzip() is None
        assert all(trial.read(n)==src.read(n) for n in src.namelist() if n!='data.wotreplay')
    assert tuple(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest() for r in (a,b))==EXPECTED
    manifest=dict(trial=str(target.resolve()),trial_sha256=merged['sha256'],sources=[dict(path=r['path'],sha256=r['sha256']) for r in (a,b)],
        donor_clock_offset=offset,donor_cutoff_raw=cutoff,anchor_count=len(events),
        anchor_p95_residual=residuals[round(.95*(len(residuals)-1))],
        donor_vehicle_ids=sorted(targets),entity_packet_kinds=sorted(ENTITY_KINDS),
        removed_packets=len(removed),added_packets=len(added),output_packets=len(output),
        donor_packet_counts=dict(Counter(b['records'][i][0] for i in added)),
        source_a_nonreplaced_packets_unchanged=True,metadata_results_terminal_preserved=True,
        originals_unchanged=True,crc_passed=True,coverage=coverage(merged),client_acceptance='not tested',
        limitations=['No claim of server replay or universal protocol support.',
                    'Recorder-local camera/input/UI events still belong to source A.',
                    'Only entity-scoped vehicle data is fused; global effect completeness not asserted.'])
    (folder/'merged-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (folder/'merged-provenance.json').write_text(json.dumps(dict(removed_a_indices=removed,
        output_source_indices=[[source,i] for t,source,i,k,p in output]),separators=(',',':')))
    config=dict(output=str(folder.resolve()),inputs=[dict(label='merged',path=str(target.resolve()))])
    (folder/'decode-merged-config.json').write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('coverage','sources')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
