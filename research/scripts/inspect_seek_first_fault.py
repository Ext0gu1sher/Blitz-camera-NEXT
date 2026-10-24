"""Decode the owned x86 first-chance AV capture offline; no process access.

Buffer names describe register windows, not inferred object types. EBP walking
uses only bytes saved at the first fault, never a later WER stack or stack scan.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def inspect(path, game_base, game_size):
    data = Path(path).read_bytes()
    if len(data) != 3676:
        raise ValueError('Expected the exact 3676-byte x86 Fault capture.')
    magic, size, tick, thread, *lengths = struct.unpack_from('<8I', data)
    if (magic, size) != (0x31415642, len(data)):
        raise ValueError('Unknown Fault layout.')
    capacities = (96, 192, 512, 2048)
    if any(n > cap for n, cap in zip(lengths, capacities)):
        raise ValueError('Invalid captured read length.')
    code, flags, linked, ip, count = struct.unpack_from('<5I', data, 32)
    context = 112
    names = ('edi', 'esi', 'ebx', 'edx', 'ecx', 'eax', 'ebp', 'eip',
             'cs', 'eflags', 'esp', 'ss')
    regs = dict(zip(names, struct.unpack_from('<12I', data, context + 156)))
    if (code != 0xc0000005 or count != 2 or regs['eip'] != ip or
            struct.unpack_from('<I', data, context)[0] & 0xffff0000 != 0x10000):
        raise ValueError('Not a consistent x86 AV record/context pair.')
    operation, address = struct.unpack_from('<2I', data, 32 + 20)

    def describe(value):
        row = dict(address=hex(value))
        if game_base <= value < game_base + game_size:
            row.update(module='wotblitz.exe', rva=hex(value - game_base),
                       preferred_va=hex(value - game_base + 0x400000))
        return row

    stack = data[1628:1628 + lengths[3]]
    frames, seen, ebp = [], set(), regs['ebp']
    while len(frames) < 64 and ebp not in seen:
        offset = ebp - regs['esp']
        if offset < 0 or offset + 24 > len(stack):
            break
        seen.add(ebp)
        previous, ret, *args = struct.unpack_from('<6I', stack, offset)
        frames.append(dict(ebp=hex(ebp), return_address=describe(ret),
                           args=[hex(v) for v in args], source='first-fault captured stack'))
        if previous <= ebp:
            break
        ebp = previous
    windows = []
    for name, start, length in zip(('esi', 'edi', 'pointer_at_edi_plus_90', 'esp'),
                                    (828, 924, 1116, 1628), lengths):
        windows.append(dict(name=name, captured_length=length,
                            words=[hex(v[0]) for v in struct.iter_unpack('<I', data[start:start + length - length % 4])]))
    return dict(path=str(Path(path).resolve()), sha256=hashlib.sha256(data).hexdigest(),
                game_base=hex(game_base), game_size=hex(game_size), tick=tick, thread=thread,
                exception_code=hex(code), exception_flags=hex(flags), linked_record=hex(linked),
                exception_ip=describe(ip), access={0: 'read', 1: 'write', 8: 'execute'}.get(operation, operation),
                fault_address=hex(address), registers={k: hex(v) for k, v in regs.items()},
                ebp_frames=frames, register_windows=windows,
                limitations='EBP chain only; no FPO unwind, object lifetime history or later dump bytes.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture')
    ap.add_argument('--game-base', required=True, type=lambda s: int(s, 0))
    ap.add_argument('--game-size', required=True, type=lambda s: int(s, 0))
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    result = inspect(args.capture, args.game_base, args.game_size)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: result[k] for k in ('exception_ip', 'access', 'fault_address', 'thread')}, indent=2))
