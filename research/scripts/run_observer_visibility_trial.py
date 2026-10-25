"""Bounded local-replay-only UI visibility trial; source/scene guards required."""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inspect_observer_trial import inspect
from inspect_observer_ui import inspect_ui
from verify_freecamera_switch import prepare, Config as BaseConfig, Header
from blitzcam.hook_transport import Remote, pe_exports, relocated_code
from blitzcam.hook_layout import plain
from blitzcam.memory import ReadOnlyMemory, find_process
from blitzcam.reader import CameraSession
from blitzcam.seek_trial import clock

FOLDER = ROOT / 'output/observer-replay-trial-20261024'


class Config(C.Structure):
    _pack_ = 4
    _fields_ = BaseConfig._fields_ + [
        ('battle_controller', C.c_uint32), ('battle', C.c_uint32),
        ('battle_screen', C.c_uint32), ('layers', C.c_uint32 * 5),
        ('layer_vfts', C.c_uint32 * 5), ('visible_entry', C.c_uint32),
        ('target_mask', C.c_uint32), ('extra_count', C.c_uint32),
        ('extras', (C.c_uint32 * 5) * 16)] + [
        (n, C.c_uint32) for n in ('ghost_enabled', 'ghost_bpi', 'ghost_logic', 'ghost_vehicle',
                                  'ghost_visual', 'ghost_entry', 'ghost_class', 'ghost_count')
        ] + [('ghost_nodes', (C.c_uint32 * 8) * 256)] + [
        (n, C.c_uint32) for n in ('opacity_count','opacity_type','opacity_index','opacity_get_entry','opacity_set_entry')
        ] + [('opacity_rows', (C.c_uint32 * 7) * 16)]

CLEAN_PATHS = ['/BattleUILayer/AimContainer'] + [
    '/HUDLayer/' + n for n in ('BottomHUDLayoutProtector', 'Ammo', 'ConsumablesPanel',
    'DestroyTimer', 'RibbonsContainerLayoutProtector', 'DamageStatisticsContainerLayoutProtector',
    'ShootButtonsLayer', 'FollowAimSwitch', 'PostmortemButtonsContainer',
    'RespawnPanelContainer', 'cancelShootButton')]


def opacity_component(m, control, index):
    assert 0 <= index <= 255
    slot = m.u32(m.u32(m.u32(control + 0xf0) + 0x24) + index * 4)
    if slot == 0xffffffff:
        return 0
    begin, end = m.u32(control + 0xe4), m.u32(control + 0xe8)
    assert 0 <= end-begin <= 4096 and (end-begin)%12 == 0 and slot < (end-begin)//12
    first, last = m.u32(begin+slot*12), m.u32(begin+slot*12+4)
    if first == last:
        return 0
    assert last-first == 4
    q = m.u32(first)
    assert m.u32(q) == m.info.base+0x3781ee4-0x400000 and m.u32(q+8) == control
    return q


