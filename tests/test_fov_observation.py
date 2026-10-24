"""Synthetic snapshots: fail closed around animation and task lifecycle gaps."""
import importlib.util
import copy
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location('fov_observation',
    Path(__file__).resolve().parents[1]/'research/scripts/probe_pose_fov_1121_readonly.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class Memory:
    def __init__(self):
        self.blocks = {}

    def put(self, p, size, values):
        b = bytearray(size)
        for off, value in values.items():
            struct.pack_into('<I', b, off, value)
        self.blocks[p] = b

    def read(self, p, n):
        for start, b in self.blocks.items():
            if start <= p and p+n <= start+len(b):
                return bytes(b[p-start:p-start+n])
        raise probe.CameraError('Unreadable synthetic span')

    def u32(self, p):
        return probe.u32(self.read(p, 4))

    def edit(self, p, offset, value):
        struct.pack_into('<I', self.blocks[p], offset, value)


def fixture():
    m = Memory()
    m.put(0x4690a30, 4, {0: 0x10000})
    m.put(0x10000, 0x48, {0: 0x11000, 0x44: 0x12000})
    m.put(0x11000, 0xa0, {0: 0x372a4c4, 0xc: 12, 0x14: 12, 0x58: 8})
    m.put(0x12000, 12, {4: 0x15000, 8: 1})
    m.put(0x13000, 4, {0: 0x372adb4})
    m.put(0x14000, 0x138, {0x134: 0x13000})
    m.put(0x15000, 8, {0: 0x15100, 4: 0x15100})
    m.put(0x15100, 0x14, {0: 0x15000, 4: 0x15000, 0x10: 0x16000})
    m.put(0x16000, 0x18, {0: 0x17000, 4: 0x17000, 8: 0x17020,
                                  0xc: 0x17100, 0x10: 0x17100, 0x14: 0x17120})
    m.put(0x17000, 0x20, {})
    m.put(0x17100, 0x20, {})
    s = SimpleNamespace(memory=m, live=lambda va: va,
                        objects=SimpleNamespace(spectator_controller=0x14000))
    return m, probe.AnimationProbe(s)


def add_animation(m, owner=0x13000, flags=1, update=True, float_binding=False):
    m.edit(0x16000, 4, 0x17004)
    m.edit(0x17000, 0, 0x18000)
    if update:
        m.edit(0x16000, 0x10, 0x17104)
        m.edit(0x17100, 0, 0x18000)
    if float_binding:
        m.put(0x18000, 0xa8, {0: 0x375e610, 0x18: flags, 0x2c: owner,
            0x74: 0x18050, 0x9c: 0x18078, 0x50: 0x380c544, 0x54: 0x14114,
            0x78: 0x380c560, 0x7c: 0x14114})
    else:
        m.put(0x18000, 0x50, {0: 0x222222, 0x18: flags, 0x2c: owner})


class FovObservationTests(unittest.TestCase):
    def test_empty_is_observational_only(self):
        _, p = fixture()
        r = p.observe()
        self.assertTrue(r['observed_quiescent'])
        self.assertFalse(r['write_ready'])
        self.assertFalse(r['frame_synchronized'])

    def test_stopped_registered_animation_is_busy_without_update_membership(self):
        m, p = fixture()
        add_animation(m, flags=0x10, update=False)
        self.assertFalse(p.observe()['observed_quiescent'])

    def test_unrelated_animation_does_not_block(self):
        m, p = fixture()
        add_animation(m, owner=0x99999)
        self.assertTrue(p.observe()['observed_quiescent'])

    def test_cleared_owner_still_detected_via_float_setter(self):
        m, p = fixture()
        add_animation(m, owner=0, flags=8, float_binding=True)
        r = p.observe()
        self.assertFalse(r['observed_quiescent'])
        self.assertTrue(r['relevant'][0]['float_animation']['binds_current_fov'])

    def test_waiting_chain_is_busy(self):
        m, p = fixture()
        add_animation(m, owner=0x99999)
        m.edit(0x18000, 0x30, 0x19000)
        m.put(0x19000, 0x50, {0: 0x222222, 0x2c: 0x13000})
        self.assertFalse(p.observe()['observed_quiescent'])

    def test_queued_job_is_busy(self):
        m, p = fixture()
        m.edit(0x11000, 0x60, 1)
        self.assertFalse(p.observe()['observed_quiescent'])

    def test_popped_job_still_running_is_busy(self):
        m, p = fixture()
        m.edit(0x11000, 0x68, 12)
        m.edit(0x11000, 0x9c, 0x19999)
        self.assertFalse(p.observe()['observed_quiescent'])

    def test_reserved_not_yet_enqueued_is_busy(self):
        m, p = fixture()
        m.edit(0x11000, 0xc, 13)
        self.assertFalse(p.observe()['observed_quiescent'])

    def test_disabled_job_manager_does_not_become_idle(self):
        m, p = fixture()
        m.edit(0x11000, 0xc, 0)
        m.edit(0x11000, 0x14, 0)
        self.assertFalse(p.observe()['observed_quiescent'])

    def test_corrupt_queue_is_unknown(self):
        m, p = fixture()
        m.edit(0x11000, 0x58, 3)
        with self.assertRaises(probe.IncoherentSample):
            p.observe()

    def test_corrupt_list_does_not_become_idle(self):
        m, p = fixture()
        m.edit(0x15100, 0, 0x15100)
        with self.assertRaises(probe.IncoherentSample):
            p.observe()

    def test_unreadable_chain_does_not_become_idle(self):
        m, p = fixture()
        add_animation(m, owner=0x99999)
        m.edit(0x18000, 0x30, 0x777770)
        with self.assertRaises(probe.CameraError):
            p.observe()

    def test_cyclic_chain_does_not_become_idle(self):
        m, p = fixture()
        add_animation(m, owner=0x99999)
        m.edit(0x18000, 0x30, 0x18000)
        with self.assertRaises(probe.IncoherentSample):
            p.observe()

    def test_changed_owner_stops(self):
        m, p = fixture()
        m.edit(0x14000, 0x134, 0x88888)
        with self.assertRaises(probe.SessionChanged):
            p.observe()

    def test_capture_bracket_ignores_progress_but_not_new_animation(self):
        m, p = fixture()
        before = p.observe()
        add_animation(m, float_binding=True)
        during = p.observe()
        later = copy.deepcopy(during)
        later['relevant'][0]['float_animation']['progress'] = .5
        later['relevant'][0]['float_animation']['elapsed'] = .25
        later['relevant'][0]['float_animation']['raw_hex'] = 'changed progress bytes'
        self.assertNotEqual(probe.structural_signature(before), probe.structural_signature(during))
        self.assertEqual(probe.structural_signature(during), probe.structural_signature(later))


if __name__ == '__main__':
    unittest.main()
