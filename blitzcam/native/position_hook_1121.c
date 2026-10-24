/* Exact-build paused replay camera playback. Per-instance vtables;
 * no executable patches, shadow writes or online camera support. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <math.h>
#include <string.h>
#define CAP 2048
#define MAX_POINTS 16384
#define MAGIC 0x33484342u
#define PI 3.14159265358979323846
#define U(p,o) (*(uint32_t*)((uintptr_t)(p)+(o)))
#define F(p,o) (*(float*)((uintptr_t)(p)+(o)))
#define B(p,o) (*(unsigned char*)((uintptr_t)(p)+(o)))
#define API __declspec(dllexport)
typedef struct {float x,y,z;} Vec;
typedef struct {float w,x,y,z;} Quat;
typedef void (__thiscall *UpdateFn)(void*,float);
typedef void (__thiscall *DrawFn)(void*,void*);
typedef void (__thiscall *SetFn)(void*,const Vec*);
typedef void (__thiscall *ScalarFn)(void*,float);
/* Actual 11.21 callee returns a matrix pointer, consumes a 4-byte argument.
 * Its projection branch tests the low byte; verified game callers pass 0. */
typedef void* (__thiscall *RefreshFn)(void*,uint32_t);
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,base,battle,owner,context,player,scene,scene_owner;
 uint32_t replay_controller,game_camera,camera,spectator,render,shadow;
 uint32_t battle_vft,update_vft,shadow_vft,context_vft,player_vft;
 uint32_t camera_vft,spectator_vft,render_vft,scene_vft,scene_owner_vft;
 uint32_t replay_vft,game_vft,player_secondary_vft,set_position,set_direction,refresh;
 float raw_time,origin,fov,angles[2],projection[16];
 Vec direction,setter_direction,a,b;
 uint32_t point_count,reverse;
 float duration,approach_seconds;
 Vec lower,upper;
 uint32_t set_fov;
 float fov_scale,aspect,start_roll;
 Quat start_quaternion;
 uint32_t orientation_enabled,fov_enabled;
 uint32_t replay_mode,camera_clock,functor,functor_vft,tick_entry,notify_entry,pause_entry,speed_count,speed_smooth;
 float play_seconds,initial_rate,schedule_seconds,schedule_offset;
} Config;
typedef struct {float time;Vec position;Quat quaternion;float horizontal_fov;} PathPoint;
typedef struct {float progress,rate,ease[4];uint32_t custom_ease;} SpeedPoint;
typedef void (__thiscall *NotifyFn)(void*);
typedef void (__thiscall *PauseFn)(void*,uint32_t);
typedef struct {
 volatile LONG commit;
 uint32_t kind,thread,stage,updates,draws;
 int64_t qpc;
 double elapsed;
 float dt;
 Vec position,goal,direction;
 float fov,angles[2],view[16],projection[16],width[3],step[3];
 float shadow_projection[3][16],shadow_vp[3][16];
 float base_roll,horizontal_fov;
 float raw_time,replay_rate,scene_rate;uint32_t clock_paused;
} Event;
typedef struct {
 Config cfg;
 volatile LONG command,heartbeat,status,error,updates,draws,events,active;
 volatile LONG update_tid,draw_tid,position_applies,detach_mask;
 int64_t frequency,start_qpc,last_qpc;
 double last_elapsed;
 Vec last_goal;
 double shooting_elapsed,replay_elapsed;
 volatile LONG clock_started,clock_paused,clock_restored,clock_tid;
 float current_rate,clock_raw;
 Event records[CAP];
 PathPoint points[MAX_POINTS];
 SpeedPoint speeds[64];
} Shared;
#pragma pack(pop)
API Shared g_shared;
static uintptr_t uc[7],sc[8]; /* include RTTI at vtable[-1] */
static UpdateFn original_update;
static DrawFn original_draw;
static DWORD attached;
static int armed;
static UpdateFn original_tick;
static int clock_attached;
static void __fastcall replay_tick_hook(void*,void*,float);
static int clock_guard(void);
static float expected_angles[2],expected_fov,expected_roll,expected_projection[16];
static Vec expected_direction;
/* +50 is a lazily refreshed direction cache, independent of Refresh's view
 * rebuild. Read the forward basis actually consumed by rendering instead. */
