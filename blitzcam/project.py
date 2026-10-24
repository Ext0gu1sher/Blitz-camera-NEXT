"""Project validation and local atomic saves; never writes into the game directory."""

import json
import math
import os
from pathlib import Path
import tempfile

from .pose import quaternion_from_angles, angles_from_quaternion
from .trajectory import Trajectory, Keyframe, Pose


def validate_project(data):
    if not isinstance(data, dict) or not isinstance(data.get("keyframes"), list):
        raise ValueError("项目需包含 keyframes 数组。")
    if not 1 <= len(data["keyframes"]) <= 200:
        raise ValueError("首版支持 1 至 200 个关键帧。")
    tolerance = data.get("arc_tolerance", 1e-6)
    if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or not 1e-8 <= tolerance <= 0.1:
        raise ValueError("弧长误差容限需在 1e-8 至 0.1 世界单位之间。")
    trajectory = Trajectory.from_dict(data)
    if trajectory.shooting_mode != 'camera_only' and trajectory.replay_timeline is not None:
        if trajectory.start_time < 0 or trajectory.end_time > trajectory.replay_timeline['duration_sec']:
            raise ValueError('摄像机关键帧需位于整场回放时间范围内。')
    if (trajectory.shooting_mode != 'camera_only' and trajectory.duration > 3600) or abs(trajectory.start_time) > 1e7:
        raise ValueError("首版轨迹时长上限为一小时。")
    if trajectory.shooting_mode == 'camera_only' and trajectory.start_time < 0:
        raise ValueError('镜头时间不能小于零。')
    if any(abs(x) > 1e7 for k in trajectory.keyframes for x in k.pose.position):
        raise ValueError("摄像机坐标超出首版允许范围。")
    return trajectory


def edit_project(data):
    frames = []
    for f in data.get("keyframes", []):
        q = quaternion_from_angles(f["yaw_deg"], f["pitch_deg"], f["roll_deg"])
        frames.append(Keyframe.from_dict({"time_sec": f["time_sec"], **Pose(f["position"], q, f["horizontal_fov_deg"]).to_dict(), "name": f.get("name", "")}).to_dict())
    extra = {}
    if 'camera_track_controls' in data:
        from .channels import tracks_from_controls
        extra['camera_tracks'] = tracks_from_controls(data['camera_track_controls'])
    return validate_project({"schema_version": 1, "quaternion_order": "wxyz", "fov_axis": "horizontal", **extra,
                             "keyframes": frames, "timing": data.get("timing", "keyframes"),
                             "easing": data.get("easing", "linear"),
                             "position_interpolation": data.get("position_interpolation", "smooth"),
                             "arc_tolerance": data.get("arc_tolerance", 1e-6), "replay_speed": data.get("replay_speed"),
                             "replay_timeline": data.get('replay_timeline'), "shooting_mode": data.get('shooting_mode')})


def controls(trajectory):
    return [{"time_sec": k.time_sec, "name": k.name, "position": list(k.pose.position),
             "horizontal_fov_deg": k.pose.horizontal_fov_deg,
             **angles_from_quaternion(k.pose.quaternion)} for k in trajectory.keyframes]


def read_project(path):
    path = Path(path)
    if path.stat().st_size > 2*1024*1024:
        raise ValueError("项目 JSON 不能超过 2 MiB。")
    return validate_project(json.loads(path.read_text(encoding="utf-8-sig")))


def recycle_project(path):
    """Recycle exactly one project file, with a warning if recycling is unavailable."""
    import ctypes as C
    from ctypes import wintypes as W
    if os.name != 'nt':
        raise OSError('将项目移到系统回收站需要 Windows。')
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() != '.json' or not path.is_file():
        raise ValueError('只能删除项目 JSON 文件。')
    class FileOperation(C.Structure):
        _fields_ = [('hwnd', W.HWND), ('wFunc', W.UINT), ('pFrom', W.LPCWSTR),
                    ('pTo', W.LPCWSTR), ('fFlags', W.WORD), ('fAnyOperationsAborted', W.BOOL),
                    ('hNameMappings', W.LPVOID), ('lpszProgressTitle', W.LPCWSTR)]
    shell = C.WinDLL('shell32', use_last_error=True)
    shell.SHFileOperationW.argtypes = [C.POINTER(FileOperation)]
    shell.SHFileOperationW.restype = C.c_int
    # Shell paths are a double-NUL-terminated list, even for a single file.
    source = C.create_unicode_buffer(str(path) + '\0')
    operation = FileOperation()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = C.cast(source, W.LPCWSTR)
    # ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI, NO_CONNECTED_ELEMENTS,
    # WANTNUKEWARNING: never silently fall back to permanent deletion.
    operation.fFlags = 0x40 | 0x10 | 0x4 | 0x400 | 0x1000 | 0x2000 | 0x4000
    result = shell.SHFileOperationW(C.byref(operation))
    if operation.fAnyOperationsAborted:
        return False
    if result:
        raise OSError(f'项目删除未完成（{result}），请检查文件是否被占用或是否有写入权限。')
    if path.exists():
        raise OSError('项目文件仍在原位置，未从列表移除。')
    return True


def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".blitzcam-", suffix=".tmp", delete=False) as f:
            name = f.name; f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


def samples(trajectory, rate_hz):
    if not isinstance(rate_hz, (int, float)) or not math.isfinite(rate_hz) or not 1 <= rate_hz <= 240:
        raise ValueError("采样率需在 1 至 240 Hz 之间。")
    if trajectory.shooting_mode == 'camera_only':
        # Preview is bounded in sample count, never in authored duration. Include
        # every exact knot so a short move in a long project cannot disappear.
        end=trajectory.end_time
        count=max(1,min(6000,math.ceil(end*rate_hz)))
        times=sorted({0.,end,*trajectory.keyframe_times(),*(end*i/count for i in range(count+1))})
        return [{"time_sec":t,**trajectory.sample(t).to_dict()} for t in times]
    if trajectory.duration * rate_hz > 100000:
        raise ValueError("单次导出上限为 100001 个样本。")
    return [{"time_sec": t, **pose.to_dict()} for t, pose in trajectory.sample_uniform(rate_hz)]
