"""Map metadata uses the active replay owner, never process startup arguments."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from blitzcam.replay_map import ReplayMapResolver, replay_metadata
from test_replay_source import source_fixture, put


class ReplayMapSourceTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.replay=Path(folder.name)/'manual.wotbreplay'
        with zipfile.ZipFile(self.replay,'w') as archive:
            archive.writestr('meta.json',json.dumps({'version':'11.21.0','battleDuration':253.12938,
                                                   'mapName':'canal','mapId':1}))
        self.session=source_fixture(self.replay,pointer_owner=True)
        self.resource='~res:/3d/Maps/canal/canal.sc2'
        terrain=Mock();terrain.catalog.return_value={'maps':[{'scene_resource':self.resource,
                     'map_id':1,'map_name':'canal','map_number':1}]}
        self.resolver=ReplayMapResolver(terrain)

    def test_active_file_supplies_map_metadata(self):
        with patch('blitzcam.replay_map.scene_resource',return_value=self.resource):
            result=self.resolver.identify(self.session)
        self.assertEqual(result['state'],'matched')
        self.assertEqual(result['replay_file'],str(self.replay.resolve()))

    def test_file_owner_change_discards_metadata_but_preserves_scene_map(self):
        metadata=replay_metadata(self.replay)
        def changed(path):
            put(self.session.memory,self.session.objects.player+0xE8,bytes(8))
            return metadata
        with patch('blitzcam.replay_map.scene_resource',return_value=self.resource), \
                patch('blitzcam.replay_map.replay_metadata',side_effect=changed):
            result=self.resolver.identify(self.session)
        self.assertEqual(result['state'],'scene_only')
        self.assertNotIn('replay_file',result)
