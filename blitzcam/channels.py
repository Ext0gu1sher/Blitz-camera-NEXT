"""Seven independent camera parameter tracks, evaluated on replay time.

Full-pose keyframes are only the compatibility projection at the union of key
times. Native playback samples the original parameter tracks through sample().
"""
from bisect import bisect_right
from copy import deepcopy
import math
from .trajectory import Trajectory, Keyframe, Pose, _number, _ease
from .pose import angles_from_quaternion, quaternion_from_angles
from .camera_smoothing import smooth_camera_curves, sample_smooth_curve

CHANNELS = ('x', 'y', 'z', 'yaw', 'pitch', 'roll', 'zoom')


def track_controls(trajectory):
    if hasattr(trajectory, 'camera_tracks'):
        return deepcopy(trajectory.camera_tracks)
    tracks = {name: [] for name in CHANNELS}
    for time, key in zip(trajectory.keyframe_times(), trajectory.keyframes):
        a = angles_from_quaternion(key.pose.quaternion)
        values = (*key.pose.position, a['yaw_deg'], a['pitch_deg'], a['roll_deg'], key.pose.horizontal_fov_deg)
        for name, value in zip(CHANNELS, values):
            if name in ('yaw', 'roll') and tracks[name]:
                previous = tracks[name][-1]['value']
                value = previous + math.remainder(value - previous, 360)
            tracks[name].append({'time_sec': time, 'value': value})
    return tracks


def tracks_from_controls(tracks):
    return deepcopy(tracks)


def _bezier(u, ctrl):
    """CSS cubic-bezier easing with P0=(0,0) P3=(1,1): solve x(s)=u, return y(s)."""
    x1, y1, x2, y2 = ctrl
    def bez(t, p1, p2):
        m = 1-t
        return 3*m*m*t*p1 + 3*m*t*t*p2 + t*t*t
    def dbez(t, p1, p2):
        m = 1-t
        return 3*m*m*p1 + 6*m*t*(p2-p1) + 3*t*t*(1-p2)
    s = u
    for _ in range(8):
        err = bez(s, x1, x2) - u
        if abs(err) <= 1e-6:
            break
        d = dbez(s, x1, x2)
        if abs(d) < 1e-9:
            break
        s -= err/d
    if abs(bez(s, x1, x2) - u) > 1e-9:
        lo, hi, s = 0.0, 1.0, u
        for _ in range(60):
            err = bez(s, x1, x2) - u
            if abs(err) <= 1e-9:
                break
            if err < 0:
                lo = s
            else:
                hi = s
            s = (lo+hi)/2
    return bez(s, y1, y2)


def _bezier_slope(ctrl, end=False):
    """Endpoint dy/dx, including coincident handles (e.g. the linear preset)."""
    x1, y1, x2, y2 = ctrl
    if end:
        x1, y1, x2, y2 = 1-x2, 1-y2, 1-x1, 1-y1
    if x1 > 0: return y1/x1
    if y1 > 0: return math.inf
    if x2 > 0: return y2/x2
    return math.inf if y2 > 0 else 1.0


