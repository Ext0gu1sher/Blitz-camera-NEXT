from pathlib import Path
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from blitzcam.preview_vendor.scenery_culling import ClientCullModes


MATERIAL = '''Material:
    RenderState:
        cullMode: FACE_BACK
    Passes:
        ShadowMap:
            RenderState:
                cullMode: FACE_FRONT
    Presets:
        AlphaTest:
            RenderState:
                cullMode: NONE
        AlphaBlend:
            RenderState:
                blend: true
'''


class PreviewCullingTests(unittest.TestCase):
    def test_opaque_wall_and_enabled_presets_use_forward_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'Materials').mkdir()
            (root/'Materials/Textured.material').write_text(MATERIAL)
            (root/'Materials/Sky.material').write_text('Material:\n    RenderState:\n        cullMode: NONE\n')
            (root/'Materials/Template.material').write_text('MaterialTemplate:\n    HIGH: "~res:/Materials/Textured.material"\n    LOW: "~res:/Materials/Sky.material"\n')
            modes = ClientCullModes(root, lambda raw: raw)
            desc = {'fxName': '~res:/Materials/Textured.material'}
            self.assertEqual(modes.resolve(desc), 2)
            self.assertEqual(modes.resolve({**desc, 'presets': {'AlphaTest': False}}), 2)
            self.assertEqual(modes.resolve({**desc, 'presets': {'AlphaBlend': True}}), 2)
            self.assertEqual(modes.resolve({**desc, 'presets': {'AlphaTest': True}}), 0)
            self.assertEqual(modes.resolve({'fxName': 'Template.material'}), 2)
            self.assertEqual(modes.resolve({'fxName': 'Sky.material'}), 0)
            self.assertIsNone(modes.resolve({'fxName': 'Missing.material'}))
            for mode in (0, 1, 2):
                self.assertEqual(modes.resolve({**desc, 'customCullMode': mode}), mode)
            forward = MATERIAL.replace('    Passes:\n', '    Passes:\n        Forward:\n            RenderState:\n                cullMode: NONE\n')
            (root/'Materials/Forward.material').write_text(forward)
            self.assertEqual(modes.resolve({'fxName': 'Forward.material'}), 0)

    def test_instance_override_and_export_survive_material_conversion(self):
        from blitzcam.preview_assets import dependencies
        maps, _ = dependencies()
        node = lambda id, **kwargs: {'##name': 'NMaterial', '#id': {'$bytes': struct.pack('<Q', id).hex()}, **kwargs}
        library = maps.MaterialLibrary({'#dataNodes': [
            node(1, customCullMode=0, enabledPresets={'AlphaTest': True}),
            node(2, parentMaterialKey=1, customCullMode=2, enabledPresets={'AlphaTest': False}),
            node(3, parentMaterialKey=1)]})
        self.assertEqual(library.resolve(2)['customCullMode'], 2)
        self.assertFalse(library.resolve(2)['presets']['AlphaTest'])
        self.assertEqual(library.resolve(3)['customCullMode'], 0)
        glb = maps.GlbBuilder()
        for mode in (0, 1, 2, None):
            index = maps._build_material(glb, SimpleNamespace(avg_color={}), None, {}, None, False, cull_mode=mode)
            material = glb.materials[index]
            self.assertEqual(material['doubleSided'], mode in (None, 0))
            self.assertEqual(material.get('extras', {}).get('clientCullMode'), mode)

    @unittest.skipUnless(shutil.which('node'), 'Node required for material assembly validation')
    def test_scene_shaders_and_instancing_preserve_face_culling(self):
        result = subprocess.run(['node', str(Path(__file__).parent/'fixtures/replay_culling_validation.mjs')], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
