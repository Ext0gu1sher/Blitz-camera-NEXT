"""Offline capture persistence tests; the game session is a mock."""

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from blitzcam.project import validate_project
from blitzcam.server import Workstation, make_handler


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patcher = patch('blitzcam.server.OUTPUT', Path(self.tmp.name))
        self.patcher.start()
        self.path = Path(self.tmp.name) / "project.json"
        self.app = Workstation(self.path)
        # Do not let background telemetry interfere with the capture call count.
        self.app.stop.set()
        self.app.poller.join()
        self.app.set_project(validate_project({"keyframes": [
            {"time_sec": 0, "position": [0, 0, 0], "quaternion": [1, 0, 0, 0], "horizontal_fov_deg": 60},
            {"time_sec": 8, "position": [8, 0, 0], "quaternion": [1, 0, 0, 0], "horizontal_fov_deg": 60},
        ]}))
        self.original = self.app.project.to_dict()
        self.original_bytes = self.path.read_bytes()
        self.snapshot = {"camera": {"position": [1, 2, 3], "quaternion": [1, 0, 0, 0],
                                    "horizontal_fov_deg": 75}, "replay": {"time": 42, "paused": True}}
        self.session = Mock()
        self.session.capture.return_value = self.snapshot
        self.app.session = self.session
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}/api/capture"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.app.close()
        self.patcher.stop()
        self.tmp.cleanup()

    def post(self, data):
        request = urllib.request.Request(self.url, data=json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def assert_untouched(self):
        self.assertEqual(self.app.project.to_dict(), self.original)
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertFalse((self.path.parent / "captures").exists())
        self.assertIsNone(self.app.sample)
        self.session.capture.assert_not_called()

    def test_duplicate_time_rejected_without_any_capture_or_project_write(self):
        for body in ({"time_sec": 0}, {"time_sec": 0, "replace_existing": False}):
            with self.subTest(body=body):
                status, result = self.post(body)
                self.assertEqual(status, 400)
                self.assertIn("该时刻已有属性关键帧", result["error"])
                self.assert_untouched()

    def test_explicit_true_replaces_only_the_matching_frame_and_saves_snapshot(self):
        status, result = self.post({"time_sec": 0, "replace_existing": True})
        self.assertEqual((status, result), (200, {"ok": True}))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["keyframes"]), 2)
        self.assertEqual(saved["keyframes"][0], {"time_sec": 0, **self.snapshot["camera"]})
        self.assertEqual(saved["keyframes"][1], self.original["keyframes"][1])
        captures = list((self.path.parent / "captures").glob("*.json"))
        self.assertEqual(len(captures), 1)
        self.assertEqual(json.loads(captures[0].read_text(encoding="utf-8")), self.snapshot)
        self.session.capture.assert_called_once_with(require_paused=True)

    def test_truthy_values_are_not_replacement_authorization(self):
        for flag in (1, "true", [True], {"enabled": True}, None):
            with self.subTest(flag=flag):
                status, result = self.post({"time_sec": 0, "replace_existing": flag})
                self.assertEqual(status, 400)
                self.assertIn("布尔值", result["error"])
                self.assert_untouched()

    def test_new_time_appends_without_replacement_permission(self):
        status, _ = self.post({"time_sec": 4})
        self.assertEqual(status, 200)
        frames = self.app.project.to_dict()["keyframes"]
        self.assertEqual([f["time_sec"] for f in frames], [0, 4, 8])
        self.assertEqual(frames[0], self.original["keyframes"][0])
        self.assertEqual(frames[2], self.original["keyframes"][1])
        self.assertEqual(frames[1], {"time_sec": 4, **self.snapshot["camera"]})
        self.session.capture.assert_called_once_with(require_paused=True)


if __name__ == "__main__":
    unittest.main()
