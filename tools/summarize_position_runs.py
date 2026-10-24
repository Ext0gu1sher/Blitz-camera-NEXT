"""Summarize locally recorded position-Hook evidence; reads no live process."""
import json, math
from pathlib import Path

root = Path(__file__).resolve().parents[1]
runs = []
for path in sorted((root/'output/playback-runs').glob('*/report.json')):
    report = json.loads(path.read_text(encoding='utf8'))
    if not report.get('position_only', False):
        continue  # Keep this historical position-only evidence separate.
    events_path = path.with_name('events.jsonl')
    events = [json.loads(line) for line in events_path.read_text(encoding='utf8').splitlines()] if events_path.exists() else []
    if not events:
        runs.append({'run': path.parent.name, 'error': report.get('error', 'No events')})
        continue
    config = report['config']
    update, pairs = None, []
    for event in events:
        if event['kind'] == 1:
            update = event
        elif event['kind'] == 2 and update and event['updates'] == update['updates']:
            pairs.append(math.dist(event['position'], update['position']))
    motion = [e for e in events if e['kind'] == 1 and e['stage'] in (1, 2, 3)]
    final = report.get('final_camera', {})
    target = report['project']['keyframes'][0 if report['reverse'] else -1]['position']
    stopped = report.get('user_stopped', False)
    result = {
        'run': path.parent.name, 'reverse': report['reverse'],
        'duration': config['duration'], 'approach_seconds': config['approach_seconds'],
        'interpolation': report['project']['position_interpolation'],
        'timing': report['project']['timing'], 'easing': report['project']['easing'],
        'error': report.get('error'), 'user_stopped': stopped,
        'hooks_detached': report['hooks_detached'],
        'module_base': report['module_base'], 'event_samples': len(events),
        'matched_update_draw_pairs': len(pairs), 'max_update_draw_position_difference': max(pairs, default=None),
        'max_fov_deviation': max(abs(e['fov']-config['fov']) for e in events),
        'max_projection_deviation': max(abs(x-y) for e in events for x,y in zip(e['projection'], config['projection'])),
        'max_target_angle_deviation': max(abs(x-y) for e in events for x,y in zip(e['angles'], config['angles'])),
        'shadow_width_ranges': [[min(e['width'][i] for e in events), max(e['width'][i] for e in events)] for i in range(3)],
        'max_update_position_step': max((math.dist(a['position'], b['position']) for a,b in zip(motion,motion[1:])), default=0),
        'native_elapsed': report['final_header']['last_elapsed'],
        'native_status': report['final_header']['status'],
        'position_applies': report['final_header']['position_applies'],
        'replay_time_before': report['reference']['replay']['time'],
        'replay_time_after': final.get('replay',{}).get('time'),
        'final_position': final.get('camera',{}).get('position'),
    }
    if final and not stopped:
        result['endpoint_error'] = math.dist(final['camera']['position'],target)
    runs.append(result)
summary = {
    'client': '11.21.0.1235', 'position_only': True,
    'offline_python_tests': 148, 'native_selftests': 9,
    'runs': runs,
    'all_runs_detached_without_error': all(r.get('hooks_detached') and not r.get('error') for r in runs),
    'visual_shadow_acceptance': 'User accepted previous minimal Hook experiment; this integration records shadow extents, not rendered-image differences.',
}
out = root/'output/ui-position-hook-verification.json'
out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(summary,ensure_ascii=False,indent=2))

