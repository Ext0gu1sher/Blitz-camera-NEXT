@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\chcp.com" 65001 >nul 2>&1
cd /d "%~dp0"
set "DIAG_EXIT=1"
set "BLITZCAM_DIAG_LOG=%~dp0output\connection-diagnostics\diagnostic-startup.log"
if not exist "%~dp0output\connection-diagnostics" mkdir "%~dp0output\connection-diagnostics" >nul 2>&1
if not exist "%~dp0output\connection-diagnostics" set "BLITZCAM_DIAG_LOG=%TEMP%\BlitzCamera-diagnostic-startup.log"
>"%BLITZCAM_DIAG_LOG%" echo Blitz Camera diagnostics launcher v4
>>"%BLITZCAM_DIAG_LOG%" echo Root: "%~dp0"
echo 正在收集诊断，请保持游戏和回放状态，稍候……
if exist "%~dp0app\blitzcam\__init__.py" goto diagnostic_portable
if exist "%~dp0blitzcam\__init__.py" goto diagnostic_source
>>"%BLITZCAM_DIAG_LOG%" echo 未找到软件文件。请把这个脚本放在解压后的 BlitzCamera.exe 旁边再运行。
goto diagnostic_finish
:diagnostic_portable
if exist "%~dp0runtime\python.exe" goto diagnostic_embedded
>>"%BLITZCAM_DIAG_LOG%" echo 缺少 runtime\python.exe。请保留软件解压后的完整目录，不要只复制 EXE。
goto diagnostic_finish
:diagnostic_embedded
"%~dp0runtime\python.exe" -X utf8 -B -c "import pathlib,sys;src=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig');exec(compile(src.split(chr(10)+'# BEGIN PYTHON'+chr(10),1)[1],sys.argv[1],'exec'))" "%~f0" >>"%BLITZCAM_DIAG_LOG%" 2>&1
set "DIAG_EXIT=%errorlevel%"
goto diagnostic_finish
:diagnostic_source
python -X utf8 -B -c "import pathlib,sys;src=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig');exec(compile(src.split(chr(10)+'# BEGIN PYTHON'+chr(10),1)[1],sys.argv[1],'exec'))" "%~f0" >>"%BLITZCAM_DIAG_LOG%" 2>&1
set "DIAG_EXIT=%errorlevel%"
if "%DIAG_EXIT%"=="9009" goto diagnostic_no_python
goto diagnostic_finish
:diagnostic_no_python
>>"%BLITZCAM_DIAG_LOG%" echo 未找到 Python。使用便携版时，请把脚本放在含 app 和 runtime 文件夹的 BlitzCamera.exe 旁边。
:diagnostic_finish
type "%BLITZCAM_DIAG_LOG%"
echo.
echo 启动日志："%BLITZCAM_DIAG_LOG%"
if not "%DIAG_EXIT%"=="0" echo 本次未能完成诊断，请把启动日志发回。
echo.
echo 按任意键关闭此窗口。
pause >nul
exit /b %DIAG_EXIT%
# BEGIN PYTHON
"""One-file, read-only connection diagnostics for an existing portable release."""

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import struct
import sys
import uuid


DIAGNOSTIC_VERSION = 4


