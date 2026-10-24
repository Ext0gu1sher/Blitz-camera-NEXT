$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$zigTool = Join-Path $taskRoot 'tools/zig-x86_64-windows-0.15.2/zig.exe'
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $taskRoot 'tools/zig-cache'
& $zigTool cc -target x86-windows-gnu -O2 -Wall -Wextra -shared blitzcam/native/freecamera_switch_1121.c -o blitzcam/native/freecamera_switch_1121.dll
if ($LASTEXITCODE) { throw 'Free-camera compilation failed' }
& $zigTool cc -target x86-windows-gnu -O2 -UNDEBUG blitzcam/native/freecamera_switch_selftest.c -o blitzcam/native/freecamera_switch_selftest.exe
if ($LASTEXITCODE) { throw 'Free-camera selftest compilation failed' }
& blitzcam/native/freecamera_switch_selftest.exe
if ($LASTEXITCODE) { throw 'Free-camera selftest failed' }
& $zigTool cc -target x86-windows-gnu -O2 -DCAMERA_LAYOUT blitzcam/native/freecamera_switch_1121.c -o blitzcam/native/freecamera_switch_layout.exe
if ($LASTEXITCODE) { throw 'Free-camera layout compilation failed' }
& blitzcam/native/freecamera_switch_layout.exe | Set-Content -Encoding utf8 blitzcam/native/freecamera_switch_1121.json
@'
import ctypes as C,hashlib,json,shutil
from pathlib import Path
from blitzcam.freecamera import Config,Header
p=Path('blitzcam/native/freecamera_switch_1121.json')
d=json.loads(p.read_text(encoding='utf-8-sig'))
assert d==dict(config_size=C.sizeof(Config),header_size=C.sizeof(Header),shared_size=C.sizeof(Config)+C.sizeof(Header))
d['sha256']=hashlib.sha256(p.with_suffix('.dll').read_bytes()).hexdigest()
d['dll']='freecamera_switch_1121.'+d['sha256'][:12]+'.dll'
shutil.copyfile(p.with_suffix('.dll'),p.parent/d['dll'])
p.write_text(json.dumps(d,indent=2),encoding='utf8')
print(d)
'@ | python -X utf8 -B -
if ($LASTEXITCODE) { throw 'Free-camera layout mismatch' }
