"""Cinema compatibility over archived shared-base bytes, with synthetic type changes.

These are offline tests, not a memory dump or a playback trial from the remote PC.
"""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import test_build_profiles as fixtures
from blitzcam.hook_guards import controller_extra, same_scene, validate_snapshot
from blitzcam.hook_layout import PathPoint, Quat, Vec
from blitzcam.playback import config_for
from blitzcam.profile import CameraError, PROFILE_1121, SessionChanged
from blitzcam.reader import CameraSession
from blitzcam.replay_launcher import ReplaySourceUnavailable, verify_launch_source
from blitzcam.replay_timeline import file_timeline, session_timeline


def controller_fixture(kind="CinemaCameraController", base=None):
    memory = fixtures.FixtureMemory()
    session = CameraSession(memory)
    pointer = int(memory.fixture["addresses"]["spectator_controller"], 16)
    data = bytearray(memory.blocks[pointer])
    struct.pack_into("<I", data, 0, session.vft[kind])
    memory.blocks[pointer] = bytes(data)
    if base is not None:
        # Rebase only the known module type pointers; historical heap pointers stay fixed.
        delta = base - memory.info.base
        types = set(session.vft.values()) | {session.live(memory.profile.replay_secondary_vft)}
        for address, original in list(memory.blocks.items()):
            data = bytearray(original)
            for offset in range(0, len(data) - 3, 4):
                value = struct.unpack_from("<I", data, offset)[0]
                if value in types:
                    struct.pack_into("<I", data, offset, value + delta)
            memory.blocks[address] = bytes(data)
        memory.info.base = base
    return memory


class CinemaControllerTests(unittest.TestCase):
    def test_unsupported_file_reader_keeps_both_camera_types_usable(self):
        for kind in ("CinemaCameraController", "SpectatorCameraController"):
            with self.subTest(kind=kind):
                memory = controller_fixture(kind)
                memory.profile = replace(memory.profile, replay_file_source_offset=None)
                session = CameraSession(memory)
                session.discover()
                with self.assertRaisesRegex(ReplaySourceUnavailable, "尚未适配游戏内回放文件读取"):
                    session_timeline(session)
                self.assertEqual(session.capture()["native_controller"]["kind"], kind)

    def test_both_supported_controllers_discover_and_capture_under_remote_aslr(self):
        for kind in ("CinemaCameraController", "SpectatorCameraController"):
            with self.subTest(kind=kind):
                session = CameraSession(controller_fixture(kind, base=0xD50000))
                session.discover()
                snapshot = session.capture()
                self.assertEqual(session.controller_kind, kind)
                self.assertEqual(snapshot["native_controller"]["kind"], kind)
                self.assertEqual(session.discovery_stats["valid_chain_count"], 1)
                self.assertEqual(session.discovery_stats["controller_kind"], kind)
                self.assertTrue(snapshot["replay"]["paused"])
                validate_snapshot(snapshot)
                if kind == "CinemaCameraController":
                    self.assertEqual(session.vft[kind], 0x4180F9C)
                    self.assertEqual(session.discovery_stats["candidate_counts"]["SpectatorCameraController"], 0)

    def test_controller_type_is_pinned_until_reconnect(self):
        for first, changed in (("CinemaCameraController", "SpectatorCameraController"),
                               ("SpectatorCameraController", "CinemaCameraController")):
            with self.subTest(first=first):
                memory = controller_fixture(first)
                session = CameraSession(memory)
                session.discover()
                pointer = session.objects.spectator_controller
                data = bytearray(memory.blocks[pointer])
                struct.pack_into("<I", data, 0, session.vft[changed])
                memory.blocks[pointer] = bytes(data)
                with self.assertRaises(SessionChanged):
                    session.capture()

    def test_two_compatible_controllers_still_fail_uniqueness(self):
        memory = controller_fixture()
        session = CameraSession(memory)
        pointer = int(memory.fixture["addresses"]["spectator_controller"], 16)
        other = bytearray(memory.blocks[pointer])
        struct.pack_into("<I", other, 0, session.vft["SpectatorCameraController"])
        memory.blocks[0x50000000] = bytes(other)
        with self.assertRaisesRegex(CameraError, "唯一"):
            session.discover()
        self.assertEqual(session.discovery_stats["valid_chain_count"], 2)
        self.assertIsNone(session.objects)

    def test_cinema_does_not_bypass_camera_links_or_scene_render_links(self):
        for target, offset in (("spectator_controller", 0xC), ("scene", 0x120), ("render", 0xB4)):
            with self.subTest(target=target):
                memory = controller_fixture()
                pointer = int(memory.fixture["addresses"][target], 16)
                data = bytearray(memory.blocks[pointer])
                struct.pack_into("<I", data, offset, 0)
                memory.blocks[pointer] = bytes(data)
                with self.assertRaisesRegex(CameraError, "唯一"):
                    CameraSession(memory).discover()

    def test_a_profile_without_verified_cinema_vft_cannot_accept_it(self):
        memory = controller_fixture()
        memory.profile = replace(PROFILE_1121, vtables=tuple(
            (key, value) for key, value in PROFILE_1121.vtables if key != "CinemaCameraController"))
        with self.assertRaisesRegex(CameraError, "唯一"):
            CameraSession(memory).discover()

    def test_unknown_base_controller_is_not_treated_as_either_derived_type(self):
        memory = controller_fixture()
        pointer = int(memory.fixture["addresses"]["spectator_controller"], 16)
        data = bytearray(memory.blocks[pointer])
        struct.pack_into("<I", data, 0, memory.info.base + 0x3830D34 - memory.profile.preferred_base)
        memory.blocks[pointer] = bytes(data)
        with self.assertRaisesRegex(CameraError, "唯一"):
            CameraSession(memory).discover()

    def test_shared_native_mode_and_finite_number_checks_remain_enforced(self):
        for offset, value in ((0x10C, 0), (0x128, 1), (0x114, 0x7FC00000)):
            with self.subTest(offset=offset):
                memory = controller_fixture()
                session = CameraSession(memory)
                session.discover()
                pointer = session.objects.spectator_controller
                data = bytearray(memory.blocks[pointer])
                struct.pack_into("<I", data, offset, value)
                memory.blocks[pointer] = bytes(data)
                with self.assertRaises(CameraError):
                    session.capture()

    def test_playback_receives_the_pinned_controller_vft_for_each_type(self):
        for kind in ("CinemaCameraController", "SpectatorCameraController"):
            with self.subTest(kind=kind):
                session = CameraSession(controller_fixture(kind))
                session.discover()
                snap = session.capture()
                pose = snap["camera"]
                rows = [PathPoint(time, Vec(*pose["position"]), Quat(*pose["quaternion"]),
                                  pose["horizontal_fov_deg"]) for time in (0, 1)]
                link = {"battle_controller": "0x50000000", "owner_at_150": "0x50001000"}
                cfg = config_for(session, snap, link, rows, 1, False, controller_extra(session))
                self.assertEqual(cfg.spectator_vft, session.vft[kind])
                self.assertEqual(cfg.spectator, session.objects.spectator_controller)
                self.assertEqual(cfg.camera, session.objects.free_camera)

    def test_reconnect_cannot_reuse_a_reference_from_the_other_controller_type(self):
        session = CameraSession(controller_fixture())
        session.discover()
        snapshot = session.capture()
        old = deepcopy(snapshot)
        old["native_controller"]["kind"] = "SpectatorCameraController"
        with self.assertRaisesRegex(CameraError, "控制器已切换"):
            same_scene(old, snapshot)


if __name__ == "__main__":
    unittest.main()
