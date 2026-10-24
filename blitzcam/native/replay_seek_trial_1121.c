/* One native seek request on the existing replay update thread. No raw-clock,
 * camera, scene or executable writes. Restore the callback BEFORE seek, then
 * never access the old signal node/scene again (rewind unregisters it). */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#define API __declspec(dllexport)
#define MAGIC 0x314b5342u
#define U(p,o) (*(uint32_t*)((uintptr_t)(p)+(o)))
#define F(p,o) (*(float*)((uintptr_t)(p)+(o)))
#define B(p,o) (*(unsigned char*)((uintptr_t)(p)+(o)))
typedef void (__thiscall *TickFn)(void*,float);
typedef void (__thiscall *SeekFn)(void*,float);
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,base,context,player,scene_owner,scene,camera;
 uint32_t context_vft,player_vft,secondary_vft,scene_owner_vft,scene_vft,camera_vft;
 uint32_t engine,head,node,functor,functor_vft,tick_entry,seek_entry;
 float raw,origin,rate,delta;
} Config;
typedef struct {
 volatile LONG heartbeat,status,error,active,detached,thread,requests;
 float raw_before,raw_after,target_after;
 uint32_t active_after,seek_after,waiting_after,task_after;
} Header;
typedef struct {Config cfg;Header h;} Shared;
#pragma pack(pop)
API Shared g_shared;
static TickFn original_tick;
static void __fastcall tick_hook(void*,void*,float);
static uint32_t live(uint32_t va){return g_shared.cfg.base+va-0x400000;}
static int readable(uint32_t p,size_t n){
 MEMORY_BASIC_INFORMATION m;
 if(p<0x10000||n>0xffffffffu-p||!VirtualQuery((void*)(uintptr_t)p,&m,sizeof(m)))return 0;
 return m.State==MEM_COMMIT&&!(m.Protect&(PAGE_NOACCESS|PAGE_GUARD))&&p+n<=(uintptr_t)m.BaseAddress+m.RegionSize;
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
static int valid(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->context,0x1b4)||!readable(c->player,0x10c)||!readable(c->scene_owner,0xa0)||!readable(c->scene,0x128)||!readable(c->camera,4))return 0;
 return U(c->context,0)==c->context_vft&&U(c->player,0)==c->player_vft&&U(c->player,0xc)==c->secondary_vft&&
 U(c->scene_owner,0)==c->scene_owner_vft&&U(c->scene,0)==c->scene_vft&&U(c->camera,0)==c->camera_vft&&
 U(c->context,0x1b0)==c->player&&U(c->scene_owner,0x20)==c->context&&U(c->scene_owner,0x1c)==c->scene&&U(c->scene_owner,0x94)==c->camera&&U(c->scene,0x120)==c->camera&&U(c->scene,0x124)==c->camera&&
 B(c->player,0x11)==1&&B(c->player,0x12)==1&&B(c->player,0x35)==1&&!B(c->player,0x2d)&&!B(c->player,0x2e)&&U(c->player,0x108)==0xffffffff&&U(c->player,0xa0)&&
 F(c->player,0x18)==c->raw&&F(c->player,0x64)==c->origin&&F(c->player,0x14)==c->rate;
}
static int restore_entry(void){
 Config*c=&g_shared.cfg;
 if(!functor_valid())return 0;
 LONG old=InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),c->tick_entry,(LONG)(uintptr_t)tick_hook);
 if((uint32_t)old!=c->tick_entry&&(uint32_t)old!=(uint32_t)(uintptr_t)tick_hook)return 0;
 g_shared.h.detached=1;return 1;
}
static void __fastcall tick_hook(void*self,void*unused,float dt){
 (void)unused;Header*h=&g_shared.h;Config*c=&g_shared.cfg;InterlockedIncrement(&h->active);
 if(InterlockedCompareExchange(&h->status,2,1)!=1){
  original_tick(self,dt);InterlockedDecrement(&h->active);return;
 }
 h->thread=GetCurrentThreadId();
 int error=0;
 if(GetTickCount()-(DWORD)h->heartbeat>1500)error=1;
 else if((uintptr_t)self!=c->player||!valid()||!functor_valid()||!in_signal()||!(U(c->node,0x48)&1))error=2;
 /* Native signal removal defers freeing an emitting node (flag +48 bit 0).
  * No code below restore+seek dereferences that node, even for logging. */
 if(!restore_entry())error=3;
 if(error){h->error=error;h->status=-1;original_tick(self,dt);}
 else{
  h->raw_before=F(c->player,0x18);h->requests=1;
  ((SeekFn)(uintptr_t)c->seek_entry)(self,c->delta);
  /* ReplayPlayer survives its own native reset; all other pointers may not. */
  if(readable(c->player,0x10c)&&U(c->player,0)==c->player_vft){
   h->raw_after=F(c->player,0x18);h->target_after=F(c->player,0x28);
   h->active_after=B(c->player,0x11);h->seek_after=B(c->player,0x2d);h->waiting_after=B(c->player,0x2e);h->task_after=U(c->player,0x108);
  }
  InterlockedExchange(&h->status,4);
 }
 InterlockedDecrement(&h->active);
}
API DWORD WINAPI HookAttach(void*unused){
 (void)unused;Config*c=&g_shared.cfg;Header*h=&g_shared.h;
 if(c->magic!=MAGIC||c->size!=sizeof(Config)||h->status||h->active||!isfinite(c->raw)||!isfinite(c->origin)||!isfinite(c->rate)||c->rate<=0||!isfinite(c->delta)||fabsf(c->delta)<.01f||fabsf(c->delta)>120||c->raw+c->delta<c->origin)return 100;
#ifndef SEEK_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->tick_entry!=live(0x140d100)||c->seek_entry!=live(0x13e5ea0)||c->functor_vft!=live(0x37c4674)||U(c->functor_vft,8)!=live(0x12f8310)||c->player_vft!=live(0x37c1f44)||c->context_vft!=live(0x37f8a00)||c->scene_owner_vft!=live(0x3853fd4)||c->scene_vft!=live(0x3713a60)||c->camera_vft!=live(0x385402c)||c->secondary_vft!=live(0x37c1f4c))return 101;
#endif
 if(!valid()||!functor_valid()||!in_signal()||U(c->functor,0x10)!=c->tick_entry)return 102;
 original_tick=(TickFn)(uintptr_t)c->tick_entry;h->status=1;
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),(LONG)(uintptr_t)tick_hook,c->tick_entry)!=c->tick_entry){h->error=4;h->status=-1;return 103;}
 return 0;
}
API DWORD WINAPI HookDetach(void*unused){
 (void)unused;
 /* Never access an old node after request execution. Once claimed, the game
  * thread owns restoration and the supervisor only waits for active=0. */
 if(InterlockedCompareExchange(&g_shared.h.status,-1,1)==1){g_shared.h.error=5;restore_entry();}
 return 0;
}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD why,LPVOID unused){(void)unused;if(why==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(dll);return TRUE;}
#ifdef SEEK_LAYOUT
int main(void){printf("{\"config_size\":%u,\"header_size\":%u,\"header_offset\":%u,\"shared_size\":%u}\n",(unsigned)sizeof(Config),(unsigned)sizeof(Header),(unsigned)offsetof(Shared,h),(unsigned)sizeof(Shared));return 0;}
#endif
