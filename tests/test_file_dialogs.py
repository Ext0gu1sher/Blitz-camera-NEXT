import ctypes as C
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from blitzcam import file_dialogs as dialogs


@unittest.skipUnless(os.name == 'nt', 'Windows Common Item Dialog')
class NativeDialogBindingTests(unittest.TestCase):
    def test_real_com_configuration_for_open_save_and_folder(self):
        # Exercise the real system COM objects and vtable ABI without opening UI.
        # Only Show is replaced; all configuration and cleanup calls are native.
        native = dialogs._method
        def method(pointer, slot, *types):
            if slot == 3:
                return lambda *args: C.c_long(dialogs.CANCELLED).value
            return native(pointer, slot, *types)
        with tempfile.TemporaryDirectory() as initial, patch.object(dialogs, '_method', side_effect=method):
            for mode in ('open', 'save', 'folder'):
                with self.subTest(mode=mode):
                    self.assertIsNone(dialogs.show_dialog(
                        title='Blitz Camera native binding test', initial=initial,
                        filters=[('中文项目 (*.json)', '*.json')],
                        save=mode == 'save', folder=mode == 'folder',
                        default_name='中文 项目' if mode == 'save' else '',
                        default_ext='json' if mode == 'save' else None))


@unittest.skipUnless(os.name == 'nt', 'Windows Common Item Dialog')
class CommonDialogTests(unittest.TestCase):
    def setUp(self):
        self.ole, self.shell, self.user = Mock(), Mock(), Mock()
        self.ole.CoInitializeEx.return_value = 0
        self.ole.CoCreateInstance.side_effect = lambda *args: self.pointer(args[-1], 10)
        self.shell.SHCreateItemFromParsingName.side_effect = lambda *args: self.pointer(args[-1], 20)
        self.calls = []
        self.result = 0
        self.fail_slot = None
        self.path = C.create_unicode_buffer('C:\\回放 A & B\\' + '很长的路径\\' * 40 + '镜头.wotbreplay')
        self.patchers = [
            patch.object(dialogs.C, 'WinDLL', side_effect=lambda name, **kw: {
                'ole32': self.ole, 'shell32': self.shell, 'user32': self.user}[name]),
            patch.object(dialogs, '_method', side_effect=self.method),
            patch.object(dialogs, '_above_overlay'),
            patch.object(dialogs, '_owner', return_value=12345),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def pointer(target, value):
        C.cast(target, C.POINTER(C.c_void_p))[0] = value
        return 0

    def method(self, pointer, slot, *types):
        def call(this, *args):
            self.calls.append((this.value, slot, args))
            if slot == self.fail_slot:
                return C.c_long(0x80004005).value
            if slot == 10:
                C.cast(args[0], C.POINTER(C.c_ulong))[0] = 0x8000  # Keep system defaults.
            elif slot == 3:
                return self.result
            elif slot == 20:
                return self.pointer(args[0], 30)
            elif slot == 5 and this.value == 30:
                return self.pointer(args[1], C.addressof(self.path))
            return 0
        return call

    def assert_released(self, *pointers):
        self.assertEqual([p for p, slot, _ in self.calls if slot == 2], list(pointers))
        self.ole.CoUninitialize.assert_called_once_with()

    def test_open_returns_full_unicode_path_preserves_defaults_and_frees_result(self):
        selected = dialogs.show_dialog(title='打开项目', filters=[('项目', '*.json')])
        self.assertEqual(selected, Path(self.path.value))
        flags = next(args[0] for _, slot, args in self.calls if slot == 9)
        self.assertTrue(flags & 0x8000)
        self.assertTrue(flags & dialogs.FOS_FILEMUSTEXIST)
        self.assertTrue(flags & dialogs.FOS_FORCEFILESYSTEM)
        self.assertIn((10, 3, (12345,)), self.calls)
        self.assertEqual(self.ole.CoTaskMemFree.call_args.args[0].value, C.addressof(self.path))
        self.assert_released(30, 10)

    def test_cancel_does_not_read_a_selection(self):
        self.result = C.c_long(dialogs.CANCELLED).value
        self.assertIsNone(dialogs.show_dialog(title='选择回放'))
        self.assertFalse(any(slot == 20 for _, slot, _ in self.calls))
        self.ole.CoTaskMemFree.assert_not_called()
        self.assert_released(10)

    def test_save_keeps_overwrite_confirmation_and_default_json_extension(self):
        dialogs.show_dialog(title='另存为', save=True, filters=[('项目', '*.json')],
                            default_ext='json', default_name='中文项目')
        flags = next(args[0] for _, slot, args in self.calls if slot == 9)
        self.assertTrue(flags & dialogs.FOS_OVERWRITEPROMPT)
        self.assertFalse(flags & dialogs.FOS_FILEMUSTEXIST)
        self.assertIn((10, 22, ('json',)), self.calls)
        self.assertIn((10, 15, ('中文项目',)), self.calls)

    def test_folder_uses_modern_picker_and_configured_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            dialogs.show_dialog(title='选文件夹', folder=True, initial=Path(directory))
        flags = next(args[0] for _, slot, args in self.calls if slot == 9)
        self.assertTrue(flags & dialogs.FOS_PICKFOLDERS)
        self.assertFalse(any(slot == 4 for _, slot, _ in self.calls))
        self.assertTrue(any(slot == 12 and args[0].value == 20 for _, slot, args in self.calls))
        self.assert_released(30, 20, 10)

    def test_replay_default_allows_system_to_restore_last_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            dialogs.show_dialog(title='回放', initial=directory, remember_location=True)
        self.assertTrue(any(slot == 11 for _, slot, _ in self.calls))
        self.assertFalse(any(slot == 12 for _, slot, _ in self.calls))

    def test_missing_initial_directory_does_not_prevent_opening(self):
        self.assertIsNotNone(dialogs.show_dialog(title='回放', initial='Z:/missing-dialog-fixture'))
        self.shell.SHCreateItemFromParsingName.assert_not_called()

    def test_native_failure_is_an_error_and_releases_com(self):
        self.fail_slot = 20
        with self.assertRaisesRegex(OSError, '80004005'):
            dialogs.show_dialog(title='打开')
        self.assert_released(10)

    def test_failed_com_initialization_is_not_uninitialized(self):
        self.ole.CoInitializeEx.return_value = C.c_long(0x80010106).value
        with self.assertRaises(OSError):
            dialogs.show_dialog(title='打开')
        self.ole.CoCreateInstance.assert_not_called()
        self.ole.CoUninitialize.assert_not_called()
