"""Bounded error/event records; never poll or inspect the game to produce a log."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import traceback

from . import __version__

MAX_BYTES = 1024 * 1024
BACKUPS = 3
_lock = threading.Lock()


def record_event(output, event, *, error=None, context=None):
    """Logging failure must not change a successful operation or hide its error."""
    try:
        record = {'time_utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(),
                  'version': __version__, 'event': event, 'context': context or {}}
        if error is not None:
            record['error'] = {'type': type(error).__name__, 'message': str(error)[:8192],
                               'traceback': ''.join(traceback.format_exception(type(error), error, error.__traceback__))[-16384:]}
        raw = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        if len(raw) > 65536:
            record['context'] = {'omitted': 'Diagnostic context exceeded 64 KiB'}
            raw = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        with _lock:
            directory = Path(output) / 'diagnostics'
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / 'events.jsonl'
            if path.exists() and path.stat().st_size + len(raw) > MAX_BYTES:
                for index in range(BACKUPS, 0, -1):
                    source = path if index == 1 else directory / f'events.{index-1}.jsonl'
                    if source.exists():
                        source.replace(directory / f'events.{index}.jsonl')
            with path.open('ab') as stream:
                stream.write(raw)
        return True
    except (OSError, ValueError, TypeError):
        return False