class ScalarTrack:
    def __init__(self, rows, name, smooth, easing):
        if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
            raise ValueError('每条摄像机轨道需要 1–200 个关键帧。')
        self.rows = []
        for row in rows:
            if not isinstance(row, dict) or not {'time_sec','value'} <= set(row) <= {'time_sec','value','ease','curve'}:
                raise ValueError('参数关键帧需要 time_sec 和 value。')
            t, value = _number(row['time_sec'], 'time_sec'), _number(row['value'], name)
            if abs(t) > 1e7 or abs(value) > 1e7:
                raise ValueError('参数关键帧超出允许范围。')
            if name == 'zoom' and not 0 < value < 180:
                raise ValueError('缩放必须大于 0°、小于 180°。')
            if name == 'pitch' and not -90 <= value <= 90:
                raise ValueError('俯仰需在 -90° 至 90° 内。')
            out = {'time_sec': t, 'value': value}
            if 'curve' in row:
                if row['curve'] != 'auto':
                    raise ValueError('摄像机曲线模式无效。')
                out['curve'] = 'auto'
            if 'ease' in row:
                ease = row['ease']
                if not isinstance(ease, list) or len(ease) != 4 or not all(isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) and 0 <= n <= 1 for n in ease):
                    raise ValueError('缓动需为 [x1,y1,x2,y2] 且分量在 0 至 1 之间。')
                out['ease'] = [float(n) for n in ease]
            self.rows.append(out)
        self.times = [r['time_sec'] for r in self.rows]
        if any(b-a < 1e-5 for a,b in zip(self.times,self.times[1:])):
            raise ValueError('同一参数的关键帧必须按时间递增，间隔至少 0.00001 秒。')
        self.smooth, self.easing = smooth, easing
        self.tangents = self._monotone_tangents() if smooth or any(r.get('curve') == 'auto' for r in self.rows) else []
        self.auto_curves = self._automatic_curves()
        self.smooth_curves = smooth_camera_curves(self.rows, self.auto_curves)

    def _automatic_curves(self):
        """Join automatic segments with shared derivatives in value/second.

        Presets supply handle influence, not a fresh stop at every knot. Shorten
        a handle when needed to keep its value inside the authored interval;
        this preserves the shared slope and prevents overshoot. Unmarked legacy
        segments keep their original evaluation, including deliberate stops.
        """
        n = len(self.rows)-1
        active = [r.get('curve') == 'auto' for r in self.rows[:-1]]
        curves = [None]*n
        if not any(active): return curves
        h = [b-a for a,b in zip(self.times, self.times[1:])]
        d = [(b['value']-a['value'])/span for a,b,span in zip(self.rows,self.rows[1:],h)]
        controls = [r.get('ease', [1/3,0,2/3,1]) for r in self.rows[:-1]]
        slopes = list(self.tangents)

        def legacy_slope(i, end):
            row = self.rows[i]
            if 'ease' in row: return d[i]*_bezier_slope(row['ease'], end)
            factor = {'linear':(1,1), 'ease_in':(0,2), 'ease_out':(2,0), 'ease_in_out':(0,0)}[self.easing][int(end)]
            return (self.tangents[i+int(end)] if self.smooth else d[i])*factor

        for k in range(n+1):
            left, right = k > 0 and active[k-1], k < n and active[k]
            if left == right: continue
            segment, end = (k-1, True) if left else (k, False)
            neighbor = k if left else k-1
            if 0 <= neighbor < n:
                velocity = legacy_slope(neighbor, not end)
            else:
                # Singular circular presets get a bounded endpoint speed.
                velocity = d[segment]*min(3.0, _bezier_slope(controls[segment], end))
            slopes[k] = velocity if math.isfinite(velocity) and velocity*d[segment] >= 0 else 0.0
        for i in range(n):
            if not active[i]: continue
            x1, _, x2, _ = controls[i]
            # A zero-length handle has no usable slope; 1/3 preserves the
            # coincident-handle linear preset while giving auto tangents room.
            left, right = x1 if x1 > 0 else 1/3, 1-x2 if x2 < 1 else 1/3
            a, b = (slopes[i]/d[i], slopes[i+1]/d[i]) if d[i] else (0.0,0.0)
            if a > 0: left = min(left, 1/a)
            if b > 0: right = min(right, 1/b)
            curves[i] = [left, min(1.0,left*a), 1-right, max(0.0,1-right*b)]
        return curves

    def _monotone_tangents(self):
        """Time-aware, shape-preserving cubic slopes; no invented extrema.

        At a direction change or a held value the tangent is zero. Weighted
        harmonic interior slopes and limited one-sided endpoints keep every
        interval inside its two authored values, even with unequal key spacing.
        """
        if len(self.rows) == 1:
            return [0.0]
        spans = [b-a for a,b in zip(self.times, self.times[1:])]
        slopes = [(b['value']-a['value'])/h
                  for a,b,h in zip(self.rows, self.rows[1:], spans)]
        if len(self.rows) == 2:
            return [slopes[0], slopes[0]]
        def endpoint(h0, h1, d0, d1):
            slope = ((2*h0+h1)*d0-h0*d1)/(h0+h1)
            if slope*d0 <= 0:
                return 0.0
            if d0*d1 <= 0 and abs(slope) > 3*abs(d0):
                return 3*d0
            return slope
        result = [endpoint(spans[0], spans[1], slopes[0], slopes[1])]
        for i in range(1, len(self.rows)-1):
            left, right = slopes[i-1], slopes[i]
            if left*right <= 0:
                result.append(0.0)
            else:
                w1, w2 = 2*spans[i]+spans[i-1], spans[i]+2*spans[i-1]
                result.append((w1+w2)/(w1/left+w2/right))
        result.append(endpoint(spans[-1], spans[-2], slopes[-1], slopes[-2]))
        return result

    def sample(self, time):
        if time <= self.times[0]: return self.rows[0]['value']
        if time >= self.times[-1]: return self.rows[-1]['value']
        i = bisect_right(self.times, time)-1
        a,b = self.rows[i:i+2]
        span = b['time_sec']-a['time_sec']
        u_lin = (time-a['time_sec'])/span
        if self.smooth_curves[i] is not None:
            return sample_smooth_curve(self.smooth_curves[i], time)
        if 'ease' in a:
            return a['value']+(b['value']-a['value'])*_bezier(u_lin, a['ease'])
        u = _ease(u_lin, self.easing)
        if not self.smooth: return a['value']+(b['value']-a['value'])*u
        return ((2*u**3-3*u*u+1)*a['value'] + (u**3-2*u*u+u)*self.tangents[i]*span
                +(-2*u**3+3*u*u)*b['value'] + (u**3-u*u)*self.tangents[i+1]*span)