def inspect_startup_source(memory):
    """Read only the known WOW64 command line; report file arguments, not other options.

    Kept self-contained so this collector works beside older portable releases.
    Missing/ambiguous file arguments never invalidate the camera observations.
    """
    import ctypes as C
    result = {"state": "unavailable", "note": "Startup arguments are not proof of later in-client replay switches."}
    try:
        handle = getattr(memory, 'handle', None)
        if type(handle) is not int or not 0 < handle < 1 << (8 * C.sizeof(C.c_void_p)):
            raise ValueError('进程读取句柄不可用。')
        nt = C.WinDLL('ntdll')
        query = nt.NtQueryInformationProcess
        query.argtypes = [C.c_void_p, C.c_uint, C.c_void_p, C.c_ulong, C.c_void_p]
        query.restype = C.c_long
        peb = C.c_size_t()
        if query(handle, 26, C.byref(peb), C.sizeof(peb), None) != 0 or not 0x10000 < peb.value < 0x100000000:
            raise ValueError('无法读取启动回放路径。')
        params = memory.u32(peb.value + 0x10)
        header = memory.read(params + 0x40, 8)
        length, capacity, address = struct.unpack('<HHI', header)
        if not 2 <= length <= capacity <= 32768 or length % 2:
            raise ValueError('进程参数布局未匹配。')
        command = memory.read(address, length).decode('utf-16le')
        if memory.read(params + 0x40, 8) != header:
            raise ValueError('进程参数读取不一致。')
        shell, kernel = C.WinDLL('shell32'), C.WinDLL('kernel32')
        shell.CommandLineToArgvW.argtypes = [C.c_wchar_p, C.POINTER(C.c_int)]
        shell.CommandLineToArgvW.restype = C.POINTER(C.c_wchar_p)
        kernel.LocalFree.argtypes = [C.c_void_p]
        argc = C.c_int()
        argv = shell.CommandLineToArgvW(command, C.byref(argc))
        if not argv:
            raise ValueError('无法解析启动参数。')
        try:
            args = [argv[i] for i in range(argc.value)]
        finally:
            kernel.LocalFree(argv)
        if not args or Path(args[0]).resolve() != memory.info.path.resolve():
            raise ValueError('进程启动参数身份不一致。')
        candidates = [a for a in args[1:] if a.lower().endswith('.wotbreplay')]
        distinct = [str(p) for p in dict.fromkeys(Path(a).resolve() for a in candidates)]
        result.update(state='unique' if len(distinct) == 1 else 'missing' if not distinct else 'ambiguous',
                      argument_count=len(args), replay_arguments=candidates,
                      distinct_replay_files=distinct, replay_argument_count=len(candidates),
                      distinct_replay_file_count=len(distinct))
    except Exception as exc:
        result['error'] = {"type": type(exc).__name__, "message": str(exc)}
    return result


def diagnostic_types(memory):
    """Extra scan labels are evidence only; they never change reader acceptance."""
    preferred = dict(memory.profile.vtables)
    if memory.profile.sha256 == "5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608":
        # Static RTTI from the exact 11.21 executable, not inferred layouts.
        preferred.update(BattleController=0x37F8F70, CinemaCameraController=0x3830F9C,
                         BaseSpectatorCameraController=0x3830D34)
    return {name: memory.info.base + va - memory.profile.preferred_base for name, va in preferred.items()}


