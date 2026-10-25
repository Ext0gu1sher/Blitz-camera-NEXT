"""Shared control defaults and validation for portable application settings."""
import json
import math
from pathlib import Path
import re

SCHEMA = json.loads((Path(__file__).parent/'web'/'control-schema.json').read_text(encoding='utf-8'))
KEY = re.compile(r'^(?:Key[A-Z]|Digit[0-9]|Numpad[0-9]|F(?:[1-9]|1[0-2])|Arrow(?:Left|Right|Up|Down)|Home|End|PageUp|PageDown|Insert|Tab|Backquote|Minus|Equal|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash)$')


def binding_error(key, action):
    if key is None:
        return ''
    if not isinstance(key, str):
        return '按键格式无效。'
    if action.get('mouse'):
        return '' if re.fullmatch(r'Mouse[0-4]', key) else '请使用鼠标按键。'
    parts = key.split('+'); code = parts[-1]; modifiers = parts[:-1]
    if modifiers != [m for m in ('Ctrl', 'Alt', 'Shift') if m in modifiers] or not KEY.fullmatch(code):
        return '请选择字母、数字、方向键、功能键或组合键；空格和 Esc 保持固定。'
    if (code == 'Tab' and (action['id'] != 'exitFlight' or modifiers) or
            code in ('F5', 'F11', 'F12') and not modifiers or
            'Ctrl' in modifiers and 'Alt' not in modifiers and code in ['Key'+c for c in 'SZYACVXRLWTNPF'] or
            'Alt' in modifiers and code in ('Tab', 'F4')):
        return '此按键保留给通用操作，请换一个。'
    return ''


def validate_controls(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'bindings', 'tuning'}:
        raise ValueError('快捷键设置格式无效。')
    bindings = value.get('bindings', {}); tuning = value.get('tuning', {})
    if not isinstance(bindings, dict) or set(bindings) - {a['id'] for a in SCHEMA['actions']}:
        raise ValueError('快捷键操作无效。')
    if not isinstance(tuning, dict) or set(tuning) - {t['id'] for t in SCHEMA['tuning']}:
        raise ValueError('控制参数无效。')
    result = {'bindings': {}, 'tuning': {}}
    used = []
    for action in SCHEMA['actions']:
        key = bindings.get(action['id'], action['key'])
        error = binding_error(key, action)
        if error:
            raise ValueError(action['label']+'：'+error)
        for other, other_key in used:
            if key is not None and key == other_key and set(action['scopes']) & set(other['scopes']):
                raise ValueError(f'“{action["label"]}”与“{other["label"]}”使用了相同按键。')
        used.append((action, key)); result['bindings'][action['id']] = key
    for item in SCHEMA['tuning']:
        number = tuning.get(item['id'], item['value'])
        if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number) or not item['min'] <= number <= item['max']:
            raise ValueError(f'{item["label"]}需为 {item["min"]}–{item["max"]} {item["unit"]}。')
        result['tuning'][item['id']] = number
    return result
