"""Read-only observer/HUD snapshot for the exact 11.21 Steam build.

Works in either replay camera mode. Does not call, hook, pause, or write game code.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from blitzcam.memory import ReadOnlyMemory, find_process
from blitzcam.profile import PROFILE_1121, CameraError
from blitzcam.replay_source import runtime_replay_source
from blitzcam.seek_trial import clock


def inspect():
    with ReadOnlyMemory(find_process()) as m:
        assert m.profile.sha256 == PROFILE_1121.sha256
        live = lambda a: m.info.base + a - 0x400000
        types = dict(m.profile.vtables)
        types.update(HUDLayer=0x384CEC4, ObserverSystemController=0x3844998,
                     ObserverBattleStatusController=0x384CE18, ReplayHUDController=0x3853E68,
                     BattleController=0x37F8F70)
        types = {k: live(v) for k, v in types.items()}
        pats = {struct.pack('<I', v): k for k, v in types.items()}
        rx = re.compile(b'|'.join(re.escape(b) for b in pats))
        found = {k: [] for k in types}
        failed = 0
        for start, length in m.regions():
            for address in range(start, start + length, 1024 * 1024):
                try:
                    data = m.read(address, min(1024 * 1024, start + length - address))
                except CameraError:
                    failed += 1
                    continue
                for match in rx.finditer(data):
                    addr = address + match.start()
                    if addr % 4 == 0:
                        found[pats[match.group()]].append(addr)
        roots = []
        for ctx in found['AvatarContextReplay']:
            try:
                player = m.u32(ctx + 0x1B0)
                if m.u32(ctx + 0x28) != live(0x37F8C14) or m.u32(player) != types['ReplayPlayer']:
                    continue
                owners = [o for o in found['GameSceneController'] if m.u32(o + 0x20) == ctx]
                if len(owners) != 1:
                    continue
                arena, avatar = m.u32(ctx + 0x2C), m.u32(ctx + 0x1AC)
                if m.u32(arena + 0x34) != ctx:
                    continue
                roots.append((ctx, player, owners[0], arena, avatar))
            except CameraError:
                continue
        result = {'pid': m.info.pid, 'read_only': True, 'failed_chunks': failed,
                  'counts': {k: len(v) for k, v in found.items()}, 'root_count': len(roots)}
        if len(roots) != 1:
            return result
        ctx, player, owner, arena, avatar = roots[0]

        def guard():
            assert m.u32(ctx) == types['AvatarContextReplay']
            assert m.u32(ctx + 0x1B0) == player and m.u32(player) == types['ReplayPlayer']
            assert m.u32(owner + 0x20) == ctx and m.u32(arena + 0x34) == ctx

        # This adapter guards the replay/owner/source identity without requiring
        # CameraSession's free-camera-only capture chain.
        adapter = SimpleNamespace(memory=m, profile=m.profile, live=live,
                                  objects=SimpleNamespace(player=player), _guard=guard)
        source = runtime_replay_source(adapter)
        key = m.u32(avatar + 0xC)
        head = m.u32(arena + 0x110)
        node = m.u32(head + 4)
        seen = set()
        model = 0
        while node and node not in seen and len(seen) < 64:
            seen.add(node)
            if m.read(node + 0xD, 1) == b'\x01':
                break
            nodekey = m.u32(node + 0x10)
            if nodekey == key:
                model = m.u32(node + 0x14)
                break
            node = m.u32(node + (0 if key < nodekey else 8))
        scene = m.u32(owner + 0x1C)
        active = m.u32(scene + 0x120)
        result.update(source={**asdict(source), 'path': str(source.path)},
                      source_sha256=hashlib.sha256(source.path.read_bytes()).hexdigest(),
                      clock=clock(m, player, types['ReplayPlayer']),
                      context=hex(ctx), context_mode=m.u32(ctx + 0x1B8),
                      recorder_entity=key, model=hex(model),
                      model_mode=m.u32(model + 0x80) if model else None,
                      free_camera_active=active == m.u32(owner + 0x94), hud=[])
        for hud in found['HUDLayer']:
            if m.u32(hud + 0x140) == live(0x384CF70):
                result['hud'].append({'address': hex(hud), 'mode': m.u32(hud + 0x180)})
        result['visibility'] = []
        for controller in found['BattleController']:
            if m.u32(controller + 0x120) != ctx:
                continue
            battle = m.u32(controller + 0x150)
            screen = m.u32(battle + 0x38)
            layers = {hex(o): m.u32(screen + o) for o in (0x5C, 0x60, 0x68, 0x6C)}
            result['visibility'].append({
                'controller': hex(controller), 'battle': hex(battle), 'screen': hex(screen),
                'counter_158': struct.unpack('<i', m.read(controller + 0x158, 4))[0],
                'hide_flag_18': m.read(battle + 0x18, 1)[0],
                'layers': {k: {'address': hex(v), 'vft': hex(m.u32(v)),
                               'flags_4c': m.read(v + 0x4C, 1)[0]} for k, v in layers.items()}})
        guard()
        return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    result = inspect()
    a.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