static Vec view_direction(uint32_t camera){return(Vec){-F(camera,0xc8),-F(camera,0xd8),-F(camera,0xe8)};}
static uint32_t live(uint32_t va){return g_shared.cfg.base+va-0x400000u;}
static float dist(Vec a,Vec b){float x=a.x-b.x,y=a.y-b.y,z=a.z-b.z;return sqrtf(x*x+y*y+z*z);}
static int readable(uint32_t p,size_t n){MEMORY_BASIC_INFORMATION m;return p>0x10000&&VirtualQuery((void*)(uintptr_t)p,&m,sizeof(m))&&m.State==MEM_COMMIT&&!(m.Protect&(PAGE_GUARD|PAGE_NOACCESS))&&(uintptr_t)p+n<=(uintptr_t)m.BaseAddress+m.RegionSize;}
static int type(uint32_t p,uint32_t v){return readable(p,4)&&U(p,0)==v;}
static void detach(void){
 Config*c=&g_shared.cfg;LONG before;
 if(readable(c->battle+0x128,4)){
  before=InterlockedCompareExchange((LONG*)(uintptr_t)(c->battle+0x128),c->update_vft,(LONG)(uintptr_t)(uc+1));
  if((uint32_t)before==(uint32_t)(uintptr_t)(uc+1)||(uint32_t)before==c->update_vft)InterlockedOr(&g_shared.detach_mask,1);
 }
 if(readable(c->shadow,4)){
  before=InterlockedCompareExchange((LONG*)(uintptr_t)c->shadow,c->shadow_vft,(LONG)(uintptr_t)(sc+1));
  if((uint32_t)before==(uint32_t)(uintptr_t)(sc+1)||(uint32_t)before==c->shadow_vft)InterlockedOr(&g_shared.detach_mask,2);
 }
 if(c->replay_mode&&readable(c->functor,0x18)){
  before=InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),c->tick_entry,(LONG)(uintptr_t)replay_tick_hook);
  if((uint32_t)before==c->tick_entry||(uint32_t)before==(uint32_t)(uintptr_t)replay_tick_hook)InterlockedOr(&g_shared.detach_mask,4);
 }
 clock_attached=0;InterlockedExchange(&g_shared.status,g_shared.error?-1:4);
}
static void fail(LONG reason){InterlockedCompareExchange(&g_shared.error,reason,0);if(clock_attached)g_shared.command=9;else detach();}
static void request_stop(void){if(clock_attached)g_shared.command=9;else detach();}
static int guard(void){
 Config*c=&g_shared.cfg;
 if((DWORD)(GetTickCount()-(DWORD)g_shared.heartbeat)>1500)return 1;
 if(g_shared.command==9)return 2;
 if(!readable(c->battle,0x154)||!readable(c->owner,0x6c)||!readable(c->context,0x1b4)||!readable(c->player,0x10c)||!readable(c->camera,0x26c)||!readable(c->spectator,0x138)||!readable(c->scene,0x128)||!readable(c->scene_owner,0xa0)||!readable(c->render,0xbc)||!readable(c->shadow,0x5e0))return 3;
 if(!type(c->battle,c->battle_vft)||!type(c->context,c->context_vft)||!type(c->player,c->player_vft)||!type(c->camera,c->camera_vft)||!type(c->spectator,c->spectator_vft)||!type(c->render,c->render_vft)||!type(c->scene,c->scene_vft)||!type(c->scene_owner,c->scene_owner_vft)||!type(c->replay_controller,c->replay_vft)||!type(c->game_camera,c->game_vft))return 4;
 if(U(c->battle,0x120)!=c->context||U(c->battle,0x150)!=c->owner||U(c->owner,0x68)!=c->spectator||U(c->context,0x1b0)!=c->player||U(c->player,0xc)!=c->player_secondary_vft||U(c->scene,0xa8)!=c->render||U(c->scene,0x120)!=c->camera||U(c->scene,0x124)!=c->camera||U(c->render,0xb4)!=c->camera||U(c->render,0xb8)!=c->camera||U(c->render,0x8c)!=c->shadow||U(c->scene_owner,0x1c)!=c->scene||U(c->scene_owner,0x20)!=c->context||U(c->scene_owner,0x8c)!=c->game_camera||U(c->scene_owner,0x94)!=c->camera||U(c->scene_owner,0x9c)!=c->replay_controller||U(c->spectator,0xc)!=c->camera||U(c->replay_controller,0x28)!=c->game_camera||U(c->game_camera,0x5b8)!=c->replay_controller)return 5;
 if(B(c->player,0x11)!=1||(!c->replay_mode&&B(c->player,0x12)!=1)||B(c->player,0x35)!=1||!U(c->player,0xa0)||B(c->player,0x2d)||B(c->player,0x2e)||U(c->player,0x108)!=0xffffffff||F(c->player,0x18)!=(c->replay_mode?g_shared.clock_raw:c->raw_time)||F(c->player,0x64)!=c->origin)return 6;
 if(c->replay_mode){int error=clock_guard();if(error)return error;}
 if(U(c->camera,8)||U(c->camera,12)||U(c->spectator,0x10c)!=0xffffffff||U(c->spectator,0x128))return 7;
 if(memcmp((void*)(uintptr_t)(c->spectator+0x30),&c->lower,12)||memcmp((void*)(uintptr_t)(c->spectator+0x3c),&c->upper,12))return 23;
 for(int i=0x10;i<0x2e;i++)if(B(c->spectator,i))return 8;
 for(int i=0;i<3;i++)if(F(c->spectator,0x80+i*4)||F(c->spectator,0x9c+i*4))return 8;
 float fov=armed?expected_fov:c->fov,roll=armed?expected_roll:c->start_roll;
 float*angles=armed?expected_angles:c->angles;float*projection=armed?expected_projection:c->projection;
 Vec direction=armed?expected_direction:c->direction;
 if(F(c->camera,0x264)!=c->fov_scale||F(c->camera,0x28)!=c->aspect)return 25;
 if(F(c->spectator,0x114)!=fov||fabsf(F(c->spectator,0x118)-fov)>0.00001f||F(c->camera,0x268)!=fov||F(c->spectator,0x110)!=0||F(c->camera,0x5c)!=roll)return 9;
 for(int i=0;i<2;i++)if(F(c->spectator,0x58+i*4)!=angles[i]||fabsf(F(c->spectator,0x60+i*4)-angles[i])>.001f)return 10;
 for(int i=0;i<16;i++)if(fabsf(F(c->camera,0x100+i*4)-projection[i])>0.00000012f)return 11;
 Vec actual=view_direction(c->camera);
 for(int i=0;i<3;i++)if(fabsf(((float*)&actual)[i]-((float*)&direction)[i])>0.00002f)return 12;
 if(g_shared.draw_tid&&g_shared.update_tid&&g_shared.update_tid!=g_shared.draw_tid)return 13;
 return 0;
}
#include "position_replay_clock.h"