def inspect_camera_state(session, memory):
    """Follow already observed roots even when the expected spectator was not scanned."""
    from types import SimpleNamespace
    from blitzcam.profile import CameraError
    from blitzcam.reader import CameraSession

    result = {"observed_type_counts": {k: len(v) for k, v in memory.observed.items()},
              "scene_roots": [], "battle_roots": [], "alternate_controllers": [],
              "note": "Read-only observations after discovery; not an engine-frozen snapshot or connection approval."}
    if session.profile.sha256 != "5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608":
        result["detail_unavailable"] = "Extra root offsets are verified only for the exact 11.21 build."
        return result
    types = diagnostic_types(memory)
    labels = {v: k for k, v in types.items()}
    u = memory.u32
    base, end = session.info.base, session.info.base + session.profile.image_size

    def describe_type(pointer):
        item = {"address": hex(pointer)}
        try:
            vft = u(pointer)
            item.update(vft=hex(vft), vft_in_client_image=base <= vft < end)
            if vft in labels:
                item["known_type"] = labels[vft]
            else:
                # A copied/replaced VFT may be outside the EXE; trust RTTI text only
                # when its locator and descriptor still lie in the verified image.
                col = u(vft - 4)
                if not base <= col <= end - 20:
                    item["rtti_unavailable"] = "locator outside verified executable"
                    return item
                signature, offset, displacement, descriptor, _ = struct.unpack("<5I", memory.read(col, 20))
                if signature or displacement or offset > 0x1000 or not base <= descriptor <= end - 136:
                    item["rtti_unavailable"] = "unrecognized locator or descriptor"
                    return item
                name = memory.read(descriptor + 8, 128).split(b"\0", 1)[0]
                if re.fullmatch(rb"\.\?AV[A-Za-z0-9_?@$]{1,120}", name):
                    item.update(rtti_name=name.decode("ascii"), rtti_subobject_offset=offset)
                else:
                    item["rtti_unavailable"] = "unrecognized bounded class name"
        except CameraError as exc:
            item["error"] = str(exc)
        return item

    contexts, free_cameras = set(), set()
    for owner in sorted(memory.observed.get("GameSceneController", ()))[:8]:
        item = {"scene_controller": hex(owner)}
        result["scene_roots"].append(item)
        try:
            if u(owner) != types["GameSceneController"]:
                item["error"] = "scene controller changed after scan"
                continue
            scene, context = u(owner + 0x1C), u(owner + 0x20)
            game, free = u(owner + 0x8C), u(owner + 0x94)
            player = u(context + 0x1B0)
            render = u(scene + session.profile.scene_render_offset)
            addresses = dict(scene=scene, context=context, game_camera=game, free_camera=free,
                             player=player, render=render)
            item["objects"] = {k: describe_type(v) for k, v in addresses.items()}
            expected = dict(scene="GameScene", context="AvatarContextReplay", game_camera="GameCamera",
                            free_camera="FreeCamera", player="ReplayPlayer", render="RenderSystem")
            item["root_types_match"] = all(item["objects"][key].get("known_type") == kind
                                            for key, kind in expected.items())
            if not item["root_types_match"]:
                continue
            contexts.add(context)
            free_cameras.add(free)
            scene_a, scene_b = session.profile.scene_camera_offsets
            render_a, render_b = session.profile.render_camera_offsets
            cameras = dict(scene_a=u(scene + scene_a), scene_b=u(scene + scene_b),
                           render_a=u(render + render_a), render_b=u(render + render_b))
            item["active_camera_pointers"] = {k: hex(v) for k, v in cameras.items()}
            item["active_camera"] = ("free" if all(v == free for v in cameras.values()) else
                                     "tracked" if all(v == game for v in cameras.values()) else "inconsistent")
            item["context_free_mode_byte"] = memory.read(context + 0x190, 1)[0]
            clock_reader = CameraSession(memory)
            clock_reader.objects = SimpleNamespace(player=player)
            try:
                item["clock_observation"] = clock_reader._clock()
            except CameraError as exc:
                item["clock_error"] = str(exc)
        except CameraError as exc:
            item["error"] = str(exc)

    for battle in sorted(memory.observed.get("BattleController", ()))[:8]:
        item = {"battle_controller": hex(battle)}
        result["battle_roots"].append(item)
        try:
            if u(battle) != types["BattleController"]:
                item["error"] = "battle controller changed after scan"
                continue
            context, owner = u(battle + 0x120), u(battle + 0x150)
            item.update(context=hex(context), context_matches_scene=context in contexts,
                        owner=describe_type(owner), update_interface_vft=hex(u(battle + 0x128)))
            controller = u(owner + 0x68)
            item["controller_at_owner_68"] = describe_type(controller)
            if controller:
                item["controller_in_scanned_regions"] = any(start <= controller < start + size
                                                            for start, size in memory.scanned_regions)
                item["controller_camera_pointer"] = hex(u(controller + 0xC))
                item["controller_camera_matches_free"] = u(controller + 0xC) in free_cameras
        except CameraError as exc:
            item["error"] = str(exc)

    for name in ("CinemaCameraController", "BaseSpectatorCameraController"):
        for pointer in sorted(memory.observed.get(name, ()))[:8]:
            item = describe_type(pointer)
            result["alternate_controllers"].append(item)
            try:
                camera = u(pointer + 0xC)
                item.update(camera_pointer=hex(camera), camera_matches_free=camera in free_cameras)
            except CameraError as exc:
                item["error"] = str(exc)
    return result


