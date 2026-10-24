"""Local acceptance using the same HTTP API as the UI. Restores the saved project."""
import json,time,urllib.request
from copy import deepcopy
from pathlib import Path
URL='http://127.0.0.1:56592'
OUT=Path('output/ui-speed-040-acceptance');OUT.mkdir(exist_ok=True)
def api(path,data=None):
    req=urllib.request.Request(URL+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=12))
def state():return api('/api/state')
def wait_for(pred,timeout=30):
    start=time.monotonic()
    while time.monotonic()-start<timeout:
        s=state()
        if pred(s):return s
        if s['playback']['state']=='error':raise RuntimeError(s['playback']['message'])
        time.sleep(.07)
    raise RuntimeError('Acceptance timed out')
def finished():
    s=wait_for(lambda s:not s['playback']['active'])
    assert s['playback']['hooks_detached']
    time.sleep(.3);s=state();assert s['sample']['replay']['paused'] and s['sample']['replay']['rate']==1
    return s
saved=state()['project'];(OUT/'saved-project.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf8')
result={}
try:
    p=deepcopy(saved);p['replay_speed']['mode']='curve';p['replay_speed']['camera_clock']='shooting'
    api('/api/project',{'project':p});api('/api/playback/start',{'reverse':True})
    wait_for(lambda s:s['playback']['state']=='playing' and s['playback'].get('shooting_elapsed',0)>.7)
    api('/api/playback/pause',{'paused':True});wait_for(lambda s:s['playback']['state']=='paused');time.sleep(.4)
    a=state();time.sleep(.8);b=state()
    check={'raw_delta':b['sample']['replay']['raw_time']-a['sample']['replay']['raw_time'],
           'shooting_delta':b['playback']['shooting_elapsed']-a['playback']['shooting_elapsed'],
           'position_equal':a['sample']['camera']['position']==b['sample']['camera']['position']}
    assert check=={'raw_delta':0,'shooting_delta':0,'position_equal':True},check
    api('/api/playback/pause',{'paused':False});wait_for(lambda s:s['playback']['state']=='playing' and s['playback']['shooting_elapsed']>b['playback']['shooting_elapsed']+.5)
    api('/api/playback/stop',{});result['curve_reverse_pause_resume_stop']={'check':check,'final':finished()['playback']}
    p=deepcopy(saved);start=p['keyframes'][0]['time_sec'];duration=p['keyframes'][-1]['time_sec']-start
    for f in p['keyframes']:f['time_sec']=(f['time_sec']-start)/duration*2
    p['replay_speed'].update(mode='fixed',rate=.25,camera_clock='replay')
    api('/api/project',{'project':p});api('/api/playback/start',{})
    result['fixed_replay_time_camera']=finished()['playback']
    p['replay_speed']['mode']='paused';api('/api/project',{'project':p});api('/api/playback/start',{'reverse':True})
    result['legacy_paused_reverse']=finished()['playback']
    p['replay_speed'].update(mode='fixed',rate=.5);api('/api/project',{'project':p});api('/api/playback/start',{'speed_only':True,'seconds':2})
    result['fixed_half_speed_stationary']=finished()['playback']
except Exception as exc:
    result['error']=repr(exc);api('/api/playback/stop',{})
finally:
    wait_for(lambda s:not s['playback']['active'],5);api('/api/project',{'project':saved})
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False))
if 'error'in result:raise SystemExit(1)
