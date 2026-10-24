"""Read-only Blitz installation inspection; writes evidence only beside this script.

Does not start/attach to a process, modify the installation, or load game DLLs.
Requires the already-installed Python lz4 package for compressed DVPL resources.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import struct
import zipfile
import zlib
import lz4.block

GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz")
PROFILE = Path(r"C:\Users\Ext1nguisher\AppData\Local\wotblitz\DAVAProject")
OUT = Path(__file__).resolve().parent / "local"
OUT.mkdir(parents=True, exist_ok=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_dvpl(path):
    data = path.read_bytes()
    usize, csize, crc, method, magic = struct.unpack("<IIII4s", data[-20:])
    payload = data[:-20]
    assert magic == b"DVPL" and len(payload) == csize
    assert zlib.crc32(payload) == crc
    if method == 0:
        decoded = payload
    elif method in (1, 2):
        decoded = lz4.block.decompress(payload, uncompressed_size=usize)
    else:
        raise ValueError(f"Unsupported DVPL compression type: {method}")
    assert len(decoded) == usize
    return decoded, {"source": str(path), "sha256": digest(data),
                     "compression_type": method, "decoded_size": usize,
                     "payload_crc32_verified": True}


exe_path = GAME / "wotblitz.exe"
exe = exe_path.read_bytes()
pe = struct.unpack_from("<I", exe, 0x3C)[0]
assert exe[pe:pe + 4] == b"PE\0\0"
machine = struct.unpack_from("<H", exe, pe + 4)[0]
magic = struct.unpack_from("<H", exe, pe + 24)[0]
manifest_path = GAME.parents[1] / "appmanifest_444200.acf"
manifest = manifest_path.read_text(encoding="utf-8")
manifest_fields = {}
for key in ("appid", "name", "installdir", "buildid", "LastUpdated"):
    match = re.search(r'"' + key + r'"\s+"([^"]*)"', manifest)
    manifest_fields[key] = match.group(1) if match else None

evidence = {
    "inspection_date_client_timezone": "2026-10-13 Asia/Shanghai",
    "scope": "Static files only; no runtime camera measurements or writes",
    "exe": {"path": str(exe_path), "sha256": digest(exe), "bytes": len(exe),
            "pe_machine": hex(machine), "pe_optional_magic": hex(magic),
            "architecture": "x86 PE32" if (machine, magic) == (0x14C, 0x10B) else "other"},
    "steam_manifest": {"path": str(manifest_path), **manifest_fields},
    "resources": [],
}

resources = [
    "version.txt", "optionsDesktop.yaml", "optionsGlobal.yaml", "Cinema.yaml",
    "EngineSettings.yaml",
    "UI/Screens3/Battle/Replay/PlaybackSpeedPanel.yaml",
    "UI/Screens3/Battle/Replay/PlaybackSpeedPanel.actions",
    "UI/Screens3/Battle/Replay/BattleScreenReplay.actions",
    "UI/Screens/Battle/BattleScreenReplay.yaml",
]
for relative in resources:
    decoded, info = read_dvpl(GAME / "Data" / (relative + ".dvpl"))
    target = OUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(decoded)
    info["decoded_copy"] = str(target)
    evidence["resources"].append(info)
    if relative == "version.txt":
        evidence["resource_version"] = decoded.decode("utf-8")

strings = [m.group().decode("ascii") for m in re.finditer(rb"[\x20-\x7e]{5,}", exe)]
anchors = ["DAVA::LZ4Compressor::Decompress", "DAVA::ComponentSlice<class GameCameraComponent>::ComponentSlice",
           "~res:/Cinema.yaml", "GameCameraUpdateSystem::Process", "GameCamera::SetRotationSmoothingMode",
           ".?AVCinemaCameraController@@", ".?AVFreeCamera@@", "ReplayPause", "SwitchFreeCamera",
           ".replayTimeWarp", ".replayPlaybackSpeedChanged", ".onFreeCameraStateChanged",
           ".?AVReplayCameraController@@", ".?AVAvatarContextReplay@@", ".?AVReplayPlayer@@",
           ".?AVGameCamera@@", ".?AVFlexFOVCamera@@"]
evidence["exe_string_anchors"] = {s: s in strings for s in anchors}
evidence["anchor_limit"] = "Strings/RTTI are static leads, not exported callable APIs or validated runtime addresses."

replays = []
for path in sorted((PROFILE / "replays").glob("*.wotbreplay")):
    try:
        with zipfile.ZipFile(path) as archive:
            meta = json.loads(archive.read("meta.json"))
            replays.append({"path": str(path), "sha256": digest(path.read_bytes()),
                            "version": meta.get("version"), "mapName": meta.get("mapName"),
                            "battleDuration": meta.get("battleDuration"),
                            "members": [{"name": i.filename, "bytes": i.file_size}
                                        for i in archive.infolist()]})
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        replays.append({"path": str(path), "error": str(error)})
evidence["replay_versions"] = dict(Counter(item.get("version", "error") for item in replays))
evidence["replay_limit"] = "Only ZIP members and selected meta.json fields inspected; event payload not decoded."
(OUT / "replay-inventory.json").write_text(json.dumps(replays, ensure_ascii=False, indent=2), encoding="utf-8")

configs = [
    PROFILE / "optionsGlobal.bin",
    Path(r"C:\Users\Ext1nguisher\Documents\Wotb\Wotb_Storage\camera plugin\optionsGlobal.bin"),
    Path(r"C:\Users\Ext1nguisher\Documents\Wotb\Wotb_Storage\camera plugin\original\optionsGlobal.bin"),
]
evidence["existing_user_configs"] = []
for path in configs:
    data = path.read_bytes()
    evidence["existing_user_configs"].append({
        "path": str(path), "bytes": len(data), "sha256": digest(data),
        "header_hex": data[:4].hex(), "values_decoded": False})
evidence["existing_local_modification_files"] = [str(GAME / name) for name in
    ("dxgi.dll", "ReShade.ini", "ReShade.log", "ReShadePreset.ini") if (GAME / name).exists()]
evidence["log_excerpts"] = []
log_path = PROFILE / "blitz-logs_20261007185507.txt"
for number, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
    if ("EngineBackend::OnGameLoopStarted" in line or "[Renderer] CurrentFlow" in line
            or "[RHI-DX11] OS registry version" in line or "[replay] Start replay event" in line):
        evidence["log_excerpts"].append({"source": str(log_path), "line": number, "text": line})
        if len(evidence["log_excerpts"]) >= 8:
            break
(OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"evidence": str(OUT / "evidence.json"), "exe": evidence["exe"],
                  "version": evidence["resource_version"], "replays": evidence["replay_versions"]},
                 ensure_ascii=False, indent=2))
