"""Bounded read-only decoder for the observed Blitz 11.21 KA2 scene archive.

This is a resource inspector, not an engine SDK. Unknown encodings fail closed.
The KA1 reference is historical DAVA source; KA2 is checked against local bytes.
"""
import struct


class Archive(dict):
    def __init__(self, offset):
        super().__init__()
        self.offset = offset


class Decoder:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.strings = {}
        self.items = 0

    def take(self, n):
        if n < 0 or self.pos+n > len(self.data):
            raise ValueError(f'Truncated archive at {self.pos}')
        value = self.data[self.pos:self.pos+n]
        self.pos += n
        return value

    def unpack(self, fmt):
        return struct.unpack('<'+fmt, self.take(struct.calcsize('<'+fmt)))

    def count(self, limit=1000000):
        n, = self.unpack('I')
        if n > limit:
            raise ValueError(f'Unbounded collection at {self.pos-4}')
        return n

    def string(self):
        key, = self.unpack('I')
        if key not in self.strings:
            raise ValueError(f'Unknown string hash {key:x} at {self.pos-4}')
        return self.strings[key]

    def archive(self, depth=0):
        if depth > 100:
            raise ValueError('Archive nesting limit')
        start = self.pos
        if self.take(2) != b'KA' or self.take(1) != b'\x02':
            raise ValueError(f'Expected observed KA2 at {start}')
        shared, = self.unpack('B')
        if shared == 255:
            result = Archive(start)
            result.end = self.pos
            return result
        if shared == 0:
            names = [self.take(self.unpack('H')[0]).decode('utf8') for _ in range(self.count())]
            hashes = self.unpack('I'*len(names))
            if len(set(hashes)) != len(hashes):
                raise ValueError('String hash collision')
            self.strings = dict(zip(hashes, names))
        elif shared != 1 or not self.strings:
            raise ValueError('Unknown KA2 string table mode')
        result = Archive(start)
        for _ in range(self.count()):
            key = self.string()
            if key in result:
                raise ValueError('Duplicate archive key')
            result[key] = self.variant(depth+1)
        result.end = self.pos
        return result

    def variant(self, depth):
        self.items += 1
        if self.items > 3000000 or depth > 100:
            raise ValueError('Resource complexity limit')
        t, = self.unpack('B')
        formats = {1:'?', 2:'i', 3:'f', 7:'I', 9:'q', 10:'Q', 11:'2f', 12:'3f',
                   13:'4f', 14:'4f', 15:'9f', 16:'16f', 17:'4f', 19:'6f',
                   21:'d', 22:'b', 23:'B', 24:'h', 25:'H', 29:'10f'}
        if t == 0:
            return None
        if t in formats:
            value = self.unpack(formats[t])
            return value[0] if len(value) == 1 else value
        if t in (4, 18, 20):
            return self.string()
        if t == 6:
            return self.take(self.count(len(self.data)))
        if t == 8:
            length = self.count(len(self.data)); end = self.pos+length
            value = self.archive(depth)
            if self.pos != end:
                raise ValueError(f'Nested archive length mismatch at {value.offset}')
            return value
        if t == 27:
            return [self.variant(depth+1) for _ in range(self.count())]
        raise ValueError(f'Unsupported variant {t} at {self.pos-1}')


def scene(data):
    decoder = Decoder(data)
    if decoder.take(4) != b'SFV2':
        raise ValueError('Not SC2')
    version, root_count = decoder.unpack('II')
    if version != 48 or decoder.take(8) != b'KA\x01\x00\x00\x00\x00\x00':
        raise ValueError('Scene differs from observed version 48 with empty tags')
    descriptor_size, = decoder.unpack('I')
    decoder.take(descriptor_size)
    root = decoder.archive()
    if decoder.pos != len(data):
        raise ValueError(f'Unconsumed scene bytes {len(data)-decoder.pos}')
    if len(root.get('#hierarchy', [])) != root_count:
        raise ValueError('Root node count mismatch')
    return root


def walk(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from walk(child, path+(key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, path+(index,))
