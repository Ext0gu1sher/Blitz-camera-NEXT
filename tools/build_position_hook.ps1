$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$zigTool = Join-Path $taskRoot 'tools/zig-x86_64-windows-0.15.2/zig.exe'
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $taskRoot 'tools/zig-cache'
& $zigTool cc -target x86-windows-gnu -O2 -g -Wall -Wextra -shared blitzcam/native/position_hook_1121.c -o blitzcam/native/position_hook_1121.dll
if ($LASTEXITCODE) { throw 'Hook compilation failed' }
& $zigTool cc -target x86-windows-gnu -O2 -UNDEBUG blitzcam/native/position_hook_selftest.c -o blitzcam/native/position_hook_selftest.exe
if ($LASTEXITCODE) { throw 'Hook selftest compilation failed' }
& blitzcam/native/position_hook_selftest.exe
if ($LASTEXITCODE) { throw 'Hook native selftests failed' }
& $zigTool cc -target x86-windows-gnu -O2 -DHOOK_LAYOUT blitzcam/native/position_hook_1121.c -o blitzcam/native/position_hook_layout.exe
if ($LASTEXITCODE) { throw 'Hook layout compilation failed' }
& blitzcam/native/position_hook_layout.exe | Set-Content -Encoding utf8 blitzcam/native/position_hook_1121.json
@'
import hashlib,json,shutil
from pathlib import Path
from blitzcam.hook_layout import C,Config,Event,PathPoint,SpeedPoint,RECORDS,POINTS,SPEED_POINTS,SHARED_SIZE
p=Path('blitzcam/native/position_hook_1121.json')
d=json.loads(p.read_text(encoding='utf-8-sig'))
assert d['config_size']==C.sizeof(Config) and d['event_size']==C.sizeof(Event) and d['records']==RECORDS and d['points']==POINTS
assert d['path_point_size']==C.sizeof(PathPoint) and d['speed_points']==SPEED_POINTS and d['speed_point_size']==C.sizeof(SpeedPoint) and d['shared_size']==SHARED_SIZE
d['sha256']=hashlib.sha256(p.with_suffix('.dll').read_bytes()).hexdigest()
d['dll']='position_hook_1121.'+d['sha256'][:12]+'.dll'
shutil.copyfile(p.with_suffix('.dll'),p.parent/d['dll'])
p.write_text(json.dumps(d,indent=2),encoding='utf8')
print('Verified position Hook:',d['dll'])
'@ | python -X utf8 -B -
if ($LASTEXITCODE) { throw 'Hook manifest check failed' }
