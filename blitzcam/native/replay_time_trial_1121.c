/* Bounded replay clock experiment. No camera writes or executable patches.
 * An owned callback pointer and two per-instance vtables are restored on exit.
 * Game pause/speed functions run ONLY inside the verified update thread. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#define API __declspec(dllexport)
#define MAGIC 0x31545242u
#define CAP 4096
#define U(p,o) (*(uint32_t*)((uintptr_t)(p)+(o)))
#define F(p,o) (*(float*)((uintptr_t)(p)+(o)))
#define B(p,o) (*(unsigned char*)((uintptr_t)(p)+(o)))
typedef void (__thiscall *TickFn)(void*,float);
typedef void (__thiscall *DrawFn)(void*,void*);
typedef void (__thiscall *NotifyFn)(void*);
typedef void (__thiscall *PauseFn)(void*,uint32_t);
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,base,context,player,scene_owner,scene,render,shadow,camera,spectator;
 uint32_t context_vft,player_vft,secondary_vft,scene_owner_vft,scene_vft,render_vft,shadow_vft,camera_vft,spectator_vft;
 uint32_t engine,head,node,functor,functor_vft,tick_entry,scene_entry,draw_entry,notify_entry,pause_entry;
 float raw,origin,initial_rate,rate,duration;
 uint32_t mode;
} Config;
typedef struct {
 volatile LONG commit;
 uint32_t kind,thread,tick,stage,paused,scale_enabled,record_index;
 int64_t qpc;
 float dt,raw,rate,scene_rate,fov,position[3],shadow_width[3];
 double sum_dt;
} Event;
typedef struct {
 volatile LONG command,heartbeat,status,error,events,active,thread,detached,restored,writes,ticks,draws;
 int64_t frequency,start_qpc;
 double sum_dt;
} Header;
typedef struct {Config cfg;Header h;Event events[CAP];} Shared;
#pragma pack(pop)
API Shared g_shared;
static uintptr_t scene_copy[28],draw_copy[8];
static TickFn original_tick,original_scene;
static DrawFn original_draw;
static int owned_speed;
static float owned_rate;
static DWORD attached;
static uint32_t live(uint32_t va){return g_shared.cfg.base+va-0x400000;}
static int readable(uint32_t p,size_t n){
 MEMORY_BASIC_INFORMATION m;
 if(p<0x10000||n>0xffffffffu-p||!VirtualQuery((void*)(uintptr_t)p,&m,sizeof(m)))return 0;
 return m.State==MEM_COMMIT&&!(m.Protect&(PAGE_NOACCESS|PAGE_GUARD))&&p+n<=(uintptr_t)m.BaseAddress+m.RegionSize;
}
static int identities(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->context,0x1b4)||!readable(c->player,0x10c)||!readable(c->scene_owner,0xa0)||!readable(c->scene,0x2ac)||!readable(c->render,0xbc)||!readable(c->camera,0x26c)||!readable(c->spectator,0x138)||!readable(c->shadow,0x56c))return 0;
 uint32_t sv=U(c->scene,0),dv=U(c->shadow,0);
 return U(c->context,0)==c->context_vft&&U(c->player,0)==c->player_vft&&U(c->player,0xc)==c->secondary_vft&&
 U(c->scene_owner,0)==c->scene_owner_vft&&(sv==c->scene_vft||sv==(uint32_t)(uintptr_t)(scene_copy+1))&&
 U(c->render,0)==c->render_vft&&(dv==c->shadow_vft||dv==(uint32_t)(uintptr_t)(draw_copy+1))&&
 U(c->camera,0)==c->camera_vft&&U(c->spectator,0)==c->spectator_vft&&U(c->context,0x1b0)==c->player&&
 U(c->scene_owner,0x20)==c->context&&U(c->scene_owner,0x1c)==c->scene&&U(c->scene_owner,0x94)==c->camera&&
 U(c->scene,0xa8)==c->render&&U(c->scene,0x120)==c->camera&&U(c->scene,0x124)==c->camera&&
 U(c->render,0xb4)==c->camera&&U(c->render,0xb8)==c->camera&&U(c->render,0x8c)==c->shadow&&U(c->spectator,0xc)==c->camera;
}
static int clock_valid(void){
 Config*c=&g_shared.cfg;
 return identities()&&B(c->player,0x11)==1&&B(c->player,0x35)==1&&!B(c->player,0x2d)&&!B(c->player,0x2e)&&U(c->player,0x108)==0xffffffff&&U(c->player,0xa0)&&F(c->player,0x64)==c->origin&&isfinite(F(c->player,0x18));
}
static int functor_valid(void){
 Config*c=&g_shared.cfg;
 return readable(c->node,0x50)&&c->functor==c->node+0x20&&U(c->functor,0)==c->functor_vft&&U(c->functor,8)==c->player&&U(c->functor,0x14)==0;
}
static int in_signal(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->engine+0x70,16)||U(c->engine+0x70,4)!=c->head||!readable(c->head,8))return 0;
 uint32_t p=U(c->head,0),prev=c->head;int found=0;
 for(int i=0;p!=c->head&&i<64;i++){
  if(!readable(p,0x50)||U(p,4)!=prev)return 0;
  if(p==c->node)found=1;prev=p;p=U(p,0);
 }
 return p==c->head&&U(c->head,4)==prev&&found;
}
static void __fastcall tick_hook(void*,void*,float);
static void detach(void){
 Config*c=&g_shared.cfg;LONG before;
 if(functor_valid()){
  before=InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),c->tick_entry,(LONG)(uintptr_t)tick_hook);
  if((uint32_t)before==(uint32_t)(uintptr_t)tick_hook||(uint32_t)before==c->tick_entry)InterlockedOr(&g_shared.h.detached,1);
 }
 if(readable(c->scene,4)){
  before=InterlockedCompareExchange((LONG*)(uintptr_t)c->scene,c->scene_vft,(LONG)(uintptr_t)(scene_copy+1));
  if((uint32_t)before==(uint32_t)(uintptr_t)(scene_copy+1)||(uint32_t)before==c->scene_vft)InterlockedOr(&g_shared.h.detached,2);
 }
 if(readable(c->shadow,4)){
  before=InterlockedCompareExchange((LONG*)(uintptr_t)c->shadow,c->shadow_vft,(LONG)(uintptr_t)(draw_copy+1));
  if((uint32_t)before==(uint32_t)(uintptr_t)(draw_copy+1)||(uint32_t)before==c->shadow_vft)InterlockedOr(&g_shared.h.detached,4);
 }
}
static void finish(LONG error){
 Header*h=&g_shared.h;Config*c=&g_shared.cfg;
 if(error)InterlockedCompareExchange(&h->error,error,0);
 if(owned_speed){
  if(h->thread==(LONG)GetCurrentThreadId()&&clock_valid()&&F(c->player,0x14)==owned_rate){
   /* Stop first. Notify again after restoring the saved (still paused) rate. */
   ((PauseFn)(uintptr_t)c->pause_entry)((void*)(uintptr_t)c->player,1);
   F(c->player,0x14)=c->initial_rate;
   ((NotifyFn)(uintptr_t)c->notify_entry)((void*)(uintptr_t)c->player);
   h->writes++;h->restored=B(c->player,0x12)==1&&F(c->player,0x14)==c->initial_rate&&F(c->scene,0x2a8)==0;
  }else h->restored=0;
  owned_speed=0;
 }
 detach();InterlockedExchange(&h->status,h->error?-1:4);
}
static int running(void){return g_shared.h.status==1||g_shared.h.status==2;}
static int guard(void){
 Header*h=&g_shared.h;Config*c=&g_shared.cfg;
 if(h->command==9)return 2;
 if(GetTickCount()-(DWORD)h->heartbeat>1500)return 1;
 if(!clock_valid()||!functor_valid())return 3;
 if(h->status==1&&(B(c->player,0x12)!=1||F(c->player,0x18)!=c->raw||F(c->player,0x14)!=c->initial_rate))return 4;
 if(h->status==2&&(B(c->player,0x12)!=0||F(c->player,0x14)!=owned_rate))return 5;
 return 0;
}
static void log_event(uint32_t kind,float dt){
 Header*h=&g_shared.h;Config*c=&g_shared.cfg;LONG i=InterlockedIncrement(&h->events)-1;
 Event*e=&g_shared.events[i%CAP];InterlockedExchange(&e->commit,0);
 LARGE_INTEGER q;QueryPerformanceCounter(&q);e->qpc=q.QuadPart;e->kind=kind;e->thread=GetCurrentThreadId();e->tick=h->ticks;e->stage=h->status;
 e->dt=dt;e->raw=F(c->player,0x18);e->rate=F(c->player,0x14);e->paused=B(c->player,0x12);e->record_index=U(c->player,0x1c);
 e->scale_enabled=B(c->scene,0x2a4);e->scene_rate=F(c->scene,0x2a8);e->fov=F(c->camera,0x268);
 memcpy(e->position,(void*)(uintptr_t)(c->camera+0x38),12);memcpy(e->shadow_width,(void*)(uintptr_t)(c->shadow+0x550),12);e->sum_dt=h->sum_dt;
 InterlockedExchange(&e->commit,i+1);
}
static int enter_thread(void){
 Header*h=&g_shared.h;LONG tid=GetCurrentThreadId();InterlockedCompareExchange(&h->thread,tid,0);
 if(h->thread!=tid){finish(6);return 0;}return 1;
}
/* Integral of a symmetric smoothstep 1 -> floor -> 1 curve.
 * Quarter-duration ramps, half-duration hold. Extend at 1x after the end,
 * so a frame straddling the endpoint is still integrated consistently. */
