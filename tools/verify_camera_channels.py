"""Exercise the local camera UI backend on an already paused replay.

Explicit live test utility: POSTs start/stop; never starts the game or a replay.
The original project and current composition are archived before the first run.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blitzcam.pose import quaternion_from_angles, angles_from_quaternion
from blitzcam.project import atomic_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/camera-channels-030'
URL = 'http://127.0.0.1:56591'

def api(path, data=None):
    request = urllib.request.Request(URL+path, data=None if data is None else json.dumps(data).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=15) as r:
        return json.load(r)

def project(kind, sample):
    camera = sample['camera']; p = camera['position']; a = angles_from_quaternion(camera['quaternion'])
    q = camera['quaternion']; f = camera['horizontal_fov_deg']
    def frame(t, pos, yaw=0, pitch=0, roll=0, zoom=0):
        return {'time_sec': t, 'position': pos,
                'quaternion': quaternion_from_angles(a['yaw_deg']+yaw,a['pitch_deg']+pitch,a['roll_deg']+roll),
                'horizontal_fov_deg': f+zoom}
    first = {'time_sec': 0, 'position': p, 'quaternion': q, 'horizontal_fov_deg': f}
    if kind == 'orientation':
        frames = [first, frame(4,p,20,5,6)]
    elif kind == 'fov':
        frames = [first, frame(4,p,zoom=12)]
    else:
        frames = [first,frame(4,[p[0]-5,p[1],p[2]+3],10,2,3,6),
                  frame(8,[p[0]-10,p[1],p[2]+4],20,5,6,12)]
    return {'keyframes':frames,'position_interpolation':'smooth','timing':'keyframes','easing':'ease_in_out'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['orientation','fov','combined','restore-project'])
    parser.add_argument('--reverse',action='store_true');parser.add_argument('--stop-after',type=float)
    parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    state=api('/api/state')
    if state['playback']['active']:raise RuntimeError('Another camera trajectory is running.')
    if not (state['sample'] and state['sample']['replay']['paused']):raise RuntimeError('Requires paused replay.')
    OUT.mkdir(parents=True,exist_ok=True)
    if not (OUT/'baseline.json').exists():atomic_json(OUT/'baseline.json',state)
    if args.kind=='restore-project':
        api('/api/project',{'project':json.loads((OUT/'baseline.json').read_text(encoding='utf8'))['project']});return
    baseline=json.loads((OUT/'baseline.json').read_text(encoding='utf8'))
    if baseline['sample']['session_id']!=state['sample']['session_id']:
        raise RuntimeError('Saved baseline belongs to a different replay session; archive the test directory and capture a new baseline first.')
    if not args.reverse:
        data=project(args.kind,baseline['sample'])
        api('/api/project',{'project':data});atomic_json(OUT/(args.kind+'-project.json'),data)
    if args.prepare_only:print(json.dumps({'prepared':args.kind}));return
    api('/api/playback/start',{'reverse':args.reverse,'orientation_enabled':args.kind!='fov','fov_enabled':args.kind!='orientation'})
    started=time.monotonic();stop_sent=False
    while time.monotonic()-started<40:
        state=api('/api/state');play=state['playback']
        if args.stop_after and not stop_sent and play['state']=='playing' and play.get('elapsed',0)>=args.stop_after:
            api('/api/playback/stop',{});stop_sent=True
        if not play['active']:
            tag=args.kind+('-reverse'if args.reverse else'-forward')+('-stopped'if args.stop_after else'')
            atomic_json(OUT/(tag+'.json'),state)
            print(json.dumps(play,ensure_ascii=False));return
        time.sleep(.15)
    raise RuntimeError('Backend did not finish within bounded test timeout.')

if __name__=='__main__':main()
