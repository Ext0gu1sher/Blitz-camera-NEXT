"""Read-only exact-build D3D11 index-buffer pool observations.

Evidence: a0c260 validates/returns a 28-byte slot, a23cc0 creates it,
a23dc0 unmaps it; see render-deep-* disassemblies. No virtual calls or writes.
Double reads detect changes, but never establish allocation lifetime or an
atomic snapshot. Pool metadata generations are native handle generations.
"""
import argparse
import ctypes as C
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam.memory import MEMORY_BASIC_INFORMATION
from blitzcam.profile import CameraError, PROFILE_1121
from blitzcam.reader import CameraSession


def decode_entry(data, index):
    resource, fmt, capacity, usage, shadow, flags, metadata = struct.unpack('<7I', data)
    generation = (metadata >> 1) & 0xff
    return dict(index=index, handle=hex(0x0c000000 | generation << 16 | index),
                in_use=bool(metadata & 1), generation=generation,
                metadata=hex(metadata), resource=hex(resource), format=fmt,
                capacity_bytes=capacity, usage=usage, cpu_shadow=hex(shadow),
                dirty=flags & 0xff, mapped=(flags >> 8) & 0xff, raw=data.hex())


def query(memory, address):
    info = MEMORY_BASIC_INFORMATION()
    n = memory.k.VirtualQueryEx(memory.handle, C.c_void_p(address), C.byref(info), C.sizeof(info))
    if not n:
        return dict(query_failed=True)
    return dict(base=hex(int(info.BaseAddress or 0)), size=int(info.RegionSize),
                state=int(info.State), protect=int(info.Protect), type=int(info.Type))


def pointer_shape(memory, pointer, vft_cache):
    """Only classify address shape/readability; this cannot validate a COM lifetime."""
    result = dict(memory=query(memory, pointer), issues=[])
    if not 0x10000 <= pointer < 0x100000000 or pointer % 4:
        result['issues'].append('resource_pointer_range_or_alignment')
        return result
    try:
        vft = memory.u32(pointer)
        result['vft'] = hex(vft)
        if vft not in vft_cache:
            methods = struct.unpack('<3I', memory.read(vft, 12))
            vft_cache[vft] = dict(methods=[hex(m) for m in methods],
                                  method_memory=[query(memory, m) for m in methods])
        result.update(vft_cache[vft])
        if any(m.get('state') != 0x1000 or m.get('protect', 0) & 0x101 or
               m.get('protect', 0) & 0xff not in (0x10, 0x20, 0x40, 0x80)
               for m in result['method_memory']):
            result['issues'].append('iunknown_method_not_executable')
    except CameraError as exc:
        result['issues'].append('resource_or_vft_unreadable')
        result['read_error'] = str(exc)
    return result


def globals_bytes(session):
    m = session.memory
    return (m.read(session.live(0x468f1a8), 16),
            m.read(session.live(0x4138cac), 4),
            m.read(session.live(0x468fea4), 44),
            m.read(session.live(0x4138e80), 4))


def snapshot(session):
    if session.profile.sha256 != PROFILE_1121.sha256:
        raise CameraError('Index pool observations require the exact 11.21 image.')
    m = session.memory
    first_globals = globals_bytes(session)
    pool, live_count, high_water, free_head = struct.unpack('<4I', first_globals[0])
    capacity = struct.unpack('<I', first_globals[1])[0]
    if not 0x10000 <= pool < 0x100000000 or not 0 < capacity <= 65536:
        raise CameraError('Unbounded or uninitialized pool; no slot traversal.')
    raw = m.read(pool, capacity * 28)
    rows, vfts = [], {}
    for index in range(capacity):
        row = decode_entry(raw[index*28:(index+1)*28], index)
        row['address'] = hex(pool + index * 28)
        if row['in_use']:
            row['pointer_shape'] = pointer_shape(m, int(row['resource'], 16), vfts)
        rows.append(row)
    ctx = struct.unpack('<11I', first_globals[2])
    dynamic = dict(raw_words=[hex(v) for v in ctx], current_wrapper=hex(ctx[0]),
                   mapped_pointer=hex(ctx[1]), used_bytes=ctx[2],
                   block_capacity=struct.unpack('<I', first_globals[3])[0])
    if ctx[0]:
        try:
            handle, block_capacity, frame_token = struct.unpack('<3I', m.read(ctx[0], 12))
            index = handle & 0xffff
            dynamic.update(handle=hex(handle), wrapper_capacity=block_capacity, frame_token=frame_token,
                           handle_index=index, handle_generation=(handle >> 16) & 0xff)
            if index < capacity:
                metadata = struct.unpack_from('<I', raw, index*28+24)[0]
                dynamic['handle_matches_slot'] = (handle >> 24 == 12 and bool(metadata & 1) and
                                                  ((handle >> 15) ^ metadata) & 0x1fe == 0)
                dynamic['slot_snapshot'] = rows[index]
        except CameraError as exc:
            dynamic['read_error'] = str(exc)
    second_raw = m.read(pool, capacity * 28)
    second_globals = globals_bytes(session)
    changed = [i for i in range(capacity) if raw[i*28:(i+1)*28] != second_raw[i*28:(i+1)*28]]
    issues = [dict(index=r['index'], handle=r['handle'], resource=r['resource'],
                   issues=r['pointer_shape']['issues']) for r in rows
              if r['in_use'] and r['pointer_shape']['issues']]
    return dict(pool=hex(pool), capacity=capacity, live_count=live_count, high_water=high_water,
                free_head=free_head, observed_in_use=sum(r['in_use'] for r in rows),
                stable_double_read=not changed and first_globals == second_globals,
                changed_slots=changed, globals_changed=first_globals != second_globals,
                pointer_shape_issues=issues, dynamic_index=dynamic, entries=rows,
                limitation='External non-atomic reads; native handle generations are not heap allocation generations. '
                           'Readable COM pointers and clean metadata do not prove object lifetime.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    session = CameraSession.connect()
    try:
        before = session.capture()
        result = snapshot(session)
        after = session.capture()
        result.update(utc=datetime.now(timezone.utc).isoformat(), read_only=True, pid=session.info.pid,
                      client_sha256=session.profile.sha256, before=before, after=after)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({k:result[k] for k in ('pid', 'pool', 'capacity', 'live_count', 'observed_in_use',
                                               'stable_double_read', 'pointer_shape_issues', 'dynamic_index')},
                         ensure_ascii=False))
    finally:
        session.close()


if __name__ == '__main__':
    main()
