"""Read-only sampling with explicit drop accounting and a completion sidecar.

Only IncoherentSample is recoverable. A session change, other exception, or
interrupt ends recording immediately; no discovery, input, or process write is
performed here. Sample attempts use scheduled slots, not successful reads.
"""

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

from .profile import IncoherentSample
from .project import atomic_json


def record_session(session, output_path, seconds, rate_hz, *, clock=time.perf_counter, sleep=time.sleep):
    """Write JSONL snapshots and return the persisted recording summary.

    ``completed`` describes a finished observation window containing at least
    one valid snapshot, not a lossless or frame-synchronized recording. Late
    slots are skipped instead of producing a catch-up burst. Output creation
    is exclusive; failures before creation do not alter an earlier recording.
    Once recording starts, capture/write errors and KeyboardInterrupt become
    a failed/interrupted summary. Failure to persist that summary still raises.
    """
    if (isinstance(seconds, bool) or isinstance(rate_hz, bool)
            or not isinstance(seconds, (int, float)) or not isinstance(rate_hz, (int, float))
            or not math.isfinite(seconds) or not math.isfinite(rate_hz)
            or not 0 < seconds <= 3600 or not 1 <= rate_hz <= 240):
        raise ValueError("录制时长需为 (0,3600] 秒，采样率需为 [1,240] Hz。")
    output_path = Path(output_path).resolve()
    summary_path = output_path.with_name(output_path.name + ".summary.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path.exists():
        raise FileExistsError(f"录制摘要已存在，未覆盖：{summary_path}")
    stream = output_path.open("x", encoding="utf-8")
    started_at = datetime.now(timezone.utc).isoformat()
    start = clock()
    deadline = start + seconds
    slot_count = math.ceil(seconds * rate_hz)
    attempts = valid = dropped = skipped = slot = 0
    reasons = Counter()
    status, failure = "completed", None
    try:
        with stream:
            while True:
                now = clock()
                if now >= deadline:
                    break
                due = start + slot / rate_hz
                if due >= deadline:
                    sleep(deadline - now)
                    continue
                if now < due:
                    sleep(due - now)
                    continue
                attempts += 1
                try:
                    snapshot = session.capture(require_paused=False)
                except IncoherentSample as exc:
                    dropped += 1
                    reasons[str(exc) or type(exc).__name__] += 1
                else:
                    line = json.dumps(snapshot, ensure_ascii=False, allow_nan=False) + "\n"
                    stream.write(line)
                    stream.flush()
                    valid += 1
                slot += 1
                # Count a rejected read as an attempt. Also skip slots missed by
                # a slow read, so neither transient failures nor stalls busy-loop.
                next_slot = min(slot_count, max(slot, math.ceil(max(0, clock() - start) * rate_hz)))
                skipped += next_slot - slot
                slot = next_slot
    except KeyboardInterrupt as exc:
        status = "interrupted"
        failure = {"type": type(exc).__name__, "message": str(exc) or "用户中断录制。"}
    except Exception as exc:
        status = "failed"
        failure = {"type": type(exc).__name__, "message": str(exc)}
    elapsed = max(0, clock() - start)
    if status == "completed" and valid == 0:
        status = "failed"
        failure = {"type": "NoValidSamples", "message": "观察窗口结束，但没有取得有效快照。"}
    summary = {
        "schema_version": 1,
        "scope": "read-only camera snapshots; not rendered frames or game execution",
        "status": status,
        "started_at_utc": started_at,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_seconds": seconds,
        "elapsed_seconds": elapsed,
        "requested_rate_hz": rate_hz,
        "attempt_count": attempts,
        "valid_sample_count": valid,
        "dropped_sample_count": dropped,
        "drop_reasons": dict(reasons),
        "missed_schedule_slots": skipped,
        "failure": failure,
        "frame_synchronized": False,
        "output_path": str(output_path),
        "summary_path": str(summary_path),
    }
    atomic_json(summary_path, summary)
    return summary
