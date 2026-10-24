"""Exact-build, bounded one-shot seek trial; importing does not access a game."""
import ctypes as C
import math
import struct
from .profile import CameraError
from .replay_trial import configuration

FIELDS = ('magic size base context player scene_owner scene camera '
          'context_vft player_vft secondary_vft scene_owner_vft scene_vft camera_vft '
          'engine head node functor functor_vft tick_entry seek_entry').split()
class Config(C.Structure):
    _pack_ = 4
    _fields_ = [(n,C.c_uint32) for n in FIELDS]+[(n,C.c_float) for n in ('raw','origin','rate','delta')]
class Header(C.Structure):
    _pack_ = 4
    _fields_ = [(n,C.c_int32) for n in ('heartbeat','status','error','active','detached','thread','requests')]+[
        (n,C.c_float) for n in ('raw_before','raw_after','target_after')]+[
        (n,C.c_uint32) for n in ('active_after','seek_after','waiting_after','task_after')]

def prepare(session,sample,target,*,max_delta=120):
    if isinstance(target,bool) or not math.isfinite(target):
        raise ValueError('目标时间必须是有限秒数。')
    delta=target-sample['replay']['time']
    if target<0 or not .01<=abs(delta)<=max_delta or not 0<max_delta<=3600:
        raise ValueError(f'跳转实验只允许当前时刻前后 0.01–{max_delta:g} 秒。')
    source,link=configuration(session,sample,.25,1)
    c=Config(magic=0x314b5342,size=C.sizeof(Config),seek_entry=session.live(0x13e5ea0),delta=delta,rate=source.initial_rate)
    for n in FIELDS:
        if n not in ('magic','size','seek_entry'):
            setattr(c,n,getattr(source,n))
    c.raw,c.origin=source.raw,source.origin
    return c,link

def clock(memory,player,expected_vft):
    """Lifecycle observation independent of camera identity/monotonic capture."""
    a=memory.read(player,0x10c)
    if struct.unpack_from('<I',a)[0]!=expected_vft:
        raise CameraError('回放播放器身份已变化，停止使用旧地址。')
    f=lambda o:struct.unpack_from('<f',a,o)[0]
    return dict(raw=f(0x18),origin=f(0x64),time=f(0x18)-f(0x64),rate=f(0x14),target_raw=f(0x28),
                active=a[0x11],paused=a[0x12],initialized=a[0x35],seek=a[0x2d],waiting=a[0x2e],
                task=struct.unpack_from('<I',a,0x108)[0],record_index=struct.unpack_from('<I',a,0x1c)[0],
                source=struct.unpack_from('<I',a,0xa0)[0])

def settled(x,rate):
    return (x['active']==x['paused']==x['initialized']==1 and not x['seek'] and not x['waiting']
            and x['task']==0xffffffff and x['source']!=0 and x['rate']==rate
            and all(math.isfinite(x[n]) for n in ('raw','origin','time','rate')))
