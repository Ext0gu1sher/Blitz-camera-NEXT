"""The Pro restart helper must wait for exit without applying an app delta."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blitzcam import offline_updater as updater


class RestartHelperTests(unittest.TestCase):
    def test_restart_waits_and_preserves_intro_without_app_replacement(self):
        self.run_restart()

    def test_wait_failure_never_launches_second_instance(self):
        self.run_restart(wait_error=OSError('wait failed'))

    def test_launch_failure_is_recorded_without_consuming_intro(self):
        self.run_restart(launch_error=OSError('launch failed'))

    def run_restart(self, wait_error=None, launch_error=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init = root/'app/blitzcam/__init__.py'; init.parent.mkdir(parents=True)
            init.write_text('unchanged', encoding='utf-8')
            intro = root/'account/pro-intro.json'
            updater.write_json(intro, {'token':'a'*32})
            job = root/'job.json'
            updater.write_json(job, {'action':'restart','root':str(root),'data_root':str(root),'pids':[123]})
            order=[]
            def wait(pids):
                self.assertEqual(pids,[123]); order.append('wait')
                if wait_error: raise wait_error
            def launch(*args, **kwargs):
                self.assertEqual(order,['wait']); order.append('launch')
                self.assertEqual(args[0],[str(root/'BlitzCamera.exe')])
                if launch_error: raise launch_error
            with patch('sys.argv',['updater','--job',str(job)]), \
                    patch.object(updater,'wait_processes',side_effect=wait), \
                    patch.object(updater,'apply',side_effect=AssertionError('Pro restart replaced app files')), \
                    patch.object(updater.subprocess,'Popen',side_effect=launch):
                updater.main()
            self.assertEqual(order,['wait'] if wait_error else ['wait','launch'])
            self.assertEqual(init.read_text(encoding='utf-8'),'unchanged')
            self.assertEqual(json.loads(intro.read_text())['token'],'a'*32)
            result=json.loads((root/'output/deployment/last-result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['ok'],not (wait_error or launch_error))
