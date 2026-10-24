import json
import shutil
import subprocess
import unittest
from pathlib import Path

from blitzcam.channels import ScalarTrack

FIXTURE = Path(__file__).parent / 'fixtures' / 'curve_parity.mjs'

CASES = [
    {'rows': [{'time_sec': 0, 'value': 0, 'ease': [.42, 0, .58, 1]}, {'time_sec': 4, 'value': 10}],
     'smooth': True, 'easing': 'ease_in'},
    {'rows': [{'time_sec': 0, 'value': -3}, {'time_sec': 2, 'value': 7, 'ease': [.16, 1, .3, 1]},
              {'time_sec': 6, 'value': 7, 'ease': [0, 0, 1, 1]}, {'time_sec': 9, 'value': -12}],
     'smooth': True, 'easing': 'linear'},
    {'rows': [{'time_sec': 1, 'value': 5, 'ease': [.7, 0, .84, 0]}, {'time_sec': 3.5, 'value': 60}],
     'smooth': False, 'easing': 'ease_in_out'},
]


class CurveParityTests(unittest.TestCase):
    def test_scalar_track_parity_with_js(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node unavailable')
        times = [i / 97 * 9 for i in range(200)]
        cases = [dict(c, times=times) for c in CASES]
        proc = subprocess.run([node, str(FIXTURE)], input=json.dumps(cases),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        for case, values in zip(CASES, got):
            track = ScalarTrack(case['rows'], 'x', case['smooth'], case['easing'])
            for t, js, py in zip(times, values, (track.sample(t) for t in times)):
                self.assertAlmostEqual(js, py, places=9, msg=f't={t}')


if __name__ == '__main__':
    unittest.main()
