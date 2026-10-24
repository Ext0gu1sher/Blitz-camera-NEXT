$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$zigTool = Join-Path $taskRoot 'tools/zig-x86_64-windows-0.15.2/zig.exe'
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $taskRoot 'tools/zig-cache'
& $zigTool cc -target x86-windows-gnu -O2 -g -Wall -Wextra -shared blitzcam/native/replay_time_trial_1121.c -o blitzcam/native/replay_time_trial_1121.dll
if ($LASTEXITCODE) { throw 'Replay trial build failed' }
& $zigTool cc -target x86-windows-gnu -O2 -UNDEBUG blitzcam/native/replay_time_trial_selftest.c -o blitzcam/native/replay_time_trial_selftest.exe
if ($LASTEXITCODE) { throw 'Replay trial selftest build failed' }
& blitzcam/native/replay_time_trial_selftest.exe
if ($LASTEXITCODE) { throw 'Replay trial selftest failed' }
& $zigTool cc -target x86-windows-gnu -O2 -DREPLAY_LAYOUT blitzcam/native/replay_time_trial_1121.c -o blitzcam/native/replay_time_trial_layout.exe
if ($LASTEXITCODE) { throw 'Replay trial layout build failed' }
& blitzcam/native/replay_time_trial_layout.exe | Set-Content -Encoding utf8 blitzcam/native/replay_time_trial_1121.json
@'
import ctypes as C,hashlib,json,shutil
from pathlib import Path
from blitzcam.replay_trial import Config,Header,Event,EVENTS,CAP
p=Path('blitzcam/native/replay_time_trial_1121.json')
d=json.loads(p.read_text(encoding='utf-8-sig'))
assert d['config_size']==C.sizeof(Config) and d['header_size']==C.sizeof(Header)
assert d['event_size']==C.sizeof(Event) and d['events_offset']==EVENTS
assert d['shared_size']==EVENTS+CAP*C.sizeof(Event)
d['sha256']=hashlib.sha256(p.with_suffix('.dll').read_bytes()).hexdigest()
d['dll']='replay_time_trial_1121.'+d['sha256'][:12]+'.dll'
shutil.copyfile(p.with_suffix('.dll'),p.parent/d['dll'])
p.write_text(json.dumps(d,indent=2),encoding='utf8')
print('Verified replay trial:',d['dll'])
'@ | python -X utf8 -B -
if ($LASTEXITCODE) { throw 'Replay trial layout mismatch' }
