import json
from pathlib import Path
import tempfile
import unittest

from blitzcam.input_controls import validate_controls
from blitzcam.settings import read_settings, save_settings


class InputControlTests(unittest.TestCase):
    def test_defaults_allow_context_reuse_and_distinct_exit(self):
        config=validate_controls()
        self.assertEqual(config['bindings']['backward'], config['bindings']['snap'])
        self.assertEqual(config['bindings']['rear'], 'KeyX')
        self.assertEqual(config['bindings']['rollRight'], 'KeyC')
        self.assertEqual(config['bindings']['exitFlightMouse'], 'Mouse0')

    def test_conflicts_reserved_and_malformed_bindings_are_rejected(self):
        for bindings in ({'forward':'KeyS'}, {'forward':'Space'}, {'rear':'Escape'},
                         {'rear':'Ctrl+KeyZ'}, {'rear':'Alt+F4'}, {'rear':'Meta+KeyH'},
                         {'rear':'Shift+Ctrl+KeyH'}, {'rear':'Ctrl+Ctrl+KeyH'},
                         {'rear':'Tab'}, {'forward':True}, {'unknown':'KeyH'},
                         {'exitFlightMouse':'KeyH'}, {'seekBack':'KeyS'}):
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                validate_controls({'bindings':bindings})

    def test_modifiers_unbinding_and_parameters(self):
        config=validate_controls({'bindings':{'forward':'Shift+KeyR','rear':None,'exitFlightMouse':'Mouse2'},
                                  'tuning':{'seekDelay':0,'seekRamp':.25,'seekMax':256,'rollSpeed':90}})
        self.assertIsNone(config['bindings']['rear'])
        self.assertEqual(config['tuning']['seekMax'],256)
        for tuning in ({'seekRamp':0},{'seekMax':257},{'rollSpeed':True},{'mouseSensitivity':float('nan')},{'seekDelay':-1}):
            with self.subTest(tuning=tuning), self.assertRaises(ValueError):validate_controls({'tuning':tuning})

    def test_saved_controls_survive_partial_settings_edits_and_bad_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'projects-custom'
            saved=save_settings(root,{'project_directory':str(folder),'input_controls':{'bindings':{'rear':'KeyH'}}})
            updated=save_settings(root,{'project_directory':str(folder),'ui_scale':125})
            self.assertEqual(updated['input_controls'],saved['input_controls'])
            content=(root/'settings.json').read_bytes()
            with self.assertRaises(ValueError):save_settings(root,{'project_directory':str(folder),'input_controls':{'bindings':{'rear':'KeyC'}}})
            self.assertEqual((root/'settings.json').read_bytes(),content)
            self.assertEqual(read_settings(root),updated)
            data=json.loads(content);data['input_controls']={'bindings':{'rear':'Space'}}
            (root/'settings.json').write_text(json.dumps(data),encoding='utf-8')
            recovered=read_settings(root)
            self.assertEqual(recovered['input_controls'],validate_controls())
            self.assertEqual(recovered['project_directory'],str(folder.resolve()))
            self.assertEqual(recovered['ui_scale'],125)
