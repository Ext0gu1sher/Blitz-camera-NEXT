"""Build an isolated, reproducible extension of the supported camera driver."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/tank-tracking-experiment/native'


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'blitzcam/native/position_hook_1121.c').read_text()
    extension = (ROOT / 'research/native/tank_tracking_1121.h').read_text()
    generated = source
    changes = [
        ('static uint32_t stage(double t)', extension + '\nstatic uint32_t stage(double t)'),
        ('PathPoint pose=path(t);Vec p=pose.position',
         'PathPoint pose=path(t);int te=tracking_pose(&pose,t);if(te){fail(te);InterlockedDecrement(&g_shared.active);return;}Vec p=pose.position'),
        ('InterlockedExchange(&e->commit,index+1);\n}',
         'tracking_record(index,kind);InterlockedExchange(&e->commit,index+1);\n}'),
        ('armed=0;clock_attached=0;g_shared.clock_raw=c->raw_time;',
         'if(!tracking_validate())return 130;armed=0;clock_attached=0;g_shared.clock_raw=c->raw_time;'),
        ('static UpdateFn original_update;', 'static uintptr_t tracking_scene_table[39];\nstatic int tracking_type_match(uint32_t,uint32_t);\nstatic void tracking_detach(void);\nstatic UpdateFn original_update;'),
        ('readable(p,4)&&U(p,0)==v;', 'readable(p,4)&&(U(p,0)==v||tracking_type_match(p,v));'),
        ('static void detach(void){', 'static void detach(void){\n tracking_detach();'),
        ('static void __fastcall update_hook(void*self,void*unused,float dt){\n (void)unused;',
         'static void tracking_camera_update(float dt){'),
        ('original_update(self,dt);InterlockedIncrement(&g_shared.updates);',
         'InterlockedIncrement(&g_shared.updates);'),
        ('static void __fastcall draw_hook(void*self,void*unused,void*render){',
         'static void __fastcall update_hook(void*self,void*unused,float dt){\n (void)unused;original_update(self,dt);if(!g_tracking.cfg.phase)tracking_camera_update(dt);\n}\nstatic void __fastcall draw_hook(void*self,void*unused,void*render){'),
        ('clock_attached=1;\n }\n return 0;', 'clock_attached=1;\n }\n if(!tracking_attach()){fail(33);return 133;}\n return 0;'),
    ]
    # Do replacements in the original BEFORE inserting the extension: its own
    # record publication deliberately has the same atomic commit idiom.
    for old, new in changes[1:] + changes[:1]:
        if generated.count(old) != 1:
            raise RuntimeError(f'Production source changed; review insertion: {old}')
        generated = generated.replace(old, new)
    (OUT / 'tracking_generated.c').write_text(generated)
    zig = ROOT / 'tools/zig-x86_64-windows-0.15.2/zig.exe'
    env = {**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(ROOT / 'tools/zig-cache')}
    common = [str(zig), 'cc', '-target', 'x86-windows-gnu', '-O2', '-Wall', '-Wextra',
              '-I', str(ROOT / 'blitzcam/native')]
    def run(args):
        result=subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode:raise RuntimeError(result.stderr or result.stdout or f'Build step failed: {args[0]}')
        return result.stdout
    run([*common, '-shared', str(OUT/'tracking_generated.c'), '-o', str(OUT/'tracking.dll')])
    run([*common, '-UNDEBUG', '-I', str(OUT), str(ROOT/'research/native/tank_tracking_selftest.c'), '-o', str(OUT/'selftest.exe')])
    print(run([str(OUT/'selftest.exe')]).strip())
    run([*common, '-DHOOK_LAYOUT', str(OUT/'tracking_generated.c'), '-o', str(OUT/'layout.exe')])
    manifest = json.loads(run([str(OUT/'layout.exe')]))
    dll = (OUT/'tracking.dll').read_bytes()
    manifest['sha256'] = hashlib.sha256(dll).hexdigest()
    manifest['dll'] = f"position_hook_1121.{manifest['sha256'][:12]}.dll"
    manifest['production_source_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    manifest['extension_sha256'] = hashlib.sha256(extension.encode()).hexdigest()
    immutable=OUT/manifest['dll']
    if immutable.exists():
        if immutable.read_bytes()!=dll:raise RuntimeError('Content-addressed DLL collision.')
    else:immutable.write_bytes(dll)
    (OUT/'position_hook_1121.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'built': str(OUT/manifest['dll']), 'production_unchanged': True}))


if __name__ == '__main__':
    build()
