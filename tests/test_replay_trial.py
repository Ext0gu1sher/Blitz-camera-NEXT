import ctypes as C
import struct
from types import SimpleNamespace
import unittest

from blitzcam.profile import CameraError, PROFILE_1121
from blitzcam.replay_trial import configuration, signal_callback, summarize


class Memory:
    def __init__(self):
        self.data = {}

    def put(self, address, *values):
        for i, value in enumerate(struct.pack('<'+'I'*len(values), *values)):
            self.data[address+i] = value

    def read(self, address, count):
        return bytes(self.data.get(address+i, 0) for i in range(count))

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]


def fixture():
    mem = Memory()
    engine, head, node, player = 0x10000, 0x20000, 0x30000, 0x40000
    mem.put(0x46909a0, engine)
    mem.put(engine+0x74, head, 1)
    mem.put(head, node, node)
    mem.put(node, head, head)
    mem.put(node+0x20, 0x37c4674)
    mem.put(node+0x28, player)
    mem.put(node+0x30, 0x140d100, 0)
    mem.put(0x37c4674+8, 0x12f8310)
    return SimpleNamespace(profile=PROFILE_1121, memory=mem, live=lambda x:x,
                           objects=SimpleNamespace(player=player)), node


class ReplayCallbackTests(unittest.TestCase):
    def test_clock_configuration_preserves_the_selected_camera_controller(self):
        for kind in ('CinemaCameraController', 'SpectatorCameraController'):
            with self.subTest(kind=kind):
                session, _ = fixture()
                session.info = SimpleNamespace(base=PROFILE_1121.preferred_base)
                session.vft = dict(PROFILE_1121.vtables)
                session.controller_kind = kind
                for field, address in (('context', 0x50000), ('scene', 0x60000),
                                       ('render', 0x70000), ('free_camera', 0x80000),
                                       ('spectator_controller', 0x90000), ('scene_controller', 0xb0000)):
                    setattr(session.objects, field, address)
                mem = session.memory
                mem.put(0x60000, session.vft['GameScene'])
                mem.put(0x7008c, 0xa0000)
                mem.put(0xa0000, 0x375b100)
                mem.put(session.vft['GameScene'] + 0x54, 0x7c46f0)
                mem.put(0x375b100 + 12, 0xc7b2c0)
                mem.put(0x602a4, 1, 0)
                sample = {'replay': {'paused': True, 'raw_time': 32, 'origin': 9, 'rate': 1}}
                cfg, _ = configuration(session, sample, .25, 1)
                self.assertEqual(cfg.spectator_vft, session.vft[kind])
                self.assertEqual(cfg.spectator, session.objects.spectator_controller)

    def test_only_registered_exact_player_callback_is_accepted(self):
        s, node = fixture()
        self.assertEqual(signal_callback(s)['functor'], node+0x20)

    def test_existing_foreign_hook_is_rejected(self):
        s, node = fixture()
        s.memory.put(node+0x30, 0xdead0000)
        with self.assertRaises(CameraError):
            signal_callback(s)

    def test_other_player_is_rejected(self):
        s, node = fixture()
        s.memory.put(node+0x28, 0x50000)
        with self.assertRaises(CameraError):
            signal_callback(s)

    def test_broken_back_link_is_rejected(self):
        s, node = fixture()
        s.memory.put(node+4, 0)
        with self.assertRaises(CameraError):
            signal_callback(s)

    def test_unbounded_or_inconsistent_count_is_rejected(self):
        for count in (0, 2, 65):
            s, _ = fixture()
            s.memory.put(0x10078, count)
            with self.assertRaises(CameraError):
                signal_callback(s)

    def test_thunk_abi_mismatch_is_rejected(self):
        s, _ = fixture()
        s.memory.put(0x37c4674+8, 0)
        with self.assertRaises(CameraError):
            signal_callback(s)

    def test_summary_checks_client_float_arithmetic(self):
        f32 = lambda x:C.c_float(x).value
        a = dict(kind=1, tick=1, raw=300., paused=0, dt=f32(1/60), rate=.25,
                 stage=2, thread=1, qpc=10, scene_rate=.25, scale_enabled=1,
                 position=[0,0,0], fov=60)
        b = dict(a, kind=2, qpc=11, raw=f32(a['raw']+f32(a['dt']*a['rate'])))
        result = summarize([a,b], {'frequency':1000,'sum_dt':a['dt'],'writes':2})
        self.assertEqual(result['max_tick_float_error'], 0)
        b['raw'] += .01
        self.assertGreater(summarize([a,b], {'frequency':1000,'sum_dt':a['dt'],'writes':2})['max_tick_float_error'], .009)


if __name__ == '__main__':
    unittest.main()
