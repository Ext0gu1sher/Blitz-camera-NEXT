"""Project format integrity, legacy migration and atomic-save regressions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blitzcam.project import convert_project, read_project, write_project, validate_project, PROJECT_FORMAT
from tests.test_multicam import fixture


class BcnProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        data = fixture()
        data['beat_grid'] = {'version': 1, 'enabled': True, 'bpm': 128, 'offset_sec': .125, 'anchor_sec': 20, 'division': 2, 'origin': 'inpoint'}
        data['replay_timeline']['replay_file'] = str(self.root/'中文 回放.wotbreplay')
        self.project = validate_project(data)

    def test_roundtrip_preserves_all_cameras_timing_beat_and_replay(self):
        old, bcn, restored = self.root/'原项目.json', self.root/'新项目.BCNPROJ', self.root/'还原.json'
        write_project(old, self.project)
        before = old.read_bytes()
        convert_project(old, bcn)
        envelope = json.loads(bcn.read_text(encoding='utf-8'))
        self.assertEqual(envelope['format'], PROJECT_FORMAT)
        self.assertEqual(envelope['format_version'], 1)
        self.assertEqual(read_project(bcn).to_dict(), self.project.to_dict())
        convert_project(bcn, restored)
        self.assertEqual(read_project(restored).to_dict(), self.project.to_dict())
        self.assertEqual(before, old.read_bytes())

    def test_invalid_future_and_renamed_json_are_rejected_without_modification(self):
        target = self.root/'bad.bcnproj'
        for data in [self.project.to_dict(), {}, {'format': 'other', 'format_version': 1},
                     {'format': PROJECT_FORMAT, 'format_version': 2},
                     {'format': PROJECT_FORMAT, 'format_version': True},
                     {'format': PROJECT_FORMAT, 'format_version': 1, 'project': {}}]:
            with self.subTest(data=data):
                raw = json.dumps(data).encode()
                target.write_bytes(raw)
                with self.assertRaises(ValueError):
                    convert_project(target, self.root/'result.json')
                self.assertEqual(target.read_bytes(), raw)
                self.assertFalse((self.root/'result.json').exists())

    def test_conversion_never_overwrites_and_cleans_temporary_files(self):
        source, target = self.root/'original.json', self.root/'existing.bcnproj'
        write_project(source, self.project)
        target.write_bytes(b'keep this file')
        with self.assertRaisesRegex(ValueError, '已存在'):
            convert_project(source, target)
        self.assertEqual(target.read_bytes(), b'keep this file')
        self.assertFalse(list(self.root.glob('.blitzcam-*')))
        with self.assertRaises(ValueError):
            convert_project(source, source)

    def test_failed_save_preserves_last_good_project(self):
        target = self.root/'project.bcnproj'
        write_project(target, self.project)
        original = target.read_bytes()
        with patch('blitzcam.project.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                write_project(target, self.project)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.blitzcam-*')))

    def test_payload_size_limit_cannot_be_bypassed_by_wrapper(self):
        target = self.root/'oversized.bcnproj'
        data = self.project.to_dict()
        data['padding'] = 'x'*(2*1024*1024)
        target.write_text(json.dumps({'format': PROJECT_FORMAT, 'format_version': 1, 'project': data}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            read_project(target)
