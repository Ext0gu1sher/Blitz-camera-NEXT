"""Bundle this source release and its evidence, never any game executable/resource."""

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.1'


def main():
    files = []
    for folder in ('blitzcam', 'tests', 'examples', 'research/notes', 'tools'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    explicit = ['README.md', 'Start Camera Lab.cmd', 'research/runtime/readonly-session-evidence.json',
                'research/local/evidence.json', 'research/local/signature-check.json',
                'output/verification.json', 'output/offline-tests.txt', 'output/qa-project.json',
                'output/first-version-live-snapshot.json', 'output/first-version-live-recording.jsonl',
                'output/captures/20261013T170522715424Z.json', 'output/qa/workstation-live.jpg',
                'output/qa/workstation-final.jpg']
    explicit += ['output/1121-live-snapshot.json', 'output/1121-after-movement.json',
                 'output/1121-paused-recording.jsonl', 'output/1121-paused-recording.jsonl.summary.json',
                 'output/1121-manual-movement.jsonl', 'output/1121-manual-movement.jsonl.summary.json',
                 'output/1121-verification.json', 'output/1121-offline-tests.txt', 'output/1121-http-state.json']
    files.extend((ROOT/'research/builds/11.21.0.1235').glob('static-*'))
    explicit += ['research/builds/11.21.0.1235/build-identity.json', 'research/scripts/inspect_build.py', 'research/scripts/probe_1121_readonly.py',
                 'research/scripts/disassemble_local_bytes.py']
    files.extend(ROOT/name for name in explicit)
    files = sorted(set(files))
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing:
        raise RuntimeError(f'Missing release inputs: {missing}')
    output = ROOT/'dist'/f'BlitzCameraLab-{VERSION}.zip'
    output.parent.mkdir(exist_ok=True)
    prefix = f'BlitzCameraLab-{VERSION}/'
    manifest = {'version': VERSION, 'scope': 'read-only capture and offline path authoring; no live game write',
                'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in files:
            archive.write(p, prefix+p.relative_to(ROOT).as_posix())
        archive.writestr(prefix+'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256.txt').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(json.dumps({'path': str(output), 'sha256': digest, 'files': len(files), 'bytes': output.stat().st_size}))


if __name__ == '__main__':
    main()
