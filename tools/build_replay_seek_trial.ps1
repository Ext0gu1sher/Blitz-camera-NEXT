$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$zigTool = Join-Path $taskRoot 'tools/zig-x86_64-windows-0.15.2/zig.exe'
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $taskRoot 'tools/zig-cache'
& $zigTool cc -target x86-windows-gnu -O2 -Wall -Wextra -shared blitzcam/native/replay_seek_trial_1121.c -o blitzcam/native/replay_seek_trial_1121.dll
if ($LASTEXITCODE) { throw 'Seek trial compilation failed' }
& $zigTool cc -target x86-windows-gnu -O2 -UNDEBUG blitzcam/native/replay_seek_trial_selftest.c -o blitzcam/native/replay_seek_trial_selftest.exe
if ($LASTEXITCODE) { throw 'Seek selftest compilation failed' }
& blitzcam/native/replay_seek_trial_selftest.exe
if ($LASTEXITCODE) { throw 'Seek selftest failed' }
& $zigTool cc -target x86-windows-gnu -O2 -DSEEK_LAYOUT blitzcam/native/replay_seek_trial_1121.c -o blitzcam/native/replay_seek_trial_layout.exe
if ($LASTEXITCODE) { throw 'Seek layout compilation failed' }
& blitzcam/native/replay_seek_trial_layout.exe | Set-Content -Encoding utf8 blitzcam/native/replay_seek_trial_1121.json
@'
import hashlib,json,shutil
from pathlib import Path
from blitzcam.seek_trial import Config,Header,C
p=Path('blitzcam/native/replay_seek_trial_1121.json')
d=json.loads(p.read_text(encoding='utf-8-sig'))
assert d==dict(config_size=C.sizeof(Config),header_size=C.sizeof(Header),header_offset=C.sizeof(Config),shared_size=C.sizeof(Config)+C.sizeof(Header))
d['sha256']=hashlib.sha256(p.with_suffix('.dll').read_bytes()).hexdigest()
d['dll']='replay_seek_trial_1121.'+d['sha256'][:12]+'.dll'
shutil.copyfile(p.with_suffix('.dll'),p.parent/d['dll'])
p.write_text(json.dumps(d,indent=2),encoding='utf8')
print(d)
'@ | python -X utf8 -B -
if ($LASTEXITCODE) { throw 'Seek layout mismatch' }
