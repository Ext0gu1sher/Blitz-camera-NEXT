"""Exercise the standalone collector using archived objects, never the live game."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import test_build_profiles as fixtures
from blitzcam.profile import CameraError


SCRIPT = Path(__file__).resolve().parents[1] / "Collect Camera Diagnostics.cmd"
namespace = {"__name__": "connection_diagnostic_test"}
exec(compile(SCRIPT.read_text(encoding="utf-8").split("\n# BEGIN PYTHON\n", 1)[1], str(SCRIPT), "exec"), namespace)
collect_diagnostics = namespace["collect_diagnostics"]


class ConnectionDiagnosticTests(unittest.TestCase):
    def add_update_chain(self, memory):
        types = namespace["diagnostic_types"](memory)
        battle, owner = 0x50000000, 0x50001000
        data = bytearray(0x154)
        struct.pack_into("<I", data, 0, types["BattleController"])
        struct.pack_into("<I", data, 0x120, int(memory.fixture["addresses"]["context"], 16))
        struct.pack_into("<I", data, 0x128, memory.info.base + 0x37F8FB0 - memory.profile.preferred_base)
        struct.pack_into("<I", data, 0x150, owner)
        memory.blocks[battle] = bytes(data)
        data = bytearray(0x6C)
        struct.pack_into("<I", data, 0x68, int(memory.fixture["addresses"]["spectator_controller"], 16))
        memory.blocks[owner] = bytes(data)

    def set_controller_type(self, memory, vft):
        pointer = int(memory.fixture["addresses"]["spectator_controller"], 16)
        data = bytearray(memory.blocks[pointer])
        struct.pack_into("<I", data, 0, vft)
        memory.blocks[pointer] = bytes(data)

    def test_real_paused_fixture_passes_without_changing_memory(self):
        memory = fixtures.FixtureMemory()
        before = dict(memory.blocks)
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "connected")
        self.assertEqual(report["discovery"]["valid_chain_count"], 1)
        self.assertTrue(report["snapshot"]["replay"]["paused"])
        self.assertEqual(report["snapshot"]["addresses"]["scene"], memory.fixture["addresses"]["scene"])
        self.assertEqual(memory.blocks, before)
        self.assertNotIn("raw_camera", report["snapshot"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["schema_version"], 4)
        self.assertEqual(report['startup_source']['state'], 'unavailable')
        json.dumps(report, allow_nan=False)

    def test_missing_controller_still_explains_actual_camera_and_clock(self):
        memory = fixtures.FixtureMemory()
        self.add_update_chain(memory)
        del memory.blocks[int(memory.fixture["addresses"]["spectator_controller"], 16)]
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stage"], "discover_camera")
        self.assertEqual(report["discovery"]["candidate_counts"]["SpectatorCameraController"], 0)
        state = report["camera_state"]
        self.assertEqual(state["scene_roots"][0]["active_camera"], "free")
        self.assertTrue(state["scene_roots"][0]["clock_observation"]["paused"])
        battle = state["battle_roots"][0]
        self.assertTrue(battle["context_matches_scene"])
        self.assertIn("error", battle["controller_at_owner_68"])

    def test_controller_outside_selected_scan_is_found_through_update_chain(self):
        memory = fixtures.FixtureMemory()
        self.add_update_chain(memory)
        pointer = int(memory.fixture["addresses"]["spectator_controller"], 16)
        memory.regions = lambda: [(p, len(b)) for p, b in memory.blocks.items() if p != pointer]
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("snapshot", report)
        self.assertEqual(report["discovery"]["candidate_counts"]["SpectatorCameraController"], 0)
        battle = report["camera_state"]["battle_roots"][0]
        self.assertFalse(battle["controller_in_scanned_regions"])
        self.assertEqual(battle["controller_at_owner_68"]["known_type"], "SpectatorCameraController")
        self.assertTrue(battle["controller_camera_matches_free"])

    def test_unverified_base_controller_is_evidence_and_never_approves_connection(self):
        memory = fixtures.FixtureMemory()
        self.add_update_chain(memory)
        self.set_controller_type(memory, namespace["diagnostic_types"](memory)["BaseSpectatorCameraController"])
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("snapshot", report)
        state = report["camera_state"]
        self.assertEqual(state["scene_roots"][0]["active_camera"], "free")
        self.assertTrue(state["scene_roots"][0]["clock_observation"]["paused"])
        self.assertEqual(state["observed_type_counts"]["BaseSpectatorCameraController"], 1)
        self.assertTrue(state["alternate_controllers"][0]["camera_matches_free"])
        self.assertEqual(state["battle_roots"][0]["controller_at_owner_68"]["known_type"], "BaseSpectatorCameraController")

    def test_new_reader_captures_cinema_and_diagnostic_reports_its_actual_kind(self):
        memory = fixtures.FixtureMemory()
        self.add_update_chain(memory)
        self.set_controller_type(memory, namespace["diagnostic_types"](memory)["CinemaCameraController"])
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "connected")
        self.assertEqual(report["discovery"]["valid_chain_count"], 1)
        self.assertEqual(report["discovery"]["controller_kind"], "CinemaCameraController")
        self.assertEqual(report["camera_state"]["observed_type_counts"]["SpectatorCameraController"], 0)

    def test_replaced_vft_exposes_verified_image_rtti_without_approving_connection(self):
        memory = fixtures.FixtureMemory()
        self.add_update_chain(memory)
        # Synthetic copied VFT refers to bounded RTTI in the verified module's range.
        vft, col, descriptor = 0x60000004, memory.info.base + 0x30000, memory.info.base + 0x30100
        self.set_controller_type(memory, vft)
        memory.blocks[vft - 4] = struct.pack("<2I", col, 0)
        memory.blocks[col] = struct.pack("<5I", 0, 0, 0, descriptor, 0)
        memory.blocks[descriptor] = bytes(8) + b".?AVSpectatorCameraController@@\0".ljust(128, b"\0")
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("snapshot", report)
        controller = report["camera_state"]["battle_roots"][0]["controller_at_owner_68"]
        self.assertFalse(controller["vft_in_client_image"])
        self.assertEqual(controller["rtti_name"], ".?AVSpectatorCameraController@@")

    def test_unknown_rtti_outside_verified_image_is_not_followed(self):
        memory = fixtures.FixtureMemory()
        self.add_update_chain(memory)
        vft, col = 0x60000004, 0x70000000
        self.set_controller_type(memory, vft)
        memory.blocks[vft - 4] = struct.pack("<2I", col, 0)
        report = collect_diagnostics(memory)
        controller = report["camera_state"]["battle_roots"][0]["controller_at_owner_68"]
        self.assertEqual(controller["rtti_unavailable"], "locator outside verified executable")
        self.assertNotIn("rtti_name", controller)
        self.assertEqual(report["status"], "failed")

    def test_following_camera_is_distinguished_from_an_allocated_free_camera(self):
        memory = fixtures.FixtureMemory()
        scene = int(memory.fixture["addresses"]["scene"], 16)
        render = int(memory.fixture["addresses"]["render"], 16)
        game = int(memory.fixture["addresses"]["game_camera"], 16)
        for pointer, offsets in ((scene, memory.profile.scene_camera_offsets),
                                 (render, memory.profile.render_camera_offsets)):
            data = bytearray(memory.blocks[pointer])
            for offset in offsets:
                struct.pack_into("<I", data, offset, game)
            memory.blocks[pointer] = bytes(data)
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["camera_state"]["scene_roots"][0]["active_camera"], "tracked")

    def test_broken_scene_link_reports_the_field_with_zero_valid_chains(self):
        memory = fixtures.FixtureMemory()
        scene = int(memory.fixture["addresses"]["scene"], 16)
        data = bytearray(memory.blocks[scene])
        struct.pack_into("<I", data, memory.profile.scene_camera_offsets[0], 0)
        memory.blocks[scene] = bytes(data)
        report = collect_diagnostics(memory)
        self.assertEqual(report["stage"], "discover_camera")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["discovery"]["valid_chain_count"], 0)
        mismatches = report["discovery"]["rejected_chain_samples"][0]["mismatches_after_rejection"]
        self.assertEqual(mismatches, [{"field": "scene.camera_a", "address": hex(scene + 0x120),
                                       "expected": memory.fixture["addresses"]["free_camera"], "actual": "0x0"}])

    def test_multiple_valid_chains_are_diagnosed_and_still_rejected(self):
        memory = fixtures.FixtureMemory()
        spectator = int(memory.fixture["addresses"]["spectator_controller"], 16)
        memory.blocks[0x3C4D0000] = memory.blocks[spectator]
        report = collect_diagnostics(memory)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stage"], "discover_camera")
        self.assertEqual(report["discovery"]["valid_chain_count"], 2)
        self.assertEqual(len(report["discovery"]["valid_chain_samples"]), 2)
        self.assertNotIn("snapshot", report)

    def test_missing_controller_and_unreadable_owner_are_distinguishable(self):
        for missing in ("spectator_controller", "context"):
            with self.subTest(missing=missing):
                memory = fixtures.FixtureMemory()
                del memory.blocks[int(memory.fixture["addresses"][missing], 16)]
                report = collect_diagnostics(memory)
                discovery = report["discovery"]
                self.assertEqual(report["stage"], "discover_camera")
                self.assertEqual(discovery["valid_chain_count"], 0)
                if missing == "context":
                    self.assertGreater(discovery["failed_reads"], 0)
                    self.assertTrue(discovery["failed_read_samples"])
                else:
                    self.assertEqual(discovery["candidate_counts"]["SpectatorCameraController"], 0)

    def test_unpaused_fixture_is_a_capture_error_after_successful_discovery(self):
        memory = fixtures.FixtureMemory()
        player = int(memory.fixture["addresses"]["player"], 16)
        data = bytearray(memory.blocks[player])
        data[0x12] = 0
        memory.blocks[player] = bytes(data)
        report = collect_diagnostics(memory)
        self.assertEqual(report["stage"], "capture_paused_camera")
        self.assertEqual(report["discovery"]["valid_chain_count"], 1)
        self.assertIn("暂停", report["error"]["message"])

    def test_process_errors_are_written_and_do_not_attempt_open(self):
        with patch("blitzcam.memory.find_process", side_effect=CameraError("未找到唯一的进程")), \
                patch("blitzcam.memory.ReadOnlyMemory") as open_memory:
            report = collect_diagnostics()
        self.assertEqual(report["stage"], "find_process")
        self.assertIn("未找到", report["error"]["message"])
        open_memory.assert_not_called()
        with tempfile.TemporaryDirectory() as root:
            first = namespace["write_report"](report, root)
            second = namespace["write_report"](report, root)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), report)

    def test_owned_read_handle_is_closed_even_on_discovery_failure(self):
        memory = fixtures.FixtureMemory()
        memory.info.image_size = memory.profile.image_size
        memory.close = Mock()
        memory.blocks.clear()
        with patch("blitzcam.memory.find_process", return_value=memory.info), \
                patch("blitzcam.memory.ReadOnlyMemory", return_value=memory):
            report = collect_diagnostics()
        self.assertEqual(report["stage"], "discover_camera")
        memory.close.assert_called_once_with()

    def test_main_uses_its_own_folder_and_saves_json(self):
        report = collect_diagnostics(fixtures.FixtureMemory())
        # The launcher body can be tested without executing its live collection entry point.
        with tempfile.TemporaryDirectory(prefix="camera 中文 ") as root:
            with patch.dict(namespace, {"collect_diagnostics": lambda: report}), \
                    patch.object(namespace["sys"], "path", list(namespace["sys"].path)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(namespace["main"](root), 0)
            self.assertIn("已保存", output.getvalue())
            files = list(Path(root).glob("output/connection-diagnostics/*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text(encoding="utf-8")), report)

    @unittest.skipUnless(os.name == "nt", "Windows batch launcher")
    def test_both_launchers_with_spaces_and_unicode_use_only_offline_fixture(self):
        project = SCRIPT.parent
        portable = project / "dist" / "BlitzCamera-0.9.3"
        if not (portable / "runtime" / "python.exe").is_file():
            self.skipTest("Portable runtime not present")
        output = project / "output" / "connection-diagnostic-acceptance"
        output.mkdir(parents=True, exist_ok=True)
        source = SCRIPT.read_text(encoding="utf-8")
        marker = 'if __name__ == "__main__":\n    raise SystemExit(main())'
        self.assertEqual(source.count(marker), 1)
        offline_entry = (
            'if __name__ == "__main__":\n'
            '    original_collect = collect_diagnostics\n'
            '    def collect_diagnostics():\n'
            '        sys.path.append(' + repr(str(project / "tests")) + ')\n'
            '        from test_build_profiles import FixtureMemory\n'
            '        from unittest.mock import patch\n'
            '        with patch("blitzcam.memory.find_process", side_effect=AssertionError("Live process forbidden")):\n'
            '            return original_collect(FixtureMemory())\n'
            '    raise SystemExit(main())'
        )
        for embedded in (True, False):
            with self.subTest(embedded=embedded), tempfile.TemporaryDirectory(prefix="camera 中文 & (a) ! ", dir=output) as temporary:
                root = Path(temporary).resolve()
                self.assertTrue(root.is_relative_to(output.resolve()))
                toolkit = root / "app" / "blitzcam" if embedded else root / "blitzcam"
                toolkit.mkdir(parents=True)
                for name in ("__init__.py", "memory.py", "reader.py", "profile.py", "pose.py", "trajectory.py"):
                    shutil.copy2(portable / "app" / "blitzcam" / name, toolkit / name)
                if embedded:
                    shutil.copytree(portable / "runtime", root / "runtime")
                launcher = root / SCRIPT.name
                # Preserve the delivered artifact's byte-level line endings.
                # write_text() on Windows silently repaired LF-only launchers.
                delivered = SCRIPT.read_bytes()
                newline = b'\r\n' if b'\r\n' in delivered else b'\n'
                byte_marker = marker.encode('utf-8').replace(b'\n', newline)
                byte_entry = offline_entry.encode('utf-8').replace(b'\n', newline)
                self.assertEqual(delivered.count(byte_marker), 1)
                launcher.write_bytes(delivered.replace(byte_marker, byte_entry))
                command = '"' + os.environ.get('COMSPEC', 'cmd.exe') + '" /d /s /c ""' + str(launcher) + '""'
                result = subprocess.run(command,
                                        input="\n", text=True, encoding="utf-8", errors="replace",
                                        capture_output=True, timeout=30, cwd=project)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                files = list(root.glob("output/connection-diagnostics/*.json"))
                self.assertEqual(len(files), 1, result.stdout + result.stderr)
                report = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "connected", report)
                self.assertEqual(report["discovery"]["valid_chain_count"], 1)
                self.assertIn('按任意键关闭此窗口', result.stdout)
                self.assertTrue((root/'output/connection-diagnostics/diagnostic-startup.log').is_file())

    def test_delivered_batch_has_windows_line_endings_without_bom(self):
        delivered = SCRIPT.read_bytes()
        self.assertTrue(delivered.startswith(b'@echo off\r\n'))
        self.assertNotIn(b'\n', delivered.replace(b'\r\n', b''))

    @unittest.skipUnless(os.name == 'nt', 'Windows batch launcher failure handling')
    def test_launcher_failures_leave_logs_and_wait_for_a_key(self):
        portable = SCRIPT.parent/'dist/BlitzCamera-0.9.3'
        for failure in ('wrong_folder', 'missing_runtime', 'no_python', 'python_failure', 'blocked_output'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix='diagnostic 中文 & (a) ! ') as temp:
                root = Path(temp)
                launcher = root/SCRIPT.name
                delivered = SCRIPT.read_bytes()
                if failure == 'python_failure':
                    if not (portable/'runtime/python.exe').is_file():
                        continue
                    (root/'app/blitzcam').mkdir(parents=True)
                    (root/'app/blitzcam/__init__.py').write_bytes(b'')
                    shutil.copytree(portable/'runtime', root/'runtime')
                    # Fail before any payload can import the reader or find a process.
                    delivered = delivered.replace(b'# BEGIN PYTHON\r\n', b'# BEGIN PYTHON\r\nthis is invalid Python !!!\r\n')
                elif failure == 'missing_runtime':
                    (root/'app/blitzcam').mkdir(parents=True)
                    (root/'app/blitzcam/__init__.py').write_bytes(b'')
                elif failure == 'no_python':
                    (root/'blitzcam').mkdir()
                    (root/'blitzcam/__init__.py').write_bytes(b'')
                launcher.write_bytes(delivered)
                env = dict(os.environ)
                if failure == 'no_python':
                    env['PATH'] = str(root)  # No alias, installed Python or game can be executed.
                if failure == 'blocked_output':
                    (root/'output').write_text('occupied by a file', encoding='utf-8')
                    (root/'temp').mkdir()
                    env['TEMP'] = str(root/'temp')
                    log = root/'temp/BlitzCamera-diagnostic-startup.log'
                else:
                    log = root/'output/connection-diagnostics/diagnostic-startup.log'
                command = '"' + os.environ.get('COMSPEC', 'cmd.exe') + '" /d /s /c ""' + str(launcher) + '""'
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                    cwd=SCRIPT.parent, env=env)
                ready = threading.Event()
                lines = []
                def read_output():
                    for line in process.stdout:
                        lines.append(line)
                        if '按任意键关闭此窗口' in line:
                            ready.set()
                reader = threading.Thread(target=read_output, daemon=True)
                reader.start()
                try:
                    self.assertTrue(ready.wait(10), ''.join(lines))
                    self.assertIsNone(process.poll(), 'Window exited before the user pressed a key: ' + ''.join(lines))
                    self.assertTrue(log.is_file(), ''.join(lines))
                    text = log.read_text(encoding='utf-8')
                    expected = {'wrong_folder': '未找到软件文件', 'missing_runtime': '缺少 runtime',
                                'no_python': '未找到 Python', 'python_failure': 'SyntaxError',
                                'blocked_output': '未找到软件文件'}[failure]
                    self.assertIn(expected, text)
                    self.assertFalse(list(root.glob('output/connection-diagnostics/*.json')))
                    process.stdin.write('\n'); process.stdin.flush()
                    self.assertNotEqual(process.wait(timeout=5), 0)
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait(timeout=5)
                    process.stdin.close()
                    reader.join(timeout=5)
                    process.stdout.close()


if __name__ == "__main__":
    unittest.main()
