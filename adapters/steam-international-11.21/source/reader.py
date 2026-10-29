"""Conservative, version-locked discovery and coherent read-side camera capture."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import math
import re
import struct
import time

from .memory import ReadOnlyMemory, find_process
from .pose import pose_from_camera, angles_from_quaternion
from .profile import CameraError, SessionChanged, IncoherentSample, PROFILE


def floats(data, offset, count):
    return list(struct.unpack_from("<" + "f" * count, data, offset))


@dataclass(frozen=True)
class Objects:
    context: int
    player: int
    replay_controller: int
    game_camera: int
    free_camera: int
    render: int
    scene: int
    scene_controller: int
    spectator_controller: int


class CameraSession:
    def __init__(self, memory):
        self.memory = memory
        self.info = memory.info
        self.profile = getattr(memory, 'profile', PROFILE)
        self.vft = {name: self.live(va) for name, va in self.profile.vtables}
        self.objects = None
        self.controller_kind = "SpectatorCameraController"
        self.discovery_stats = {}
        self._previous_clock = None

    @classmethod
    def connect(cls, pid=None):
        memory = ReadOnlyMemory(find_process(pid))
        try:
            session = cls(memory)
            session.discover()
            session.capture(require_paused=True)
            return session
        except Exception:
            memory.close(); raise

    def live(self, va):
        return self.info.base + va - self.profile.preferred_base

    def discover(self):
        patterns = {struct.pack("<I", value): name for name, value in self.vft.items()}
        rx = re.compile(b"|".join(re.escape(p) for p in patterns))
        found = {name: [] for name in self.vft}
        size = failed = 0; start_time = time.perf_counter()
        for start, length in self.memory.regions():
            for address in range(start, start+length, 1024*1024):
                try:
                    data = self.memory.read(address, min(1024*1024, start+length-address))
                except CameraError:
                    failed += 1; continue
                size += len(data)
                for match in rx.finditer(data):
                    p = address + match.start()
                    if p % 4 == 0:
                        found[patterns[match.group()]].append(p)
        u = self.memory.u32
        viable = []
        # One positive chain joins context, replay player, both cameras, scene and controllers.
        for owner in found["GameSceneController"]:
            try:
                scene, context = u(owner+0x1C), u(owner+0x20)
                game, free, controller = u(owner+0x8C), u(owner+0x94), u(owner+0x9C)
                player, render = u(context+0x1B0), u(scene+self.profile.scene_render_offset)
                for kind in ("SpectatorCameraController", "CinemaCameraController"):
                    for spectator in found.get(kind, ()):
                        candidate = Objects(context, player, controller, game, free, render, scene, owner, spectator)
                        try:
                            self._guard(candidate, controller_kind=kind)
                            viable.append((candidate, kind))
                        except CameraError:
                            continue
            except CameraError:
                continue
        viable = list(dict.fromkeys(viable))
        self.discovery_stats = {"read_mb": round(size/1048576, 2), "failed_chunks": failed,
                                "seconds": time.perf_counter()-start_time,
                                "candidate_counts": {k: len(v) for k, v in found.items()},
                                "valid_chain_count": len(viable)}
        if len(viable) != 1:
            raise CameraError("未确认唯一的回放自由镜头对象链。请进入本地回放，切到自由镜头并暂停，再重新连接。")
        self.objects, self.controller_kind = viable[0]
        self.discovery_stats["controller_kind"] = self.controller_kind
        return self.objects

    def _guard(self, objects=None, *, controller_kind=None):
        a = objects or self.objects
        if a is None:
            raise SessionChanged("尚未完成回放相机识别。")
        kind = controller_kind or self.controller_kind
        if kind not in ("SpectatorCameraController", "CinemaCameraController") or kind not in self.vft:
            raise SessionChanged("自由镜头控制器类型尚未适配。")
        u = self.memory.u32
        types = ((a.context, "AvatarContextReplay"), (a.player, "ReplayPlayer"),
                 (a.replay_controller, "ReplayCameraController"), (a.game_camera, "GameCamera"),
                 (a.free_camera, "FreeCamera"), (a.render, "RenderSystem"),
                 (a.scene, "GameScene"), (a.scene_controller, "GameSceneController"),
                 (a.spectator_controller, kind))
        try:
            for pointer, name in types:
                if u(pointer) != self.vft[name]:
                    raise SessionChanged(f"{name} 对象已变化，读取已停止；请重新连接。")
            scene_a, scene_b = self.profile.scene_camera_offsets
            render_a, render_b = self.profile.render_camera_offsets
            links = ((a.context+0x1B0, a.player), (a.player+0xC, self.live(self.profile.replay_secondary_vft)),
                     (a.replay_controller+0x28, a.game_camera), (a.game_camera+0x5B8, a.replay_controller),
                     (a.scene+self.profile.scene_render_offset, a.render), (a.scene+scene_a, a.free_camera), (a.scene+scene_b, a.free_camera),
                     (a.render+render_a, a.free_camera), (a.render+render_b, a.free_camera),
                     (a.scene_controller+0x1C, a.scene), (a.scene_controller+0x20, a.context),
                     (a.scene_controller+0x8C, a.game_camera), (a.scene_controller+0x94, a.free_camera),
                     (a.scene_controller+0x9C, a.replay_controller), (a.spectator_controller+0xC, a.free_camera))
            if any(u(address) != value for address, value in links):
                raise SessionChanged("回放或相机引用已变化，读取已停止；请重新连接。")
        except CameraError as exc:
            if isinstance(exc, SessionChanged):
                raise
            raise SessionChanged(str(exc)) from exc

    def _clock(self):
        d = self.memory.read(self.objects.player, 0x10C)
        if d[0x11] != 1 or d[0x12] not in (0, 1) or d[0x35] != 1 or struct.unpack_from('<I', d, 0xA0)[0] == 0:
            raise SessionChanged("回放时钟尚未初始化或处于未适配状态。")
        token = struct.unpack_from('<I', d, 0x108)[0]
        if d[0x2D] != 0 or d[0x2E] != 0 or token != 0xFFFFFFFF:
            raise SessionChanged("回放正在跳转或重建，读取已停止；稳定后请重新连接。")
        raw, origin, rate = (floats(d, o, 1)[0] for o in (0x18, 0x64, 0x14))
        relative = raw-origin
        if not all(math.isfinite(x) for x in (raw, origin, relative, rate)) or relative < -0.01 or not 0 <= rate <= 64:
            raise SessionChanged("回放时钟读数无效。")
        return {"time": relative, "paused": bool(d[0x12]), "rate": rate,
                "raw_time": raw, "origin": origin, "warp_target": floats(d, 0x28, 1)[0],
                "active_tick": True, "seek_active": False, "seek_waiting": False,
                "rebuild_task_pending": False}

    @staticmethod
    def _clock_interval(before, after, elapsed, same_capture=True):
        if after['origin'] != before['origin'] or after['time'] < before['time'] - 1e-5:
            raise SessionChanged("回放时间倒退或起点改变，读取已停止；请重新连接。")
        # This catches large jumps. It is not an engine tick fence or proof that no small seek occurred.
        max_advance = max(before['rate'], after['rate']) * max(0, elapsed) + 0.25
        if after['time'] - before['time'] > max_advance:
            raise SessionChanged("回放时间出现不合理前跳，读取已停止；请重新连接。")
        if same_capture and (before['paused'] != after['paused'] or before['rate'] != after['rate'] or
                             (before['paused'] and before['time'] != after['time'])):
            raise IncoherentSample("采样跨越暂停或速率变化，已丢弃此次快照。")

    def _camera(self):
        d = self.memory.read(self.objects.free_camera, 0x26C)
        if struct.unpack_from("<2I", d, 8) != (0, 0):
            raise SessionChanged("自由镜头出现未适配的组件变换，拒绝误读原始坐标。")
        camera = {"position": floats(d, 0x38, 3), "target": floats(d, 0x44, 3),
                  "direction": floats(d, 0x50, 3), "base_roll_deg": floats(d, 0x5C, 1)[0],
                  "up_hint": floats(d, 0x60, 3), "aspect": floats(d, 0x28, 1)[0],
                  "projected_fov_field": floats(d, 0x2C, 1)[0], "interface_fov": floats(d, 0x268, 1)[0],
                  "fov_scale": floats(d, 0x264, 1)[0], "view": floats(d, 0xC0, 16),
                  "projection": floats(d, 0x100, 16), "view_projection": floats(d, 0x140, 16)}
        return camera

    def _native_controller(self):
        d = self.memory.read(self.objects.spectator_controller, 0x138)
        if struct.unpack_from('<I', d, 0x10C)[0] != 0xFFFFFFFF or struct.unpack_from('<I', d, 0x128)[0] != 0:
            raise SessionChanged("自由镜头控制器切换到未适配状态，读取已停止。")
        result = {"kind": self.controller_kind, "target_angles": floats(d, 0x58, 2),
                "smoothed_angles": floats(d, 0x60, 2), "input_vector_80": floats(d, 0x80, 3),
                "input_vector_9c": floats(d, 0x9C, 3), "target_position": floats(d, 0xAC, 3),
                "direction_scaled": floats(d, 0xB8, 3), "effective_up": floats(d, 0xC4, 3),
                "position_smoothing_coefficient": floats(d, 0xFC, 1)[0],
                "native_roll_radians": floats(d, 0x110, 1)[0],
                "current_interface_fov": floats(d, 0x114, 1)[0], "target_interface_fov": floats(d, 0x118, 1)[0],
                "state_10c": struct.unpack_from("<I", d, 0x10C)[0],
                "state_128": struct.unpack_from("<I", d, 0x128)[0],
                "animation_related_address": hex(struct.unpack_from("<I", d, 0x134)[0]),
                "restore_contract_verified": False}
        numbers = [n for value in result.values() for n in (value if isinstance(value, list) else [value])
                   if isinstance(n, (int, float))]
        if not all(math.isfinite(n) for n in numbers):
            raise SessionChanged("自由镜头控制器含无效数值，读取已停止。")
        return result

    @staticmethod
    def _quality(cam):
        scalars = [x for value in cam.values() for x in (value if isinstance(value, list) else [value])]
        if not all(math.isfinite(x) for x in scalars):
            raise CameraError("相机含无效数值，未记录属性关键帧。")
        view, proj, p = cam["view"], cam["projection"], cam["position"]
        if not 0.1 < cam["aspect"] < 10 or proj[0] <= 0 or proj[5] <= 0:
            raise CameraError("投影不是已适配的透视相机。")
        expected = {1: 0, 2: 0, 3: 0, 4: 0, 6: 0, 7: 0, 8: 0, 9: 0, 11: -1, 12: 0, 13: 0, 15: 0}
        if any(abs(proj[i]-x) > 1e-5 for i, x in expected.items()):
            raise CameraError("投影布局变化，无法正确计算缩放。")
        eye = [sum(p[i]*view[i*4+j] for i in range(3))+view[12+j] for j in range(4)]
        eye_error = max(abs(x-y) for x, y in zip(eye, [0, 0, 0, 1]))
        rotation_error = max(abs(sum(view[i*4+a]*view[i*4+b] for i in range(3))-(a == b)) for a in range(3) for b in range(3))
        vp = [sum(view[r*4+k]*proj[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]
        vp_error = max(abs(x-y) for x, y in zip(vp, cam["view_projection"]))
        scale = max(1, *map(abs, p))
        if eye_error > 0.001 + scale*1e-6 or rotation_error > 1e-4 or vp_error > 0.001 + scale*1e-6:
            raise IncoherentSample("相机和矩阵尚未一致，丢弃此次快照。")
        if abs(proj[5]/proj[0]-cam["aspect"]) > 1e-4:
            raise IncoherentSample("投影宽高比不匹配，丢弃此次快照。")
        return {"eye_error": eye_error, "rotation_error": rotation_error, "vp_error": vp_error,
                "coherence": "two_equal_reads", "frame_synchronized": False,
                "active_root_verified": False}

    def capture(self, require_paused=True):
        self._guard()
        started = time.perf_counter()
        before = self._clock()
        if self._previous_clock is not None:
            previous, previous_at = self._previous_clock
            self._clock_interval(previous, before, started-previous_at, same_capture=False)
        if require_paused and not before["paused"]:
            raise CameraError("记录属性关键帧前请先暂停回放。")
        camera = None
        for _ in range(4):
            control_a = self._native_controller()
            a, b = self._camera(), self._camera()
            control_b = self._native_controller()
            if a == b and control_a == control_b:
                camera = a; break
        if camera is None:
            raise IncoherentSample("相机正在更新，未得到一致快照；请稍后重试。")
        quality = self._quality(camera)
        after = self._clock()
        self._guard()
        finished = time.perf_counter()
        self._clock_interval(before, after, finished-started)
        self._previous_clock = (after, finished)
        quality.update(clock_before=before['time'], clock_after=after['time'],
                       read_window_seconds=finished-started, engine_tick_fence=False)
        pose = pose_from_camera({**camera, "proj": camera["projection"]})
        pose_data = {**pose.to_dict(), **angles_from_quaternion(pose.quaternion)}
        return {"schema_version": 1, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "monotonic": time.perf_counter(), "session_id": f"{self.info.pid}:{self.objects.context:x}:{self.objects.free_camera:x}",
                "build": {"version": self.profile.version, "sha256": self.profile.sha256, "path": str(self.info.path)},
                "replay": after, "camera": pose_data, "raw_camera": camera, "quality": quality,
                "native_controller": control_b,
                "addresses": {k: hex(v) for k, v in asdict(self.objects).items()},
                "capabilities": {"read": True, "live_write": False, "restore_verified": False}}

    def close(self):
        self.memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
