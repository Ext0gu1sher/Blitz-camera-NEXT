$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$zigTool = Join-Path $taskRoot 'tools/zig-x86_64-windows-0.15.2/zig.exe'
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $taskRoot 'tools/zig-cache'
& $zigTool cc -target x86-windows-gnu -O2 -Wall -Wextra -shared blitzcam/native/replay_seek_phase_trial_1121.c -o blitzcam/native/replay_seek_phase_trial_1121.dll
if ($LASTEXITCODE) { throw 'Phase trial compilation failed' }
& $zigTool cc -target x86-windows-gnu -O2 -UNDEBUG blitzcam/native/replay_seek_phase_selftest.c -o blitzcam/native/replay_seek_phase_selftest.exe
if ($LASTEXITCODE) { throw 'Phase selftest compilation failed' }
& blitzcam/native/replay_seek_phase_selftest.exe
if ($LASTEXITCODE) { throw 'Phase selftest failed' }
& $zigTool cc -target x86-windows-gnu -O2 -Wall -Wextra -UNDEBUG blitzcam/native/replay_ui_component_selftest.c -o blitzcam/native/replay_ui_component_selftest.exe
if ($LASTEXITCODE) { throw 'UI component selftest compilation failed' }
& blitzcam/native/replay_ui_component_selftest.exe
if ($LASTEXITCODE) { throw 'UI component selftest failed' }
& blitzcam/native/replay_ui_component_selftest.exe --corrupt
if ($LASTEXITCODE) { throw 'UI component invariant selftest failed' }
& $zigTool cc -target x86-windows-gnu -O2 -DSEEK_LAYOUT blitzcam/native/replay_seek_phase_trial_1121.c -o blitzcam/native/replay_seek_phase_layout.exe
if ($LASTEXITCODE) { throw 'Phase layout compilation failed' }
& blitzcam/native/replay_seek_phase_layout.exe | Set-Content -Encoding utf8 blitzcam/native/replay_seek_phase_trial_1121.json
@'
import hashlib,json,shutil
from pathlib import Path
from blitzcam.seek_phase_trial import Config,Header,UiRepairState,C
from research.scripts.inspect_ui_component_repair import inspect
assert len(inspect('output/native-selftest-ui-relocation.bin')['callback_storage_changes'])==1
assert len(inspect('output/native-selftest-ui-corrupt.bin')['invariant_failures'])==2
p=Path('blitzcam/native/replay_seek_phase_trial_1121.json')
d=json.loads(p.read_text(encoding='utf-8-sig'))
assert {k:d[k] for k in ('config_size','header_size','header_offset','shared_size')}==dict(config_size=C.sizeof(Config),header_size=C.sizeof(Header),header_offset=C.sizeof(Config),shared_size=C.sizeof(Config)+C.sizeof(Header))
assert d['ui_state_size']==C.sizeof(UiRepairState) and d['ui_event_size']==48
d['sha256']=hashlib.sha256(p.with_suffix('.dll').read_bytes()).hexdigest()
d['dll']='replay_seek_phase_trial_1121.'+d['sha256'][:12]+'.dll'
shutil.copyfile(p.with_suffix('.dll'),p.parent/d['dll'])
p.write_text(json.dumps(d,indent=2),encoding='utf8')
print(d)
'@ | python -X utf8 -B -
if ($LASTEXITCODE) { throw 'Phase layout mismatch' }
