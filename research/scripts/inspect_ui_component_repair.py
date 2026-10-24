"""Decode the experimental UI removal event file offline (no process access).

Addresses describe observations, not allocation generations or proven types.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct

FIELDS = ('sequence stage owner component outer_begin outer_end '
          'header begin end capacity refs component_owner').split()
EVENT = struct.Struct('<12I')


def inspect(path):
    data = Path(path).read_bytes()
    if len(data) % EVENT.size:
        raise ValueError('Incomplete 48-byte event; stop the writer or read it again.')
    rows = [dict(zip(FIELDS, values)) for values in EVENT.iter_unpack(data)]
    pending, changes, failures = {}, [], []
    for expected, row in enumerate(rows, 1):
        if row['sequence'] != expected:
            raise ValueError('Event sequence has a gap; log is incomplete.')
        key = row['owner'], row['component']
        if row['stage'] == 3:
            pending[key] = row
        elif row['stage'] == 4:
            before = pending.pop(key, None)
            if before and any(before[n] != row[n] for n in
                              ('outer_begin', 'outer_end', 'header', 'begin', 'end', 'capacity')):
                changes.append(dict(before=before, after=row))
        if row['stage'] & 0xc0000000:
            failures.append(row)
    return dict(path=str(Path(path).resolve()), event_count=len(rows),
                stages=dict(Counter(str(r['stage']) for r in rows)),
                callback_storage_changes=changes, invariant_failures=failures,
                events=rows,
                limitations='Callback-boundary storage observations only; no allocation-generation/free-stack proof. A clean log is not full replay validation.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    result = inspect(args.capture)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: result[k] for k in ('event_count', 'stages', 'invariant_failures')}, indent=2))
