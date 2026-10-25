"""Read-only roster and UI tree inspection for a verified paused replay."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from blitzcam.memory import ReadOnlyMemory, find_process
from blitzcam.seek_trial import clock


def inspect_ui(snapshot):
    with ReadOnlyMemory(find_process(snapshot['pid'])) as m:
        live = lambda a: m.info.base + a - 0x400000
        ctx, player = int(snapshot['context'], 16), snapshot['source']['player']
        def guard():
            assert m.u32(ctx) == live(0x37F8A00) and m.u32(ctx + 0x1B0) == player
            c = clock(m, player, live(0x37C1F44))
            assert c['paused'] and c['raw'] == snapshot['clock']['raw']
        guard()
        arena = m.u32(ctx + 0x2C)
        assert m.u32(arena) == live(0x3844A04) and m.u32(arena + 0x34) == ctx
        head = m.u32(arena + 0x110)
        roster = []
        visited = set()
        def node(a):
            if a == head:
                return
            assert a not in visited and len(visited) < 64 and not m.read(a + 0xD, 1)[0]
            visited.add(a)
            node(m.u32(a))
            model = m.u32(a + 0x14)
            assert m.u32(model) == live(0x38449E8)
            key = m.u32(a + 0x10)
            assert key == m.u32(model + 0x18)
            roster.append(dict(id=key, model=hex(model), observer=m.u32(model + 0x80), team=m.u32(model + 0x28)))
            node(m.u32(a + 8))
        node(m.u32(head + 4))
        rows = []
        seen = set()
        def walk(a, parent='', depth=0):
            assert a not in seen and len(seen) < 10000 and depth < 40
            seen.add(a)
            name = m.read(m.u32(a + 0x30), 160).split(b'\0')[0].decode('utf-8', 'replace')
            path = parent + '/' + name
            count = m.u32(a + 0x48)
            rows.append(dict(address=hex(a), vft=hex(m.u32(a)), parent=hex(m.u32(a + 0x38)),
                             path=path, depth=depth, visible=bool(m.read(a + 0x4C, 1)[0] & 2), count=count))
            h = m.u32(a + 0x44)
            item = m.u32(h)
            n = 0
            while item != h:
                assert n < 1000
                child = m.u32(item + 8)
                assert m.u32(child + 0x38) == a
                walk(child, path, depth + 1)
                item = m.u32(item)
                n += 1
            assert n == count
        for key in ('0x5c', '0x60'):
            row = snapshot['visibility'][0]['layers'][key]
            a = int(row['address'], 16)
            assert m.u32(a) == int(row['vft'], 16)
            walk(a)
        guard()
        return dict(snapshot=snapshot, roster=roster, tree=rows,
                    tournament_rows=[r for r in rows if int(r['vft'], 16) == live(0x38491B8)],
                    marker_roots=[r for r in rows if r['path'].endswith('/SpectatorBothVehicleMarker')])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    result = inspect_ui(json.loads(args.snapshot.read_text()))
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(roster=result['roster'], tournament_row_count=len(result['tournament_rows']),
                          marker_count=len(result['marker_roots']),
                          top_controls=[r for r in result['tree'] if r['depth'] <= 1]), indent=2))
