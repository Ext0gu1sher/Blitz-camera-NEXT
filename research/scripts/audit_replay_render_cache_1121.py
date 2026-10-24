"""Read-only, exact-build NMaterial cache snapshots for replay rewind research.

Layout evidence: c9f660 deletes 0x60-byte pass blocks from NMaterial+90;
c9f900 allocates and initializes those blocks. This only checks container
structure; it cannot prove GPU resource validity or allocation ownership.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam.reader import CameraSession
from blitzcam.profile import CameraError

HASH = '5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608'


def words(data, offset, count):
    return struct.unpack_from('<'+'I'*count, data, offset)


def vector(memory, data, offset, stride, max_bytes=64*1024*1024):
    start, end, cap = words(data, offset, 3)
    result = dict(start=hex(start), end=hex(end), capacity_end=hex(cap))
    if not start and not end and not cap:
        result.update(valid=True, count=0, capacity=0)
        return result
    errors = []
    if not 0x10000 <= start <= end <= cap < 0x100000000:
        errors.append('pointer_order_or_range')
    elif (end-start) % stride or (cap-start) % stride:
        errors.append('element_alignment')
    elif cap-start > max_bytes:
        errors.append('capacity_bound')
    else:
        result.update(count=(end-start)//stride, capacity=(cap-start)//stride)
        if cap > start:
            try:
                memory.read(start, 1)
                memory.read(cap-1, 1)
                # MSVC large allocation deallocator accesses this metadata.
                if cap-start >= 4096:
                    raw = memory.u32(start-4)
                    result['large_allocation_base'] = hex(raw)
                    if not 4 <= start-raw <= 35:
                        errors.append('large_allocation_header')
            except CameraError:
                errors.append('allocation_endpoints_unreadable')
    result.update(valid=not errors, errors=errors)
    return result


def snapshot(session, addresses=None):
    memory = session.memory
    vft = session.live(0x3759f4c)
    if addresses is None:
        addresses = set()
        rx = re.compile(re.escape(struct.pack('<I', vft)))
        for start, length in memory.regions():
            for a in range(start, start+length, 1024*1024):
                try:
                    data = memory.read(a, min(1024*1024, start+length-a))
                except CameraError:
                    continue
                for match in rx.finditer(data):
                    if not (a+match.start()) % 4:
                        addresses.add(a+match.start())
    rows = []
    for address in sorted(addresses):
        try:
            data = memory.read(address, 0xa4)
            # Secondary vft provides a stronger identity check than a lone hit.
            if words(data, 0, 1)[0] != vft or words(data, 0x20, 1)[0] != session.live(0x3759f68):
                continue
            row = dict(address=hex(address), flags=data[0xa0:0xa4].hex(),
                       passes=vector(memory, data, 0x90, 8, 8192), blocks=[])
            if row['passes']['valid'] and row['passes']['count']:
                p, e, _ = words(data, 0x90, 3)
                entries = memory.read(p, e-p)
                for at in range(0, len(entries), 8):
                    key, child = words(entries, at, 2)
                    item = dict(key=hex(key), address=hex(child))
                    try:
                        block = memory.read(child, 0x60)
                        item.update(raw=block.hex(), vectors={hex(o): vector(memory, block, o, 4)
                                                              for o in (0x10, 0x1c, 0x28)})
                    except CameraError as exc:
                        item['error'] = str(exc)
                    row['blocks'].append(item)
            rows.append(row)
        except CameraError:
            continue
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    session = CameraSession.connect()
    try:
        if session.profile.sha256 != HASH:
            raise RuntimeError('Only the verified 11.21 hash is supported.')
        before = session.capture()
        first = snapshot(session)
        time.sleep(.1)
        second = snapshot(session, [int(r['address'], 16) for r in first])
        after = session.capture()
        invalid = [r for r in second if not r['passes']['valid'] or any(
            'error' in b or any(not v['valid'] for v in b.get('vectors', {}).values())
            for b in r['blocks'])]
        result = dict(utc=datetime.now(timezone.utc).isoformat(), read_only=True,
                      client_sha256=HASH, pid=session.info.pid, before=before, after=after,
                      materials=second, first_count=len(first), second_count=len(second),
                      changed_between_reads=first != second, invalid=invalid,
                      limitation='Non-atomic external snapshot, structural checks only; not GPU validity or allocation ownership.')
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(dict(pid=session.info.pid, materials=len(second),
                              pass_blocks=sum(len(r['blocks']) for r in second),
                              invalid=len(invalid), changed=first != second,
                              replay=after['replay'], path=args.out), ensure_ascii=False))
    finally:
        session.close()


if __name__ == '__main__':
    main()
