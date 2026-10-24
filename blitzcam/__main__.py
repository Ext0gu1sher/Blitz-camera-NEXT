"""CLI capture/record are read-only; the UI separately supports explicit playback."""

import argparse
import json
from pathlib import Path
import sys

from .profile import CameraError
from .project import atomic_json, read_project, samples
from .reader import CameraSession
from .recording import record_session
from . import __version__


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=f"Blitz Camera Lab {__version__} · 摄像机属性关键帧与回放运镜")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("inspect", "capture", "record"):
        c = commands.add_parser(name); c.add_argument("--pid", type=int)
        if name in ("capture", "record"): c.add_argument("--out", type=Path, required=True)
        if name == "record":
            c.add_argument("--seconds", type=float, default=5); c.add_argument("--hz", type=float, default=50)
    c = commands.add_parser("sample"); c.add_argument("project", type=Path); c.add_argument("--hz", type=float, default=100); c.add_argument("--out", type=Path, required=True)
    c = commands.add_parser("serve"); c.add_argument("--project", type=Path); c.add_argument("--port", type=int, default=0); c.add_argument("--no-browser", action="store_true")
    c = commands.add_parser("overlay", help="启动或显示透明悬浮摄影面板"); c.add_argument("--project", type=Path); c.add_argument("--port", type=int, default=0)
    c = commands.add_parser("desktop", help="启动独立桌面工作台"); c.add_argument("--project", type=Path); c.add_argument("--port", type=int, default=0)
    args = p.parse_args(argv)
    try:
        if args.command in ("overlay", "desktop"):
            from .desktop import launch
            launch(args.project,args.port,view='workbench' if args.command == 'desktop' else 'overlay',owned=args.command == 'desktop'); return 0
        if args.command == "serve":
            from .server import serve
            serve(args.project, args.port, not args.no_browser); return 0
        if args.command == "sample":
            trajectory = read_project(args.project)
            result = {"schema_version": 1, "scope": "offline trajectory samples; not game execution",
                      "duration": trajectory.duration, "length": trajectory.length, "samples": samples(trajectory, args.hz)}
            atomic_json(args.out, result)
            print(f"已导出 {len(result['samples'])} 个离线样本：{args.out}"); return 0
        if args.command == "record" and not (0 < args.seconds <= 3600 and 1 <= args.hz <= 240):
            raise ValueError("录制时长需为 (0,3600] 秒，采样率需为 [1,240] Hz。")
        with CameraSession.connect(args.pid) as session:
            if args.command == "inspect":
                print(json.dumps({"discovery": session.discovery_stats, "snapshot": session.capture()}, ensure_ascii=False, indent=2)); return 0
            if args.command == "capture":
                atomic_json(args.out, session.capture()); print(f"已保存只读摄像机快照：{args.out}"); return 0
            result = record_session(session, args.out, args.seconds, args.hz)
            print(f"有效快照 {result['valid_sample_count']}，尝试 {result['attempt_count']}，"
                  f"暂态丢样 {result['dropped_sample_count']}：{args.out}")
            print(f"录制摘要：{result['summary_path']}")
            if result["status"] != "completed":
                failure = result["failure"]
                print(f"录制已{'中断' if result['status'] == 'interrupted' else '失败'}："
                      f"{failure['type']}：{failure['message']}", file=sys.stderr)
                return 130 if result["status"] == "interrupted" else 2
        return 0
    except KeyboardInterrupt:
        print("已中断。", file=sys.stderr); return 130
    except (CameraError, ValueError, OSError) as exc:
        print(f"已停止：{exc}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
