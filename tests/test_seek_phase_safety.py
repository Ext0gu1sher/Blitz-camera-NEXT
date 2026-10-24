import unittest
import ctypes as C
import json
from types import SimpleNamespace
from unittest.mock import patch

from tools import verify_replay_seek_phase as trial
from blitzcam.seek_phase_trial import prepare
from blitzcam.seek_trial import Config as OriginalConfig


class SeekPhaseSafetyTests(unittest.TestCase):
    def test_diagnostic_path_supports_relocated_unicode_folders(self):
        session=SimpleNamespace(memory=SimpleNamespace(u32=lambda _:123),live=lambda va:va)
        path='D:\\相机工具\\output\\replay-seek-phase-runs\\one\\first-fault.bin'
        with patch('blitzcam.seek_phase_trial.original_prepare',return_value=(OriginalConfig(),{})) as original:
            cfg,_=prepare(session,{},10,1,path,ui_repair=False,max_delta=3600)
            self.assertEqual(cfg.fault_path.decode('utf8'),path)
            self.assertEqual(cfg.ui_repair,0)
            self.assertEqual(original.call_args.kwargs,{'max_delta':3600})

    def test_disabled_seek_rejects_before_service_process_or_file_access(self):
        for execute in (False, True):
            with self.subTest(execute=execute), \
                 patch.object(trial.CameraSession, 'connect') as connect, \
                 patch.object(trial.urllib.request, 'urlopen') as network, \
                 patch.object(trial.Path, 'mkdir') as mkdir, \
                 patch.object(trial, 'atomic_json') as write:
                with self.assertRaisesRegex(RuntimeError, 'Live seek disabled'):
                    trial.run(SimpleNamespace(mode='seek', execute=execute))
                for operation in (connect, network, mkdir, write):
                    operation.assert_not_called()

    def test_noop_still_requires_explicit_execute_without_touching_game(self):
        with patch.object(trial.CameraSession, 'connect') as connect, \
             patch.object(trial.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(RuntimeError, 'pass --execute'):
                trial.run(SimpleNamespace(mode='noop', execute=False))
            connect.assert_not_called()
            network.assert_not_called()

    def test_failed_repair_rejects_before_service_process_or_file_access(self):
        for execute in (False, True):
            with self.subTest(execute=execute), \
                 patch.object(trial.CameraSession, 'connect') as connect, \
                 patch.object(trial.urllib.request, 'urlopen') as network, \
                 patch.object(trial.Path, 'mkdir') as mkdir, \
                 patch.object(trial, 'atomic_json') as write:
                with self.assertRaisesRegex(RuntimeError, 'UI repair seek disabled'):
                    trial.run(SimpleNamespace(mode='repair-seek', execute=execute))
                for operation in (connect, network, mkdir, write):
                    operation.assert_not_called()

    def test_repair_bodies_checked_with_aslr_and_any_difference_rejected(self):
        base, start = 0x12340000, 0xcfab30-0x400000
        data = bytes((i % 251 for i in range(0x640)))
        memory = SimpleNamespace(read=lambda address, size: data[address-base-start:address-base-start+size])
        session = SimpleNamespace(profile=trial.PROFILE_1121, info=SimpleNamespace(path='unused', base=base),
                                  live=lambda va: base+va-0x400000, memory=memory)
        with patch.object(trial, 'relocated_code', return_value={start: data}):
            trial.verify_original_removal_code(session)
            memory.read = lambda address, size: b'\x00'*size
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                trial.verify_original_removal_code(session)

    def test_native_repair_layout_and_exports_match_manifest(self):
        native = trial.ROOT/'blitzcam/native'
        manifest = json.loads((native/'replay_seek_phase_trial_1121.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['ui_state_size'], C.sizeof(trial.UiRepairState))
        self.assertEqual(manifest['ui_event_size'], 48)
        self.assertEqual(manifest['config_size'], C.sizeof(trial.Config))
        self.assertEqual(manifest['sha256'], trial.hashlib.sha256((native/manifest['dll']).read_bytes()).hexdigest())
        exports = trial.pe_exports(native/manifest['dll'])
        self.assertTrue({'g_shared', 'g_ui_repair', 'HookAttach@4', 'HookDetach@4'} <= exports.keys())


if __name__ == '__main__':
    unittest.main()
