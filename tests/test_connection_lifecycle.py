"""Connection cancellation and scan admission without accessing a game."""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from blitzcam.profile import CameraError
from tests.fixtures.game_workstation import Workstation


class ConnectionLifecycleTests(unittest.TestCase):
    def test_connection_failure_is_persisted_with_stage_and_project_context(self):
        with tempfile.TemporaryDirectory() as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
            app=Workstation(Path(tmp)/'project.json')
            try:
                with patch.object(app.backend,'connect',side_effect=CameraError('fixture replay mismatch')):
                    app.connect();app.connect_worker.join(timeout=2)
                events=[json.loads(line) for line in (Path(tmp)/'diagnostics/events.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(events[-1]['event'],'connection.failed')
                self.assertEqual(events[-1]['context']['stage'],'connect')
                self.assertEqual(events[-1]['error']['message'],'fixture replay mismatch')
                self.assertIn('replay_speed',events[-1]['context']['project_timing'])
            finally:
                app.close()

    def test_project_switch_cancels_inflight_connection_to_previous_project(self):
        from blitzcam.project import write_project
        with tempfile.TemporaryDirectory() as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
            app=Workstation(Path(tmp)/'project.json')
            entered,release=threading.Event(),threading.Event()
            session=Mock()
            def connect():
                entered.set()
                if not release.wait(5):raise RuntimeError('scan not released')
                return session
            try:
                other=Path(tmp)/'other.json';write_project(other,app.project)
                with patch.object(app.backend,'connect',side_effect=connect):
                    app.connect();self.assertTrue(entered.wait(2))
                    app.open_project(other)
                    release.set();app.connect_worker.join(timeout=2)
                self.assertEqual(app.connection['state'],'disconnected')
                self.assertIsNone(app.session)
                session.close.assert_called_once()
                session.capture.assert_not_called()
            finally:
                release.set();app.close()

    def test_disconnected_scan_cannot_overlap_a_new_connection(self):
        with tempfile.TemporaryDirectory() as tmp, patch('blitzcam.server.OUTPUT', Path(tmp)):
            app = Workstation(Path(tmp)/'project.json')
            entered, release, closed = threading.Event(), threading.Event(), threading.Event()
            session = Mock()
            session.capture.return_value = {'replay': {'paused': True}}
            session.close.side_effect = closed.set

            def connect():
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test did not release the scan')
                return session

            try:
                with patch.object(app.backend, 'connect', side_effect=connect) as backend, \
                     patch('blitzcam.server.session_timeline', return_value=None):
                    app.connect()
                    self.assertTrue(entered.wait(2))
                    app.disconnect()
                    self.assertEqual(app.connection['state'], 'disconnected')
                    try:
                        for _ in range(8):
                            with self.assertRaisesRegex(CameraError, '连接检查'):
                                app.connect()
                            app.disconnect()
                        self.assertEqual(backend.call_count, 1)
                    finally:
                        release.set()
                        self.assertTrue(closed.wait(2))
                        worker = getattr(app, 'connect_worker', None)
                        if worker:
                            worker.join(timeout=2)
                    session.close.assert_called_once()
                    session.capture.assert_not_called()
                    self.assertIsNone(app.session)
                    self.assertIsNone(app.sample)
                    self.assertEqual(app.connection['state'], 'disconnected')

                # A completed cancellation does not prevent the next connection.
                next_session = Mock()
                with patch.object(app.backend, 'connect', return_value=next_session), \
                     patch('blitzcam.server.session_timeline', return_value=None):
                    app.connect()
                    app.connect_worker.join(timeout=2)
                self.assertIs(app.session, next_session)
                app.disconnect()
                next_session.close.assert_called_once()
                with patch.object(app.stop, 'wait', side_effect=[False, True]):
                    app._poll()
                next_session.capture.assert_called_once()
            finally:
                release.set()
                app.close()
