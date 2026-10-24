"""Explicit absolute clocks for offline preview; never changes a replay's clock."""

from dataclasses import dataclass
import math


@dataclass
class TimelineClock:
    mode: str
    anchor_source: float
    anchor_timeline: float = 0.0
    speed: float = 1.0
    session_id: str | None = None
    last_source: float | None = None
    invalidated: bool = False

    def __post_init__(self):
        if self.mode not in ("capture", "replay"):
            raise ValueError("clock mode must be capture or replay")
        if not all(math.isfinite(v) for v in (self.anchor_source, self.anchor_timeline, self.speed)) or self.speed <= 0:
            raise ValueError("clock anchors/speed must be finite; speed must be positive")

    def sample(self, source_time, session_id=None):
        if not math.isfinite(source_time):
            raise ValueError("source time must be finite")
        if self.invalidated:
            raise ValueError("clock requires explicit re-arming")
        if self.mode == "replay" and self.session_id is not None and session_id != self.session_id:
            self.invalidated = True
            raise ValueError("replay session changed; re-arm at the intended replay time")
        if self.last_source is not None and source_time < self.last_source-1e-6:
            self.invalidated = True
            raise ValueError("source clock moved backward; re-arm rather than silently replaying the path")
        self.last_source = source_time
        # Repeated paused replay time produces the same camera pose; capture time may keep advancing.
        return self.anchor_timeline + (source_time-self.anchor_source)*self.speed
