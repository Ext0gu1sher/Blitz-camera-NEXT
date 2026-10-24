/* Locally built, exact-build paused replay experiment. Per-instance vtables;
 * no executable patches, shadow writes, online camera support or UI integration. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <math.h>
#include <string.h>
#define CAP 8192
#define MAGIC 0x31484342u
#define U(p,o) (*(uint32_t*)((uintptr_t)(p)+(o)))
#define F(p,o) (*(float*)((uintptr_t)(p)+(o)))
#define B(p,o) (*(unsigned char*)((uintptr_t)(p)+(o)))
#define API __declspec(dllexport)
typedef struct {float x,y,z;} Vec;
typedef void (__thiscall *UpdateFn)(void*,float);
typedef void (__thiscall *DrawFn)(void*,void*);
typedef void (__thiscall *SetFn)(void*,const Vec*);
/* Actual 11.21 callee returns a matrix pointer and ends in ret 4.
 * Existing game callers pass a null optional projection context. */
typedef void* (__thiscall *RefreshFn)(void*,void*);
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,base,battle,owner,context,player,scene,scene_owner;
 uint32_t replay_controller,game_camera,camera,spectator,render,shadow;
 uint32_t battle_vft,update_vft,shadow_vft,context_vft,player_vft;
 uint32_t camera_vft,spectator_vft,render_vft,scene_vft,scene_owner_vft;
 uint32_t replay_vft,game_vft,player_secondary_vft,set_position,set_direction,refresh;
 float raw_time,origin,fov,angles[2],projection[16];
 Vec direction,setter_direction,a,b;
} Config;
typedef struct {
 volatile LONG commit;
 uint32_t kind,thread,stage,updates,draws;
 int64_t qpc;
 double elapsed;
 float dt;
 Vec position,goal,direction;
 float fov,angles[2],view[16],projection[16],width[3],step[3];
 float shadow_projection[3][16],shadow_vp[3][16];
} Event;
typedef struct {
 Config cfg;
 volatile LONG command,heartbeat,status,error,updates,draws,events,active;
 volatile LONG update_tid,draw_tid,position_applies,detach_mask;
 int64_t frequency,start_qpc,last_qpc;
 double last_elapsed;
 Vec last_goal;
 Event records[CAP];
} Shared;
#pragma pack(pop)
API Shared g_shared;
static uintptr_t uc[7],sc[8]; /* include RTTI at vtable[-1] */
static UpdateFn original_update;
static DrawFn original_draw;
static DWORD attached;
static int armed;
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
 InterlockedExchange(&g_shared.status,g_shared.error?-1:4);
}
static void fail(LONG reason){InterlockedCompareExchange(&g_shared.error,reason,0);detach();}
static int guard(void){
 Config*c=&g_shared.cfg;
 if((DWORD)(GetTickCount()-(DWORD)g_shared.heartbeat)>1500)return 1;
 if(g_shared.command==9)return 2;
 if(!readable(c->battle,0x154)||!readable(c->owner,0x6c)||!readable(c->context,0x1b4)||!readable(c->player,0x10c)||!readable(c->camera,0x26c)||!readable(c->spectator,0x138)||!readable(c->scene,0x128)||!readable(c->scene_owner,0xa0)||!readable(c->render,0xbc)||!readable(c->shadow,0x5e0))return 3;
 if(!type(c->battle,c->battle_vft)||!type(c->context,c->context_vft)||!type(c->player,c->player_vft)||!type(c->camera,c->camera_vft)||!type(c->spectator,c->spectator_vft)||!type(c->render,c->render_vft)||!type(c->scene,c->scene_vft)||!type(c->scene_owner,c->scene_owner_vft)||!type(c->replay_controller,c->replay_vft)||!type(c->game_camera,c->game_vft))return 4;
 if(U(c->battle,0x120)!=c->context||U(c->battle,0x150)!=c->owner||U(c->owner,0x68)!=c->spectator||U(c->context,0x1b0)!=c->player||U(c->player,0xc)!=c->player_secondary_vft||U(c->scene,0xa8)!=c->render||U(c->scene,0x120)!=c->camera||U(c->scene,0x124)!=c->camera||U(c->render,0xb4)!=c->camera||U(c->render,0xb8)!=c->camera||U(c->render,0x8c)!=c->shadow||U(c->scene_owner,0x1c)!=c->scene||U(c->scene_owner,0x20)!=c->context||U(c->scene_owner,0x8c)!=c->game_camera||U(c->scene_owner,0x94)!=c->camera||U(c->scene_owner,0x9c)!=c->replay_controller||U(c->spectator,0xc)!=c->camera||U(c->replay_controller,0x28)!=c->game_camera||U(c->game_camera,0x5b8)!=c->replay_controller)return 5;
 if(B(c->player,0x11)!=1||B(c->player,0x12)!=1||B(c->player,0x35)!=1||!U(c->player,0xa0)||B(c->player,0x2d)||B(c->player,0x2e)||U(c->player,0x108)!=0xffffffff||F(c->player,0x18)!=c->raw_time||F(c->player,0x64)!=c->origin)return 6;
 if(U(c->camera,8)||U(c->camera,12)||U(c->spectator,0x10c)!=0xffffffff||U(c->spectator,0x128))return 7;
 for(int i=0x10;i<0x2e;i++)if(B(c->spectator,i))return 8;
 for(int i=0;i<3;i++)if(F(c->spectator,0x80+i*4)||F(c->spectator,0x9c+i*4))return 8;
 if(F(c->spectator,0x114)!=c->fov||F(c->spectator,0x118)!=c->fov||F(c->camera,0x268)!=c->fov||F(c->spectator,0x110)!=0||F(c->camera,0x5c)!=0)return 9;
 for(int i=0;i<2;i++)if(F(c->spectator,0x58+i*4)!=c->angles[i])return 10;
 for(int i=0;i<16;i++)if(fabsf(F(c->camera,0x100+i*4)-c->projection[i])>0.00000012f)return 11;
 for(int i=0;i<3;i++)if(fabsf(F(c->camera,0x50+i*4)-((float*)&c->direction)[i])>0.00002f)return 12;
 if(g_shared.draw_tid&&g_shared.update_tid&&g_shared.update_tid!=g_shared.draw_tid)return 13;
 return 0;
}
static Vec path(double elapsed){
 Config*c=&g_shared.cfg;Vec from=c->b,to=c->a;double t=elapsed;
 if(t>=11){from=c->a;to=c->b;t-=11;}if(t>8)t=8;if(t<0)t=0;
 double u=t/8;Vec p;if(u==0)return from;if(u==1)return to;
 p.x=(float)(from.x+(to.x-from.x)*u);p.y=(float)(from.y+(to.y-from.y)*u);
 p.z=(float)(from.z+(to.z-from.z)*u+2*sin(3.141592653589793*u));return p;
}
static uint32_t stage(double t){return !armed?0:t<8?1:t<11?2:t<19?3:4;}
static void log_event(uint32_t kind,float dt){
 LONG index=InterlockedIncrement(&g_shared.events)-1;if(index>=CAP){fail(14);return;}
 Event*e=&g_shared.records[index];Config*c=&g_shared.cfg;LARGE_INTEGER now;
 QueryPerformanceCounter(&now);e->qpc=now.QuadPart;e->kind=kind;e->thread=GetCurrentThreadId();
 e->elapsed=armed?(double)(now.QuadPart-g_shared.start_qpc)/g_shared.frequency:0;
 e->stage=stage(e->elapsed);e->dt=dt;e->updates=g_shared.updates;e->draws=g_shared.draws;
 e->position=*(Vec*)(uintptr_t)(c->camera+0x38);e->direction=*(Vec*)(uintptr_t)(c->camera+0x50);
 e->goal=*(Vec*)(uintptr_t)(c->spectator+0xac);e->fov=F(c->camera,0x268);
 memcpy(e->angles,(void*)(uintptr_t)(c->spectator+0x58),8);
 memcpy(e->view,(void*)(uintptr_t)(c->camera+0xc0),64);memcpy(e->projection,(void*)(uintptr_t)(c->camera+0x100),64);
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
  int error=guard();if(error){if(error==2)detach();else fail(error);}
  else{
   LARGE_INTEGER now;QueryPerformanceCounter(&now);
   if(g_shared.command==1&&!armed){
    if(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.b)>.01f)fail(17);
    else{armed=1;g_shared.start_qpc=now.QuadPart;g_shared.last_qpc=now.QuadPart;g_shared.last_goal=*(Vec*)(uintptr_t)(g_shared.cfg.spectator+0xac);g_shared.status=2;}
   }
   if(armed&&g_shared.status==2){
    double t=(double)(now.QuadPart-g_shared.start_qpc)/g_shared.frequency;
    if((double)(now.QuadPart-g_shared.last_qpc)/g_shared.frequency>.15)fail(18);
    else if(memcmp((void*)(uintptr_t)(g_shared.cfg.spectator+0xac),&g_shared.last_goal,12))fail(19);
    else{
     Vec p=path(t);Config*c=&g_shared.cfg;*(Vec*)(uintptr_t)(c->spectator+0xac)=p;
     ((SetFn)(uintptr_t)c->set_position)((void*)(uintptr_t)c->camera,&p);
     ((SetFn)(uintptr_t)c->set_direction)((void*)(uintptr_t)c->camera,&c->setter_direction);
     ((RefreshFn)(uintptr_t)c->refresh)((void*)(uintptr_t)c->camera,NULL);
     g_shared.last_goal=p;g_shared.last_qpc=now.QuadPart;g_shared.last_elapsed=t;
     InterlockedIncrement(&g_shared.position_applies);if(t>=22)g_shared.command=9;
    }
   }
   if(g_shared.status==1||g_shared.status==2)log_event(1,dt);
   if(g_shared.command==9)detach();if(!armed&&GetTickCount()-attached>15000)fail(20);
  }
 }
 InterlockedDecrement(&g_shared.active);
}
static void __fastcall draw_hook(void*self,void*unused,void*render){
 (void)unused;InterlockedIncrement(&g_shared.active);
 InterlockedCompareExchange(&g_shared.draw_tid,GetCurrentThreadId(),0);InterlockedIncrement(&g_shared.draws);
 if(g_shared.status==1||g_shared.status==2){int e=guard();if(e){if(e==2)detach();else fail(e);}else log_event(2,0);}
 original_draw(self,render);InterlockedDecrement(&g_shared.active);
}
API DWORD WINAPI HookAttach(void*unused){
 (void)unused;Config*c=&g_shared.cfg;if(c->magic!=MAGIC||c->size!=sizeof(Config)||g_shared.status)return 100;
#ifndef HOOK_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->update_vft!=live(0x37f8fb0)||c->shadow_vft!=live(0x375b100)||c->set_position!=live(0xa95710)||c->set_direction!=live(0xa92b80)||c->refresh!=live(0xa7aee0))return 101;
#endif
 int error=guard();if(error){g_shared.error=error;return 102;}
 if(U(c->battle,0x128)!=c->update_vft||U(c->shadow,0)!=c->shadow_vft)return 103;
#ifndef HOOK_SELF_TEST
 if(U(c->update_vft,12)!=live(0x17754b0)||U(c->shadow_vft,12)!=live(0xc7b2c0))return 104;
#endif
 memcpy(uc,(void*)(uintptr_t)(c->update_vft-4),sizeof(uc));memcpy(sc,(void*)(uintptr_t)(c->shadow_vft-4),sizeof(sc));
 original_update=(UpdateFn)uc[4];original_draw=(DrawFn)sc[4];uc[4]=(uintptr_t)update_hook;sc[4]=(uintptr_t)draw_hook;
 LARGE_INTEGER f;QueryPerformanceFrequency(&f);g_shared.frequency=f.QuadPart;attached=GetTickCount();
 InterlockedExchange(&g_shared.status,1);
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)c->shadow,(LONG)(uintptr_t)(sc+1),c->shadow_vft)!=c->shadow_vft){fail(21);return 105;}
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->battle+0x128),(LONG)(uintptr_t)(uc+1),c->update_vft)!=c->update_vft){fail(22);return 106;}
 return 0;
}
API DWORD WINAPI HookDetach(void*unused){(void)unused;g_shared.command=9;detach();return g_shared.detach_mask==3?0:107;}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD why,LPVOID unused){(void)unused;if(why==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(dll);return TRUE;}
#ifdef HOOK_LAYOUT
int main(void){
 printf("{\"config_size\":%u,\"event_size\":%u,\"shared_size\":%u,\"records\":%u,\"command\":%u,\"heartbeat\":%u,\"status\":%u,\"error\":%u,\"updates\":%u,\"draws\":%u,\"events\":%u,\"active\":%u,\"position_applies\":%u,\"detach_mask\":%u,\"frequency\":%u,\"last_elapsed\":%u}\n",
 (unsigned)sizeof(Config),(unsigned)sizeof(Event),(unsigned)sizeof(Shared),(unsigned)offsetof(Shared,records),(unsigned)offsetof(Shared,command),(unsigned)offsetof(Shared,heartbeat),(unsigned)offsetof(Shared,status),(unsigned)offsetof(Shared,error),(unsigned)offsetof(Shared,updates),(unsigned)offsetof(Shared,draws),(unsigned)offsetof(Shared,events),(unsigned)offsetof(Shared,active),(unsigned)offsetof(Shared,position_applies),(unsigned)offsetof(Shared,detach_mask),(unsigned)offsetof(Shared,frequency),(unsigned)offsetof(Shared,last_elapsed));return 0;
}
#endif
