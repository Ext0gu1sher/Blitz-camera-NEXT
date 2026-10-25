"""Project-wide BPM grid settings; markers are derived in the editor."""
import math


def validate_beat_grid(value):
    if value is None:
        return None
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('卡点设置格式无效。')
    if type(value.get('enabled')) is not bool:
        raise ValueError('卡点开关需为布尔值。')
    result = {'version': 1, 'enabled': value['enabled']}
    for key, low, high, label in [('bpm', 20, 300, 'BPM'), ('offset_sec', -60, 60, '首拍偏移'), ('anchor_sec', 0, 1e7, '首拍时刻')]:
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{label}需在 {low} 至 {high} 之间。')
        result[key] = number
    if type(value.get('division')) is not int or value['division'] not in (1, 2, 4):
        raise ValueError('卡点细分需为每拍、半拍或四分之一拍。')
    if value.get('origin') not in ('inpoint', 'playhead'):
        raise ValueError('首拍起点需为入点或播放头。')
    result.update(division=value['division'], origin=value['origin'])
    return result
