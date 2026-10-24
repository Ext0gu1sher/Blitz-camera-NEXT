"""Decode replay UI resources into the research folder; installation is read-only."""
from pathlib import Path
import hashlib,json,struct,zlib
import lz4.block
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(r'C:\Program Files (x86)\Steam\steamapps\common\World of Tanks Blitz\Data\UI\Screens3\Battle\Replay')
OUT=ROOT/'builds/11.21.0.1235/replay-ui';OUT.mkdir(exist_ok=True)
evidence=[]
paths=list(SOURCE.glob('*.dvpl'))+[SOURCE.parents[2]/'Screens/Battle/BattleScreenReplay.yaml.dvpl',SOURCE.parent/'BattleScreen.yaml.dvpl']
for p in sorted(paths):
    b=p.read_bytes();usize,csize,crc,method,magic=struct.unpack('<IIII4s',b[-20:]);payload=b[:-20]
    assert magic==b'DVPL' and len(payload)==csize and zlib.crc32(payload)==crc
    if method==0:decoded=payload
    elif method in (1,2):decoded=lz4.block.decompress(payload,uncompressed_size=usize)
    else:raise ValueError(method)
    assert len(decoded)==usize
    (OUT/p.stem).write_bytes(decoded)
    evidence.append({'source':str(p),'sha256':hashlib.sha256(b).hexdigest(),'compression':method,'crc_verified':True})
(OUT/'sources.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
print(OUT)
