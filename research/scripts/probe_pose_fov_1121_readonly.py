"""Exact-build RPM-only observation of replay pose and animation quiescence.

No write handle, game calls, hooks, input injection or thread suspension.
Idle here is an observation, never a permission to write asynchronously.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam.profile import CameraError, IncoherentSample, SessionChanged, PROFILE_1121
from blitzcam.reader import CameraSession


def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def vector_pointers(mem, header):
    begin, end, cap = struct.unpack('<3I', header)
    if not (begin <= end <= cap and (end-begin) % 4 == 0 and
            (cap-begin) % 4 == 0 and cap-begin <= 16384):
        raise IncoherentSample('Invalid/bounded animation vector.')
    if end == begin:
        return []
    if begin < 0x10000 or begin % 4:
        raise IncoherentSample('Invalid animation vector address.')
    return list(struct.unpack('<'+'I'*((end-begin)//4), mem.read(begin, end-begin)))


class AnimationProbe:
    def __init__(self, session):
        self.s = session
        self.mem = session.memory
        self.core = self.mem.u32(session.live(0x4690a30))
        self.jobs = self.mem.u32(self.core)
        self.manager = self.mem.u32(self.core+0x44)
        self.owner = self.mem.u32(session.objects.spectator_controller+0x134)
        self.field = session.objects.spectator_controller+0x114
        self.guard()

    def guard(self):
        s, m = self.s, self.mem
        if (m.u32(s.live(0x4690a30)) != self.core or m.u32(self.core) != self.jobs or
            m.u32(self.core+0x44) != self.manager or
            m.u32(self.jobs) != s.live(0x372a4c4) or
            m.u32(s.objects.spectator_controller+0x134) != self.owner or
            m.u32(self.owner) != s.live(0x372adb4)):
            raise SessionChanged('Animation/core identity changed.')

    def jobs_header(self):
        # +10 is a waiter count, NOT an executing-job ID. +68..+9f is the
        # in-flight record copied out of the deque by 0x92aec0 before pop.
        d = self.mem.read(self.jobs, 0xa0)
        count, size = u32(d, 0x60), u32(d, 0x58)
        if size > 1048576 or (size and size & (size-1)) or count > size:
            raise IncoherentSample('Invalid/bounded main-thread job deque.')
        return {'reserved_id': u32(d, 0xc), 'waiters': u32(d, 0x10),
                'completed_id': u32(d, 0x14), 'queue_map': hex(u32(d, 0x54)),
                'queue_map_size': u32(d, 0x58), 'queue_start': u32(d, 0x5c),
                'queue_count': u32(d, 0x60), 'inflight_id': u32(d, 0x68),
                'inflight_mode': u32(d, 0x6c), 'inflight_origin_thread': u32(d, 0x70),
                'inflight_functor': hex(u32(d, 0x9c))}

    def containers(self):
        m = self.mem
        h = m.read(self.manager+4, 8)
        head, count = struct.unpack('<2I', h)
        if not 0 <= count <= 64 or head < 0x10000:
            raise IncoherentSample('Invalid animation map header.')
        head_bytes = m.read(head, 8)
        node, prev = u32(head_bytes), head
        nodes, entries, seen = [], [], set()
        while node != head:
            if node in seen or len(seen) >= count:
                raise IncoherentSample('Animation map cycle/count mismatch.')
            seen.add(node)
            d = m.read(node, 0x14)
            nxt, back, group, bucket = u32(d), u32(d, 4), u32(d, 8), u32(d, 0x10)
            if back != prev or not bucket:
                raise IncoherentSample('Animation map link mismatch.')
            vectors = m.read(bucket, 0x18)
            registered = vector_pointers(m, vectors[:12])
            update = vector_pointers(m, vectors[12:24])
            nodes.append((node, d.hex(), bucket, vectors.hex()))
            entries.append({'group': group, 'bucket': hex(bucket),
                            'registered': registered, 'update': update})
            prev, node = node, nxt
        if len(seen) != count or u32(head_bytes, 4) != prev:
            raise IncoherentSample('Animation map traversal incomplete.')
        if m.read(self.manager+4, 8) != h or m.read(head, 8) != head_bytes:
            raise IncoherentSample('Animation map changed during traversal.')
        for p, raw, bucket, vectors in nodes:
            if m.read(p, 0x14).hex() != raw or m.read(bucket, 0x18).hex() != vectors:
                raise IncoherentSample('Animation containers changed during traversal.')
        return entries

    def animation(self, p):
        if p < 0x10000 or p % 4:
            raise IncoherentSample('Invalid animation pointer.')
        d = self.mem.read(p, 0x50)
        result = {'address': hex(p), 'vft': hex(u32(d)), 'flags': u32(d, 0x18),
                  'owner': hex(u32(d, 0x2c)), 'next': hex(u32(d, 0x30)),
                  'track': u32(d, 0x34), 'group': u32(d, 0x48)}
        related = u32(d, 0x2c) == self.owner
        if u32(d) == self.s.live(0x375e610):
            # Only this verified type has an A8-byte layout.
            full = self.mem.read(p, 0xa8)
            get, put = u32(full, 0x74), u32(full, 0x9c)
            callbacks = []
            for ptr, preferred in ((get, 0x380c544), (put, 0x380c560)):
                if not ptr:
                    callbacks.append(None)
                    continue
                cb = self.mem.read(ptr, 8)
                callbacks.append({'address': hex(ptr), 'vft': hex(u32(cb)),
                                  'expected_type': u32(cb) == self.s.live(preferred),
                                  'float_address': hex(u32(cb, 4))})
            binding = any(cb and cb['expected_type'] and
                          cb['float_address'] == hex(self.field) for cb in callbacks)
            related = related or binding
            if related:
                result.update(float_animation={
                    'elapsed': struct.unpack_from('<f', full, 0x1c)[0],
                    'duration': struct.unpack_from('<f', full, 0x20)[0],
                    'progress': struct.unpack_from('<f', full, 0x24)[0],
                    'time_scale': struct.unpack_from('<f', full, 0x40)[0],
                    'end': struct.unpack_from('<f', full, 0xa0)[0],
                    'start': struct.unpack_from('<f', full, 0xa4)[0],
                    'getter': callbacks[0], 'setter': callbacks[1],
                    'binds_current_fov': binding, 'raw_hex': full.hex()})
        result['related'] = related
        return result

    def observe(self):
        self.guard()
        jobs_a = self.jobs_header()
        containers_a = self.containers()
        roots = {p for c in containers_a for key in ('registered', 'update') for p in c[key]}
        todo, found = list(roots), {}
        while todo:
            p = todo.pop()
            if p in found:
                continue
            if len(found) >= 512:
                raise IncoherentSample('Animation chain bound exceeded.')
            a = self.animation(p)
            found[p] = a
            if int(a['next'], 16):
                todo.append(int(a['next'], 16))
        for root in roots:
            chain_seen, p = set(), root
            while p:
                if p in chain_seen:
                    raise IncoherentSample('Animation next-chain cycle.')
                chain_seen.add(p)
                p = int(found[p]['next'], 16)
        jobs_b = self.jobs_header()
        containers_b = self.containers()
        if containers_a != containers_b or jobs_a != jobs_b:
            raise IncoherentSample('Animation/job structure changed across observation.')
        # Metadata may have changed even if vector headers did not.
        for p, a in found.items():
            d = self.mem.read(p, 0x50)
            if (hex(u32(d)), u32(d, 0x18), hex(u32(d, 0x2c)), hex(u32(d, 0x30)),
                u32(d, 0x34), u32(d, 0x48)) != tuple(a[k] for k in
                    ('vft', 'flags', 'owner', 'next', 'track', 'group')):
                raise IncoherentSample('Animation metadata changed across observation.')
        relevant = [a for a in found.values() if a['related']]
        no_jobs = (jobs_b['reserved_id'] != 0 and
                   jobs_b['queue_count'] == 0 and jobs_b['inflight_id'] == 0 and
                   jobs_b['inflight_functor'] == '0x0' and
                   jobs_b['reserved_id'] == jobs_b['completed_id'])
        self.guard()
        return {'owner': hex(self.owner), 'field': hex(self.field), 'jobs': jobs_b,
                'containers': containers_b, 'relevant': relevant,
                'registered_or_chained_count': len(found),
                'observed_quiescent': not relevant and no_jobs,
                'frame_synchronized': False, 'write_ready': False}


def angle_check(snap):
    n, r = snap['native_controller'], snap['raw_camera']
    yaw, pitch = map(math.radians, n['smoothed_angles'])
    expected = [math.sin(yaw)*math.cos(pitch), math.cos(yaw)*math.cos(pitch), -math.sin(pitch)]
    return {'expected_direction': expected,
            'native_direction_residual': math.dist(expected, [x/100 for x in n['direction_scaled']]),
            'camera_direction_residual': math.dist(expected, r['direction']),
            'scaled_fov_residual_deg': abs(r['interface_fov']*r['fov_scale']-r['projected_fov_field'])}


def structural_signature(observation):
    result = {k: observation[k] for k in ('owner', 'field', 'jobs', 'containers',
              'registered_or_chained_count', 'observed_quiescent')}
    relevant = []
    for a in observation['relevant']:
        item = {k: a[k] for k in ('address', 'vft', 'flags', 'owner', 'next', 'track', 'group')}
        if 'float_animation' in a:
            item['binding'] = {k: a['float_animation'][k] for k in
                ('duration', 'time_scale', 'start', 'end', 'getter', 'setter', 'binds_current_fov')}
        relevant.append(item)
    result['relevant'] = sorted(relevant, key=lambda a: a['address'])
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--hz', type=float, default=100)
    args = ap.parse_args()
    if not 1 <= args.seconds <= 180 or not 1 <= args.hz <= 200:
        raise ValueError('Bounded observation only.')
    args.out.mkdir(parents=True, exist_ok=False)
    with CameraSession.connect() as s:
        if s.profile != PROFILE_1121:
            raise CameraError('Requires the exact 11.21.0.1235 build/hash.')
        first = s.capture(require_paused=True)
        probe = AnimationProbe(s)
        with (args.out/'start.json').open('x', encoding='utf8') as f:
            json.dump(first, f, ensure_ascii=False, indent=2)
        print(json.dumps({'ready': True, 'session': first['session_id'],
                          'time': first['replay']['time'], 'out': str(args.out)}), flush=True)
        begin, count, drops = time.perf_counter(), 0, 0
        with (args.out/'samples.jsonl').open('x', encoding='utf8') as f:
            while time.perf_counter()-begin < args.seconds:
                at = time.perf_counter()
                try:
                    anim = probe.observe()
                    snap = s.capture(require_paused=True)
                    if (snap['session_id'] != first['session_id'] or
                        snap['replay']['time'] != first['replay']['time'] or
                        snap['replay']['origin'] != first['replay']['origin']):
                        raise SessionChanged('Paused replay time/identity changed.')
                    extra = s.memory.read(s.objects.spectator_controller, 0x138)
                    anim_after = probe.observe()
                    if structural_signature(anim) != structural_signature(anim_after):
                        raise IncoherentSample('Animation/job structure changed around camera capture.')
                    row = {'sample': snap, 'animation': anim, 'checks': angle_check(snap),
                           'input_bytes': list(extra[0x10:0x2e]),
                           'animation_bracketed': True,
                           'window_started': at, 'window_finished': time.perf_counter()}
                    count += 1
                except IncoherentSample as exc:
                    drops += 1
                    row = {'drop': str(exc), 'monotonic': time.perf_counter()}
                except CameraError as exc:
                    f.write(json.dumps({'stopped': str(exc), 'monotonic': time.perf_counter()})+'\n')
                    f.flush()
                    raise
                f.write(json.dumps(row, ensure_ascii=False)+'\n')
                f.flush()
                time.sleep(max(0, 1/args.hz-(time.perf_counter()-at)))
        report = {'utc': datetime.now(timezone.utc).isoformat(), 'valid': count, 'dropped': drops,
                  'observed_seconds': time.perf_counter()-begin, 'writes_performed': 0,
                  'write_ready': False, 'engine_tick_fence': False}
        with (args.out/'summary.json').open('x', encoding='utf8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
