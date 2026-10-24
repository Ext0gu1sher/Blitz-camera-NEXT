"""Exact-hash Steam layouts. Never select a layout by version text alone."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class BuildProfile:
    version: str = "11.20.0.887"
    sha256: str = "4813544d3d6b9f45a357e87f5a14d065bd108c4acd324ac1506cb6d1ad6ff0af"
    preferred_base: int = 0x400000
    image_size: int = 73433088
    machine: int = 0x14C
    optional_magic: int = 0x10B
    vtables: tuple = ()
    replay_secondary_vft: int = 0x36EB164
    scene_render_offset: int = 0xAC
    scene_camera_offsets: tuple = (0x128, 0x12C)
    render_camera_offsets: tuple = (0xB0, 0xB4)
    scene_path_offset: int | None = None
    replay_file_source_offset: int | None = None
    replay_file_holder_vft: int | None = None
    replay_file_vft: int | None = None


VFT_PREFERRED = {
    "ReplayPlayer": 0x36EB15C,
    "AvatarContextReplay": 0x3706310,
    "ReplayCameraController": 0x370F9E8,
    "GameCamera": 0x370AAFC,
    "FreeCamera": 0x372040C,
    "RenderSystem": 0x369C810,
    "GameScene": 0x363E518,
    "GameSceneController": 0x37203B4,
    "SpectatorCameraController": 0x370FAB0,
}
REPLAY_SECONDARY_VFT = 0x36EB164
DYNAMIC_BINDING_PREFERRED = 0x4599918
PROFILE = BuildProfile(vtables=tuple(VFT_PREFERRED.items()))
PROFILE_1121 = BuildProfile(
    version="11.21.0.1235",
    sha256="5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608",
    image_size=74563584,
    vtables=tuple({
        "ReplayPlayer": 0x37C1F44, "AvatarContextReplay": 0x37F8A00,
        "ReplayCameraController": 0x3844B80, "GameCamera": 0x382DA70,
        "FreeCamera": 0x385402C, "RenderSystem": 0x3777120,
        "GameScene": 0x3713A60, "GameSceneController": 0x3853FD4,
        "SpectatorCameraController": 0x3844C48,
        "CinemaCameraController": 0x3830F9C,
    }.items()),
    replay_secondary_vft=0x37C1F4C,
    scene_render_offset=0xA8,
    scene_camera_offsets=(0x120, 0x124),
    render_camera_offsets=(0xB4, 0xB8),
    scene_path_offset=0x268,
    replay_file_source_offset=0xE8,
    replay_file_holder_vft=0x37BD758,
    replay_file_vft=0x37C1CAC,
)
PROFILES = MappingProxyType({p.sha256: p for p in (PROFILE, PROFILE_1121)})


class CameraError(RuntimeError):
    """A readable diagnostic, rather than an unsafe best-effort continuation."""


class SessionChanged(CameraError):
    """The replay/camera identity changed; a new discovery is required."""


class IncoherentSample(CameraError):
    """A transient read straddled an update; discard this sample, not the session."""
