"""Replay rate curves, independent from camera path easing. No process access."""
import math
from copy import deepcopy

DEFAULT = {"mode":"paused", "rate":0.25, "camera_clock":"replay", "interpolation":"smooth",
           "keyframes":[{"progress":0.,"rate":1.},{"progress":0.25,"rate":0.25},
                        {"progress":0.75,"rate":0.25},{"progress":1.,"rate":1.}]}

def number(x,lo,hi,label):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not lo<=x<=hi:
        raise ValueError(f"{label}需在 {lo}–{hi} 之间。")
    return float(x)

def validate_speed(value=None):
    if value is None:value={}
    if not isinstance(value,dict):raise ValueError("回放速度设置需为对象。")
    s=deepcopy(DEFAULT);s.update(value)
    if s['mode'] not in ('paused','fixed','curve'):raise ValueError('未知回放速度模式。')
    if s['camera_clock'] not in ('shooting','replay'):raise ValueError('未知镜头时间模式。')
    if s['interpolation'] not in ('linear','smooth'):raise ValueError('未知倍速过渡。')
    s['rate']=number(s['rate'],.0625,1,'回放倍率')
    fs=s['keyframes']
    if not isinstance(fs,list) or not 2<=len(fs)<=64:raise ValueError('速度曲线需要 2–64 个关键帧。')
    frames=[]
    for f in fs:
        if not isinstance(f,dict):raise ValueError('速度关键帧需为对象。')
        frame={'progress':number(f.get('progress'),0,1,'拍摄进度'),'rate':number(f.get('rate'),.0625,1,'倍率')}
        if 'ease' in f:
            ease=f['ease']
            if not isinstance(ease,list) or len(ease)!=4:raise ValueError('速度曲线手柄需要四个坐标。')
            frame['ease']=[number(v,0,1,'速度曲线手柄时间') if i%2==0 else number(v,-1e6,1e6,'速度曲线手柄倍率') for i,v in enumerate(ease)]
            if ease[0]>ease[2]:raise ValueError('速度曲线手柄不能交叉。')
        frames.append(frame)
    if frames[0]['progress']!=0 or frames[-1]['progress']!=1 or any(b['progress']-a['progress']<1e-5 for a,b in zip(frames,frames[1:])):
        raise ValueError('速度关键帧必须从 0% 到 100%，按进度递增且不能重合。')
    s['keyframes']=frames
    for a,b in zip(frames,frames[1:]):
        if 'ease' in a and any(not .0625-1e-9<=a['rate']+(b['rate']-a['rate'])*a['ease'][i]<=1+1e-9 for i in (1,3)):
            raise ValueError('速度手柄倍率需在 1/16×–1× 内。')
    result={k:s[k] for k in DEFAULT}
    if 'time_range' in value:
        bounds=value['time_range']
        if not isinstance(bounds,dict):raise ValueError('速度曲线时间范围需为对象。')
        start=number(bounds.get('start_sec'),0,3600,'速度曲线起点')
        end=number(bounds.get('end_sec'),0,3600,'速度曲线终点')
        if start>=end:raise ValueError('速度曲线终点需晚于起点。')
        result['time_range']={'start_sec':start,'end_sec':end}
    return result

def mean_rate(s):
    if s['mode']=='fixed':return s['rate']
    return rate_integral(s,1)


def bezier_area(ease,u):
    """Exact integral of y dx for a monotone cubic, up to normalized x=u."""
    x1,y1,x2,y2=ease
    x=(0.,3*x1,3*x2-6*x1,1+3*x1-3*x2)
    y=(0.,3*y1,3*y2-6*y1,1+3*y1-3*y2)
    t=1.
    if u<1:
        lo,hi=0.,1.
        for _ in range(42):
            t=(lo+hi)/2
            if t*(x[1]+t*(x[2]+t*x[3]))<u:lo=t
            else:hi=t
        t=(lo+hi)/2
    return sum(y[i]*j*x[j]*t**(i+j)/(i+j) for i in range(1,4) for j in range(1,4))


def rate_integral(s, progress):
    """Integral over normalized shooting time, matching preview/native clocks."""
    p=max(0.,min(1.,progress))
    if s['mode']=='fixed':return p*s['rate']
    total=0.
    for a,b in zip(s['keyframes'],s['keyframes'][1:]):
        span=b['progress']-a['progress']
        u=max(0.,min(1.,(p-a['progress'])/span))
        if u<=0:break
        area=bezier_area(a['ease'],u) if 'ease' in a else u**3-.5*u**4 if s['interpolation']=='smooth' else .5*u*u
        total+=span*(a['rate']*u+(b['rate']-a['rate'])*area)
    return total


def shooting_progress(s, replay_progress):
    if replay_progress<=0:return 0.
    if replay_progress>=1:return 1.
    target=mean_rate(s)*max(0.,min(1.,replay_progress))
    lo,hi=0.,1.
    for _ in range(50):
        mid=(lo+hi)/2
        if rate_integral(s,mid)<target:lo=mid
        else:hi=mid
    return (lo+hi)/2


def schedule_time(s,time,start,end):
    """Shooting seconds from an authored range, holding endpoint rates outside."""
    if s['mode']=='fixed':return (time-start)/s['rate']
    total=(end-start)/mean_rate(s)
    if time<=start:return (time-start)/s['keyframes'][0]['rate']
    if time>=end:return total+(time-end)/s['keyframes'][-1]['rate']
    return total*shooting_progress(s,(time-start)/(end-start))


def playback_timing(trajectory, s):
    schedule=getattr(trajectory,'speed_schedule',None)
    if schedule:
        total,offset=schedule
        seconds=getattr(trajectory,'shooting_seconds',total-offset)
        if not .5<=seconds<=120:raise ValueError('剩余拍摄时长需为 0.5–120 秒，请调整工作区间。')
        return seconds,total,offset
    seconds=shooting_duration(trajectory.duration,s,trajectory.shooting_mode)
    return seconds,seconds,0.

def shooting_duration(duration,s,shooting_mode=None):
    if shooting_mode == 'camera_only':
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('镜头动画需有大于零的时长。')
        return duration
    result=duration/mean_rate(s) if s['mode']!='paused' and s['camera_clock']=='replay' else duration
    if not .5<=result<=120:raise ValueError('实际拍摄时长需在 0.5–120 秒；请缩短轨迹或提高倍率。')
    return result
