"""Offline summary of the bounded 11.21 RPM-only pose/FOV observation."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path


def direction_angle(a, b):
    dot = sum(x*y for x,y in zip(a,b))/math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
    return math.degrees(math.acos(max(-1, min(1, dot))))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    args = p.parse_args()
    rows = [json.loads(x) for x in (args.directory/'samples.jsonl').read_text(encoding='utf8').splitlines()]
    valid = [r for r in rows if 'sample' in r]
    first, last = valid[0]['sample'], valid[-1]['sample']
    by_animation = defaultdict(list)
    for r in valid:
        for a in r['animation']['relevant']:
            by_animation[a['address']].append((r,a))
    events = []
    for address, values in by_animation.items():
        f = values[0][1].get('float_animation')
        if not f:
            events.append({'address': address, 'unrecognized_related_type': True})
            continue
        events.append({'address': address, 'samples': len(values),
            'duration_parameter': f['duration'], 'start': f['start'], 'end': f['end'],
            'first_elapsed': f['elapsed'], 'last_elapsed': values[-1][1]['float_animation']['elapsed'],
            'first_monotonic': values[0][0]['window_started'],
            'last_monotonic': values[-1][0]['window_started'],
            'observed_wall_span': values[-1][0]['window_started']-values[0][0]['window_started'],
            'flags_observed': sorted({a['flags'] for _,a in values}),
            'all_setters_bind_current_fov': all(a['float_animation']['setter']['expected_type'] and
                a['float_animation']['setter']['float_address']==r['animation']['field'] for r,a in values),
            'busy_with_queue_and_inflight_empty': sum(r['animation']['jobs']['queue_count']==0 and
                r['animation']['jobs']['inflight_id']==0 and
                r['animation']['jobs']['inflight_functor']=='0x0' for r,_ in values),
            'max_interpolation_residual': max(abs(a['float_animation']['start']+
                (a['float_animation']['end']-a['float_animation']['start'])*a['float_animation']['progress']-
                r['sample']['native_controller']['current_interface_fov']) for r,a in values)})
    tail = [r for r in valid if r['sample']['monotonic']>=last['monotonic']-3]
    report = {'source': str(args.directory), 'build': first['build'],
        'valid': len(valid), 'drops': dict(Counter(r['drop'] for r in rows if 'drop' in r)),
        'first_utc': first['captured_at_utc'], 'last_utc': last['captured_at_utc'],
        'sample_span_seconds': last['monotonic']-first['monotonic'],
        'unique_replay_times': sorted({r['sample']['replay']['time'] for r in valid}),
        'unique_sessions': sorted({r['sample']['session_id'] for r in valid}),
        'max_position_change': max(math.dist(first['camera']['position'],r['sample']['camera']['position']) for r in valid),
        'first_camera': first['camera'], 'last_camera': last['camera'],
        'first_native_angles': first['native_controller']['target_angles'],
        'last_native_angles': last['native_controller']['target_angles'],
        'max_native_direction_formula_residual': max(r['checks']['native_direction_residual'] for r in valid),
        'max_native_to_camera_direction_separation_deg': max(direction_angle(
            r['sample']['raw_camera']['direction'],r['sample']['native_controller']['direction_scaled']) for r in valid),
        'max_interface_scale_to_projected_fov_residual_deg': max(r['checks']['scaled_fov_residual_deg'] for r in valid),
        'fov_animations': events,
        'tail': {'samples': len(tail), 'span_seconds': tail[-1]['sample']['monotonic']-tail[0]['sample']['monotonic'],
            'all_observed_quiescent': all(r['animation']['observed_quiescent'] for r in tail),
            'all_input_bytes_zero': all(not any(r['input_bytes']) for r in tail),
            'all_input_vectors_zero': all(not any(r['sample']['native_controller'][k]) for r in tail
                for k in ('input_vector_80','input_vector_9c')),
            'max_target_smoothed_angle_difference': max(abs(a-b) for r in tail for a,b in zip(
                r['sample']['native_controller']['target_angles'],r['sample']['native_controller']['smoothed_angles'])),
            'max_current_goal_fov_difference': max(abs(r['sample']['native_controller']['current_interface_fov']-
                r['sample']['native_controller']['target_interface_fov']) for r in tail),
            'max_native_camera_fov_difference': max(abs(r['sample']['native_controller']['current_interface_fov']-
                r['sample']['raw_camera']['interface_fov']) for r in tail),
            'max_direction_formula_residual': max(r['checks']['camera_direction_residual'] for r in tail)},
        'writes_performed': 0, 'write_ready': False, 'frame_synchronized': False,
        'interpretation': 'Known wheel-FOV writer observed; asynchronous snapshots are not an engine commit fence.'}
    with (args.directory/'analysis.json').open('x',encoding='utf8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
