"""Exact-build research probe. Query/read access only; does not edit profiles."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import blitzcam.memory as memory
from blitzcam.profile import PROFILE_1121

BUILD = ROOT/'research/builds/11.21.0.1235'
SHA = '5030ee4b9f6ec7db1c06efa2b92f9dd7243574be5d8d9578c118119318bc9608'


def main():
    static = json.loads((BUILD/'static-rtti.json').read_text(encoding='utf-8'))
    assert static['sha256'] == SHA
    profile = PROFILE_1121
    info = memory.find_process()
    with memory.ReadOnlyMemory(info) as mem:
        if mem.profile != profile:
            raise memory.CameraError('研究探针只适用于指定的 11.21 构建。')
        vfts = {}
        for name, value in static['types'].items():
            primary = [t for t in value['tables'] if t['subobject_offset'] == 0]
            assert len(primary) == 1
            vfts[name] = info.base + primary[0]['vft'] - profile.preferred_base
        patterns = {struct.pack('<I', v): name for name, v in vfts.items()}
        rx = re.compile(b'|'.join(re.escape(p) for p in patterns))
        found = {n: [] for n in vfts}
        for start, length in mem.regions():
            for address in range(start, start+length, 1024*1024):
                try: data = mem.read(address, min(1024*1024, start+length-address))
                except memory.CameraError: continue
                for match in rx.finditer(data):
                    pointer = address+match.start()
                    if pointer % 4 == 0: found[patterns[match.group()]].append(pointer)
        blocks = {}
        for name, candidates in found.items():
            # Keep only small type-matched blocks, not a process dump.
            if len(candidates) > 32: continue
            for p in candidates:
                size = 0x640 if name == '.?AVGameCamera@@' else 0x280
                try: blocks[hex(p)] = {'type': name, 'hex': mem.read(p, size).hex()}
                except memory.CameraError: continue
        result = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'pid': info.pid,
                  'module_base': hex(info.base), 'sha256': SHA, 'production_profile_modified': False,
                  'candidates': {n: list(map(hex, p)) for n, p in found.items()}, 'blocks': blocks}
        (BUILD/'probe-objects.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        for name, pointers in result['candidates'].items():
            print(name, pointers)
        for name in ['.?AVGameSceneController@@', '.?AVReplayCameraController@@', '.?AVGameScene@@', '.?AVAvatarContextReplay@@']:
            for p in found[name]:
                print('\nWORDS', name, hex(p))
                data = bytes.fromhex(blocks[hex(p)]['hex'])
                for offset in range(0, min(len(data), 0x200), 16):
                    print(hex(offset), [hex(x) for x in struct.unpack_from('<4I', data, offset)])


if __name__ == '__main__': main()