class ChannelTrajectory(Trajectory):
    @classmethod
    def from_dict(cls, data):
        tracks = data['camera_tracks']
        if not isinstance(tracks, dict) or set(tracks) != set(CHANNELS):
            raise ValueError('时间轴需要 X、Y、Z、水平角度、俯仰、横滚和缩放七条轨道。')
        if data.get('timing', 'keyframes') != 'keyframes':
            raise ValueError('独立参数时间轴需遵守关键帧时间。')
        # Validate settings through the existing evaluator before using them.
        settings = dict(easing=data.get('easing', 'linear'), position_interpolation=data.get('position_interpolation', 'smooth'),
                        arc_tolerance=data.get('arc_tolerance', 1e-6), replay_speed=data.get('replay_speed'), replay_timeline=data.get('replay_timeline'), shooting_mode=data.get('shooting_mode'))
        Trajectory([Keyframe(0,Pose((0,0,0),(1,0,0,0),60))], **settings)
        children = {name: ScalarTrack(tracks[name], name, name in ('x','y','z') and settings['position_interpolation']=='smooth', settings['easing']) for name in CHANNELS}
        times = sorted({t for child in children.values() for t in child.times})
        if len(times) > 200 or (data.get('shooting_mode') != 'camera_only' and times[-1]-times[0] > 3600):
            raise ValueError('摄像机轨道合计最多 200 个不同时刻、最长一小时。')
        names = {k.time_sec:k.name for k in (Keyframe.from_dict(k) for k in data['keyframes'])}
        obj = cls.__new__(cls)
        obj.children, obj.camera_tracks = children, {name:deepcopy(child.rows) for name,child in children.items()}
        # Length is a per-interval polyline estimate for display, not a spatial retimer.
        # Sample each knot interval: bounded cost even for very long animations.
        sample_times=sorted({*times,*(a+(b-a)*i/32 for a,b in zip(times,times[1:]) for i in range(1,32))})
        points = [obj.position(t) for t in sample_times]
        obj.channel_length = sum(math.dist(a,b) for a,b in zip(points,points[1:]))
        keys = [Keyframe(t,obj.sample(t),names.get(t,'')) for t in times]
        Trajectory.__init__(obj, keys, **settings)
        return obj

    def position(self, time):
        return tuple(self.children[name].sample(time) for name in ('x','y','z'))

    @property
    def length(self):
        return self.channel_length

    def sample(self, time):
        time = _number(time,'time_sec')
        a = [self.children[name].sample(time) for name in ('yaw','pitch','roll')]
        return Pose(self.position(time), quaternion_from_angles(*a), self.children['zoom'].sample(time))

    def to_dict(self):
        return {**super().to_dict(), 'camera_tracks':deepcopy(self.camera_tracks)}
