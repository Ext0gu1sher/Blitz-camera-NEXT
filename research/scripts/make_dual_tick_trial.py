"""Exact-pair v2: preserve donor server tick association, not arrival jitter."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from analyze_dual_replay import read_replay, coverage
from make_dual_replay_trial import EXPECTED, ENTITY_KINDS, framing, raw_record


def tick_index(records):
    bases = [(i, int.from_bytes(p, 'little')) for i, (k, t, p) in enumerate(records) if k == 36]
    assert len(bases) == 1 and len(records[bases[0][0]][2]) == 4
    base = bases[0][1]
    tick = None
    assigned = []
    starts = {}
    for i, (k, t, p) in enumerate(records):
        if k == 35:
            assert len(p) == 1
            if tick is None:
                tick = base
                assert p[0] == tick % 256
            else:
                assert p[0] == (tick + 1) % 256
                tick += 1
            starts[tick] = (i, t)
        if k == 36:
            assert tick == base
        assigned.append(tick)
    return base, assigned, starts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-folder', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    audit = json.loads((args.source_folder / 'audit.json').read_text(encoding='utf8'))
    a, b = [read_replay(v['path']) for v in audit['inputs']]
    assert (a['sha256'], b['sha256']) == EXPECTED and a['roster'] == b['roster']
    base_a, ticks_a, starts_a = tick_index(a['records'])
    base_b, ticks_b, starts_b = tick_index(b['records'])
    assert base_a == base_b and set(starts_b) <= set(starts_a)
    targets = {eid for eid, v in a['roster'].items() if v['team'] == 1 and not v['observer']}
    assert len(targets) == 7
    selected = lambda k, p: k in ENTITY_KINDS and len(p) >= 4 and int.from_bytes(p[:4], 'little') in targets
    end_tick = max(starts_b)
    donor = defaultdict(list)
    for i, (k, t, p) in enumerate(b['records']):
        if selected(k, p):
            assert ticks_b[i] is not None
            donor[ticks_b[i]].append(i)
    output = []
    provenance = []
    removed = []
    for i, (k, t, p) in enumerate(a['records']):
        if selected(k, p) and ticks_a[i] <= end_tick:
            removed.append(i)
        else:
            output.append((k, t, p)); provenance.append((0, i))
        if k == 35:
            for j in donor.get(ticks_a[i], []):
                dk, dt, dp = b['records'][j]
                output.append((dk, t, dp)); provenance.append((1, j))
    assert all(x[1] <= y[1] for x, y in zip(output, output[1:]))
    _, newticks, newstarts = tick_index(output)
    assert [(tick, t) for tick, (i, t) in newstarts.items()] == [(tick, t) for tick, (i, t) in starts_a.items()]
    for row, tick, (source, i) in zip(output, newticks, provenance):
        original = (a, b)[source]['records'][i]
        assert row[0] == original[0] and row[2] == original[2]
        assert tick == (ticks_a, ticks_b)[source][i]
        if source == 0:
            assert row == original
    assert [i for source, i in provenance if source == 1] == [i for i, (k, t, p) in enumerate(b['records']) if selected(k, p)]
    # Every donor movement retains its source server tick; no invented samples.
    header, terminal = framing(a['data'])
    data = bytearray(header + b''.join(raw_record(*r) for r in output) + terminal)
    struct.pack_into('<I', data, 4, len(data) - 8)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / 'dual-team-merged.wotbreplay'
    with zipfile.ZipFile(a['path']) as src, zipfile.ZipFile(target, 'x') as dst:
        dst.comment = src.comment
        for info in src.infolist():
            dst.writestr(info, data if info.filename == 'data.wotreplay' else src.read(info))
    got = read_replay(target)
    assert got['records'] == output and got['roster'] == a['roster']
    for row in coverage(got):
        if not row['observer']:
            assert row['creates'] == 1 and row['exits'] == 0
    assert tuple(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest() for r in (a, b)) == EXPECTED
    manifest = dict(trial=str(target.resolve()), trial_sha256=got['sha256'], sources=audit['inputs'],
        strategy='donor packets placed immediately after the matching source-A server tick',
        tick_base=base_a, donor_last_tick=end_tick, donor_last_tick_time=starts_a[end_tick][1],
        removed_packets=len(removed), added_packets=sum(map(len, donor.values())),
        output_packets=len(output), donor_packet_counts=dict(Counter(b['records'][i][0] for ids in donor.values() for i in ids)),
        source_a_kept_packets_unchanged=True, payloads_unchanged=True, all_server_tick_associations_preserved=True,
        original_metadata_results_terminal_preserved=True, originals_unchanged=True, client_acceptance='not tested')
    (args.out / 'merged-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    (args.out / 'merged-provenance.json').write_text(json.dumps(dict(removed_a_indices=removed, output_source_indices=provenance)))
    print(json.dumps({k: v for k, v in manifest.items() if k != 'sources'}, indent=2))


if __name__ == '__main__':
    main()
