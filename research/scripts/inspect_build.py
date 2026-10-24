"""Read PE/RTTI evidence from disk. Never load or execute client code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


class PE:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        nt = self.u32off(0x3C); opt = nt + 24
        if self.data[:2] != b'MZ' or self.data[nt:nt+4] != b'PE\0\0':
            raise ValueError('not PE')
        self.machine = struct.unpack_from('<H', self.data, nt+4)[0]
        if struct.unpack_from('<H', self.data, opt)[0] != 0x10B:
            raise ValueError('this inspector requires PE32')
        self.base = self.u32off(opt+28)
        self.image_size = self.u32off(opt+56)
        count = struct.unpack_from('<H', self.data, nt+6)[0]
        table = opt + struct.unpack_from('<H', self.data, nt+20)[0]
        self.sections = []
        for i in range(count):
            p = table+i*40
            name = self.data[p:p+8].rstrip(b'\0').decode()
            vs, rva, size, raw = struct.unpack_from('<4I', self.data, p+8)
            flags = self.u32off(p+36)
            self.sections.append(dict(name=name, virtual_size=vs, rva=rva, size=size, raw=raw, flags=flags))

    def u32off(self, offset):
        return struct.unpack_from('<I', self.data, offset)[0]

    def offset(self, va):
        rva = va-self.base
        for s in self.sections:
            if s['rva'] <= rva < s['rva']+s['size']:
                return s['raw']+rva-s['rva']
        raise ValueError(f'unmapped VA {va:x}')

    def va(self, offset):
        for s in self.sections:
            if s['raw'] <= offset < s['raw']+s['size']:
                return self.base+s['rva']+offset-s['raw']
        raise ValueError('unmapped offset')

    def u32(self, va): return self.u32off(self.offset(va))

    def refs(self, va):
        for match in re.finditer(re.escape(struct.pack('<I', va)), self.data):
            try: yield self.va(match.start())
            except ValueError: continue

    def executable(self, va):
        return any(s['flags'] & 0x20000000 and self.base+s['rva'] <= va < self.base+s['rva']+s['virtual_size'] for s in self.sections)

    def rtti(self, name):
        encoded = name.encode()+b'\0'
        td = self.va(self.data.index(encoded)-8)
        tables = []
        for ref in self.refs(td):
            col = ref-12
            try:
                sig, delta, cd, typ, hierarchy = struct.unpack_from('<5I', self.data, self.offset(col))
                if sig != 0 or delta > 0x1000 or cd != 0 or typ != td: continue
                hs, attrs, count, array = struct.unpack_from('<4I', self.data, self.offset(hierarchy))
                if hs != 0 or not 1 <= count <= 64: continue
                self.offset(array)
                for table_ref in self.refs(col):
                    vft = table_ref+4
                    slots = []
                    for i in range(64):
                        target = self.u32(vft+4*i)
                        if not self.executable(target): break
                        slots.append(target)
                    if slots:
                        tables.append(dict(vft=vft, subobject_offset=delta, col=col,
                                           slots=slots, references=list(self.refs(vft))))
            except (ValueError, struct.error): continue
        return dict(type_descriptor=td, tables=tables)


TYPES = ['ReplayPlayer', 'AvatarContextReplay', 'ReplayCameraController', 'GameCamera',
         'FreeCamera', 'GameScene', 'GameSceneController', 'SpectatorCameraController',
         'BaseSpectatorCameraController', 'FlexFOVCamera']


def inspect(path):
    pe = PE(path)
    names = [f'.?AV{t}@@' for t in TYPES] + ['.?AVRenderSystem@DAVA@@', '.?AVCamera@DAVA@@', '.?AVScene@DAVA@@']
    return dict(source=str(pe.path), sha256=hashlib.sha256(pe.data).hexdigest(), file_bytes=len(pe.data),
                machine=pe.machine, base=pe.base, image_size=pe.image_size, sections=pe.sections,
                types={name: pe.rtti(name) for name in names})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('exe', type=Path); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.exe)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    for name, item in result['types'].items():
        print(name, [(hex(t['vft']), hex(t['subobject_offset']), [hex(x) for x in t['references'][:6]]) for t in item['tables']])
