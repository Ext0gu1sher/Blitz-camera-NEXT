/* Isolated experiment: the real ReplayHUD camera action, deferred to the
 * engine main-job pump. No game clock, camera fields or replay reconstruction
 * are written. Only the one-shot tick functor is temporarily replaced. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#define API __declspec(dllexport)
#define MAGIC 0x31434642u
#define U(p,o) (*(uint32_t*)((uintptr_t)(p)+(o)))
#define B(p,o) (*(unsigned char*)((uintptr_t)(p)+(o)))
#define F(p,o) (*(float*)((uintptr_t)(p)+(o)))
typedef void (__thiscall *TickFn)(void*,float);
typedef uint32_t (__thiscall *QueueFn)(void*,void*,uint32_t);
typedef void* (__thiscall *AnyFn)(void*,const unsigned char*,uint32_t);
typedef void (__thiscall *ActionFn)(void*,const void*);
typedef void (__thiscall *DestroyFn)(void*);
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,base,context,player,scene_owner,scene,render,game_camera,free_camera;
 uint32_t hud,model,engine,head,node,functor,job_manager,tick_entry,queue_entry;
 uint32_t any_entry,action_entry,destroy_entry,initial_camera,want_free,execute;
 float raw,origin,rate;
} Config;
typedef struct {
 volatile LONG heartbeat,status,error,active,detached,thread,queued,job_thread;
 volatile LONG requests,job_calls,clones,destroys,before_mode,after_mode;
 uint32_t token;
} Header;
typedef struct {Config cfg;Header h;} Shared;
typedef struct {void **vft;uint32_t cookie;} Job;
typedef struct {unsigned char storage[0x24];Job *ptr;} Function;
#pragma pack(pop)
_Static_assert(sizeof(Function)==40&&offsetof(Function,ptr)==36,"Native inline function ABI");
API Shared g_shared;
static TickFn original_tick;
static void __fastcall tick_hook(void*,void*,float);
static uint32_t live(uint32_t va){return g_shared.cfg.base+va-0x400000;}
static int readable(uint32_t p,size_t n){
 MEMORY_BASIC_INFORMATION m;
 if(p<0x10000||n>0xffffffffu-p||!VirtualQuery((void*)(uintptr_t)p,&m,sizeof(m)))return 0;
 return m.State==MEM_COMMIT&&!(m.Protect&(PAGE_NOACCESS|PAGE_GUARD))&&p+n<=(uintptr_t)m.BaseAddress+m.RegionSize;
}
static int mode(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->scene,0x128)||!readable(c->render,0xbc))return -1;
 uint32_t a=U(c->scene,0x120);
 if(U(c->scene,0x124)!=a||U(c->render,0xb4)!=a||U(c->render,0xb8)!=a)return -1;
 return a==c->free_camera?1:a==c->game_camera?0:-1;
}
static int valid(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->context,0x1b4)||!readable(c->player,0x10c)||!readable(c->scene_owner,0xa0)||
    !readable(c->scene,0x128)||!readable(c->render,0xbc)||!readable(c->game_camera,4)||
    !readable(c->free_camera,4)||!readable(c->hud,0x150)||!readable(c->model,0xc))return 0;
 return U(c->context,0)==live(0x37f8a00)&&U(c->player,0)==live(0x37c1f44)&&U(c->player,0xc)==live(0x37c1f4c)&&
 U(c->scene_owner,0)==live(0x3853fd4)&&U(c->scene,0)==live(0x3713a60)&&U(c->render,0)==live(0x3777120)&&
 U(c->game_camera,0)==live(0x382da70)&&U(c->free_camera,0)==live(0x385402c)&&
 U(c->hud,0)==live(0x3853e68)&&U(c->model,0)==live(0x385332c)&&
 U(c->context,0x1b0)==c->player&&U(c->scene_owner,0x20)==c->context&&U(c->scene_owner,0x1c)==c->scene&&
 U(c->scene_owner,0x8c)==c->game_camera&&U(c->scene_owner,0x94)==c->free_camera&&U(c->scene,0xa8)==c->render&&
 U(c->hud,0x120)==c->context&&U(c->hud,0x148)==c->model&&
 U(c->scene,0x120)==c->initial_camera&&mode()>=0&&B(c->context,0x190)==mode()&&
 B(c->player,0x11)==1&&B(c->player,0x12)==1&&B(c->player,0x35)==1&&!B(c->player,0x2d)&&!B(c->player,0x2e)&&
 U(c->player,0x108)==0xffffffff&&U(c->player,0xa0)&&F(c->player,0x18)==c->raw&&F(c->player,0x64)==c->origin&&F(c->player,0x14)==c->rate;
}
static int functor_valid(void){
 Config*c=&g_shared.cfg;
 return readable(c->node,0x50)&&c->functor==c->node+0x20&&U(c->functor,0)==live(0x37c4674)&&
 U(c->functor,8)==c->player&&U(c->functor,0x14)==0;
}
static int in_signal(int job){
 Config*c=&g_shared.cfg;
 if(!readable(c->engine,0x80)||U(c->engine,0x74)!=c->head||!readable(c->head,8))return 0;
 uint32_t p=U(c->head,0),prev=c->head;int found=0,emits=0,pump=0;
 for(int i=0;p!=c->head&&i<64;i++){
  if(!readable(p,0x50)||U(p,4)!=prev)return 0;
  if(p==c->node)found=1;
  if(U(p,0x48)&1){emits++;pump=U(p,0x20)==live(0x372ab00)&&U(p,0x24)==c->job_manager&&U(p,0x28)==live(0x92aec0);}
  prev=p;p=U(p,0);
 }
 return p==c->head&&U(c->head,4)==prev&&found&&emits==1&&
 (job?(pump&&!(U(c->node,0x48)&1)):(U(c->node,0x48)&1));
}
static int restore_entry(void){
 Config*c=&g_shared.cfg;if(!functor_valid())return 0;
 LONG old=InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),c->tick_entry,(LONG)(uintptr_t)tick_hook);
 if((uint32_t)old!=c->tick_entry&&(uint32_t)old!=(uint32_t)(uintptr_t)tick_hook)return 0;
 g_shared.h.detached=1;return 1;
}
static void __fastcall job_invoke(Job*self,void*unused){
 (void)unused;Config*c=&g_shared.cfg;Header*h=&g_shared.h;InterlockedIncrement(&h->active);
 h->job_thread=GetCurrentThreadId();InterlockedIncrement(&h->job_calls);
 if(self->cookie!=MAGIC||InterlockedCompareExchange(&h->status,3,2)!=2)goto done;
 if(h->job_thread!=h->thread){h->error=10;goto reject;}
 if(GetTickCount()-(DWORD)h->heartbeat>1500){h->error=11;goto reject;}
 if(!valid()||!functor_valid()||!in_signal(1)||U(c->functor,0x10)!=c->tick_entry){h->error=12;goto reject;}
 h->before_mode=mode();
 /* The HUD action dispatches a toggle. The mode guard makes this operation
  * idempotent; the bool argument alone does NOT make native dispatch a setter. */
 if(c->execute&&(uint32_t)h->before_mode!=c->want_free){
  uint32_t any[5]={0};unsigned char wanted=(unsigned char)c->want_free;
  ((AnyFn)(uintptr_t)c->any_entry)(any,&wanted,1);
  h->requests=1;
  ((ActionFn)(uintptr_t)c->action_entry)((void*)(uintptr_t)c->hud,any);
  ((DestroyFn)(uintptr_t)c->destroy_entry)((unsigned char*)any+4);
 }
 h->after_mode=mode();h->status=4;goto done;
 reject:h->status=-1;
 done:InterlockedExchange(&h->queued,0);InterlockedDecrement(&h->active);
}
static void* __fastcall job_clone(Job*self,void*unused,void*dest){(void)unused;memcpy(dest,self,sizeof(Job));InterlockedIncrement(&g_shared.h.clones);return dest;}
static void* __fastcall job_type(Job*self,void*unused){(void)self;(void)unused;return(void*)"BlitzCamFreeCamera1121";}
static void __fastcall job_destroy(Job*self,void*unused,int heap){(void)self;(void)unused;InterlockedIncrement(&g_shared.h.destroys);if((unsigned char)heap)g_shared.h.error=14;}
static void*job_vft[]={job_clone,job_clone,job_invoke,job_type,job_destroy};
static void __fastcall tick_hook(void*self,void*unused,float dt){
 (void)unused;Config*c=&g_shared.cfg;Header*h=&g_shared.h;InterlockedIncrement(&h->active);
 if(InterlockedCompareExchange(&h->status,2,1)!=1){original_tick(self,dt);goto done;}
 h->thread=GetCurrentThreadId();int error=0;
 if(GetTickCount()-(DWORD)h->heartbeat>1500)error=1;
 else if((uintptr_t)self!=c->player||!valid()||!functor_valid()||!in_signal(0))error=2;
 if(!restore_entry())error=3;
 if(error){h->error=error;h->status=-1;original_tick(self,dt);goto done;}
 Job job={job_vft,MAGIC};Function fn={0};fn.ptr=&job;h->queued=1;
 h->token=((QueueFn)(uintptr_t)c->queue_entry)((void*)(uintptr_t)c->job_manager,&fn,1);
 if(!h->token){h->error=4;h->status=-1;h->queued=0;}
 original_tick(self,dt);
 done:InterlockedDecrement(&h->active);
}
API DWORD WINAPI HookAttach(void*unused){
 (void)unused;Config*c=&g_shared.cfg;Header*h=&g_shared.h;
 if(c->magic!=MAGIC||c->size!=sizeof(Config)||c->want_free>1||c->execute>1||h->status||h->active||h->queued||
    !isfinite(c->raw)||!isfinite(c->origin)||!isfinite(c->rate)||c->rate<=0)return 100;
#ifndef CAMERA_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->tick_entry!=live(0x140d100)||c->queue_entry!=live(0x91d090)||
    c->action_entry!=live(0x1e173e0)||c->any_entry!=live(0x717250)||c->destroy_entry!=live(0x6a4720))return 101;
 if(!readable(live(0x4690a30),4))return 105;
 uint32_t p=U(live(0x4690a30),0);
 if(!readable(p,4)||U(p,0)!=c->job_manager||!readable(c->job_manager,0x64)||!U(c->job_manager,0xc))return 106;
