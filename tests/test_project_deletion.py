"""Project removal, current-workspace retirement and native recycle semantics."""
import ctypes as C
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

from blitzcam.editor_state import editor_state_path
from blitzcam.project import recycle_project, validate_project, read_project
from blitzcam.server import record_recent
from tests import test_project_files as project_files


class ProjectDeletionTests(unittest.TestCase):
    setUp = project_files.ProjectFileTests.setUp
    tearDown = project_files.ProjectFileTests.tearDown
    request = project_files.ProjectFileTests.request

    def test_delete_current_retires_old_path_and_does_not_create_another_project(self):
        result = self.request('/api/projects/new', {'name':'待删除'})
        target = Path(result['path'])
        before = self.app.project.to_dict()
        revision = self.app.project_revision
        view = {'schema_version':1, 'timeline':{'playhead':3}}
        self.app.save_editor_state(str(target), view)
        replay = self.out/'same.wotbreplay'; replay.write_bytes(b'keep replay')
        recycled = self.out/'recycled.bcnproj'
        with patch('blitzcam.server.recycle_project', side_effect=lambda p: (p.rename(recycled), True)[1]) as recycle:
            reply = self.request('/api/projects/delete', {'path':str(target), 'expected_revision':revision})
        self.assertTrue(reply['ok']); recycle.assert_called_once_with(target)
        self.assertEqual(read_project(recycled).to_dict(), before)
        self.assertFalse(target.exists()); self.assertEqual(replay.read_bytes(), b'keep replay')
        self.assertFalse(editor_state_path(self.out,target).exists())
        self.assertNotEqual(self.app.project_path, target)
        self.assertFalse(self.app.project_path.exists())
        self.assertEqual(self.request('/api/projects/recent')['projects'], [])
        # Late autosave and close-handshake requests from another window cannot
        # resurrect the deleted file or overwrite the replacement workspace.
        with self.assertRaises(ValueError):
            self.app.save_editor_state(str(target), view)
        with self.assertRaises(ValueError):
            self.app.set_project(validate_project(before), revision)
        self.assertFalse(target.exists()); self.assertFalse(self.app.project_path.exists())

    def test_delete_other_project_preserves_current_workspace(self):
        old = self.request('/api/projects/new', {'name':'旧项目'})['path']
        self.request('/api/projects/new', {'name':'当前项目'})
        current_path = self.app.project_path
        current = self.app.project.to_dict(); revision = self.app.project_revision
        with patch('blitzcam.server.recycle_project', side_effect=lambda p: (p.unlink(), True)[1]):
            self.request('/api/projects/delete', {'path':old})
        self.assertEqual(self.app.project_path,current_path)
        self.assertEqual(self.app.project.to_dict(),current)
        self.assertEqual(self.app.project_revision,revision)
        self.assertTrue(current_path.is_file()); self.assertFalse(Path(old).exists())
        self.assertEqual([x['path'] for x in self.request('/api/projects/recent')['projects']],[str(current_path)])

    def test_cancelled_or_failed_recycle_preserves_file_and_listing(self):
        target = Path(self.request('/api/projects/new', {'name':'保留'})['path'])
        content = target.read_bytes(); revision = self.app.project_revision
        listing = self.request('/api/projects/recent')
        with patch('blitzcam.server.recycle_project', return_value=False):
            self.assertEqual(self.request('/api/projects/delete', {'path':str(target)}), {'cancelled':True})
        with patch('blitzcam.server.recycle_project', side_effect=OSError('file busy')):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/projects/delete', {'path':str(target)})
            self.assertEqual(caught.exception.code,400)
        self.assertEqual(target.read_bytes(),content)
        self.assertEqual(self.app.project_path,target)
        self.assertEqual(self.app.project_revision,revision)
        self.assertEqual(self.request('/api/projects/recent'),listing)

    def test_forget_existing_project_keeps_its_file(self):
        target = Path(self.request('/api/projects/new', {'name':'仅移出列表'})['path'])
        content = target.read_bytes()
        with patch('blitzcam.server.recycle_project') as recycle:
            self.request('/api/projects/forget', {'path':str(target)})
        recycle.assert_not_called(); self.assertEqual(target.read_bytes(),content)
        self.assertEqual(self.request('/api/projects/recent')['projects'],[])

    def test_delete_rejects_unlisted_files_replays_directories_and_invalid_paths(self):
        unlisted = self.out/'unlisted.json'; unlisted.write_text('{}',encoding='utf-8')
        replay = self.out/'replay.wotbreplay'; replay.write_bytes(b'replay');record_recent(replay)
        folder = self.out/'folder.json'; folder.mkdir(); record_recent(folder)
        with patch('blitzcam.server.recycle_project') as recycle:
            for target in (None, 1, '', 'bad\0path', str(unlisted), str(replay), str(folder)):
                with self.subTest(target=target), self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request('/api/projects/delete', {'path':target})
                self.assertEqual(caught.exception.code,400)
        recycle.assert_not_called();self.assertTrue(unlisted.exists());self.assertTrue(replay.exists());self.assertTrue(folder.is_dir())

    def test_delete_rejects_active_playback_launch_and_stale_revision(self):
        target = self.request('/api/projects/new', {'name':'工作中'})['path']
        with patch('blitzcam.server.recycle_project') as recycle:
            with patch.object(self.app.playback,'state',return_value={'active':True}),self.assertRaises(urllib.error.HTTPError):
                self.request('/api/projects/delete',{'path':target})
            self.app.replay_launch['state']='choosing'
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/projects/delete',{'path':target})
            self.app.replay_launch['state']='idle'
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/projects/delete',{'path':target,'expected_revision':-1})
        recycle.assert_not_called();self.assertTrue(Path(target).exists())


@unittest.skipUnless(os.name == 'nt', 'Windows recycle API')
class NativeRecycleTests(unittest.TestCase):
    def test_native_recycle_uses_exact_unicode_double_terminated_path_and_protection_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'项目 A.json'; target.write_text('{}')
            shell = Mock()
            def perform(pointer):
                operation=pointer._obj
                self.assertEqual(operation.wFunc,3)
                self.assertEqual(operation.pFrom,str(target.resolve()))
                address=C.cast(C.byref(operation,type(operation).pFrom.offset),C.POINTER(C.c_void_p)).contents.value
                self.assertEqual(C.wstring_at(address,len(str(target.resolve()))+2),str(target.resolve())+'\0\0')
                self.assertTrue(operation.fFlags & 0x40)  # Recycle/undo.
                self.assertTrue(operation.fFlags & 0x4000)  # Warn before permanent fallback.
                self.assertTrue(operation.fFlags & 0x1000)  # No recursive deletion.
                target.unlink();return 0
            shell.SHFileOperationW.side_effect=perform
            with patch.object(C,'WinDLL',return_value=shell):self.assertTrue(recycle_project(target))
            shell.SHFileOperationW.assert_called_once()

    def test_cancel_error_and_false_success_are_not_reported_as_completed_deletions(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'keep.json';target.write_text('{}')
            shell = Mock()
            def cancel(pointer):pointer._obj.fAnyOperationsAborted=True;return 0
            with patch.object(C,'WinDLL',return_value=shell):
                shell.SHFileOperationW.side_effect=cancel
                self.assertFalse(recycle_project(target))
                shell.SHFileOperationW.side_effect=None;shell.SHFileOperationW.return_value=5
                with self.assertRaises(OSError):recycle_project(target)
                shell.SHFileOperationW.return_value=0
                with self.assertRaises(OSError):recycle_project(target)
            self.assertTrue(target.is_file())


if __name__ == '__main__':
    unittest.main()
