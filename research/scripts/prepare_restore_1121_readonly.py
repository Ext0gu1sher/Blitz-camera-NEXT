"""Read-only evidence for a proposed position restore; never grants write readiness."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from blitzcam.profile import CameraError, IncoherentSample, PROFILE_1121
from blitzcam.reader import CameraSession


def controller_extra(session):
    data = session.memory.read(session.objects.spectator_controller, 0x138)
    vector = lambda off: list(struct.unpack_from('<3f', data, off))
    return {'input_bytes_10_2d': list(data[0x10:0x2e]),
            'bounds_min': vector(0x30), 'bounds_max': vector(0x3c),
            'position_boxes_begin_end': [hex(x) for x in struct.unpack_from('<2I', data, 0x48)],
            'target_position': vector(0xac),
            'scene_related_pointer_08': hex(struct.unpack_from('<I', data, 8)[0])}


def battle_links(session):
    # Independently traced RTTI +128 update interface in this exact build.
    pattern = struct.pack('<I', session.live(0x37f8f70))
    result = []
    mem = session.memory
    for start, length in mem.regions():
        for address in range(start, start+length, 1024*1024):
            try:
                data = mem.read(address, min(1024*1024, start+length-address))
            except CameraError:
                continue
            for match in re.finditer(re.escape(pattern), data):
                p = address+match.start()
                if p % 4:
                    continue
                try:
                    context = mem.u32(p+0x120)
                    interface = mem.u32(p+0x128)
                    owner = mem.u32(p+0x150)
                    controller = mem.u32(owner+0x68)
                    if (context == session.objects.context and
                        interface == session.live(0x37f8fb0) and
                        controller == session.objects.spectator_controller):
                        result.append({'battle_controller': hex(p), 'context_at_120': hex(context),
                                       'owner_at_150': hex(owner), 'spectator_at_owner_68': hex(controller)})
                except CameraError:
                    pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Evidence output already exists; choose a new path.')
    result = {'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'read-only preparation; not a restore test', 'write_ready': False,
              'writes_performed': 0, 'active_engine_root_verified': False}
    with CameraSession.connect() as session:
        if session.profile != PROFILE_1121:
            raise CameraError('This probe requires the exact supported 11.21 build.')
        result['battle_controller_links'] = battle_links(session)
        samples, drops = [], []
        for _ in range(100):
            before = controller_extra(session)
            try:
                snap = session.capture(require_paused=True)
                after = controller_extra(session)
                if before != after or after['target_position'] != snap['native_controller']['target_position']:
                    raise IncoherentSample('Extra controller fields changed across capture.')
                samples.append({'snapshot': snap, 'extra': after})
            except IncoherentSample as exc:
                drops.append(str(exc))
            time.sleep(.02)
        if not samples:
            raise CameraError('No coherent paused samples.')
        first, last = samples[0]['snapshot'], samples[-1]['snapshot']
        result.update(valid_samples=len(samples), dropped_samples=len(drops), drop_reasons=drops,
                      observed_span_seconds=last['monotonic']-first['monotonic'], first=samples[0], last=samples[-1])
        result['checks'] = {
            'unique_replay_times': len({s['snapshot']['replay']['time'] for s in samples}),
            'all_input_bytes_zero': all(not any(s['extra']['input_bytes_10_2d']) for s in samples),
            'all_input_vectors_zero': all(not any(s['snapshot']['native_controller'][key])
                for s in samples for key in ('input_vector_80', 'input_vector_9c')),
            'max_goal_camera_distance': max(math.dist(s['extra']['target_position'], s['snapshot']['camera']['position']) for s in samples),
            'max_position_deviation': max(math.dist(first['camera']['position'], s['snapshot']['camera']['position']) for s in samples),
            'current_fov_equals_goal': all(s['snapshot']['native_controller']['current_interface_fov'] ==
                s['snapshot']['native_controller']['target_interface_fov'] for s in samples),
            'target_inside_primary_bounds': all(all(lo <= x <= hi for lo,x,hi in zip(
                s['extra']['bounds_min'],s['extra']['target_position'],s['extra']['bounds_max'])) for s in samples)}
        # FOV equality does not prove animation inactivity; this is explicitly not a write gate.
        result['unresolved'] = ['active engine scene root', 'full constraint semantics',
                                'game update thread/phase fence', 'FOV animation inactivity']
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps({k: result[k] for k in ('write_ready','writes_performed','battle_controller_links','valid_samples','checks')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
