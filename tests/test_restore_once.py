"""Offline checks of the supervised writer's attempt budget and write boundary.

All Windows entry points are replaced before a writer can open a handle.
"""

from contextlib import ExitStack
from copy import deepcopy
import ctypes as C
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1]/'research/scripts/restore_position_1121_once.py'
SPEC = importlib.util.spec_from_file_location('restore_once_under_test', SCRIPT)
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)


def capture():
    return {'build': {'sha256': restore.PROFILE_1121.sha256},
            'replay': {'paused': True, 'time': 23., 'origin': 9.},
            'session_id': 'test-session', 'addresses': {'camera': '0x2000'},
            'camera': {'position': [1., 2., 3.], 'quaternion': [0., 0., 0., 1.],
                       'horizontal_fov_deg': 68.}}


class PairGates(unittest.TestCase):
    def test_explicit_lateral_range_and_quaternion_sign(self):
        saved = capture(); current = deepcopy(saved)
        current['camera']['position'][0] += 18.
        current['camera']['quaternion'] = [0., 0., 0., -1.]
        self.assertEqual(restore.validate_pair(saved, current, 25.)['distance'], 18.)
        with self.assertRaises(restore.CameraError):
            restore.validate_pair(saved, current)

    def test_identity_clock_mode_and_pose_changes_are_rejected(self):
        for field, value in [('session_id', 'other'), ('sha256', '0'*64),
                             ('paused', False), ('time', 24.), ('origin', 8.),
                             ('position', [float('nan'), 2., 3.]),
                             ('quaternion', [0., 0., 1., 0.]),
                             ('horizontal_fov_deg', 70.)]:
            with self.subTest(field=field):
                saved = capture(); current = deepcopy(saved)
                current['camera']['position'][0] += 1.
                parent = (current['build'] if field == 'sha256' else
                          current['replay'] if field in ('paused', 'time', 'origin') else
                          current['camera'] if field in ('position', 'quaternion', 'horizontal_fov_deg') else current)
                parent[field] = value
                with self.assertRaises(restore.CameraError):
                    restore.validate_pair(saved, current)


class OneShotBudget(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.k = Mock()
        self.k.OpenProcess.return_value = 123
        self.stack.enter_context(patch.object(restore.C, 'WinDLL', return_value=self.k))
        self.stack.enter_context(patch.object(restore, 'identity', return_value={'pid': 1}))
        self.verify = self.stack.enter_context(patch.object(restore, 'verify_live', return_value=(capture(), {}, {})))
        self.protection = 4
        self.count = 12
        self.calls = []

        def query(handle, address, pointer, size):
            region = C.cast(pointer, C.POINTER(restore.MEMORY_BASIC_INFORMATION)).contents
            region.BaseAddress = 0x1000; region.RegionSize = 0x1000
            region.State = 0x1000; region.Type = 0x20000; region.Protect = self.protection
            return size

        def write(handle, address, buffer, size, count):
            self.calls.append((handle, address.value, C.string_at(buffer, size), size))
            C.cast(count, C.POINTER(C.c_size_t)).contents.value = self.count
            return 1

        self.k.VirtualQueryEx.side_effect = query
        self.k.WriteProcessMemory.side_effect = write
        self.session = SimpleNamespace(info=SimpleNamespace(pid=1),
                                       objects=SimpleNamespace(spectator_controller=0x1000),
                                       memory=Mock())
        self.session.memory.read.return_value = struct.pack('<3f', 4., 5., 6.)
        self.writer = restore.OneTargetWrite()
        self.journal = Mock()

    def commit(self):
        return self.writer.commit(self.session, capture(), {}, {'pid': 1}, self.journal)

    def test_exact_twelve_bytes_once_then_handle_closes(self):
        self.assertTrue(self.commit()['full_payload_written'])
        self.assertEqual(self.calls, [(123, 0x10ac, struct.pack('<3f', 1., 2., 3.), 12)])
        self.k.OpenProcess.assert_called_once_with(0x438, False, 1)
        self.k.CloseHandle.assert_called_once_with(123)
        with self.assertRaises(restore.CameraError):
            self.commit()
        self.k.WriteProcessMemory.assert_called_once()

    def test_partial_write_consumes_attempt_without_retry(self):
        self.count = 4
        self.assertFalse(self.commit()['full_payload_written'])
        self.assertTrue(self.writer.used)
        with self.assertRaises(restore.CameraError):
            self.commit()
        self.assertEqual(len(self.calls), 1)

    def test_exception_during_write_still_consumes_attempt(self):
        self.k.WriteProcessMemory.side_effect = OSError('simulated API failure')
        with self.assertRaises(OSError):
            self.commit()
        self.assertTrue(self.writer.used)
        with self.assertRaises(restore.CameraError):
            self.commit()
        self.k.WriteProcessMemory.assert_called_once()
        self.k.CloseHandle.assert_called_once_with(123)

    def test_readonly_region_is_never_written(self):
        self.protection = 2
        with self.assertRaises(restore.CameraError):
            self.commit()
        self.k.WriteProcessMemory.assert_not_called()
        self.k.CloseHandle.assert_called_once_with(123)

    def test_process_identity_change_is_never_written(self):
        with patch.object(restore, 'identity', return_value={'pid': 2}):
            with self.assertRaises(restore.CameraError):
                self.commit()
        self.k.WriteProcessMemory.assert_not_called()
        self.k.CloseHandle.assert_called_once_with(123)

    def test_mode_change_after_journal_is_never_written(self):
        self.verify.side_effect = [(capture(), {}, {}), restore.CameraError('mode changed')]
        with self.assertRaises(restore.CameraError):
            self.commit()
        self.journal.assert_called_once()
        self.k.WriteProcessMemory.assert_not_called()
        self.k.CloseHandle.assert_called_once_with(123)

    def test_target_change_after_journal_is_never_written(self):
        self.session.memory.read.side_effect = [b'a'*12, b'b'*12]
        with self.assertRaises(restore.CameraError):
            self.commit()
        self.k.WriteProcessMemory.assert_not_called()
        self.k.CloseHandle.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
