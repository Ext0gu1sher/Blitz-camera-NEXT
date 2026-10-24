import json
import math
from pathlib import Path
import unittest

from blitzcam.pose import quaternion_from_angles, angles_from_quaternion, pose_from_camera, matrix_from_quaternion
from blitzcam.reader import CameraSession, Objects
from blitzcam.profile import SessionChanged, VFT_PREFERRED
from blitzcam.clocks import TimelineClock


class PoseTests(unittest.TestCase):
    def test_euler_roundtrip_orientation_including_vertical(self):
        for angles in [(0, 0, 0), (130, -35, 22), (-179, 65, -90), (73, 90, 40), (21, -90, -65)]:
            q = quaternion_from_angles(*angles)
            a = angles_from_quaternion(q)
            q2 = quaternion_from_angles(a['yaw_deg'], a['pitch_deg'], a['roll_deg'])
            self.assertAlmostEqual(abs(sum(x*y for x, y in zip(q, q2))), 1, places=12)

    def test_actual_camera_basis_and_fov(self):
        path = Path(__file__).resolve().parents[1]/'research/runtime/readonly-session-evidence.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        cam = data['movement']['last']['free']
        pose = pose_from_camera(cam)
        matrix = matrix_from_quaternion(pose.quaternion)
        for i in range(3):
            self.assertAlmostEqual(-matrix[i][2], cam['base_dir'][i], places=6)
        self.assertAlmostEqual(pose.horizontal_fov_deg, cam['proj_fov'], places=4)

    def test_corrupt_matrix_rejected(self):
        path = Path(__file__).resolve().parents[1]/'research/runtime/readonly-session-evidence.json'
        cam = json.loads(path.read_text(encoding='utf-8'))['movement']['last']['free']
        cam = {k: v for k, v in cam.items() if not isinstance(v, str)}
        cam.update(projection=cam.pop('proj'), view_projection=cam.pop('vp'))
        self.assertLess(CameraSession._quality(cam)['eye_error'], 1e-4)
        cam['position'][0] += 1
        with self.assertRaisesRegex(Exception, '一致'):
            CameraSession._quality(cam)


class ClockTests(unittest.TestCase):
    def test_pause_and_speed_are_source_time_not_wall_time(self):
        c = TimelineClock('replay', 35, session_id='A')
        self.assertEqual(c.sample(35, 'A'), 0)
        self.assertEqual(c.sample(35, 'A'), 0)
        self.assertEqual(c.sample(37, 'A'), 2)
        independent = TimelineClock('capture', 100)
        self.assertEqual(independent.sample(108), 8)

    def test_restart_or_backwards_requires_rearm(self):
        c = TimelineClock('replay', 35, session_id='A')
        c.sample(36, 'A')
        with self.assertRaises(ValueError): c.sample(35, 'A')
        with self.assertRaises(ValueError): c.sample(37, 'A')
        c = TimelineClock('replay', 35, session_id='A')
        with self.assertRaises(ValueError): c.sample(35, 'B')


class GuardTests(unittest.TestCase):
    def test_stale_or_non_replay_chain_is_rejected(self):
        class Memory:
            class Info:
                base = 0x590000
            info = Info()
            values = {}
            def u32(self, p): return self.values.get(p, 0)
        memory = Memory(); session = CameraSession(memory)
        session.objects = Objects(*range(0x1000, 0xA000, 0x1000))
        with self.assertRaises(SessionChanged): session._guard()

    def test_full_positive_chain_then_context_switch_rejected(self):
        class Memory:
            class Info: base = 0x590000
            info = Info()
            values = {}
            def u32(self, p): return self.values.get(p, 0)
        memory = Memory(); session = CameraSession(memory)
        a = Objects(*range(0x1000, 0xA000, 0x1000)); session.objects = a
        type_fields = {'context':'AvatarContextReplay','player':'ReplayPlayer','replay_controller':'ReplayCameraController',
                       'game_camera':'GameCamera','free_camera':'FreeCamera','render':'RenderSystem','scene':'GameScene',
                       'scene_controller':'GameSceneController','spectator_controller':'SpectatorCameraController'}
        for field, kind in type_fields.items(): memory.values[getattr(a,field)] = session.vft[kind]
        from blitzcam.profile import REPLAY_SECONDARY_VFT
        for address, value in [(a.context+0x1b0,a.player),(a.player+0xc,session.live(REPLAY_SECONDARY_VFT)),
             (a.replay_controller+0x28,a.game_camera),(a.game_camera+0x5b8,a.replay_controller),
             (a.scene+0xac,a.render),(a.scene+0x128,a.free_camera),(a.scene+0x12c,a.free_camera),
             (a.render+0xb0,a.free_camera),(a.render+0xb4,a.free_camera),
             (a.scene_controller+0x1c,a.scene),(a.scene_controller+0x20,a.context),
             (a.scene_controller+0x8c,a.game_camera),(a.scene_controller+0x94,a.free_camera),
             (a.scene_controller+0x9c,a.replay_controller),(a.spectator_controller+0xc,a.free_camera)]:
            memory.values[address] = value
        session._guard()
        memory.values[a.scene_controller+0x20] = 0
        with self.assertRaises(SessionChanged): session._guard()


if __name__ == '__main__': unittest.main()
