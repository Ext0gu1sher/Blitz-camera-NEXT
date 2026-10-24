"""Offline numerical contracts; these tests make no game-control claims."""

import json
import math
import unittest

from blitzcam.trajectory import Keyframe, Pose, Trajectory, quaternion_slerp


def pose(x=0, y=0, z=0, q=(1, 0, 0, 0), fov=60):
    return Pose((x, y, z), q, fov)


class TrajectoryTests(unittest.TestCase):
    def test_eight_second_export_has_exact_endpoints_and_801_samples(self):
        a, b = pose(), pose(32, 24, 0, (0, 0, 0, 1), 90)
        trajectory = Trajectory([Keyframe(11, a), Keyframe(19, b)], timing="constant_speed")
        samples = trajectory.sample_uniform(100)
        self.assertEqual(len(samples), 801)
        self.assertEqual(samples[0], (11, a))
        self.assertEqual(samples[-1], (19, b))
        self.assertEqual(trajectory.sample(100), b)
        self.assertEqual(trajectory.sample(-100), a)
        for _, sample in samples:
            self.assertAlmostEqual(math.hypot(*sample.quaternion), 1)
        for (_, previous), (_, current) in zip(samples, samples[1:]):
            self.assertAlmostEqual(math.dist(previous.position, current.position), 0.05, delta=4e-6)
        midpoint = trajectory.sample(15)
        self.assertAlmostEqual(midpoint.position[0], 16, delta=2e-6)
        self.assertAlmostEqual(midpoint.horizontal_fov_deg, 75)

    def test_arc_length_reparam_is_spatially_uniform_on_uneven_curved_path(self):
        trajectory = Trajectory([Keyframe(0, pose()), Keyframe(1, pose(1, 2)),
                                 Keyframe(7, pose(8, 3)), Keyframe(8, pose(9, -2))],
                                timing="constant_speed", arc_tolerance=1e-7)
        samples = trajectory.sample_uniform(100)
        step = trajectory.length / 800
        distances = [math.dist(a.position, b.position) for (_, a), (_, b) in zip(samples, samples[1:])]
        # Chords slightly undercount curved arc lengths; at 100 Hz the deviation
        # should remain small. Uniform spline parameter would fail this by far.
        self.assertLess(max(abs(d - step) for d in distances), step * 0.003)
        self.assertGreater(trajectory.length, math.dist((0, 0, 0), (9, -2, 0)))

    def test_keyframe_timestamps_and_global_retiming_are_distinct(self):
        frames = [Keyframe(10, pose()), Keyframe(11, pose(1)), Keyframe(18, pose(9))]
        timed = Trajectory(frames, position_interpolation="linear")
        constant = Trajectory(frames, timing="constant_speed", position_interpolation="linear")
        self.assertEqual(timed.sample(11), frames[1].pose)
        self.assertAlmostEqual(timed.sample(14.5).position[0], 5)
        self.assertAlmostEqual(constant.sample(11).position[0], 9 / 8)
        self.assertAlmostEqual(constant.sample(14).position[0], 4.5)

    def test_arc_length_does_not_depend_on_world_origin(self):
        coordinates = [(0, 0, 0), (2, 5, 1), (12, -3, 8)]
        def make(offset):
            return Trajectory([Keyframe(i * 4, pose(*(v + offset for v in point)))
                               for i, point in enumerate(coordinates)], timing="constant_speed")
        original, translated = make(0), make(1e9)
        self.assertEqual(original.length, translated.length)
        a, b = original.sample(3.71), translated.sample(3.71)
        for x, y in zip(a.position, b.position):
            self.assertAlmostEqual(y - 1e9, x, delta=2e-7)

    def test_ease_in_out_changes_speed_not_shape_or_duration(self):
        frames = [Keyframe(0, pose()), Keyframe(8, pose(8))]
        smooth = Trajectory(frames, timing="constant_speed", easing="ease_in_out")
        self.assertAlmostEqual(smooth.sample(2).position[0], 1.25, delta=2e-6)
        self.assertAlmostEqual(smooth.sample(4).position[0], 4, delta=2e-6)
        self.assertAlmostEqual(smooth.sample(6).position[0], 6.75, delta=2e-6)
        self.assertEqual(smooth.sample(8), frames[-1].pose)
        early = math.dist(smooth.sample(0).position, smooth.sample(0.01).position)
        middle = math.dist(smooth.sample(4).position, smooth.sample(4.01).position)
        self.assertLess(early, middle / 100)
        for mode, expected in [("ease_in", 0.5), ("ease_out", 3.5)]:
            result = Trajectory(frames, easing=mode).sample(2)
            self.assertAlmostEqual(result.position[0], expected, delta=2e-6)

    def test_slerp_antipodal_near_equal_and_shortest_rotation(self):
        self.assertEqual(quaternion_slerp((2, 0, 0, 0), (-3, 0, 0, 0), 0.5), (1, 0, 0, 0))
        near = quaternion_slerp((1, 0, 0, 0), (1, 1e-10, 0, 0), 0.5)
        self.assertAlmostEqual(math.hypot(*near), 1)
        # 350 degrees around Z takes the short route of -10 degrees.
        b = (math.cos(math.radians(175)), 0, 0, math.sin(math.radians(175)))
        mid = quaternion_slerp((1, 0, 0, 0), b, 0.5)
        self.assertAlmostEqual(mid[0], math.cos(math.radians(2.5)))
        self.assertAlmostEqual(mid[3], -math.sin(math.radians(2.5)))

    def test_quaternion_normalizes_extreme_finite_input(self):
        for magnitude in (1e308, 1e-308):
            p = pose(q=(magnitude, magnitude, 0, 0))
            self.assertAlmostEqual(math.hypot(*p.quaternion), 1)

    def test_stationary_path_can_rotate_and_change_fov(self):
        frames = [Keyframe(0, pose()), Keyframe(8, pose(q=(0, 0, 0, 1), fov=100))]
        trajectory = Trajectory(frames, timing="constant_speed")
        self.assertEqual(trajectory.length, 0)
        result = trajectory.sample(4)
        self.assertEqual(result.position, (0, 0, 0))
        self.assertAlmostEqual(result.horizontal_fov_deg, 80)
        self.assertAlmostEqual(result.quaternion[0], math.sqrt(0.5))

    def test_repeated_position_is_a_hold_not_a_spline_loop(self):
        frames = [Keyframe(0, pose()), Keyframe(1, pose(1)), Keyframe(2, pose(1)), Keyframe(3, pose(2))]
        timed = Trajectory(frames)
        self.assertEqual(timed.sample(1.5).position, (1, 0, 0))
        constant = Trajectory(frames, timing="constant_speed")
        self.assertEqual(constant.sample(1.5).position, (1, 0, 0))
        self.assertAlmostEqual(constant.length, 2)
        frames[2] = Keyframe(2, pose(1, q=(0, 0, 0, 1)))
        with self.assertRaisesRegex(ValueError, "原地转向或缩放变化"):
            Trajectory(frames, timing="constant_speed")
        self.assertNotEqual(Trajectory(frames).sample(1.5).quaternion, frames[1].pose.quaternion)

    def test_single_pose_and_nonintegral_sample_duration(self):
        stationary = Trajectory([Keyframe(2, pose(1))])
        self.assertEqual(stationary.sample_uniform(), [(2, pose(1))])
        trajectory = Trajectory([Keyframe(0, pose()), Keyframe(0.025, pose(1))])
        self.assertEqual([t for t, _ in trajectory.sample_uniform(100)], [0, 0.01, 0.02, 0.025])

    def test_uniform_sampling_rejects_unrepresentable_time_intervals(self):
        trajectory = Trajectory([Keyframe(1e15, pose()), Keyframe(1e15 + 1, pose(1))])
        with self.assertRaisesRegex(ValueError, "resolution"):
            trajectory.sample_uniform(10)
        with self.assertRaisesRegex(ValueError, "10,000,000"):
            trajectory.sample_uniform(10_000_001)

    def test_random_access_and_json_roundtrip_are_deterministic(self):
        trajectory = Trajectory([Keyframe(0, pose()), Keyframe(3, pose(1, 2)), Keyframe(8, pose(5, 3, 2))],
                                timing="constant_speed", easing="ease_in_out")
        clone = Trajectory.from_dict(json.loads(json.dumps(trajectory.to_dict(), allow_nan=False)))
        expected = trajectory.sample(2.723)
        for t in (7, 1, 8, -1, 0, 2.723):
            trajectory.sample(t)
        self.assertEqual(trajectory.sample(2.723), expected)
        self.assertEqual(clone.sample(2.723), expected)
        self.assertEqual(clone.to_dict(), trajectory.to_dict())

    def test_invalid_numbers_and_formats_are_rejected(self):
        for invalid in (float("nan"), float("inf"), True, "3"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    pose(invalid)
                with self.assertRaises(ValueError):
                    Keyframe(invalid, pose())
                with self.assertRaises(ValueError):
                    Trajectory([Keyframe(0, pose())]).sample(invalid)
        for fov in (0, -1, 180, 181):
            with self.assertRaises(ValueError):
                pose(fov=fov)
        with self.assertRaises(ValueError):
            pose(q=(0, 0, 0, 0))
        with self.assertRaises(ValueError):
            Pose((1, 2), (1, 0, 0, 0), 60)
        for frames in ([], [Keyframe(1, pose()), Keyframe(1, pose())], [Keyframe(1, pose()), Keyframe(0, pose())]):
            with self.assertRaises(ValueError):
                Trajectory(frames)
        for setting in ({"timing": "wall_clock"}, {"easing": "bounce"}, {"arc_tolerance": 0}, {"position_interpolation": "bad"}):
            with self.assertRaises(ValueError):
                Trajectory([Keyframe(0, pose())], **setting)
        for setting in ({"quaternion_order": "xyzw"}, {"fov_axis": "vertical"}, {"schema_version": 2}):
            data = Trajectory([Keyframe(0, pose())]).to_dict()
            data.update(setting)
            with self.assertRaises(ValueError):
                Trajectory.from_dict(data)
        for rate in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                Trajectory([Keyframe(0, pose())]).sample_uniform(rate)


if __name__ == "__main__":
    unittest.main()
