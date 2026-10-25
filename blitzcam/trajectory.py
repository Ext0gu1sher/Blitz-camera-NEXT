"""Deterministic, offline camera trajectories. No game or clock access.

Coordinates use the caller's world units. Quaternions are (w, x, y, z), and
FOV is horizontal in degrees. ``sample(t)`` consumes an absolute *timeline*
time: the caller must select a replay clock or an independent capture clock.
It never integrates wall-clock frame deltas or changes either clock.

``keyframes`` timing honors every timestamp and applies easing per segment.
``constant_speed`` timing retimes the whole geometric path by arc length;
intermediate timestamps no longer specify arrival times. It is constant in
space only with linear easing. Other easing maps intentionally vary speed.
Orientation and FOV follow the retimed segment's distance fraction.

Smooth positions use interpolating cubic Hermite/Catmull-Rom curves. They can
overshoot and cross obstacles; this offline module has no collision model.
Arc lengths are numerical approximations with an absolute world-unit tolerance.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _vector(value: Iterable[float], size: int, name: str) -> tuple[float, ...]:
    try:
        result = tuple(_number(v, name) for v in value)
    except TypeError as exc:
        raise ValueError(f"{name} must contain {size} finite numbers") from exc
    if len(result) != size:
        raise ValueError(f"{name} must contain {size} finite numbers")
    return result


def normalize_quaternion(value: Iterable[float]) -> Quaternion:
    q = _vector(value, 4, "quaternion (wxyz)")
    # Scale first so finite but very large/small inputs can be normalized.
    scale = max(abs(v) for v in q)
    if scale == 0:
        raise ValueError("quaternion must have nonzero norm")
    scaled = tuple(v / scale for v in q)
    norm = math.sqrt(sum(v * v for v in scaled))
    return tuple(v / norm for v in scaled)  # type: ignore[return-value]


def quaternion_slerp(a: Iterable[float], b: Iterable[float], fraction: float) -> Quaternion:
    """Shortest-rotation interpolation, including antipodal/near-equal inputs."""
    t = _number(fraction, "fraction")
    if not 0 <= t <= 1:
        raise ValueError("fraction must be within [0, 1]")
    qa, qb = normalize_quaternion(a), normalize_quaternion(b)
    dot = sum(x * y for x, y in zip(qa, qb))
    if dot < 0:
        qb = tuple(-v for v in qb)
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        return normalize_quaternion(tuple(x + t * (y - x) for x, y in zip(qa, qb)))
    theta = math.acos(dot)
    denominator = math.sin(theta)
    wa = math.sin((1 - t) * theta) / denominator
    wb = math.sin(t * theta) / denominator
    return normalize_quaternion(tuple(wa * x + wb * y for x, y in zip(qa, qb)))


@dataclass(frozen=True)
class Pose:
    position: Vector3
    quaternion: Quaternion
    horizontal_fov_deg: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _vector(self.position, 3, "position"))
        object.__setattr__(self, "quaternion", normalize_quaternion(self.quaternion))
        fov = _number(self.horizontal_fov_deg, "缩放")
        if not 0 < fov < 180:
            raise ValueError("缩放必须大于 0°、小于 180°。")
        object.__setattr__(self, "horizontal_fov_deg", fov)

    def to_dict(self) -> dict[str, Any]:
        return {"position": list(self.position), "quaternion": list(self.quaternion),
                "horizontal_fov_deg": self.horizontal_fov_deg}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Pose:
        try:
            return cls(data["position"], data["quaternion"], data["horizontal_fov_deg"])
        except (KeyError, TypeError) as exc:
            raise ValueError("摄像机数据需要包含位置、姿态和缩放。") from exc


@dataclass(frozen=True)
class Keyframe:
    time_sec: float
    pose: Pose
    name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_sec", _number(self.time_sec, "time_sec"))
        if not isinstance(self.pose, Pose):
            raise ValueError("keyframe pose must be a Pose")

    def to_dict(self) -> dict[str, Any]:
        return {"time_sec": self.time_sec, **self.pose.to_dict(), **({"name": self.name} if self.name else {})}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Keyframe:
        try:
            name = data.get("name", "")
            if not isinstance(name, str) or len(name) > 64 or any(ord(c) < 32 for c in name):
                raise ValueError("旧项目名称需为至多 64 字的单行文本。")
            return cls(data["time_sec"], Pose.from_dict(data), name.strip())
        except (KeyError, TypeError) as exc:
            raise ValueError("keyframe requires time_sec and pose fields") from exc


def _ease(t: float, method: str) -> float:
    if method == "ease_in":
        return t * t
    if method == "ease_out":
        return t * (2 - t)
    if method == "ease_in_out":
        return t * t * (3 - 2 * t)
    return t


def _simpson_leaves(f: Callable[[float], float], a: float, b: float,
                    tolerance: float, max_depth: int = 20) -> list[tuple[float, float, float]]:
    """Adaptive Simpson integral as ordered (start, end, length) leaves."""
    def visit(lo: float, hi: float, fa: float, fm: float, fb: float,
              estimate: float, tol: float, depth: int) -> list[tuple[float, float, float]]:
        mid = (lo + hi) / 2
        fl, fr = f((lo + mid) / 2), f((mid + hi) / 2)
        left = (mid - lo) * (fa + 4 * fl + fm) / 6
        right = (hi - mid) * (fm + 4 * fr + fb) / 6
        delta = left + right - estimate
        if not math.isfinite(delta):
            raise ValueError("path coordinates exceed the numerical range")
        if abs(delta) <= 15 * tol:
            return [(lo, hi, max(0.0, left + right + delta / 15))]
        if depth == 0:
            raise ValueError("arc-length tolerance could not be reached; increase arc_tolerance")
        return (visit(lo, mid, fa, fl, fm, left, tol / 2, depth - 1)
                + visit(mid, hi, fm, fr, fb, right, tol / 2, depth - 1))

    if a == b:
        return [(a, b, 0.0)]
    fa, fm, fb = f(a), f((a + b) / 2), f(b)
    estimate = (b - a) * (fa + 4 * fm + fb) / 6
    return visit(a, b, fa, fm, fb, estimate, tolerance, max_depth)


class _Segment:
    def __init__(self, p0: Vector3, p1: Vector3, m0: Vector3, m1: Vector3,
                 linear: bool, tolerance: float) -> None:
        self.p0, self.p1, self.m0, self.m1 = p0, p1, m0, m1
        self.delta = tuple(b - a for a, b in zip(p0, p1))
        self.linear = linear or p0 == p1
        self.tolerance = tolerance
        if self.linear:
            self.leaves = [(0.0, 1.0, math.dist(p0, p1))]
        else:
            self.leaves = _simpson_leaves(self.speed, 0, 1, tolerance)
        self.cumulative = [0.0]
        for _, _, distance in self.leaves:
            self.cumulative.append(self.cumulative[-1] + distance)
        self.length = self.cumulative[-1]
        if not math.isfinite(self.length):
            raise ValueError("path length must be finite")

    def position(self, u: float) -> Vector3:
        if u <= 0:
            return self.p0
        if u >= 1:
            return self.p1
        if self.linear:
            return tuple((1 - u) * a + u * b for a, b in zip(self.p0, self.p1))
        u2, u3 = u * u, u * u * u
        weights = (-2 * u3 + 3 * u2, u3 - 2 * u2 + u, u3 - u2)
        return tuple(a + weights[0] * delta + weights[1] * ma + weights[2] * mb
                     for a, delta, ma, mb in zip(self.p0, self.delta, self.m0, self.m1))

    def speed(self, u: float) -> float:
        u2 = u * u
        # Use relative coordinates so a large world origin does not pollute
        # lengths through cancellation between absolute-position terms.
        weights = (-6 * u2 + 6 * u, 3 * u2 - 4 * u + 1, 3 * u2 - 2 * u)
        return math.hypot(*(weights[0] * delta + weights[1] * ma + weights[2] * mb
                            for delta, ma, mb in zip(self.delta, self.m0, self.m1)))

    def at_distance_fraction(self, fraction: float) -> Vector3:
        if self.linear or fraction <= 0 or fraction >= 1:
            return self.position(fraction)
        distance = fraction * self.length
        index = min(len(self.leaves) - 1, bisect_right(self.cumulative, distance) - 1)
        lo, hi, _ = self.leaves[index]
        start = lo
        target = distance - self.cumulative[index]
        # Invert integrated arc length, not the curve parameter. Bisection makes
        # inversion robust even at a zero derivative; no frame history is used.
        local_tolerance = self.tolerance / max(1, len(self.leaves))
        for _ in range(48):
            mid = (lo + hi) / 2
            length = sum(leaf[2] for leaf in _simpson_leaves(self.speed, start, mid, local_tolerance))
            if abs(length - target) <= local_tolerance:
                return self.position(mid)
            if length < target:
                lo = mid
            else:
                hi = mid
        return self.position((lo + hi) / 2)


class Trajectory:
    """Immutable-input, random-access trajectory evaluator (standard library only)."""

    def __init__(self, keyframes: Sequence[Keyframe], *, timing: str = "keyframes",
                 easing: str = "linear", position_interpolation: str = "smooth",
                 arc_tolerance: float = 1e-6, replay_speed=None, replay_timeline=None, shooting_mode=None) -> None:
        from .speed import validate_speed
        from .replay_timeline import validate_timeline
        self.replay_timeline = validate_timeline(replay_timeline)
        if shooting_mode not in (None, 'camera_only', 'replay'):
            raise ValueError('未知拍摄模式。')
        self.shooting_mode = shooting_mode
        self.replay_speed = validate_speed(replay_speed)
        if shooting_mode == 'camera_only':
            self.replay_speed.update(mode='paused', camera_clock='shooting')
        elif shooting_mode == 'replay' and self.replay_speed['mode'] == 'paused':
            self.replay_speed.update(mode='curve', camera_clock='replay', rate=1.,
                                     keyframes=[{'progress':0.,'rate':1.},{'progress':1.,'rate':1.}])
        if self.replay_timeline and shooting_mode!='camera_only' and self.replay_speed['mode']=='curve':
            # Older projects used the work area as their curve domain. Remember
            # it once so later in/out edits only trim playback, never retime knots.
            self.replay_speed.setdefault('time_range',{
                'start_sec':self.replay_timeline['work_start_sec'],
                'end_sec':self.replay_timeline['work_end_sec']})
        self.keyframes = tuple(keyframes)
        if not self.keyframes or not all(isinstance(k, Keyframe) for k in self.keyframes):
            raise ValueError("at least one Keyframe is required")
        self._times = tuple(k.time_sec for k in self.keyframes)
        if any(b <= a for a, b in zip(self._times, self._times[1:])):
            raise ValueError("keyframe times must be strictly increasing")
        if not math.isfinite(self._times[-1] - self._times[0]):
            raise ValueError("timeline duration must be finite")
        if timing not in ("keyframes", "constant_speed"):
            raise ValueError("timing must be keyframes or constant_speed")
        if easing not in ("linear", "ease_in", "ease_out", "ease_in_out"):
            raise ValueError("unsupported easing")
        if position_interpolation not in ("smooth", "linear"):
            raise ValueError("position_interpolation must be smooth or linear")
        tolerance = _number(arc_tolerance, "arc_tolerance")
        if tolerance <= 0:
            raise ValueError("arc_tolerance must be positive")
        self.timing, self.easing = timing, easing
        self.position_interpolation, self.arc_tolerance = position_interpolation, tolerance
        points = [k.pose.position for k in self.keyframes]
        tangents = []
        for i, p in enumerate(points):
            if len(points) == 1 or (i > 0 and p == points[i - 1]) or (i + 1 < len(points) and p == points[i + 1]):
                tangent = (0.0, 0.0, 0.0)
            elif i == 0:
                tangent = tuple(b - a for a, b in zip(p, points[1]))
            elif i == len(points) - 1:
                tangent = tuple(b - a for a, b in zip(points[i - 1], p))
            else:
                tangent = tuple((b - a) / 2 for a, b in zip(points[i - 1], points[i + 1]))
            tangents.append(tangent)
        self._segments = tuple(_Segment(points[i], points[i + 1], tangents[i], tangents[i + 1],
                                        position_interpolation == "linear", tolerance / max(1, len(points) - 1))
                               for i in range(len(points) - 1))
        self._distances = [0.0]
        for segment in self._segments:
            self._distances.append(self._distances[-1] + segment.length)
        if not math.isfinite(self.length):
            raise ValueError("path length must be finite")
        if timing == "constant_speed" and self.length > 0:
            for i, segment in enumerate(self._segments):
                if segment.length == 0:
                    a, b = self.keyframes[i].pose, self.keyframes[i + 1].pose
                    dot = abs(sum(x * y for x, y in zip(a.quaternion, b.quaternion)))
                    if dot < 1 - 1e-12 or a.horizontal_fov_deg != b.horizontal_fov_deg:
                        raise ValueError("按整条路径弧长分配无法安排移动路径中的原地转向或缩放变化，请选择遵守关键帧时间。")

    @property
    def start_time(self) -> float:
        return self._times[0]

    @property
    def end_time(self) -> float:
        return self._times[-1]

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def length(self) -> float:
        return self._distances[-1]

    def sample(self, timeline_time_sec: float) -> Pose:
        """Evaluate an absolute timeline time; outside the range hold endpoints."""
        time = _number(timeline_time_sec, "timeline_time_sec")
        if time <= self.start_time:
            return self.keyframes[0].pose
        if time >= self.end_time:
            return self.keyframes[-1].pose
        if self.timing == "constant_speed" and self.length > 0:
            progress = _ease((time - self.start_time) / self.duration, self.easing)
            distance = progress * self.length
            if distance >= self.length:
                return self.keyframes[-1].pose
            index = min(len(self._segments) - 1, bisect_right(self._distances, distance) - 1)
            fraction = (distance - self._distances[index]) / self._segments[index].length
        else:
            index = bisect_right(self._times, time) - 1
            fraction = _ease((time - self._times[index]) / (self._times[index + 1] - self._times[index]), self.easing)
        fraction = min(1.0, max(0.0, fraction))
        a, b = self.keyframes[index].pose, self.keyframes[index + 1].pose
        return Pose(self._segments[index].at_distance_fraction(fraction),
                    quaternion_slerp(a.quaternion, b.quaternion, fraction),
                    (1 - fraction) * a.horizontal_fov_deg + fraction * b.horizontal_fov_deg)

    def sample_uniform(self, sample_rate_hz: float = 100) -> list[tuple[float, Pose]]:
        """Sample the timeline at a fixed rate, including the exact final time.

        The final interval may be shorter than the others. This exports numerical
        poses; it neither exports rendered frames nor proves game camera control.
        """
        rate = _number(sample_rate_hz, "sample_rate_hz")
        if rate <= 0:
            raise ValueError("sample_rate_hz must be positive")
        count = self.duration * rate
        if not math.isfinite(count) or count > 10_000_000:
            raise ValueError("sample request exceeds 10,000,000 intervals")
        if self.duration == 0:
            return [(self.start_time, self.keyframes[0].pose)]
        times = [self.start_time + i / rate for i in range(math.ceil(count))]
        times = [t for t in times if t < self.end_time]
        times.append(self.end_time)
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("sample interval is below the timeline's floating-point resolution")
        return [(t, self.sample(t)) for t in times]

    def keyframe_times(self) -> list[float]:
        """Actual knot arrival times after optional global distance retiming."""
        if self.timing != "constant_speed" or self.length == 0:
            return list(self._times)
        result = []
        for distance in self._distances:
            fraction = distance / self.length
            lo, hi = 0., 1.
            for _ in range(48):
                mid = (lo + hi) / 2
                if _ease(mid, self.easing) < fraction: lo = mid
                else: hi = mid
            result.append(self.start_time + (lo + hi) / 2 * self.duration)
        result[0], result[-1] = self.start_time, self.end_time
        return result

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "quaternion_order": "wxyz", "fov_axis": "horizontal",
                **({'beat_grid': self.beat_grid} if getattr(self, 'beat_grid', None) is not None else {}),
                **({'multicam': self.multicam} if getattr(self, 'multicam', None) else {}),
                **({'replay_timeline': self.replay_timeline} if self.replay_timeline is not None else {}),
                **({'shooting_mode': self.shooting_mode} if self.shooting_mode is not None else {}),
                "timing": self.timing, "easing": self.easing,
                "position_interpolation": self.position_interpolation,
                "arc_tolerance": self.arc_tolerance, "replay_speed": self.replay_speed,
                "keyframes": [k.to_dict() for k in self.keyframes]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Trajectory:
        if not isinstance(data, Mapping):
            raise ValueError("trajectory must be an object")
        if type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) != 1:
            raise ValueError("unsupported trajectory schema_version")
        if data.get("quaternion_order", "wxyz") != "wxyz":
            raise ValueError("quaternion_order must be wxyz")
        if data.get("fov_axis", "horizontal") != "horizontal":
            raise ValueError("缩放需按水平方向定义。")
        if 'camera_tracks' in data:
            from .channels import ChannelTrajectory
            return ChannelTrajectory.from_dict(data)
        try:
            keyframes = [Keyframe.from_dict(k) for k in data["keyframes"]]
        except (KeyError, TypeError) as exc:
            raise ValueError("trajectory requires a keyframes array") from exc
        return cls(keyframes, timing=data.get("timing", "keyframes"),
                   easing=data.get("easing", "linear"),
                   position_interpolation=data.get("position_interpolation", "smooth"),
                   arc_tolerance=data.get("arc_tolerance", 1e-6), replay_speed=data.get("replay_speed"), replay_timeline=data.get('replay_timeline'), shooting_mode=data.get('shooting_mode'))
