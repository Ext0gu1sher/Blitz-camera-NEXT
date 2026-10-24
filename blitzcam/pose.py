"""Z-up world; camera local +X right, +Y up, -Z forward; quaternions wxyz."""

import math
from .trajectory import Pose, normalize_quaternion


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def quaternion_from_matrix(m):
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = (s/4, (m[2][1]-m[1][2])/s, (m[0][2]-m[2][0])/s, (m[1][0]-m[0][1])/s)
    else:
        i = max(range(3), key=lambda n: m[n][n]); j, k = (i+1) % 3, (i+2) % 3
        s = math.sqrt(max(0, 1 + m[i][i] - m[j][j] - m[k][k])) * 2
        if s < 1e-12:
            raise ValueError("相机基底无法转换为旋转。")
        xyz = [0.0, 0.0, 0.0]
        xyz[i], xyz[j], xyz[k] = s/4, (m[i][j]+m[j][i])/s, (m[i][k]+m[k][i])/s
        q = ((m[k][j]-m[j][k])/s, *xyz)
    q = normalize_quaternion(q)
    return tuple(-v for v in q) if q[0] < 0 else q


def matrix_from_quaternion(q):
    w, x, y, z = normalize_quaternion(q)
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def quaternion_from_angles(yaw_deg, pitch_deg, roll_deg):
    angles = (float(yaw_deg), float(pitch_deg), float(roll_deg))
    if not all(math.isfinite(x) for x in angles) or not -90 <= angles[1] <= 90:
        raise ValueError("角度必须有限，俯仰需在 -90 至 90 度之间。")
    yaw, pitch, roll = (math.radians(v) for v in angles)
    f = (math.cos(pitch)*math.cos(yaw), math.cos(pitch)*math.sin(yaw), math.sin(pitch))
    right = (math.sin(yaw), -math.cos(yaw), 0)
    up = cross(right, f)
    r = tuple(right[i]*math.cos(roll)-up[i]*math.sin(roll) for i in range(3))
    u = tuple(up[i]*math.cos(roll)+right[i]*math.sin(roll) for i in range(3))
    return quaternion_from_matrix(tuple((r[i], u[i], -f[i]) for i in range(3)))


def angles_from_quaternion(q):
    m = matrix_from_quaternion(q)
    f, up = tuple(-m[i][2] for i in range(3)), tuple(m[i][1] for i in range(3))
    yaw = math.atan2(f[1], f[0]) if math.hypot(f[0], f[1]) > 1e-10 else 0.0
    pitch = math.atan2(f[2], math.hypot(f[0], f[1]))
    right0 = (math.sin(yaw), -math.cos(yaw), 0)
    up0 = cross(right0, f)
    roll = math.atan2(dot(up, right0), dot(up, up0))
    return {k: math.degrees(v) for k, v in zip(("yaw_deg", "pitch_deg", "roll_deg"), (yaw, pitch, roll))}


def pose_from_camera(camera):
    view, proj = camera["view"], camera["proj"]
    # Stored DAVA view is row-vector layout; these columns are world-space camera axes.
    matrix = tuple(tuple(view[r*4+c] for c in range(3)) for r in range(3))
    horizontal_fov = math.degrees(2*math.atan(1/proj[0]))
    return Pose(tuple(camera["position"]), quaternion_from_matrix(matrix), horizontal_fov)
