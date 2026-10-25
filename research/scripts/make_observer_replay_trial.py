"""Build a disposable 11.21 observer-identity trial; never edit the source.

Changes only recorder VehicleInfo.observer_mode in the initial arena roster.
Unknown terminal-record bytes are preserved, not claimed to be recomputed.
The client must still accept the resulting file before any HUD result counts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from blitzcam.replay_events import _varint


def varint(n):
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    return bytes(out + bytes([n]))


def fields(data):
    off = 0
    while off < len(data):
        start = off
        tag, off = _varint(data, off)
        field, wire = tag >> 3, tag & 7
        assert field > 0
        if wire == 0:
            value, off = _varint(data, off)
        elif wire in (1, 2, 5):
            size = 8 if wire == 1 else 4
            if wire == 2:
                size, off = _varint(data, off)
            value = data[off:off + size]
            assert len(value) == size
            off += size
        else:
            raise ValueError(f'Unsupported wire type {wire}')
        yield field, wire, value, data[start:off]


def message(field, data):
    return varint((field << 3) | 2) + varint(len(data)) + data


def rewrite_roster(root, dbid, remove=False):
    changed = []
    outer = bytearray()
    for f, w, v, raw in fields(root):
        if (f, w) != (1, 2):
            outer.extend(raw)
            continue
        inner = bytearray()
        for g, x, vehicle, original in fields(v):
            if (g, x) != (1, 2):
                inner.extend(original)
                continue
            vf = list(fields(vehicle))
            scalars = {a: c for a, b, c, _ in vf if b == 0}
            if scalars.get(7) != dbid:
                inner.extend(original)
                continue
            existing = [(b, c) for a, b, c, _ in vf if a == 14]
            assert existing == ([(0, 2)] if remove else []), existing
            updated = b''.join(r for a, _, _, r in vf if a != 14)
            if not remove:
                updated += varint(14 << 3) + varint(2)
            inner.extend(message(1, updated))
            changed.append(scalars[1])
        outer.extend(message(1, bytes(inner)))
    assert len(changed) == 1, changed
    return bytes(outer), changed[0]


def transform(data, dbid, remove=False):
    assert struct.unpack_from('<I', data)[0] == 0x12345678
    assert struct.unpack_from('<I', data, 4)[0] == len(data) - 8
    off = 12
    for _ in range(2):
        off += 1 + data[off]
    off += 1
    result = bytearray(data[:off])
    changes = []
    count = 0
    terminal = False
    while off + 12 <= len(data):
        size, kind, clock = struct.unpack_from('<IIf', data, off)
        end = off + 12 + size
        assert end <= len(data)
        payload = data[off + 12:end]
        if kind == 0xFFFFFFFF:
            assert end == len(data)
            result.extend(data[off:])
            terminal = True
            break
        if kind == 8 and len(payload) >= 16 and struct.unpack_from('<I', payload, 4)[0] == 48:
            n = struct.unpack_from('<I', payload, 8)[0]
            assert n == len(payload) - 12
            args = payload[12:]
            wrapper, at = _varint(args, 0)
            length_at = at
            if args[at] == 255:
                length = int.from_bytes(args[at + 1:at + 4], 'little')
                at += 4
            else:
                length = args[at]
                at += 1
            assert at + length == len(args)
            if wrapper == 1:
                root, entity = rewrite_roster(args[at:], dbid, remove)
                prefix = bytes([len(root)]) if len(root) < 255 else b'\xff' + len(root).to_bytes(3, 'little')
                new_args = args[:length_at] + prefix + root
                payload = payload[:8] + struct.pack('<I', len(new_args)) + new_args
                changes.append({'record': count, 'raw_clock': clock, 'vehicle_id': entity, 'size_delta': len(payload) - size})
        result.extend(struct.pack('<I', len(payload)) + data[off + 4:off + 12] + payload)
        count += 1
        off = end
    assert terminal and len(changes) == 1
    struct.pack_into('<I', result, 4, len(result) - 8)
    return bytes(result), changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    folder = args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'observer-both-player.wotbreplay'
    control = folder / 'original-control.wotbreplay'
    manifest = folder / 'manifest.json'
    assert not any(p.exists() for p in (target, control, manifest))
    before = source.read_bytes()
    sha = lambda b: hashlib.sha256(b).hexdigest()
    with zipfile.ZipFile(source) as z:
        assert z.testzip() is None
        metadata = json.loads(z.read('meta.json'))
        assert metadata['version'] == '11.21.0'
        data = z.read('data.wotreplay')
        altered, changes = transform(data, int(metadata['dbid']))
        reverted, _ = transform(altered, int(metadata['dbid']), remove=True)
        assert reverted == data, 'Roundtrip changed unrelated bytes'
        assert len(altered) - len(data) == 2
        with zipfile.ZipFile(target, 'x') as out:
            out.comment = z.comment
            for info in z.infolist():
                out.writestr(info, altered if info.filename == 'data.wotreplay' else z.read(info))
    with zipfile.ZipFile(target) as trial, zipfile.ZipFile(source) as original:
        assert trial.testzip() is None
        assert trial.namelist() == original.namelist()
        for name in trial.namelist():
            if name != 'data.wotreplay':
                assert trial.read(name) == original.read(name)
    control.write_bytes(before)
    assert source.read_bytes() == before
    report = {'source': str(source), 'source_sha256': sha(before), 'trial': str(target),
              'trial_sha256': sha(target.read_bytes()), 'control': str(control),
              'changed_packets': changes, 'recorded_vehicle_count_unchanged': True,
              'target_mode': 2, 'source_unchanged': True, 'exact_reverse_verified': True,
              'terminal_record': 'preserved verbatim; semantics unconfirmed',
              'client_acceptance': 'not yet tested'}
    manifest.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