static double mapped_time(double t){
 Config*c=&g_shared.cfg;double d=c->duration,r=d/4.,f=c->rate;
 if(t<=0)return 0;
 if(t>=d)return d*(.25+.75*f)+(t-d);
 if(t<r){double u=t/r;return t-(1-f)*r*(u*u*u-.5*u*u*u*u);}
 if(t<3*r)return r*(1+f)/2+f*(t-r);
 double v=t-3*r,u=v/r;
 return r*(1+f)/2+2*r*f+f*v+(1-f)*r*(u*u*u-.5*u*u*u*u);
}
static float frame_rate(float dt){
 if(g_shared.cfg.mode!=2)return g_shared.cfg.rate;
 double t=g_shared.h.sum_dt;
 return dt>0?(float)((mapped_time(t+dt)-mapped_time(t))/dt):1.f;
}
static void __fastcall tick_hook(void*self,void*unused,float dt){
 (void)unused;Header*h=&g_shared.h;Config*c=&g_shared.cfg;InterlockedIncrement(&h->active);
 int valid=enter_thread()&&running();
 if(valid){int e=guard();if(e){finish(e==2?0:e);valid=0;}}
 /* Finish at the NEXT replay-update entry: the last simulated frame has
  * already passed Scene update and Draw with its matching effective rate. */
 if(valid&&h->status==2&&h->sum_dt>=c->duration){finish(0);valid=0;}
 if(valid&&(!isfinite(dt)||dt<0||dt>.25f)){finish(7);valid=0;}
 if(valid&&h->command==1&&h->status==1&&c->mode){
  owned_rate=frame_rate(dt);F(c->player,0x14)=owned_rate;owned_speed=1;h->restored=0;h->writes++;
  ((NotifyFn)(uintptr_t)c->notify_entry)(self);
  ((PauseFn)(uintptr_t)c->pause_entry)(self,0);
  LARGE_INTEGER q;QueryPerformanceCounter(&q);h->start_qpc=q.QuadPart;h->status=2;
 }
 if(valid&&h->status==2&&c->mode==2){
  float next=frame_rate(dt);
  if(next!=owned_rate){owned_rate=next;F(c->player,0x14)=next;h->writes++;((NotifyFn)(uintptr_t)c->notify_entry)(self);}
 }
 if(valid){InterlockedIncrement(&h->ticks);log_event(1,dt);}
 original_tick(self,dt);
 if(valid&&running()){
  if(h->status==2)h->sum_dt+=dt;
  if(clock_valid())log_event(2,dt);else{finish(3);valid=0;}
 }
 if(running()&&GetTickCount()-attached>30000)finish(8);
 InterlockedDecrement(&h->active);
}
static void __fastcall scene_hook(void*self,void*unused,float dt){
 (void)unused;InterlockedIncrement(&g_shared.h.active);int valid=enter_thread()&&running();
 if(valid){int e=guard();if(e){finish(e==2?0:e);valid=0;}}
 if(valid)log_event(3,dt);
 original_scene(self,dt);
 if(valid&&running()&&clock_valid())log_event(4,dt);
 InterlockedDecrement(&g_shared.h.active);
}
static void __fastcall draw_hook(void*self,void*unused,void*render){
 (void)unused;InterlockedIncrement(&g_shared.h.active);int valid=enter_thread()&&running();
 if(valid){int e=guard();if(e){finish(e==2?0:e);valid=0;}}
 if(valid){InterlockedIncrement(&g_shared.h.draws);log_event(5,0);}
 original_draw(self,render);InterlockedDecrement(&g_shared.h.active);
}
API DWORD WINAPI HookAttach(void*unused){
 (void)unused;Header*h=&g_shared.h;Config*c=&g_shared.cfg;
 if(c->magic!=MAGIC||c->size!=sizeof(Config)||h->status||h->active||c->mode>2||!isfinite(c->rate)||c->rate<.0625f||c->rate>1||!isfinite(c->duration)||c->duration<1||c->duration>12||!isfinite(c->initial_rate)||c->initial_rate<=0||!isfinite(c->raw)||!isfinite(c->origin))return 100;
#ifndef REPLAY_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->tick_entry!=live(0x140d100)||c->notify_entry!=live(0x140ec00)||c->pause_entry!=live(0x1402000)||c->scene_entry!=live(0x7c46f0)||c->draw_entry!=live(0xc7b2c0)||c->functor_vft!=live(0x37c4674)||c->scene_vft!=live(0x3713a60)||c->shadow_vft!=live(0x375b100)||U(c->functor_vft,8)!=live(0x12f8310))return 101;
#endif
 if(!clock_valid()||!functor_valid()||!in_signal()||B(c->player,0x12)!=1||F(c->player,0x18)!=c->raw||F(c->player,0x14)!=c->initial_rate||!B(c->scene,0x2a4)||F(c->scene,0x2a8)!=0)return 102;
 if(U(c->functor,0x10)!=c->tick_entry||U(c->scene,0)!=c->scene_vft||U(c->shadow,0)!=c->shadow_vft||U(c->scene_vft,0x54)!=c->scene_entry||U(c->shadow_vft,12)!=c->draw_entry)return 103;
 memcpy(scene_copy,(void*)(uintptr_t)(c->scene_vft-4),sizeof(scene_copy));memcpy(draw_copy,(void*)(uintptr_t)(c->shadow_vft-4),sizeof(draw_copy));
 original_tick=(TickFn)(uintptr_t)c->tick_entry;original_scene=(TickFn)(uintptr_t)c->scene_entry;original_draw=(DrawFn)(uintptr_t)c->draw_entry;
 scene_copy[22]=(uintptr_t)scene_hook;draw_copy[4]=(uintptr_t)draw_hook;owned_speed=0;
 LARGE_INTEGER f;QueryPerformanceFrequency(&f);h->frequency=f.QuadPart;attached=GetTickCount();h->restored=1;h->status=1;
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)c->scene,(LONG)(uintptr_t)(scene_copy+1),c->scene_vft)!=c->scene_vft){finish(9);return 104;}
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)c->shadow,(LONG)(uintptr_t)(draw_copy+1),c->shadow_vft)!=c->shadow_vft){finish(9);return 105;}
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),(LONG)(uintptr_t)tick_hook,c->tick_entry)!=c->tick_entry){finish(9);return 106;}
 return 0;
}
API DWORD WINAPI HookDetach(void*unused){(void)unused;g_shared.h.command=9;return 0;}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD why,LPVOID unused){(void)unused;if(why==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(dll);return TRUE;}
#ifdef REPLAY_LAYOUT
int main(void){printf("{\"config_size\":%u,\"header_size\":%u,\"event_size\":%u,\"events_offset\":%u,\"shared_size\":%u}\n",(unsigned)sizeof(Config),(unsigned)sizeof(Header),(unsigned)sizeof(Event),(unsigned)offsetof(Shared,events),(unsigned)sizeof(Shared));return 0;}
#endif
