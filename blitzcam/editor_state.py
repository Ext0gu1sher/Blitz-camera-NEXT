"""Per-project editing sessions, kept separate from authored camera data."""

from hashlib import sha256
import json
from pathlib import Path

from .project import atomic_json


def validate_editor_state(value):
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('编辑器状态格式无效。')
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('编辑器状态包含无效数值。') from exc
    if len(text.encode('utf-8')) > 32768:
        raise ValueError('编辑器状态过大。')
    # Only view data belongs here. Project edits use the normal revision guard.
    return {key: value[key] for key in ('schema_version', 'saved_at', 'timeline', 'path_view', 'preview', 'inspector', 'workspace_tab', 'splits') if key in value}


def editor_state_path(output, project_path):
    identity = str(Path(project_path).resolve()).casefold().encode('utf-8')
    return Path(output)/'editor-sessions'/(sha256(identity).hexdigest()+'.json')


def read_editor_state(output, project_path):
    try:
        path = editor_state_path(output, project_path)
        if path.stat().st_size > 32768:
            return None
        return validate_editor_state(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return None


def write_editor_state(output, project_path, value):
    value = validate_editor_state(value)
    atomic_json(editor_state_path(output, project_path), value)
    return value
