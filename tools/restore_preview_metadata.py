"""Restore optional preview metadata from the pinned local Agent source checkout."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT/'blitzcam/preview_vendor'


def restore(source):
    source = Path(source)
    provenance = json.loads((VENDOR/'provenance.json').read_text(encoding='utf8'))
    expected = provenance['source_sha256']
    verified = {}
    for name in ('models.pb', 'tanks.pb'):
        data = (source/'data'/name).read_bytes()
        digest = expected.get('data/'+name) or expected['data'+chr(92)+name]
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Metadata does not match pinned Agent version: '+name)
        verified[name] = data
    # Check both files before writing either destination.
    destination = VENDOR/'data'
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in verified.items():
        target = destination/name
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
    return {'source_commit': provenance['agent_commit'], 'files': sorted(verified)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Local Agent source root containing data/models.pb and data/tanks.pb')
    args = parser.parse_args()
    print(json.dumps(restore(args.source)))
