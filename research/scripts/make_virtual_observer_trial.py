"""Disposable exact-sample virtual-observer trial; no installed files are edited.

Keep all 14 original roster entries intact. Add one observer-only identity and
redirect the Avatar cell's candidate player-vehicle reference to that identity.
This first variant deliberately has no extra materialized vehicle. Whether the
client accepts such an observer is an experiment, not a protocol claim.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from make_observer_replay_trial import fields, message, varint

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'output/observer-replay-trial-20261024/original-control.wotbreplay'
OUT = ROOT / 'output/virtual-observer-trial-20261024'
ORIGINAL_SHA = '50ae08302cd51c1d5990c69d799e8733ffa7f067efee066b2584c586bf0b40e7'
OLD = 136616900
NEW = 0x70000001
DBID = 2147483001
NAME = b'ReplayCamera'


def roster(root, reverse=False):
    result = bytearray()
    found = 0
    for field, wire, block, raw in fields(root):
        if (field, wire) != (1, 2):
            result.extend(raw)
            continue
        rows = list(fields(block))
        assert all((f, w) == (1, 2) for f, w, _, _ in rows)
        assert len(rows) == (15 if reverse else 14)
        originals = []
        extra = None
        for _, _, value, encoded in rows:
            vf = list(fields(value))
            scalars = {f: v for f, w, v, _ in vf if w == 0}
            assert scalars.get(14, 0) == (2 if scalars[1] == NEW else 0)
            if reverse and scalars[1] == NEW:
                found += 1
                continue
            originals.append(encoded)
            if not reverse:
                assert scalars[1] != NEW and scalars.get(7) != DBID
                if scalars[1] == OLD:
                    found += 1
                    extra = b''.join(
                        varint(f << 3) + varint(NEW if f == 1 else DBID)
                        if f in (1, 7) else message(3, NAME) if f == 3 else r
                        for f, w, v, r in vf)
                    extra += varint(14 << 3) + varint(2)
        assert len(originals) == 14
        if not reverse:
            assert extra is not None
            originals.append(message(1, extra))
        result.extend(message(1, b''.join(originals)))
    assert found == 1
    return bytes(result)


def ghost_payload(kind, payload):
    assert kind in (33, 5) and struct.unpack_from('<I', payload)[0] == OLD
    ghost = struct.pack('<I', NEW) + payload[4:]
    if kind == 5:
        assert len(payload) == 217 and struct.unpack_from('<H', payload, 4)[0] == 2
        assert struct.unpack_from('<I', payload, 38)[0] == len(payload) - 42
        assert payload[57] == len(NAME) and payload[58:70] == b'Wot_Bismarck'
        ghost = ghost[:58] + NAME + ghost[70:]
    return ghost


def transform(data, reverse=False, materialize=False):
    assert struct.unpack_from('<II', data) == (0x12345678, len(data) - 8)
    offset = 12
    for _ in range(2):
        offset += 1 + data[offset]
    offset += 1
    result = bytearray(data[:offset])
    changes = []
    index = 0
    terminal = False
    inserted = 0
    expected_extra = None
    while offset + 12 <= len(data):
        size, kind, clock = struct.unpack_from('<IIf', data, offset)
        end = offset + 12 + size
        assert end <= len(data)
        payload = data[offset + 12:end]
        before = payload
        if reverse and expected_extra is not None:
            assert data[offset:end] == expected_extra
            expected_extra = None
            inserted += 1
            offset = end
            continue
        if kind == 0xFFFFFFFF:
            assert end == len(data)
            result.extend(data[offset:])
            terminal = True
            break
        if kind == 8 and len(payload) >= 16 and struct.unpack_from('<I', payload, 4)[0] == 48 and payload[12] == 1:
            assert index == 4 and payload[13] == 255
            assert int.from_bytes(payload[14:17], 'little') == len(payload) - 17
            assert struct.unpack_from('<I', payload, 8)[0] == len(payload) - 12
            root = roster(payload[17:], reverse)
            args = b'\x01\xff' + len(root).to_bytes(3, 'little') + root
            payload = payload[:8] + struct.pack('<I', len(args)) + args
        if kind == 1:
            # Exact-sample envelope: 36-byte cell bootstrap, 82 property bytes;
            # first property tag 2 is followed by the original roster vehicle ID.
            assert index == 10 and len(payload) == 122
            assert struct.unpack_from('<I', payload, 36)[0] == 82 and payload[40] == 2
            assert struct.unpack_from('<I', payload, 41)[0] == (NEW if reverse else OLD)
            payload = payload[:41] + struct.pack('<I', OLD if reverse else NEW) + payload[45:]
        if payload != before:
            changes.append({'record': index, 'kind': kind, 'clock': clock, 'size_delta': len(payload) - size})
        result.extend(struct.pack('<I', len(payload)) + data[offset + 4:offset + 12] + payload)
        if materialize and kind in (33, 5) and struct.unpack_from('<I', payload)[0] == OLD:
            extra = ghost_payload(kind, payload)
            extra_record = struct.pack('<IIf', len(extra), kind, clock) + extra
            if reverse:
                expected_extra = extra_record
            else:
                result.extend(extra_record)
                inserted += 1
        offset = end
        index += 1
    assert terminal and [c['record'] for c in changes] == [4, 10]
    assert inserted == (2 if materialize else 0) and expected_extra is None
    struct.pack_into('<I', result, 4, len(result) - 8)
    return bytes(result), changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--materialize', action='store_true', help='Add one cloned observer vehicle entry/materialization pair')
    args = parser.parse_args()
    original = SOURCE.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    OUT.mkdir(exist_ok=True)
    variant = 'materialized' if args.materialize else 'roster-only'
    target = OUT / f'virtual-observer-{variant}.wotbreplay'
    manifest = OUT / ('manifest-materialized.json' if args.materialize else 'manifest.json')
    assert not target.exists() and not manifest.exists()
    with zipfile.ZipFile(SOURCE) as z:
        assert z.testzip() is None
        data = z.read('data.wotreplay')
        altered, changes = transform(data, materialize=args.materialize)
        reverted, _ = transform(altered, reverse=True, materialize=args.materialize)
        assert reverted == data, 'Failed byte-for-byte reversal'
        with zipfile.ZipFile(target, 'x') as out:
            out.comment = z.comment
            for item in z.infolist():
                out.writestr(item, altered if item.filename == 'data.wotreplay' else z.read(item))
    with zipfile.ZipFile(target) as trial, zipfile.ZipFile(SOURCE) as source:
        assert trial.testzip() is None and trial.namelist() == source.namelist()
        assert all(trial.read(n) == source.read(n) for n in trial.namelist() if n != 'data.wotreplay')
    assert SOURCE.read_bytes() == original
    report = dict(source=str(SOURCE), source_sha256=ORIGINAL_SHA, trial=str(target),
                  trial_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                  original_vehicle=OLD, virtual_observer=NEW, virtual_dbid=DBID,
                  original_roster_rows_preserved=14, observer_rows_added=1,
                  extra_vehicle_materialized=args.materialize, added_packets=2 if args.materialize else 0,
                  changed_packets=changes,
                  original_metadata_preserved=True, terminal_record_preserved=True,
                  exact_reverse_verified=True, client_acceptance='not tested')
    manifest.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
