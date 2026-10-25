"""Portable application preferences, independent of camera project contents."""
import json
import math
import os
from pathlib import Path
import tempfile

from .project import atomic_json
from .input_controls import validate_controls


def documents_directory():
    if os.name == 'nt':
        import ctypes
        folder = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, folder) == 0 and folder.value:
            return Path(folder.value)
    return Path.home()/'Documents'


def ui_scale(value):
    if isinstance(value, bool) or value not in (100, 110, 125, 150, 175, 200):
        raise ValueError('界面缩放请选择 100%、110%、125%、150%、175% 或 200%。')
    return int(value)


def keyframe_start_seconds(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 3600:
        raise ValueError('赛前片段长度需为 0–3600 秒；留空表示自动读取回放。')
    return float(value)


def directory_path(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 32768 or any(ord(c) < 32 for c in value):
        raise ValueError('请输入有效的项目保存文件夹。')
    path = Path(os.path.expandvars(value.strip())).expanduser()
    if not path.is_absolute():
        raise ValueError('请使用完整的文件夹路径，或点击“选择文件夹”。')
    return path.resolve()


def read_settings(output):
    default = str((documents_directory()/'Blitz-Camera-Project').resolve())
    directory = default
    start_seconds = None
    scale = 100
    controls = validate_controls()
    try:
        path = Path(output)/'settings.json'
        if path.stat().st_size <= 65536:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('schema_version') == 1:
                saved = directory_path(data.get('project_directory'))
                directory = default if saved == (Path(output)/'projects').resolve() else str(saved)
                start_seconds = keyframe_start_seconds(data.get('replay_keyframe_start_seconds'))
                scale = ui_scale(data.get('ui_scale', 100))
                controls = validate_controls(data.get('input_controls'))
    except (OSError, ValueError, TypeError):
        pass
    return {'schema_version': 1, 'project_directory': directory, 'default_project_directory': default,
            'replay_keyframe_start_seconds': start_seconds, 'ui_scale': scale, 'input_controls': controls}


def save_settings(output, value):
    if not isinstance(value, dict):
        raise ValueError('设置格式无效。')
    directory = directory_path(value.get('project_directory'))
    start_seconds = keyframe_start_seconds(value.get('replay_keyframe_start_seconds',
                                                    read_settings(output)['replay_keyframe_start_seconds']))
    scale = ui_scale(value.get('ui_scale', read_settings(output)['ui_scale']))
    controls = validate_controls(value.get('input_controls', read_settings(output)['input_controls']))
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Test actual access, including ACLs/read-only shares, before committing.
        with tempfile.TemporaryFile(dir=directory, prefix='.blitzcam-check-') as probe:
            probe.write(b'Blitz Camera'); probe.flush()
    except OSError as exc:
        raise ValueError(f'该文件夹无法保存项目，请选择可写的文件夹：{exc}') from exc
    atomic_json(Path(output)/'settings.json', {'schema_version': 1, 'project_directory': str(directory),
                                            'replay_keyframe_start_seconds': start_seconds, 'ui_scale': scale,
                                            'input_controls': controls})
    return read_settings(output)