def ghost_snapshot(m, s, context):
    bpi = m.u32(context + 0x1ac)
    logic = m.u32(bpi + 0x10)
    vehicle, visual = m.u32(logic + 4), m.u32(logic + 0x74)
    assert m.u32(bpi + 0xc) == m.u32(visual + 0x58) == 0x70000001
    assert m.u32(bpi + 0x18) == 2
    for address, vft in [(logic, 0x38023d4), (vehicle, 0x37f7d8c), (visual, 0x3713afc)]:
        assert m.u32(address) == s.live(vft)
    cls = m.u32(s.live(0x471ef94))
    assert m.read(cls, 9) == b'\0\0\0\0User\0'
    rows, seen = [], set()

    def visit(a, parent, depth):
        assert a not in seen and len(seen) < 256 and depth < 32
        seen.add(a)
        begin, end = m.u32(a + 8), m.u32(a + 12)
        assert 0 <= end - begin <= 1024 and (end - begin) % 4 == 0
        assert m.u32(a + 0x18) == parent
        rows.append([a, parent, m.u32(a), begin, end, m.u32(a + 0x48), m.u32(a + 0x4c), 0])
        for p in range(begin, end, 4):
            visit(m.u32(p), a, depth + 1)

    visit(visual, m.u32(visual + 0x18), 0)
    return dict(bpi=bpi, logic=logic, vehicle=vehicle, visual=visual, cls=cls, nodes=rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--action', choices=['probe', 'show', 'restore'], required=True)
    p.add_argument('--restore-report', type=Path)
    p.add_argument('--url')
    p.add_argument('--manifest', type=Path, default=FOLDER / 'manifest.json')
    p.add_argument('--clean', action='store_true', help='Show tournament layers while hiding identified personal UI roots')
    p.add_argument('--hide-ghost', action='store_true', help='Hide only the materialized virtual observer entity')
    p.add_argument('--suppress-personal', action='store_true', help='Use native opacity components for persistent personal UI suppression')
    args = p.parse_args()
    report = {'action': args.action, 'passed': False}
    run = args.manifest.resolve().parent / (datetime.now(timezone.utc).strftime('%H%M%S%f') + '-' + args.action)
    run.mkdir()
    try:
        service = json.loads((ROOT / 'output/workstation-service.json').read_text())
        with urllib.request.urlopen((args.url or service['url']).rstrip('/') + '/api/state', timeout=10) as response:
            state = json.load(response)
        assert not state['playback']['active'] and state['playback'].get('hooks_detached', True)
        snap = inspect()
        manifest = json.loads(args.manifest.read_text())
        assert snap['source_sha256'] == manifest['trial_sha256']
        assert snap['root_count'] == 1 and snap['free_camera_active'] and snap['model_mode'] == 2
        assert len(snap['visibility']) == 1 and snap['visibility'][0]['counter_158'] == 0
        report['snapshot_before'] = snap
        with ReadOnlyMemory(find_process(snap['pid'])) as m:
            s = CameraSession(m)
            original, chain, before = prepare(s, 1, 0)
            assert original.context == int(snap['context'], 16)
            c = Config()
            for name, _ in BaseConfig._fields_:
                setattr(c, name, getattr(original, name))
            c.magic, c.size, c.execute = 0x34485542, C.sizeof(Config), int(args.action != 'probe')
            v = snap['visibility'][0]
            c.battle_controller, c.battle, c.battle_screen = (int(v[k], 16) for k in ('controller', 'battle', 'screen'))
            layer_addresses = [int(v['layers'][hex(o)]['address'], 16) for o in (0x5C, 0x60, 0x68, 0x6C)]
            layer_addresses.append(m.u32(layer_addresses[1] + 0x260))
            for i, address in enumerate(layer_addresses):
                c.layers[i], c.layer_vfts[i] = address, m.u32(address)
            mask = lambda: sum(((m.read(a + 0x4C, 1)[0] >> 1) & 1) << i for i, a in enumerate(layer_addresses))
            report['before_mask'] = mask()
            report['layers'] = [hex(a) for a in layer_addresses]
            c.target_mask = 31
            extra_rows = []
            prior = None
            if args.clean:
                assert args.action in ('show', 'probe')
                ui = inspect_ui(snap)
                (run / 'ui-before.json').write_text(json.dumps(ui, indent=2) + '\n', encoding='utf-8')
                for path in CLEAN_PATHS:
                    hits = [r for r in ui['tree'] if r['path'] == path]
                    assert len(hits) == 1, path
                    row = hits[0]
                    extra_rows.append(dict(path=path, control=int(row['address'], 16),
                                           parent=int(row['parent'], 16), vft=int(row['vft'], 16),
                                           before_visible=int(row['visible']), desired=0))
                c.target_mask = 3  # world markers + tournament HUD; omit direction/notification controls
            if args.action == 'restore':
                assert args.restore_report is not None
                prior = json.loads(args.restore_report.read_text())
                assert prior['layers'] == report['layers'] and prior['snapshot_before']['context'] == snap['context']
                c.target_mask = prior['before_mask']
                extra_rows = [dict(row, desired=row['before_visible']) for row in prior.get('extras', [])]
            assert len(extra_rows) <= 16
            for i, row in enumerate(extra_rows):
                a = row['control']
                assert m.u32(a) == row['vft'] and m.u32(a + 0x38) == row['parent']
                name = m.u32(a + 0x30)
                assert m.read(name, 160).split(b'\0')[0].decode() == row['path'].rsplit('/', 1)[1]
                c.extras[i][:] = [a, row['parent'], row['vft'], name, row['desired']]
            c.extra_count = len(extra_rows)
            report['extras'] = extra_rows
            opacity_rows = []
            if args.suppress_personal or (prior and prior.get('opacity')):
                c.opacity_type, c.opacity_index = m.u32(s.live(0x4695104)), m.u32(s.live(0x4696d94))
                c.opacity_get_entry, c.opacity_set_entry = s.live(0xce2d60), s.live(0x102ab30)
                if args.suppress_personal:
                    assert args.clean and args.action in ('probe', 'show')
                    hits = [r for r in ui['tree'] if r['path'] in ('/HUDLayer/Ammo','/HUDLayer/ConsumablesPanel','/BattleUILayer/EnemyMarker')]
                    assert len(hits) == 9 and sum(r['path'].endswith('/EnemyMarker') for r in hits) == 7
                    for row in hits:
                        a = int(row['address'],16); q = opacity_component(m,a,c.opacity_index)
                        opacity_rows.append(dict(path=row['path'],control=a,parent=int(row['parent'],16),vft=int(row['vft'],16),
                            name=m.u32(a+0x30),component=q,before=m.u32(q+0x14) if q else 0x3f800000,desired=0))
                else:
                    for old in prior['opacity']:
                        a=old['control'];q=opacity_component(m,a,c.opacity_index)
                        assert q and m.u32(q+0x14)==old['desired']
                        opacity_rows.append(dict(old,component=q,before=m.u32(q+0x14),desired=old['before']))
                c.opacity_count=len(opacity_rows)
                for i,row in enumerate(opacity_rows):
                    assert m.read(row['name'],160).split(b'\0')[0].decode()==row['path'].rsplit('/',1)[1]
                    c.opacity_rows[i][:]=[row[k] for k in ('control','parent','vft','name','component','before','desired')]
            report['opacity']=opacity_rows
            if args.hide_ghost or (prior and prior.get('ghost')):
                if args.hide_ghost:
                    assert args.action in ('show', 'probe')
                    assert manifest['trial_sha256'] in {
                        '35d3159d5b3f662539202fbdbb0ad3ed71ad4d8f9cafc5bafa4b7175e65323af',
                        'cee9bb68878dce8b1d217ec2427a4eff2b8bca540a7717c2e7fdd9cda5be18d7',
                        '8381de0f2474ed79804aeae31e11f0d24a39df42f8d7204213874fe36f8056df',
                    }
                ghost = ghost_snapshot(m, s, c.context)
                if prior and prior.get('ghost'):
                    old = prior['ghost']
                    assert all(ghost[k] == old[k] for k in ('bpi', 'logic', 'vehicle', 'visual', 'cls'))
                    assert len(ghost['nodes']) == len(old['nodes'])
                    for row, old_row in zip(ghost['nodes'], old['nodes']):
                        assert row[:5] == old_row[:5]
                        row[7] = int(not (old_row[5] & 1))
                c.ghost_enabled = 1
                c.ghost_bpi, c.ghost_logic, c.ghost_vehicle, c.ghost_visual, c.ghost_class = (
                    ghost[k] for k in ('bpi', 'logic', 'vehicle', 'visual', 'cls'))
                c.ghost_entry = s.live(0xd71ef0)
                c.ghost_count = len(ghost['nodes'])
                for i, row in enumerate(ghost['nodes']):
                    c.ghost_nodes[i][:] = row
                report['ghost'] = ghost
            c.visible_entry = s.live(0xD05020)
            code = relocated_code(s.info.path, s.info.base)
            rva, size = 0xD05020 - 0x400000, 0xA0
            expected = [b[rva - a:rva - a + size] for a, b in code.items() if a <= rva and rva + size <= a + len(b)]
            assert len(expected) == 1 and m.read(c.visible_entry, size) == expected[0]
            if c.opacity_count:
                for va,length in [(0xce2d60,0x125),(0x102ab30,0x1b8)]:
                    rva=va-0x400000
                    expected=[b[rva-a:rva-a+length] for a,b in code.items() if a<=rva and rva+length<=a+len(b)]
                    assert len(expected)==1 and m.read(s.live(va),length)==expected[0]
            if c.ghost_enabled:
                for va, length in [(0xd71ef0, 0x15), (0xd71e50, 0x91), (0xdbddc0, 0x8b)]:
                    rva = va - 0x400000
                    expected = [b[rva-a:rva-a+length] for a, b in code.items() if a <= rva and rva+length <= a+len(b)]
                    assert len(expected) == 1 and m.read(s.live(va), length) == expected[0]
            compiled = FOLDER / 'observer_hud_visibility_1121.dll'
            digest = hashlib.sha256(compiled.read_bytes()).hexdigest()
            dll = FOLDER / ('observer_hud_visibility_1121.' + digest[:12] + '.dll')
            if not dll.exists():
                shutil.copyfile(compiled, dll)
            assert hashlib.sha256(dll.read_bytes()).hexdigest() == digest
            def as_plain(v):
                return [as_plain(x) for x in v] if isinstance(v, C.Array) else v
            report.update(config={k: as_plain(getattr(c, k)) for k, _ in Config._fields_},
                          dll_sha256=digest, clock_before=before)

            def journal(row):
                with (run / 'operations.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(row) + '\n')

            with Remote(s, journal) as driver:
                exports = pe_exports(dll)
                base = driver.load(dll)
                shared, offset = base + exports['g_shared'], C.sizeof(Config)
                read = lambda: Header.from_buffer_copy(m.read(shared + offset, C.sizeof(Header)))
                h = read()
                assert not (h.active or h.queued) and h.status in (0, 4, -1)
                driver.write_bounds = (shared, shared + C.sizeof(Config) + C.sizeof(Header))
                driver.write(shared, bytes(c), 'owned observer visibility config')
                driver.write(shared + offset, bytes(Header()), 'owned observer visibility status')
                beat = lambda: driver.write(shared + offset, struct.pack('<I', driver.k.GetTickCount() & 0xFFFFFFFF), 'owned watchdog')
                driver.detach_address = base + exports['HookDetach@4']
                driver.detach_probe = lambda: not (read().active or read().queued) and m.u32(c.functor + 0x10) == c.tick_entry
                try:
                    beat()
                    result = driver.call(base + exports['HookAttach@4'], 0, 'one UI visibility job on paused local replay')
                    assert result == 0, f'Attach rejected {result}'
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        h = read()
                        if h.status in (1, 2):
                            beat()
                        assert not h.error and h.status != -1, f'Native guard {h.error}'
                        if h.status == 4 and not h.active and not h.queued:
                            break
                        time.sleep(0.025)
                    else:
                        raise RuntimeError('Timed out; no resubmission')
                    report['native'] = plain(h)
                    assert h.thread == h.job_thread and h.job_calls == 1 and h.detached
                finally:
                    driver.call(driver.detach_address, 0, 'finish observer visibility job')
                    assert driver.detach_probe(), 'Incomplete callback cleanup'
                    driver.detach_address = None
            after = clock(m, c.player, s.vft['ReplayPlayer'])
            report.update(after_mask=mask(), clock_after=after, hooks_detached=True)
            assert all(after[k] == before[k] for k in ('raw', 'origin', 'rate', 'paused'))
            assert m.u32(c.scene + 0x120) == c.free_camera
            assert report['after_mask'] == (c.target_mask if c.execute else report['before_mask'])
            for row in opacity_rows:
                q=opacity_component(m,row['control'],c.opacity_index)
                if c.execute:
                    assert q and m.u32(q+0x14)==row['desired']
                else:
                    assert q==row['component'] and (not q or m.u32(q+0x14)==row['before'])
                row['after_component']=q
            if c.execute:
                assert all(((m.read(r['control'] + 0x4C, 1)[0] >> 1) & 1) == r['desired'] for r in extra_rows)
            if c.ghost_enabled:
                after_ghost = ghost_snapshot(m, s, c.context)
                assert len(after_ghost['nodes']) == c.ghost_count
                for row, old in zip(after_ghost['nodes'], report['ghost']['nodes']):
                    assert row[:5] == old[:5]
                    assert row[5:7] == ([((old[5] & ~1) | int(not old[7])), old[6]] if c.execute else old[5:7])
                report['ghost_after'] = after_ghost
            report['passed'] = True
    except BaseException as exc:
        report['error'] = str(exc)
        raise
    finally:
        (run / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('REPORT', run / 'report.json')
        print(json.dumps({k: report.get(k) for k in ('passed', 'action', 'before_mask', 'after_mask', 'native', 'error')}, indent=2))


if __name__ == '__main__':
    main()
