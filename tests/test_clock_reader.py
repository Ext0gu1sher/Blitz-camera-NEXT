import json
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest

from blitzcam.reader import CameraSession, Objects
from blitzcam.profile import IncoherentSample, SessionChanged


class ReaderClockTests(unittest.TestCase):
    def player_bytes(self):
        data = bytearray(0x10C)
        data[0x11] = data[0x12] = data[0x35] = 1
        struct.pack_into('<f', data, 0x14, 1)
        struct.pack_into('<f', data, 0x18, 44.955482482910156)
        struct.pack_into('<f', data, 0x64, 9.803201675415039)
        struct.pack_into('<f', data, 0x28, 42.06603240966797)
        struct.pack_into('<I', data, 0xA0, 0x12345678)
        struct.pack_into('<I', data, 0x108, 0xFFFFFFFF)
        return data

    def session(self, data):
        memory = SimpleNamespace(info=SimpleNamespace(base=0x590000), read=lambda *_: data)
        session = CameraSession(memory)
        session.objects = Objects(*range(0x1000, 0xA000, 0x1000))
        return session

    def test_residual_warp_target_does_not_mean_active_seek(self):
        clock = self.session(self.player_bytes())._clock()
        self.assertAlmostEqual(clock['time'], 35.15228080749512)
        self.assertGreater(clock['warp_target'], 0)
        self.assertFalse(clock['seek_active'])

    def test_inactive_queued_executing_or_waiting_replay_rejected(self):
        for offset, value in [(0x11, 0), (0x35, 0), (0x2D, 1), (0x2E, 1), (0x108, 0)]:
            with self.subTest(offset=offset):
                data = self.player_bytes(); data[offset] = value
                with self.assertRaises(SessionChanged): self.session(data)._clock()
        data = self.player_bytes(); struct.pack_into('<I', data, 0xA0, 0)
        with self.assertRaises(SessionChanged): self.session(data)._clock()

    def test_clock_jump_and_origin_change_stop_session(self):
        a = dict(time=35., origin=10., rate=1., paused=False)
        for changes in [dict(time=5.), dict(time=35.1, origin=11.), dict(time=40.)]:
            with self.subTest(changes=changes):
                with self.assertRaises(SessionChanged):
                    CameraSession._clock_interval(a, {**a, **changes}, .01)

    def test_rate_or_pause_change_is_transient(self):
        a = dict(time=35., origin=10., rate=1., paused=False)
        for changes in [dict(rate=2.), dict(paused=True)]:
            with self.assertRaises(IncoherentSample):
                CameraSession._clock_interval(a, {**a, **changes}, .01)
        CameraSession._clock_interval(a, {**a, 'time': 35.02}, .02)
        CameraSession._clock_interval(a, {**a, 'time': 35.4, 'rate': 2.}, .3, same_capture=False)

    def fake_capture(self, clocks):
        path = Path(__file__).resolve().parents[1]/'research/runtime/readonly-session-evidence.json'
        cam = json.loads(path.read_text(encoding='utf-8'))['movement']['last']['free']
        cam = {k: v for k, v in cam.items() if not isinstance(v, str)}
        cam.update(projection=cam.pop('proj'), view_projection=cam.pop('vp'))
        s = self.session(self.player_bytes())
        s.info = SimpleNamespace(base=0x590000, pid=1, path=Path('fixture.exe'))
        s._guard = lambda: None
        s._camera = lambda: cam
        s._native_controller = lambda: {}
        stream = iter(clocks); s._clock = lambda: next(stream)
        return s

    def test_full_capture_rejects_playing_backward_race(self):
        a = dict(time=35., origin=10., rate=1., paused=False)
        session = self.fake_capture([a, {**a, 'time': 5.}])
        with self.assertRaises(SessionChanged): session.capture(require_paused=False)

    def test_jump_between_two_internally_stable_captures_is_rejected(self):
        a = dict(time=35., origin=10., rate=1., paused=True)
        session = self.fake_capture([a, a, {**a, 'time': 5.}])
        snapshot = session.capture()
        self.assertFalse(snapshot['quality']['active_root_verified'])
        self.assertFalse(snapshot['quality']['frame_synchronized'])
        with self.assertRaises(SessionChanged): session.capture()


if __name__ == '__main__': unittest.main()
