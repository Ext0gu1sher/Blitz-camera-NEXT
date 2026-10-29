"""Record the game window while running one bounded tracking experiment."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from research.scripts import tank_tracking_trial as trial
from research.scripts.tank_tracking_launcher import ensure_driver


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    known,rest=parser.parse_known_args()
    args=trial.parser().parse_args(['--execute',*rest])
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('FFmpeg is not available.')
    video=known.video.resolve()
    if video.exists():raise FileExistsError(video)
    video.parent.mkdir(parents=True,exist_ok=True)
    ensure_driver()
    process=None;marks=[];started=None
    log_path=video.with_suffix('.capture.log')
    with log_path.open('w',encoding='utf8') as log:
        def progress(state):
            nonlocal process,started
            if process is None and state['state'] in ('positioning','playing'):
                started=time.monotonic()
                process=subprocess.Popen([ffmpeg,'-hide_banner','-loglevel','warning','-f','gdigrab',
                    '-framerate','30','-draw_mouse','0','-i','title=WoT Blitz','-t','90','-an',
                    '-c:v','libx264','-preset','ultrafast','-crf','18','-pix_fmt','yuv420p',
                    '-movflags','+faststart',str(video)],stdin=subprocess.PIPE,stdout=log,stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            marks.append({**state,'recording_elapsed':None if started is None else time.monotonic()-started})
            print(state['message'],flush=True)
        try:
            result=trial.run(args,on_progress=progress)
        finally:
            if process is not None:
                try:process.communicate(b'q\n',timeout=20)
                except subprocess.TimeoutExpired:
                    process.terminate();process.wait(timeout=5)
            video.with_suffix('.capture.json').write_text(json.dumps({
                'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
                'video':str(video),'marks':marks,'capture_exit_code':process.returncode if process else None,
            },ensure_ascii=False,indent=2),encoding='utf8')
    if process is None or process.returncode!=0 or not video.is_file():
        raise RuntimeError(f'Game recording did not complete: {log_path}')
    print(json.dumps({'video':str(video),'tracking_run':result['state']['run_path']},ensure_ascii=False))


if __name__=='__main__':main()
