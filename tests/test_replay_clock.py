import io
from pathlib import Path
import json
import shutil
import struct
import subprocess
import unittest
import warnings
import zipfile

from blitzcam.replay_clock import origin_from_data,replay_origin,MAX_DATA_BYTES
from tests.fixtures.replay_data import header,packet,replay_data


class ReplayClockTests(unittest.TestCase):
    def test_per_replay_origins_preserve_client_float_precision(self):
        for origin in (0,1.8336540460586548,4.18244743347168,15.758445739746094):
            with self.subTest(origin=origin):
                self.assertEqual(origin_from_data(replay_data(origin)),origin)

    def test_markers_inside_payload_are_not_records(self):
        data=header()+packet(0,0,packet(0x11,99))+packet(0x11,4.25)
        self.assertEqual(origin_from_data(data),4.25)

    def test_first_marker_matches_client_initialization(self):
        self.assertEqual(origin_from_data(header()+packet(0x11,4.25)+packet(0x11,99)),4.25)

    def test_missing_truncated_or_unrecognized_stream_fails(self):
        for data in (b'',replay_data()[1:],header()[:-2],header()+packet(0,0,b'payload')[:-1],
                     header()+packet(0xFFFFFFFF,0)+packet(0x11,4.25)):
            with self.subTest(data=data),self.assertRaises(ValueError):origin_from_data(data)

    def test_invalid_origin_and_client_size_cap_fail(self):
        for origin in (-1,float('nan'),float('inf'),3601):
            with self.subTest(origin=origin),self.assertRaises(ValueError):origin_from_data(replay_data(origin))
        data=bytearray(replay_data());struct.pack_into('<I',data,4,MAX_DATA_BYTES)
        with self.assertRaises(ValueError):origin_from_data(data)

    def test_zip_requires_exactly_one_bounded_data_entry(self):
        for entries in ([],[('data.wotreplay',b'bad')],
                        [('data.wotreplay',replay_data()),('data.wotreplay',replay_data())],
                        [('data.wotreplay',replay_data())]):
            with self.subTest(count=len(entries)):
                buffer=io.BytesIO()
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',UserWarning)
                    with zipfile.ZipFile(buffer,'w') as z:
                        for name,data in entries:z.writestr(name,data)
                with zipfile.ZipFile(buffer) as z:
                    if len(entries)==1 and len(entries[0][1])>=14:self.assertEqual(replay_origin(z),4.25)
                    else:
                        with self.assertRaises(ValueError):replay_origin(z)

    @unittest.skipUnless(shutil.which('node'),'Node required for preview clock parity')
    def test_vehicle_clock_conversion_and_camera_time_are_independent(self):
        script=Path(__file__).parent/'fixtures/replay_clock.mjs'
        result=subprocess.run(['node',str(script)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