def collect_diagnostics(memory=None):
    """Use the installed reader and its unchanged acceptance checks; never write to it."""
    report = {
        "schema_version": DIAGNOSTIC_VERSION,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "stage": "load_toolkit",
        "environment": {"windows": platform.platform(), "python": platform.python_version(),
                        "python_bits": struct.calcsize("P") * 8},
        "read_only": True,
    }
    owned_memory = None
    try:
        from blitzcam import __version__
        from blitzcam.memory import ReadOnlyMemory, find_process
        from blitzcam.profile import CameraError
        from blitzcam.reader import CameraSession

        report["toolkit_version"] = __version__

        class TracedMemory:
            def __init__(self, source):
                self.source, self.info, self.profile = source, source.info, source.profile
                self.failures = 0
                self.samples = []
                self.phase = "discover_camera"
                types = diagnostic_types(source)
                self.patterns = {struct.pack("<I", types[k]): k for k in (
                    "GameSceneController", "BattleController", "SpectatorCameraController",
                    "CinemaCameraController", "BaseSpectatorCameraController") if k in types}
                self.observed = {name: set() for name in self.patterns.values()}
                self.scanned_regions = []

            def read(self, address, size):
                try:
                    data = self.source.read(address, size)
                except CameraError as exc:
                    self.failures += 1
                    if len(self.samples) < 16:
                        self.samples.append({"address": hex(address), "size": size,
                                             "phase": self.phase, "error": str(exc)})
                    raise
                if self.phase == "discover_camera":
                    # Independent literal searches also retain overlapping matches.
                    for pattern, name in self.patterns.items():
                        found = self.observed[name]
                        offset = data.find(pattern)
                        while offset >= 0 and len(found) < 64:
                            pointer = address + offset
                            if pointer % 4 == 0:
                                found.add(pointer)
                            offset = data.find(pattern, offset + 1)
                return data

            def u32(self, address):
                return struct.unpack("<I", self.read(address, 4))[0]

            def regions(self):
                for start, size in self.source.regions():
                    self.scanned_regions.append((start, size))
                    yield start, size

        class DiagnosticSession(CameraSession):
            def __init__(self, source):
                super().__init__(source)
                self.accepted = set()
                self.rejection_counts = Counter()
                self.rejected_samples = []
                self.sample_kinds = set()

            def _guard(self, objects=None, **kwargs):
                try:
                    super()._guard(objects, **kwargs)
                except CameraError as exc:
                    if objects is not None:
                        reason = re.sub(r"0x[0-9a-fA-F]+", "<address>", str(exc))
                        self.rejection_counts[reason] += 1
                        # Keep one sample per scene owner and reason, with a bounded report.
                        kind = (objects.scene_controller, reason)
                        if kind not in self.sample_kinds and len(self.rejected_samples) < 12:
                            self.sample_kinds.add(kind)
                            self.rejected_samples.append(self.describe_rejection(objects, str(exc),
                                kwargs.get("controller_kind") or getattr(self, "controller_kind", "SpectatorCameraController")))
                    raise
                if objects is not None:
                    self.accepted.add(objects)

            def describe_rejection(self, a, reason, controller_kind):
                scene_a, scene_b = self.profile.scene_camera_offsets
                render_a, render_b = self.profile.render_camera_offsets
                checks = [(name + ".type", pointer, self.vft[name]) for pointer, name in (
                    (a.context, "AvatarContextReplay"), (a.player, "ReplayPlayer"),
                    (a.replay_controller, "ReplayCameraController"), (a.game_camera, "GameCamera"),
                    (a.free_camera, "FreeCamera"), (a.render, "RenderSystem"),
                    (a.scene, "GameScene"), (a.scene_controller, "GameSceneController"),
                    (a.spectator_controller, controller_kind))]
                checks += [
                    ("context.player", a.context + 0x1B0, a.player),
                    ("player.secondary_type", a.player + 0xC, self.live(self.profile.replay_secondary_vft)),
                    ("replay_controller.game_camera", a.replay_controller + 0x28, a.game_camera),
                    ("game_camera.replay_controller", a.game_camera + 0x5B8, a.replay_controller),
                    ("scene.render", a.scene + self.profile.scene_render_offset, a.render),
                    ("scene.camera_a", a.scene + scene_a, a.free_camera),
                    ("scene.camera_b", a.scene + scene_b, a.free_camera),
                    ("render.camera_a", a.render + render_a, a.free_camera),
                    ("render.camera_b", a.render + render_b, a.free_camera),
                    ("scene_controller.scene", a.scene_controller + 0x1C, a.scene),
                    ("scene_controller.context", a.scene_controller + 0x20, a.context),
                    ("scene_controller.game_camera", a.scene_controller + 0x8C, a.game_camera),
                    ("scene_controller.free_camera", a.scene_controller + 0x94, a.free_camera),
                    ("scene_controller.replay_controller", a.scene_controller + 0x9C, a.replay_controller),
                    ("spectator_controller.free_camera", a.spectator_controller + 0xC, a.free_camera),
                ]
                mismatches = []
                # A second read explains the rejection, but is not an engine-frozen snapshot.
                for name, address, expected in checks:
                    item = {"field": name, "address": hex(address), "expected": hex(expected)}
                    try:
                        actual = self.memory.u32(address)
                        if actual == expected:
                            continue
                        item["actual"] = hex(actual)
                    except CameraError as exc:
                        item["error"] = str(exc)
                    mismatches.append(item)
                return {"guard_error": reason, "addresses": {k: hex(v) for k, v in asdict(a).items()},
                        "mismatches_after_rejection": mismatches}

        if memory is None:
            report["stage"] = "find_process"
            info = find_process()
            report["process"] = {"pid": info.pid, "path": str(info.path), "base": hex(info.base),
                                 "image_size": info.image_size}
            report["stage"] = "verify_client_and_open_read_only"
            owned_memory = memory = ReadOnlyMemory(info)
        else:
            report["process"] = {"pid": memory.info.pid, "path": str(memory.info.path),
                                 "base": hex(memory.info.base)}

        report["build"] = {"version": memory.profile.version, "sha256": memory.profile.sha256}
        report["startup_source"] = inspect_startup_source(memory)
        traced = TracedMemory(memory)
        session = DiagnosticSession(traced)
        report["stage"] = "discover_camera"
        try:
            session.discover()
            report["stage"] = traced.phase = "capture_paused_camera"
            snapshot = session.capture(require_paused=True)
            report["snapshot"] = {key: snapshot[key] for key in ("replay", "camera", "quality", "addresses")}
            report["status"] = "connected"
            report["stage"] = "complete"
        finally:
            traced.phase = "inspect_camera_state"
            try:
                report["camera_state"] = inspect_camera_state(session, traced)
            except Exception as exc:
                report["camera_state"] = {"error": {"type": type(exc).__name__, "message": str(exc)}}
            report["discovery"] = dict(session.discovery_stats)
            report["discovery"].update(
                valid_chain_count=len(session.accepted),
                valid_chain_samples=[{k: hex(v) for k, v in asdict(a).items()}
                                     for a in sorted(session.accepted, key=lambda a: tuple(asdict(a).values()))[:8]],
                guard_rejections=dict(session.rejection_counts),
                rejected_chain_samples=session.rejected_samples,
                failed_reads=traced.failures,
                failed_read_samples=traced.samples,
            )
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if owned_memory is not None:
            owned_memory.close()
    return report


