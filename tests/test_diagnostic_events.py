import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from blitzcam.diagnostics import record_event
from blitzcam.server import make_handler
from tests.fixtures.game_workstation import Workstation


class DiagnosticEventTests(unittest.TestCase):
    def test_failed_play_request_is_saved_even_without_a_playback_run(self):
        with tempfile.TemporaryDirectory() as folder, patch('blitzcam.server.OUTPUT',Path(folder)):
            root=Path(folder);app=Workstation(root/'project.json')
            app.stop.set();app.poller.join()
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/playback/start',data=b'{}',headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request,timeout=5)
                self.assertEqual(raised.exception.code,400)
                error=json.load(raised.exception)['error'];raised.exception.close()
                record=json.loads((root/'diagnostics/events.jsonl').read_text(encoding='utf-8'))
                self.assertEqual(record['event'],'request.failed')
                self.assertEqual(record['context']['path'],'/api/playback/start')
                self.assertEqual(record['error']['message'],error)
                self.assertIn('replay_timeline',record['context']['project_timing'])
                self.assertFalse((root/'playback-runs').exists())
            finally:
                server.shutdown();server.server_close();thread.join();app.close()

    def test_rotation_bounds_disk_usage_and_keeps_recent_errors(self):
        with tempfile.TemporaryDirectory() as folder, patch('blitzcam.diagnostics.MAX_BYTES',600):
            for index in range(30):
                self.assertTrue(record_event(folder,'failure',context={'index':index,'message':'a'*60}))
            files=list((Path(folder)/'diagnostics').glob('events*.jsonl'))
            self.assertEqual(len(files),4)
            self.assertTrue(all(path.stat().st_size<=600 for path in files))
            current=[json.loads(line) for line in (Path(folder)/'diagnostics/events.jsonl').read_text().splitlines()]
            self.assertEqual(current[-1]['context']['index'],29)

    def test_unwritable_destination_does_not_replace_the_original_error(self):
        with tempfile.TemporaryDirectory() as folder:
            occupied=Path(folder)/'file';occupied.write_text('keep')
            self.assertFalse(record_event(occupied,'failure',error=ValueError('original')))
            self.assertEqual(occupied.read_text(),'keep')