static Quat qnormalize(Quat q){double n=sqrt((double)q.w*q.w+(double)q.x*q.x+(double)q.y*q.y+(double)q.z*q.z);return(Quat){(float)(q.w/n),(float)(q.x/n),(float)(q.y/n),(float)(q.z/n)};}
static Quat qslerp(Quat a,Quat b,double t){
 a=qnormalize(a);b=qnormalize(b);double dot=(double)a.w*b.w+(double)a.x*b.x+(double)a.y*b.y+(double)a.z*b.z;
 if(dot<0){b=(Quat){-b.w,-b.x,-b.y,-b.z};dot=-dot;}
 double wa=1-t,wb=t;if(dot<.9995){double theta=acos(fmin(1.,dot)),denom=sin(theta);wa=sin((1-t)*theta)/denom;wb=sin(t*theta)/denom;}
 return qnormalize((Quat){(float)(wa*a.w+wb*b.w),(float)(wa*a.x+wb*b.x),(float)(wa*a.y+wb*b.y),(float)(wa*a.z+wb*b.z)});
}
static PathPoint interpolate(PathPoint a,PathPoint b,double u){
 PathPoint p=a;p.position=(Vec){(float)(a.position.x+(b.position.x-a.position.x)*u),(float)(a.position.y+(b.position.y-a.position.y)*u),(float)(a.position.z+(b.position.z-a.position.z)*u)};
 p.quaternion=qslerp(a.quaternion,b.quaternion,u);p.horizontal_fov=(float)(a.horizontal_fov+(b.horizontal_fov-a.horizontal_fov)*u);return p;
}
/* Camera local +X right,+Y up,-Z forward; world Z up; q is wxyz.
 * Native yaw=90-UI yaw, pitch=-UI pitch. Camera base roll=-UI roll:
 * verified base-view multiplication at 0xA8A4A0 uses [cos,-sin;sin,cos]. */
