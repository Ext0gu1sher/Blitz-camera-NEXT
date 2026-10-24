"""Read archived NewReplayFile objects; no live processes or game writes."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from test_cinema_controller import controller_fixture
from blitzcam.reader import CameraSession
from blitzcam.replay_launcher import ReplaySourceUnavailable
from blitzcam.replay_source import runtime_replay_source
from blitzcam.replay_timeline import file_timeline, replay_matches, session_timeline


def put(memory, address, data):
    for base, original in memory.blocks.items():
        if base <= address and address + len(data) <= base + len(original):
            block = bytearray(original)
            block[address-base:address-base+len(data)] = data
            memory.blocks[base] = bytes(block)
            return
    raise AssertionError('Fixture write outside archived blocks')


def source_fixture(path, kind='CinemaCameraController'):
    archive = json.loads((Path(__file__).parent/'fixtures/1121-replay-source.json').read_text(encoding='utf-8'))
    memory = controller_fixture(kind, base=int(archive['module_base'], 16))
    memory.blocks.update({int(p,16):bytes.fromhex(b) for p,b in archive['blocks'].items()})
    session = CameraSession(memory)
    session.discover()
    source, holder, metadata = (int(archive[k],16) for k in ('source','holder','metadata'))
    put(memory, session.objects.player + 0xE8, struct.pack('<II', source, holder))
    put(memory, session.objects.player + 0xA0, struct.pack('<I', metadata))
    encoded = str(path).encode('utf-8')
    pointer = 0x60000000
    memory.blocks[pointer] = encoded + b'\0'
    put(memory, source, struct.pack('<4I', pointer,0,0,0) + struct.pack('<II',len(encoded),len(encoded)|15))
    return session


class RuntimeReplaySourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root/'手动打开 A.wotbreplay'
        with zipfile.ZipFile(self.path,'w') as archive:
            archive.writestr('meta.json',json.dumps({'version':'11.21.0','battleDuration':253.12938}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_file_is_identified_for_both_camera_types_without_arguments(self):
        for kind in ('CinemaCameraController','SpectatorCameraController'):
            with self.subTest(kind=kind):
                session = source_fixture(self.path, kind)
                with patch('blitzcam.replay_map.launch_replay_path', side_effect=AssertionError('argv must not be needed')):
                    actual = session_timeline(session)
                self.assertEqual(actual['replay_file'],str(self.path.resolve()))
                self.assertEqual(actual['verification'],'runtime_replay')
                self.assertTrue(replay_matches(file_timeline(self.path),actual))
                self.assertEqual(session.capture()['native_controller']['kind'],kind)

    def test_runtime_file_wins_over_a_different_stale_startup_argument(self):
        other = self.root/'old.wotbreplay'
        other.write_bytes(b'previous launch')
        with patch('blitzcam.replay_map.launch_replay_path', return_value=other) as arguments:
            actual = session_timeline(source_fixture(self.path))
        arguments.assert_not_called()
        self.assertFalse(replay_matches({'replay_file':str(other)},actual))

    def test_corrupt_type_or_links_do_not_fall_back_to_launch_arguments(self):
        for change in ('owner_type','owner_link','file_type','file_link','version','archive_key'):
            with self.subTest(change=change):
                session = source_fixture(self.path)
                old = runtime_replay_source(session)
                targets = {'owner_type':old.holder, 'owner_link':session.objects.player+0xEC,
                           'file_type':old.metadata, 'file_link':old.source+0x4C,
                           'version':old.metadata+0xC}
                if change == 'archive_key':
                    pointer = session.memory.u32(old.metadata+0x24)
                    put(session.memory,pointer,b'0')
                else:
                    put(session.memory,targets[change],b'\0'*4)
                with patch('blitzcam.replay_map.launch_replay_path',return_value=self.path) as arguments:
                    with self.assertRaises(ReplaySourceUnavailable):
                        session_timeline(session)
                arguments.assert_not_called()

    def test_unbounded_unterminated_and_relative_paths_are_rejected(self):
        for change in ('length','terminator','relative'):
            with self.subTest(change=change):
                session = source_fixture(self.path)
                old = runtime_replay_source(session)
                if change == 'length':
                    put(session.memory,old.source+0x10,struct.pack('<I',0x7FFFFFFF))
                elif change == 'terminator':
                    session.memory.blocks[0x60000000] = str(self.path).encode('utf-8') + b'x'
                else:
                    raw=b'a.wotbreplay\0'
                    put(session.memory,old.source,raw.ljust(16,b'\0')+struct.pack('<II',len(raw)-1,15))
                with self.assertRaises(ReplaySourceUnavailable):
                    session_timeline(session)

    def test_a_source_switch_during_file_hashing_is_rejected(self):
        session = source_fixture(self.path)
        def switch(path):
            result = file_timeline(path)
            put(session.memory,session.objects.player+0xE8,b'\0'*8)
            return result
        with patch('blitzcam.replay_timeline.file_timeline',side_effect=switch):
            with self.assertRaises(ReplaySourceUnavailable):
                session_timeline(session)

    def test_cross_region_file_version_is_accepted(self):
        # The embedded owner carries the client build tag while the archive
        # object records the file's own version (e.g. a "_china" suffix). Both
        # describe the same loaded file; the archive version is authoritative.
        path = self.root/'跨区回放.wotbreplay'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('meta.json',json.dumps({'version':'11.21.0_china','battleDuration':253.12938}))
        session = source_fixture(path)
        metadata = runtime_replay_source(session).metadata
        encoded = b'11.21.0_china'
        put(session.memory,metadata+0xC,encoded.ljust(16,b'\0'))
        put(session.memory,metadata+0x1C,struct.pack('<I',len(encoded)))
        source = runtime_replay_source(session)
        self.assertEqual(source.version,'11.21.0_china')
        self.assertEqual(source.client_version,'11.21.0')
        actual = session_timeline(session)
        self.assertEqual(actual['version'],'11.21.0_china')
        self.assertTrue(replay_matches(file_timeline(path),actual))

    def test_file_version_must_match_the_loaded_replay(self):
        session = source_fixture(self.path)
        actual = file_timeline(self.path)
        with patch('blitzcam.replay_timeline.file_timeline',return_value={**actual,'version':'11.20.0'}):
            with self.assertRaisesRegex(ReplaySourceUnavailable,'已变化'):
                session_timeline(session)

    def test_missing_disk_file_does_not_invalidate_the_camera(self):
        session = source_fixture(self.root/'missing.wotbreplay')
        with self.assertRaises(ReplaySourceUnavailable):
            session_timeline(session)
        self.assertTrue(session.capture()['replay']['paused'])

    def test_legacy_profiles_keep_the_argument_reader(self):
        session = source_fixture(self.path)
        session.profile = replace(session.profile,replay_file_source_offset=None)
        with patch('blitzcam.replay_map.launch_replay_path',return_value=self.path) as arguments:
            actual = session_timeline(session)
        self.assertEqual(actual['source'],'launch_argument')
        arguments.assert_called_once_with(session.memory)


if __name__ == '__main__':
    unittest.main()
