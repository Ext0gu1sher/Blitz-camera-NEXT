"""Explicit deployed-adapter fixture for pre-existing game workflow tests.

These tests mock sessions/native workers and exercise editing and lifecycle
rules. Deployment authorization itself is exercised with real signed packages
in test_deployment and the deployment UI acceptance tests.
"""
from types import SimpleNamespace
from blitzcam.server import Workstation as HostWorkstation, CameraSession
from blitzcam.playback import PositionPlayback


class Workstation(HostWorkstation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deployment.files = {}  # explicitly simulate an authenticated edition
        self.backend = SimpleNamespace(require=lambda: None, loaded=False,
                                       connect=lambda *a, **kw: CameraSession.connect(*a, **kw))
        self.playback = PositionPlayback(self.playback.output)
