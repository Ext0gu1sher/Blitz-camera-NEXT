"""Recording tests use only a fake session/clock and temporary local outputs."""

import json
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from blitzcam.profile import CameraError, IncoherentSample, SessionChanged
from blitzcam.recording import record_session


class FakeClock:
    def __init__(self):
        self.time = 0.0
        self.sleeps = []

    def __call__(self):
        return self.time

    def sleep(self, seconds):
        if seconds <= 0:
            raise AssertionError("scheduler must only sleep for positive intervals")
        self.sleeps.append(seconds)
        self.time += seconds


class FakeSession:
    def __init__(self, clock, events):
        self.clock, self.events = clock, iter(events)
        self.attempt_times = []

    def capture(self, require_paused=True):
        if require_paused:
            raise AssertionError("recording should permit replay playback")
        self.attempt_times.append(self.clock())
        event = next(self.events)
        if isinstance(event, BaseException):
            raise event
        return event() if callable(event) else event


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "record.jsonl"
        self.clock = FakeClock()

    def run_recording(self, events, seconds=0.4, hz=10):
        session = FakeSession(self.clock, events)
        summary = record_session(session, self.path, seconds, hz,
                                 clock=self.clock, sleep=self.clock.sleep)
        stored = json.loads(Path(summary["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(summary, stored)
        samples = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        return summary, samples, session

    def test_transient_drops_keep_schedule_and_preserve_reasons(self):
        summary, samples, session = self.run_recording([
            IncoherentSample("相机正在更新"), {"sample": 1},
            IncoherentSample("矩阵尚未一致"), {"sample": 2},
        ])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual((summary["attempt_count"], summary["valid_sample_count"], summary["dropped_sample_count"]), (4, 2, 2))
        self.assertEqual(summary["drop_reasons"], {"相机正在更新": 1, "矩阵尚未一致": 1})
        self.assertEqual(samples, [{"sample": 1}, {"sample": 2}])
        for actual, expected in zip(session.attempt_times, [0, 0.1, 0.2, 0.3]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(summary["elapsed_seconds"], 0.4)
        self.assertFalse(summary["frame_synchronized"])

    def test_session_change_stops_without_consuming_later_events(self):
        summary, samples, session = self.run_recording([
            {"sample": 1}, SessionChanged("回放已重建"), {"sample": 2},
        ])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure"], {"type": "SessionChanged", "message": "回放已重建"})
        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["dropped_sample_count"], 0)
        self.assertEqual(samples, [{"sample": 1}])
        self.assertEqual(len(session.attempt_times), 2)

    def test_other_camera_error_is_not_a_transient_drop(self):
        summary, samples, session = self.run_recording([CameraError("读取权限失效"), {"sample": 1}])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure"]["type"], "CameraError")
        self.assertEqual(summary["attempt_count"], 1)
        self.assertEqual(summary["dropped_sample_count"], 0)
        self.assertEqual(samples, [])
        self.assertEqual(len(session.attempt_times), 1)

    def test_serialization_failure_is_fatal_and_does_not_write_nan(self):
        summary, samples, _ = self.run_recording([{"invalid": float("nan")}, {"sample": 2}])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure"]["type"], "ValueError")
        self.assertEqual(summary["attempt_count"], 1)
        self.assertEqual(summary["dropped_sample_count"], 0)
        self.assertEqual(samples, [])

    def test_keyboard_interrupt_preserves_prefix_and_summary(self):
        summary, samples, _ = self.run_recording([{ "sample": 1 }, KeyboardInterrupt(), {"sample": 2}])
        self.assertEqual(summary["status"], "interrupted")
        self.assertEqual(summary["failure"]["type"], "KeyboardInterrupt")
        self.assertEqual(summary["attempt_count"], 2)
        self.assertEqual(summary["valid_sample_count"], 1)
        self.assertEqual(samples, [{"sample": 1}])

    def test_all_transient_reads_fail_cleanly_without_busy_loop(self):
        summary, samples, session = self.run_recording([IncoherentSample("更新中") for _ in range(5)], seconds=0.25, hz=20)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failure"]["type"], "NoValidSamples")
        self.assertEqual((summary["attempt_count"], summary["dropped_sample_count"]), (5, 5))
        self.assertEqual(samples, [])
        self.assertAlmostEqual(self.clock(), 0.25)
        self.assertGreaterEqual(len(self.clock.sleeps), 5)
        self.assertEqual(len(session.attempt_times), 5)

    def test_slow_read_skips_expired_slots_instead_of_catching_up(self):
        def slow_snapshot():
            self.clock.time += 0.25
            return {"sample": 1}
        summary, samples, session = self.run_recording([slow_snapshot, {"sample": 2}, {"sample": 3}], seconds=0.5)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["missed_schedule_slots"], 2)
        self.assertEqual(len(samples), 3)
        for actual, expected in zip(session.attempt_times, [0, 0.3, 0.4]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(summary["elapsed_seconds"], 0.5)

    def test_slow_read_past_deadline_counts_only_window_slots(self):
        def slow_snapshot():
            self.clock.time += 5
            return {"sample": 1}
        summary, samples, session = self.run_recording([slow_snapshot], seconds=0.5)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["missed_schedule_slots"], 4)
        self.assertEqual(summary["attempt_count"], 1)
        self.assertEqual(len(samples), 1)
        self.assertEqual(session.attempt_times, [0])

    def test_interrupt_while_waiting_preserves_summary(self):
        session = FakeSession(self.clock, [{"sample": 1}])
        def interrupt_sleep(_seconds):
            raise KeyboardInterrupt()
        summary = record_session(session, self.path, 1, 10,
                                 clock=self.clock, sleep=interrupt_sleep)
        self.assertEqual(summary["status"], "interrupted")
        self.assertEqual(summary["attempt_count"], 1)
        self.assertEqual(summary["valid_sample_count"], 1)
        self.assertTrue(Path(summary["summary_path"]).is_file())

    def test_existing_recording_is_never_replaced(self):
        self.path.write_text("previous recording\n", encoding="utf-8")
        session = FakeSession(self.clock, [{"sample": 1}])
        with self.assertRaises(FileExistsError):
            record_session(session, self.path, 1, 10, clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "previous recording\n")
        self.assertEqual(session.attempt_times, [])
        self.assertFalse(self.path.with_name(self.path.name + ".summary.json").exists())

    def test_invalid_schedule_does_not_create_output(self):
        session = FakeSession(self.clock, [])
        for seconds, hz in [(0, 10), (1, 0), (float("nan"), 10), (1, float("inf")), (True, 10)]:
            with self.subTest(seconds=seconds, hz=hz):
                with self.assertRaises(ValueError):
                    record_session(session, self.path, seconds, hz, clock=self.clock, sleep=self.clock.sleep)
        self.assertFalse(self.path.exists())

    def test_cli_status_codes_do_not_label_failed_recording_as_success(self):
        from blitzcam.__main__ import main
        for status, expected in [("completed", 0), ("failed", 2), ("interrupted", 130)]:
            with self.subTest(status=status):
                result = {"status": status, "valid_sample_count": 1, "attempt_count": 2,
                          "dropped_sample_count": 1, "summary_path": str(self.path) + ".summary.json",
                          "failure": None if status == "completed" else {"type": "Example", "message": "stopped"}}
                context = MagicMock()
                with patch("blitzcam.__main__.CameraSession.connect", return_value=context), \
                     patch("blitzcam.__main__.record_session", return_value=result), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["record", "--out", str(self.path)]), expected)
                context.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
