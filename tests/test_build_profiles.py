"""Version selection and new-build reads against archived, real object slices."""

from dataclasses import replace
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from blitzcam.memory import verify_binary
from blitzcam.profile import CameraError, PROFILE, PROFILE_1121
from blitzcam.reader import CameraSession, Objects


class FixtureMemory:
    def __init__(self, profile=PROFILE_1121):
        path = Path(__file__).parent/'fixtures/1121-paused-objects.json'
        self.fixture = json.loads(path.read_text(encoding='utf-8'))
        self.profile = profile
        self.info = SimpleNamespace(base=int(self.fixture['module_base'], 16), pid=1, path=Path('fixture.exe'))
        self.blocks = {int(p, 16): bytes.fromhex(b) for p, b in self.fixture['blocks'].items()}

    def read(self, address, size):
        for base, data in self.blocks.items():
            if base <= address and address+size <= base+len(data):
                return data[address-base:address-base+size]
        raise CameraError('Outside archived fixture')

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def regions(self):
        return [(p, len(b)) for p, b in self.blocks.items()]


class BuildProfileTests(unittest.TestCase):
    def binary_info(self, profile):
        data = bytearray(256)
        struct.pack_into('<I', data, 0x3c, 0x80)
        data[0x80:0x84] = b'PE\0\0'
        struct.pack_into('<H', data, 0x84, profile.machine)
        struct.pack_into('<H', data, 0x98, profile.optional_magic)
        struct.pack_into('<I', data, 0xb4, profile.preferred_base)
        return SimpleNamespace(path=SimpleNamespace(read_bytes=lambda: data), image_size=profile.image_size), data

    def test_each_exact_hash_selects_its_own_profile(self):
        for profile in (PROFILE, PROFILE_1121):
            info, _ = self.binary_info(profile)
            with patch('blitzcam.memory.hashlib.sha256', return_value=Mock(hexdigest=lambda: profile.sha256)):
                self.assertIs(verify_binary(info), profile)

    def test_unknown_hash_cannot_fall_back_to_old_profile(self):
        info, _ = self.binary_info(PROFILE_1121)
        with patch('blitzcam.memory.hashlib.sha256', return_value=Mock(hexdigest=lambda: '0'*64)):
            with self.assertRaisesRegex(CameraError, '尚未适配'):
                verify_binary(info)

    def test_runtime_size_or_architecture_mismatch_is_rejected(self):
        for wrong_arch in (False, True):
            info, data = self.binary_info(PROFILE_1121)
            if wrong_arch:
                struct.pack_into('<H', data, 0x84, 0x8664)
            else:
                info.image_size = PROFILE.image_size
            with patch('blitzcam.memory.hashlib.sha256', return_value=Mock(hexdigest=lambda: PROFILE_1121.sha256)):
                with self.assertRaises(CameraError):
                    verify_binary(info)

    def test_new_build_discovers_complete_real_chain_and_captures(self):
        memory = FixtureMemory()
        session = CameraSession(memory)
        objects = session.discover()
        self.assertEqual(objects.scene, int(memory.fixture['addresses']['scene'], 16))
        snapshot = session.capture()
        self.assertEqual(snapshot['build']['version'], '11.21.0.1235')
        self.assertAlmostEqual(snapshot['replay']['time'], 23.61650562286377)
        self.assertTrue(snapshot['replay']['paused'])
        self.assertAlmostEqual(snapshot['camera']['position'][0], -135.54177856445312)
        self.assertAlmostEqual(snapshot['camera']['horizontal_fov_deg'], 68.41167535035929)
        # New depth coefficients must not be mistaken for an invalid FOV layout.
        self.assertEqual(snapshot['raw_camera']['projection'][10], 0)
        self.assertEqual(snapshot['raw_camera']['projection'][14], 1)
        self.assertLess(snapshot['quality']['eye_error'], 1e-4)
        self.assertLess(snapshot['quality']['vp_error'], 1e-4)
        self.assertFalse(snapshot['quality']['active_root_verified'])
        self.assertFalse(snapshot['capabilities']['live_write'])

    def test_old_scene_or_render_offsets_fail_even_with_correct_new_types(self):
        for change in ({'scene_render_offset': PROFILE.scene_render_offset},
                       {'scene_camera_offsets': PROFILE.scene_camera_offsets},
                       {'render_camera_offsets': PROFILE.render_camera_offsets}):
            with self.subTest(change=change):
                session = CameraSession(FixtureMemory(replace(PROFILE_1121, **change)))
                with self.assertRaisesRegex(CameraError, '唯一'):
                    session.discover()

    def test_old_vtables_do_not_identify_new_build(self):
        with self.assertRaises(CameraError):
            CameraSession(FixtureMemory(PROFILE)).discover()

    def test_changed_scene_camera_link_stops_a_discovered_session(self):
        memory = FixtureMemory()
        session = CameraSession(memory)
        session.discover()
        scene = session.objects.scene
        data = bytearray(memory.blocks[scene])
        struct.pack_into('<I', data, 0x120, 0)
        memory.blocks[scene] = bytes(data)
        with self.assertRaises(CameraError):
            session.capture()


if __name__ == '__main__':
    unittest.main()
