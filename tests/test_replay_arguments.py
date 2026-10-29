"""Historical research diagnostics only; application replay recognition never uses argv."""
from contextlib import contextmanager
import ctypes as C
import json
import os
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_connection_diagnostics import namespace


class ArgumentMemory:
    def __init__(self, args):
        self.info = SimpleNamespace(path=Path(r'D:\Client Files\wotblitz.exe'))
        self.handle = 777  # Only the fake NtQueryInformationProcess below sees it.
        self.command = subprocess.list2cmdline(args).encode('utf-16le')
        self.header = struct.pack('<HHI', len(self.command), len(self.command), 0x33000)
        self.blocks = {0x11010: struct.pack('<I', 0x22000),
                       0x22040: self.header, 0x33000: self.command}
        self.header_reads = 0
        self.change_header = False

    def read(self, address, count):
        if address == 0x22040:
            self.header_reads += 1
            if self.change_header and self.header_reads > 1:
                return bytes(count)
        for base, data in self.blocks.items():
            if base <= address and address + count <= base + len(data):
                return data[address - base:address - base + count]
        raise AssertionError('Read outside synthetic startup blocks')

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]


@contextmanager
def fake_query():
    original_dll = C.WinDLL
    nt = Mock()
    def query(handle, kind, peb_pointer, size, returned):
        assert handle == 777 and kind == 26
        peb_pointer._obj.value = 0x11000
        return 0
    nt.NtQueryInformationProcess.side_effect = query
    # Only CommandLineToArgvW/LocalFree are real OS calls; they parse our own string.
    with patch.object(C, 'WinDLL', side_effect=lambda name: nt if name == 'ntdll' else original_dll(name)):
        yield


@unittest.skipUnless(os.name == 'nt', 'Windows argument parsing of synthetic strings')
class ReplayArgumentTests(unittest.TestCase):
    exe = r'D:\Client Files\wotblitz.exe'
    replay = r'C:\回放 项目\shot A.wotbreplay'

    def report(self, args):
        with fake_query():
            return namespace['inspect_startup_source'](ArgumentMemory(args))

    def test_unicode_quoted_file_survives_the_full_native_parse(self):
        args = [self.exe, self.replay, '--option', 'some value']
        report = self.report(args)
        self.assertEqual(report['state'], 'unique')
        self.assertEqual(report['replay_arguments'], [self.replay])

    def test_missing_file_is_distinct_from_an_unreadable_command_line(self):
        args = [self.exe, '--option', 'private-option-value']
        report = self.report(args)
        self.assertEqual(report['state'], 'missing')
        self.assertEqual(report['argument_count'], 3)
        self.assertEqual(report['distinct_replay_file_count'], 0)
        self.assertNotIn('private-option-value', json.dumps(report))

    def test_duplicate_spelling_case_and_relative_segments_identify_one_file(self):
        args = [self.exe, self.replay, self.replay.upper(), r'C:\回放 项目\nested\..\shot A.wotbreplay']
        report = self.report(args)
        self.assertEqual(report['state'], 'unique')
        self.assertEqual(report['replay_argument_count'], 3)
        self.assertEqual(report['distinct_replay_file_count'], 1)

    def test_distinct_files_never_fall_back_to_first_or_last(self):
        args = [self.exe, self.replay, r'C:\回放 项目\different.wotbreplay']
        report = self.report(args)
        self.assertEqual(report['state'], 'ambiguous')
        self.assertEqual(report['distinct_replay_file_count'], 2)

    def test_executable_mismatch_is_not_a_missing_file(self):
        args = [r'D:\Other\wotblitz.exe', self.replay]
        report = self.report(args)
        self.assertEqual(report['state'], 'unavailable')
        self.assertIn('身份不一致', report['error']['message'])

    def test_header_change_discards_diagnostic_observation(self):
        memory = ArgumentMemory([self.exe, self.replay])
        memory.change_header = True
        with fake_query():
            report = namespace['inspect_startup_source'](memory)
        self.assertEqual(report['state'], 'unavailable')
        self.assertIn('读取不一致', report['error']['message'])

    def test_closed_or_invalid_handles_never_reach_a_native_api(self):
        for handle in (None, 0, -1, True, Mock()):
            memory = ArgumentMemory([self.exe, self.replay])
            memory.handle = handle
            with self.subTest(handle=handle), patch.object(C, 'WinDLL') as native:
                report = namespace['inspect_startup_source'](memory)
                self.assertEqual(report['state'], 'unavailable')
                native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
