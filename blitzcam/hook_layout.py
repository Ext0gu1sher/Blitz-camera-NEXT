"""Shared x86 structures; no process access at import time."""
import ctypes as C
INTS=['magic', 'size', 'base', 'battle', 'owner', 'context', 'player', 'scene', 'scene_owner', 'replay_controller', 'game_camera', 'camera', 'spectator', 'render', 'shadow', 'battle_vft', 'update_vft', 'shadow_vft', 'context_vft', 'player_vft', 'camera_vft', 'spectator_vft', 'render_vft', 'scene_vft', 'scene_owner_vft', 'replay_vft', 'game_vft', 'player_secondary_vft', 'set_position', 'set_direction', 'refresh']
class Vec(C.Structure):
    _pack_=4
    _fields_=[(x,C.c_float)for x in ('x','y','z')]

class Quat(C.Structure):
    _pack_=4
    _fields_=[(x,C.c_float)for x in ('w','x','y','z')]

class Config(C.Structure):
    _pack_=4
    _fields_=[(n,C.c_uint32)for n in INTS]+[(n,C.c_float)for n in ('raw_time','origin','fov')]+[('angles',C.c_float*2),('projection',C.c_float*16)]+[(n,Vec)for n in ('direction','setter_direction','a','b')]+[('point_count',C.c_uint32),('reverse',C.c_uint32),('duration',C.c_float),('approach_seconds',C.c_float),('lower',Vec),('upper',Vec)]+[('set_fov',C.c_uint32),('fov_scale',C.c_float),('aspect',C.c_float),('start_roll',C.c_float),('start_quaternion',Quat),('orientation_enabled',C.c_uint32),('fov_enabled',C.c_uint32)]+[(n,C.c_uint32)for n in ('replay_mode','camera_clock','functor','functor_vft','tick_entry','notify_entry','pause_entry','speed_count','speed_smooth')]+[(n,C.c_float)for n in ('play_seconds','initial_rate','schedule_seconds','schedule_offset')]

class Event(C.Structure):
    _pack_=4
    _fields_=[('commit',C.c_int32)]+[(n,C.c_uint32)for n in ('kind','thread','stage','updates','draws')]+[('qpc',C.c_int64),('elapsed',C.c_double),('dt',C.c_float)]+[(n,Vec)for n in ('position','goal','direction')]+[('fov',C.c_float),('angles',C.c_float*2),('view',C.c_float*16),('projection',C.c_float*16),('width',C.c_float*3),('step',C.c_float*3),('shadow_projection',(C.c_float*16)*3),('shadow_vp',(C.c_float*16)*3),('base_roll',C.c_float),('horizontal_fov',C.c_float)]+[(n,C.c_float)for n in ('raw_time','replay_rate','scene_rate')]+[('clock_paused',C.c_uint32)]

def plain(value):
    if isinstance(value,C.Array):return[plain(x)for x in value]
    if isinstance(value,Vec):return[value.x,value.y,value.z]
    if isinstance(value,Quat):return[value.w,value.x,value.y,value.z]
    if isinstance(value,C.Structure):return{n:plain(getattr(value,n))for n,*_ in value._fields_}
    return value

class Header(C.Structure):
    _pack_=4
    _fields_=[(n,C.c_int32)for n in ('command','heartbeat','status','error','updates','draws','events','active','update_tid','draw_tid','position_applies','detach_mask')]+[(n,C.c_int64)for n in ('frequency','start_qpc','last_qpc')]+[('last_elapsed',C.c_double),('last_goal',Vec)]+[(n,C.c_double)for n in ('shooting_elapsed','replay_elapsed')]+[(n,C.c_int32)for n in ('clock_started','clock_paused','clock_restored','clock_tid')]+[(n,C.c_float)for n in ('current_rate','clock_raw')]

class PathPoint(C.Structure):
    _pack_=4
    _fields_=[('time',C.c_float),('position',Vec),('quaternion',Quat),('horizontal_fov',C.c_float)]

CAP=2048
MAX_POINTS=16384
HEADER=C.sizeof(Config)
RECORDS=HEADER+C.sizeof(Header)
POINTS=RECORDS+CAP*C.sizeof(Event)

class SpeedPoint(C.Structure):
    _pack_=4
    _fields_=[("progress",C.c_float),("rate",C.c_float),("ease",C.c_float*4),("custom_ease",C.c_uint32)]

    @classmethod
    def from_key(cls,key):
        return cls(key['progress'],key['rate'],(C.c_float*4)(*key.get('ease',[0,0,0,0])),int('ease' in key))

SPEED_POINTS=POINTS+MAX_POINTS*C.sizeof(PathPoint)

SHARED_SIZE=SPEED_POINTS+64*C.sizeof(SpeedPoint)