static int orientation(Quat q,Vec*direction,float*out){
 q=qnormalize(q);double w=q.w,x=q.x,y=q.y,z=q.z;
 Vec f={(float)(-2*(x*z+y*w)),(float)(-2*(y*z-x*w)),(float)(-(1-2*(x*x+y*y)))};
 Vec up={(float)(2*(x*y-z*w)),(float)(1-2*(x*x+z*z)),(float)(2*(y*z+x*w))};
 double yaw=atan2(f.y,f.x),pitch=atan2(f.z,hypot(f.x,f.y));
 Vec right={(float)sin(yaw),(float)-cos(yaw),0};
 Vec up0={right.y*f.z,-right.x*f.z,right.x*f.y-right.y*f.x};
 double roll=atan2(up.x*right.x+up.y*right.y,up.x*up0.x+up.y*up0.y+up.z*up0.z);
 out[0]=(float)(90-yaw*180/PI);out[1]=(float)(-pitch*180/PI);out[2]=(float)(-roll*180/PI);*direction=f;
 return isfinite(out[0])&&isfinite(out[1])&&isfinite(out[2])&&fabsf(out[1])<=80.001f;
}
static PathPoint path(double elapsed){
 Config*c=&g_shared.cfg;PathPoint*pts=g_shared.points;
 if(elapsed<c->approach_seconds){
  double u=elapsed/c->approach_seconds;u=u*u*(3-2*u);
  PathPoint to=pts[c->reverse?c->point_count-1:0],from={0,c->b,c->start_quaternion,c->fov*c->fov_scale};
  PathPoint p=interpolate(from,to,u);if(dist(from.position,to.position)>.001f)p.position.z+=(float)(2*sin(PI*u));return p;
 }
 double t=elapsed-c->approach_seconds;if(c->reverse)t=c->duration-t;
 if(t<=0)return pts[0];if(t>=c->duration)return pts[c->point_count-1];
 uint32_t lo=0,hi=c->point_count-1;
 while(lo+1<hi){uint32_t mid=(lo+hi)/2;if(pts[mid].time<=t)lo=mid;else hi=mid;}
 double u=(t-pts[lo].time)/(pts[hi].time-pts[lo].time);
 return interpolate(pts[lo],pts[hi],u);
}
static uint32_t stage(double t){return !armed?0:t<g_shared.cfg.approach_seconds?1:t<g_shared.cfg.approach_seconds+g_shared.cfg.duration?2:3;}
static void log_event(uint32_t kind,float dt){
 LONG index=InterlockedIncrement(&g_shared.events)-1;
 Event*e=&g_shared.records[index%CAP];InterlockedExchange(&e->commit,0);Config*c=&g_shared.cfg;LARGE_INTEGER now;
 QueryPerformanceCounter(&now);e->qpc=now.QuadPart;e->kind=kind;e->thread=GetCurrentThreadId();
 e->elapsed=g_shared.last_elapsed;
 e->stage=stage(e->elapsed);e->dt=dt;e->updates=g_shared.updates;e->draws=g_shared.draws;
 e->position=*(Vec*)(uintptr_t)(c->camera+0x38);e->direction=view_direction(c->camera);
 e->goal=*(Vec*)(uintptr_t)(c->spectator+0xac);e->fov=F(c->camera,0x268);
 memcpy(e->angles,(void*)(uintptr_t)(c->spectator+0x58),8);
 memcpy(e->view,(void*)(uintptr_t)(c->camera+0xc0),64);memcpy(e->projection,(void*)(uintptr_t)(c->camera+0x100),64);
 e->raw_time=F(c->player,0x18);e->replay_rate=F(c->player,0x14);e->scene_rate=F(c->scene,0x2a8);e->clock_paused=B(c->player,0x12);
 e->base_roll=F(c->camera,0x5c);e->horizontal_fov=(float)(2*atan(1./e->projection[0])*180/PI);
 memcpy(e->width,(void*)(uintptr_t)(c->shadow+0x550),12);memcpy(e->step,(void*)(uintptr_t)(c->shadow+0x560),12);
 uint32_t arr=U(c->shadow,0x288);if(U(c->shadow,0x294)!=3||!readable(arr,24)){fail(15);return;}
 for(int i=0;i<3;i++){
  uint32_t cam=U(arr,i*8);if(!readable(cam,0x180)){fail(16);return;}
  memcpy(e->shadow_projection[i],(void*)(uintptr_t)(cam+0x100),64);
  memcpy(e->shadow_vp[i],(void*)(uintptr_t)(cam+0x140),64);
 }
 InterlockedExchange(&e->commit,index+1);
}
static void __fastcall update_hook(void*self,void*unused,float dt){
 (void)unused;InterlockedIncrement(&g_shared.active);
 InterlockedCompareExchange(&g_shared.update_tid,GetCurrentThreadId(),0);
 original_update(self,dt);InterlockedIncrement(&g_shared.updates);
 if(g_shared.status==1||g_shared.status==2){
  int error=guard();if(error){if(error==2)request_stop();else fail(error);}
  else{
   LARGE_INTEGER now;QueryPerformanceCounter(&now);
   if(g_shared.command==1&&!armed){
    if(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.b)>.01f)fail(17);
    else{Config*c=&g_shared.cfg;memcpy(expected_angles,c->angles,8);expected_fov=c->fov;expected_roll=c->start_roll;memcpy(expected_projection,c->projection,64);expected_direction=c->direction;armed=1;g_shared.start_qpc=now.QuadPart;g_shared.last_qpc=now.QuadPart;g_shared.last_goal=*(Vec*)(uintptr_t)(c->spectator+0xac);g_shared.status=2;}
   }
   if(armed&&g_shared.status==2){
    double t=(double)(now.QuadPart-g_shared.start_qpc)/g_shared.frequency;
    if(g_shared.cfg.replay_mode){
     if(g_shared.clock_started)t=g_shared.cfg.approach_seconds+(g_shared.cfg.camera_clock?g_shared.replay_elapsed:g_shared.shooting_elapsed);
     else if(t>g_shared.cfg.approach_seconds)t=g_shared.cfg.approach_seconds;
    }
    if((double)(now.QuadPart-g_shared.last_qpc)/g_shared.frequency>.15)fail(18);
    else if(memcmp((void*)(uintptr_t)(g_shared.cfg.spectator+0xac),&g_shared.last_goal,12))fail(19);
    else{
     PathPoint pose=path(t);Vec p=pose.position,direction;float angles[3];Config*c=&g_shared.cfg;
     float fov=c->fov_enabled?pose.horizontal_fov/c->fov_scale:c->fov;
     if((c->orientation_enabled&&!orientation(pose.quaternion,&direction,angles))||!isfinite(fov)||fov<5||fov>90){fail(24);InterlockedDecrement(&g_shared.active);return;}
     *(Vec*)(uintptr_t)(c->spectator+0xac)=p;
     ((SetFn)(uintptr_t)c->set_position)((void*)(uintptr_t)c->camera,&p);
     Vec setter=c->setter_direction;
     if(c->orientation_enabled){
      angles[0]=expected_angles[0]+remainderf(angles[0]-expected_angles[0],360.f);
      memcpy((void*)(uintptr_t)(c->spectator+0x58),angles,8);memcpy((void*)(uintptr_t)(c->spectator+0x60),angles,8);
      setter=(Vec){direction.x*100,direction.y*100,direction.z*100};*(Vec*)(uintptr_t)(c->spectator+0xb8)=setter;
      /* Base roll is an independent scalar; position/direction setters invalidate
       * base view, then Refresh builds the roll view and VP through native code. */
      F(c->camera,0x5c)=angles[2];memcpy(expected_angles,angles,8);expected_roll=angles[2];
     }
     ((SetFn)(uintptr_t)c->set_direction)((void*)(uintptr_t)c->camera,&setter);
     if(c->fov_enabled){F(c->spectator,0x114)=F(c->spectator,0x118)=fov;((ScalarFn)(uintptr_t)c->set_fov)((void*)(uintptr_t)c->camera,fov);expected_fov=fov;}
     ((RefreshFn)(uintptr_t)c->refresh)((void*)(uintptr_t)c->camera,0);
     expected_direction=view_direction(c->camera);memcpy(expected_projection,(void*)(uintptr_t)(c->camera+0x100),64);
     g_shared.last_goal=p;g_shared.last_qpc=now.QuadPart;g_shared.last_elapsed=t;
     InterlockedIncrement(&g_shared.position_applies);if(t>=c->duration+c->approach_seconds)g_shared.command=9;
    }
   }
   if(g_shared.status==1||g_shared.status==2)log_event(1,dt);
   if(g_shared.command==9)request_stop();if(!armed&&GetTickCount()-attached>15000)fail(20);
  }
 }
 InterlockedDecrement(&g_shared.active);
}
static void __fastcall draw_hook(void*self,void*unused,void*render){
 (void)unused;InterlockedIncrement(&g_shared.active);
 InterlockedCompareExchange(&g_shared.draw_tid,GetCurrentThreadId(),0);InterlockedIncrement(&g_shared.draws);
 if(g_shared.status==1||g_shared.status==2){int e=guard();if(e){if(e==2)request_stop();else fail(e);}else log_event(2,0);}
 original_draw(self,render);InterlockedDecrement(&g_shared.active);
}
API DWORD WINAPI HookAttach(void*unused){
 (void)unused;Config*c=&g_shared.cfg;if(c->magic!=MAGIC||c->size!=sizeof(Config)||g_shared.status||g_shared.active)return 100;
 if(c->point_count<2||c->point_count>MAX_POINTS||c->reverse>1||!isfinite(c->duration)||c->duration<=0||(c->replay_mode&&(c->duration<0.5f||c->duration>120))||!isfinite(c->approach_seconds)||c->approach_seconds<0||c->approach_seconds>3)return 108;
 if(c->orientation_enabled>1||c->fov_enabled>1||!isfinite(c->fov_scale)||c->fov_scale<=0||!isfinite(c->aspect)||c->aspect<=0)return 111;
 if(g_shared.points[0].time!=0||g_shared.points[c->point_count-1].time!=c->duration)return 109;
 for(uint32_t i=0;i<c->point_count;i++){
  PathPoint*p=&g_shared.points[i];if(!isfinite(p->time)||(i&&p->time<=g_shared.points[i-1].time))return 109;
  for(int j=0;j<3;j++){float x=((float*)&p->position)[j];if(!isfinite(x)||x<((float*)&c->lower)[j]+.1f||x>((float*)&c->upper)[j]-.1f)return 110;}
  double norm=0;for(int j=0;j<4;j++){float x=((float*)&p->quaternion)[j];if(!isfinite(x))return 111;norm+=(double)x*x;}
  if(fabs(norm-1)>.0001||!isfinite(p->horizontal_fov))return 111;
  Vec d;float a[3];if((c->orientation_enabled&&!orientation(p->quaternion,&d,a))||(c->fov_enabled&&(p->horizontal_fov/c->fov_scale<5||p->horizontal_fov/c->fov_scale>90)))return 111;
 }
#ifndef HOOK_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->update_vft!=live(0x37f8fb0)||c->shadow_vft!=live(0x375b100)||c->set_position!=live(0xa95710)||c->set_direction!=live(0xa92b80)||c->refresh!=live(0xa7aee0)||c->set_fov!=live(0x15eaf10)||U(c->camera_vft,16)!=c->set_fov)return 101;
#endif
 armed=0;clock_attached=0;g_shared.clock_raw=c->raw_time;g_shared.current_rate=c->initial_rate;g_shared.clock_paused=1;g_shared.clock_restored=1;
 if(c->replay_mode&&!validate_clock_config())return 112;
 int error=guard();if(error){g_shared.error=error;return 102;}
 if(U(c->battle,0x128)!=c->update_vft||U(c->shadow,0)!=c->shadow_vft)return 103;
#ifndef HOOK_SELF_TEST
 if(U(c->update_vft,12)!=live(0x17754b0)||U(c->shadow_vft,12)!=live(0xc7b2c0))return 104;
#endif
 memcpy(uc,(void*)(uintptr_t)(c->update_vft-4),sizeof(uc));memcpy(sc,(void*)(uintptr_t)(c->shadow_vft-4),sizeof(sc));
 original_update=(UpdateFn)uc[4];original_draw=(DrawFn)sc[4];uc[4]=(uintptr_t)update_hook;sc[4]=(uintptr_t)draw_hook;
 LARGE_INTEGER f;QueryPerformanceFrequency(&f);g_shared.frequency=f.QuadPart;attached=GetTickCount();armed=0;
 InterlockedExchange(&g_shared.status,1);
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)c->shadow,(LONG)(uintptr_t)(sc+1),c->shadow_vft)!=c->shadow_vft){fail(21);return 105;}
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->battle+0x128),(LONG)(uintptr_t)(uc+1),c->update_vft)!=c->update_vft){fail(22);return 106;}
 if(c->replay_mode){
  original_tick=(UpdateFn)(uintptr_t)c->tick_entry;
  if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),(LONG)(uintptr_t)replay_tick_hook,c->tick_entry)!=c->tick_entry){fail(26);return 113;}
  clock_attached=1;
 }
 return 0;
}
API DWORD WINAPI HookDetach(void*unused){(void)unused;g_shared.command=9;if(!g_shared.active&&!clock_attached)detach();return 0;}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD why,LPVOID unused){(void)unused;if(why==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(dll);return TRUE;}
#ifdef HOOK_LAYOUT
int main(void){
 printf("{\"config_size\":%u,\"event_size\":%u,\"shared_size\":%u,\"records\":%u,\"command\":%u,\"heartbeat\":%u,\"status\":%u,\"error\":%u,\"updates\":%u,\"draws\":%u,\"events\":%u,\"active\":%u,\"position_applies\":%u,\"detach_mask\":%u,\"frequency\":%u,\"last_elapsed\":%u,\"points\":%u,\"path_point_size\":%u,\"speed_points\":%u,\"speed_point_size\":%u}\n",
 (unsigned)sizeof(Config),(unsigned)sizeof(Event),(unsigned)sizeof(Shared),(unsigned)offsetof(Shared,records),(unsigned)offsetof(Shared,command),(unsigned)offsetof(Shared,heartbeat),(unsigned)offsetof(Shared,status),(unsigned)offsetof(Shared,error),(unsigned)offsetof(Shared,updates),(unsigned)offsetof(Shared,draws),(unsigned)offsetof(Shared,events),(unsigned)offsetof(Shared,active),(unsigned)offsetof(Shared,position_applies),(unsigned)offsetof(Shared,detach_mask),(unsigned)offsetof(Shared,frequency),(unsigned)offsetof(Shared,last_elapsed),(unsigned)offsetof(Shared,points),(unsigned)sizeof(PathPoint),(unsigned)offsetof(Shared,speeds),(unsigned)sizeof(SpeedPoint));return 0;
}
#endif