#endif
 /* At attach neither callback need be emitting; the linked list is checked
  * when the real tick and main-job pump run. */
 if(!valid()||!functor_valid()||U(c->functor,0x10)!=c->tick_entry)return 102;
 original_tick=(TickFn)(uintptr_t)c->tick_entry;h->status=1;
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),(LONG)(uintptr_t)tick_hook,c->tick_entry)!=c->tick_entry){h->error=5;h->status=-1;return 103;}
 return 0;
}
API DWORD WINAPI HookDetach(void*unused){
 (void)unused;Header*h=&g_shared.h;
 if(InterlockedCompareExchange(&h->status,-1,1)==1){h->error=6;restore_entry();}
 InterlockedCompareExchange(&h->status,-1,2);
#ifndef CAMERA_SELF_TEST
 DWORD begin=GetTickCount();while((h->active||h->queued)&&GetTickCount()-begin<1500)Sleep(5);
#endif
 return 0;
}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD why,LPVOID unused){(void)unused;if(why==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(dll);return TRUE;}
#ifdef CAMERA_LAYOUT
int main(void){printf("{\"config_size\":%u,\"header_size\":%u,\"shared_size\":%u}\n",(unsigned)sizeof(Config),(unsigned)sizeof(Header),(unsigned)sizeof(Shared));return 0;}
#endif