def write_report(report, root):
    destination = Path(root) / "output" / "connection-diagnostics"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = destination / (stamp + "-" + uuid.uuid4().hex[:8] + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return path


def main(root=None):
    root = Path(sys.argv[1]).resolve().parent if root is None else Path(root).resolve()
    # Prefer this folder's toolkit, including under embedded Python's isolated _pth.
    sys.path.insert(0, str(root / "app" if (root / "app" / "blitzcam").is_dir() else root))
    print("正在收集连接诊断（第 4 版）。请保持当前回放和镜头状态，稍候……", flush=True)
    report = collect_diagnostics()
    try:
        path = write_report(report, root)
    except OSError as exc:
        print("无法保存诊断文件：" + str(exc))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    if report["status"] == "connected":
        print("这次只读检查已成功识别暂停的自由镜头。")
    else:
        print("失败阶段：" + report["stage"])
        print(report.get("error", {}).get("message", "未知错误"))
        if report["stage"] == "discover_camera" and "discovery" in report:
            print("通过校验的对象链数量：" + str(report["discovery"]["valid_chain_count"]))
            for root in report.get("camera_state", {}).get("scene_roots", []):
                if "active_camera" in root:
                    print("场景实际相机：" + {"free": "自由镜头", "tracked": "跟随镜头",
                                            "inconsistent": "相机关联尚未一致"}[root["active_camera"]])
            for root in report.get("camera_state", {}).get("battle_roots", []):
                controller = root.get("controller_at_owner_68", {})
                kind = controller.get("known_type", controller.get("rtti_name", controller.get("vft", "未知")))
                print("更新链中的镜头控制器：" + kind)
    source = report.get('startup_source', {})
    if source.get('state') in ('missing', 'ambiguous'):
        print('启动参数中的回放文件数量：' + str(source['distinct_replay_file_count']))
        print('镜头识别与回放文件核对分别记录；不会把已选择文件当作游戏实际载入的文件。')
    print("诊断文件已保存，请将这个 JSON 文件发回：\n" + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
