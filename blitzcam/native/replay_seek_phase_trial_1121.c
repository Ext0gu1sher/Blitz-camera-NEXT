/* Research only. Defer a seek out of the emitting Replay tick into the native
 * main-job queue. Optional exact-build UI component repair, installed in that
 * pump and resident until process exit. No clock/camera/cache flag writes. AV
 * recording returns CONTINUE_SEARCH; it never hides a game failure. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#define API __declspec(dllexport)
#define MAGIC 0x32534b42u
#define U(p,o) (*(uint32_t*)((uintptr_t)(p)+(o)))
#define F(p,o) (*(float*)((uintptr_t)(p)+(o)))
#define B(p,o) (*(unsigned char*)((uintptr_t)(p)+(o)))
typedef void (__thiscall *TickFn)(void*,float);
typedef void (__thiscall *SeekFn)(void*,float);
typedef uint32_t (__thiscall *QueueFn)(void*,void*,uint32_t);
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,base,context,player,scene_owner,scene,camera;
 uint32_t context_vft,player_vft,secondary_vft,scene_owner_vft,scene_vft,camera_vft;
 uint32_t engine,head,node,functor,functor_vft,tick_entry,seek_entry;
 float raw,origin,rate,delta;
 uint32_t mode,job_manager,queue_entry;
 char fault_path[260];
 uint32_t ui_repair;
} Config;
typedef struct {
 volatile LONG heartbeat,status,error,active,detached,thread,requests;
 volatile LONG queued,job_thread,emitting_nodes,job_calls,clones,destroys,faults,observer;
 uint32_t job_token,queue_depth;
 float raw_before,raw_after;
 uint32_t emitting_node,emitting_vft,emitting_owner,emitting_entry;
} Header;
typedef struct {Config cfg;Header h;} Shared;
typedef struct {void **vft;uint32_t cookie;} Job;
typedef struct {unsigned char storage[0x24];Job *ptr;} Function;
typedef struct {
 uint32_t magic,size,tick,thread,read_lengths[4];
 EXCEPTION_RECORD exception;
 CONTEXT context;
 unsigned char child[0x60],material[0xc0],entries[0x200],stack[0x800];
} Fault;
#pragma pack(pop)
_Static_assert(sizeof(Job)==8,"Inline job layout");
_Static_assert(sizeof(Function)==0x28&&offsetof(Function,ptr)==0x24,"Native Function layout");
API Shared g_shared;
static TickFn original_tick;
static void __fastcall tick_hook(void*,void*,float);
static HANDLE fault_file=INVALID_HANDLE_VALUE;
static void *observer;
static volatile LONG fault_claim;
static Fault fault;
#include "replay_seek_phase_guards_1121.h"
#include "replay_ui_component_repair_1121.h"

static int emitting(void){
 Config*c=&g_shared.cfg;uint32_t p=U(c->head,0),prev=c->head;int n=0;
 for(int i=0;p!=c->head&&i<64;i++){
  if(!readable(p,0x50)||U(p,4)!=prev)return -1;
  if(U(p,0x48)&1){
   n++;g_shared.h.emitting_node=p;g_shared.h.emitting_vft=U(p,0x20);
   g_shared.h.emitting_owner=U(p,0x24);g_shared.h.emitting_entry=U(p,0x28);
  }
  prev=p;p=U(p,0);
 }
 return p==c->head&&U(c->head,4)==prev?n:-1;
}
static uint32_t copy_memory(void*dst,uint32_t src,size_t size){
 SIZE_T n=0;ReadProcessMemory(GetCurrentProcess(),(void*)(uintptr_t)src,dst,size,&n);return(uint32_t)n;
}
static LONG CALLBACK first_fault(EXCEPTION_POINTERS*p){
 if(p->ExceptionRecord->ExceptionCode!=EXCEPTION_ACCESS_VIOLATION||InterlockedCompareExchange(&fault_claim,1,0))return EXCEPTION_CONTINUE_SEARCH;
 fault.magic=0x31415642;fault.size=sizeof(Fault);fault.tick=GetTickCount();fault.thread=GetCurrentThreadId();
 fault.exception=*p->ExceptionRecord;fault.context=*p->ContextRecord;
 fault.read_lengths[0]=copy_memory(fault.child,p->ContextRecord->Esi,sizeof(fault.child));
 fault.read_lengths[1]=copy_memory(fault.material,p->ContextRecord->Edi,sizeof(fault.material));
 uint32_t entries=0;memcpy(&entries,fault.material+0x90,4);
 if(fault.read_lengths[1]>=0xa0)fault.read_lengths[2]=copy_memory(fault.entries,entries,sizeof(fault.entries));
 fault.read_lengths[3]=copy_memory(fault.stack,p->ContextRecord->Esp,sizeof(fault.stack));
 DWORD n=0;if(fault_file!=INVALID_HANDLE_VALUE){WriteFile(fault_file,&fault,sizeof(Fault),&n,NULL);FlushFileBuffers(fault_file);}
 if(ui_log!=INVALID_HANDLE_VALUE)FlushFileBuffers(ui_log);
 InterlockedIncrement(&g_shared.h.faults);
 return EXCEPTION_CONTINUE_SEARCH;
}
static int restore_entry(void){
 Config*c=&g_shared.cfg;if(!functor_valid())return 0;
 LONG old=InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),c->tick_entry,(LONG)(uintptr_t)tick_hook);
 if((uint32_t)old!=c->tick_entry&&(uint32_t)old!=(uint32_t)(uintptr_t)tick_hook)return 0;
 g_shared.h.detached=1;return 1;
}
static void __fastcall job_invoke(Job*self,void*unused){
 (void)unused;Header*h=&g_shared.h;Config*c=&g_shared.cfg;InterlockedIncrement(&h->active);
 h->job_thread=GetCurrentThreadId();InterlockedIncrement(&h->job_calls);
 if(self->cookie!=MAGIC||InterlockedCompareExchange(&h->status,3,2)!=2)goto done;
 if((DWORD)h->job_thread!=(DWORD)h->thread){h->error=10;goto reject;}
 if(GetTickCount()-(DWORD)h->heartbeat>1500){h->error=11;goto reject;}
 if(!valid()||!in_signal()){h->error=12;goto reject;}
 h->emitting_nodes=emitting();
 /* The queue pump itself emits one engine callback. Replay must not emit.
  * 372ab00/92b960 wraps owner at +4 and function at +8; 92aec0 drains jobs. */
 if(h->emitting_nodes!=1||h->emitting_vft!=live(0x372ab00)||h->emitting_owner!=c->job_manager||h->emitting_entry!=live(0x92aec0)||(U(c->node,0x48)&1)){h->error=13;goto reject;}
 h->raw_before=F(c->player,0x18);
 if(c->ui_repair){
#ifndef SEEK_SELF_TEST
  if(!ui_install()){h->error=15;goto reject;}
#endif
 }
 if(c->mode==1){
  h->requests=1;((SeekFn)(uintptr_t)c->seek_entry)((void*)(uintptr_t)c->player,c->delta);
 }
 /* No node, old context or scene access after native cleanup. */
 if(readable(c->player,0x10c)&&U(c->player,0)==c->player_vft)h->raw_after=F(c->player,0x18);
 InterlockedExchange(&h->status,4);goto done;
 reject:InterlockedExchange(&h->status,-1);
 done:InterlockedExchange(&h->queued,0);InterlockedDecrement(&h->active);
}
static void* __fastcall job_clone(Job*self,void*unused,void*dest){
 (void)unused;memcpy(dest,self,sizeof(Job));InterlockedIncrement(&g_shared.h.clones);return dest;
}
static void* __fastcall job_type(Job*self,void*unused){
 (void)self;(void)unused;static const char key[]="BlitzCamSeekPhaseTrial1121";return(void*)key;
}
static void __fastcall job_destroy(Job*self,void*unused,int heap){
 (void)self;(void)unused;InterlockedIncrement(&g_shared.h.destroys);
 /* Eight-byte clones always use the native function's inline storage. */
 /* The native ABI uses a bool byte; callers need not clear upper bits. */
 if((unsigned char)heap)g_shared.h.error=14;
}
static void*job_vft[]={job_clone,job_clone,job_invoke,job_type,job_destroy};
static void __fastcall tick_hook(void*self,void*unused,float dt){
 (void)unused;Header*h=&g_shared.h;Config*c=&g_shared.cfg;InterlockedIncrement(&h->active);
 if(InterlockedCompareExchange(&h->status,2,1)!=1){original_tick(self,dt);goto done;}
 h->thread=GetCurrentThreadId();
 int error=0;
 if(GetTickCount()-(DWORD)h->heartbeat>1500)error=1;
 else if((uintptr_t)self!=c->player||!valid()||!functor_valid()||!in_signal()||!(U(c->node,0x48)&1))error=2;
 if(!restore_entry())error=3;
 if(error){h->error=error;h->status=-1;original_tick(self,dt);goto done;}
 Job job={job_vft,MAGIC};Function fn;memset(&fn,0,sizeof(fn));fn.ptr=&job;
 InterlockedExchange(&h->queued,1);
 h->job_token=((QueueFn)(uintptr_t)c->queue_entry)((void*)(uintptr_t)c->job_manager,&fn,1);
 if(!h->job_token){h->error=4;h->status=-1;h->queued=0;}
 original_tick(self,dt);
 done:InterlockedDecrement(&h->active);
}
API DWORD WINAPI HookAttach(void*unused){
 (void)unused;Config*c=&g_shared.cfg;Header*h=&g_shared.h;
 if(c->magic!=MAGIC||c->size!=sizeof(Config)||h->status||h->active||h->queued||
    (observer&&!(g_ui_repair.installed&&c->ui_repair))||
    (g_ui_repair.installed&&(!c->ui_repair||fault_claim||g_ui_repair.violations))||c->ui_repair>1||c->mode>1||!isfinite(c->raw)||!isfinite(c->origin)||!isfinite(c->rate)||c->rate<=0||!isfinite(c->delta)||fabsf(c->delta)>3600||c->raw+c->delta<c->origin)return 100;
#ifndef SEEK_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->tick_entry!=live(0x140d100)||c->seek_entry!=live(0x13e5ea0)||c->queue_entry!=live(0x91d090)||c->functor_vft!=live(0x37c4674)||U(c->functor_vft,8)!=live(0x12f8310)||c->player_vft!=live(0x37c1f44)||c->context_vft!=live(0x37f8a00)||c->scene_owner_vft!=live(0x3853fd4)||c->scene_vft!=live(0x3713a60)||c->camera_vft!=live(0x385402c)||c->secondary_vft!=live(0x37c1f4c))return 101;
 if(!readable(live(0x4690a30),4))return 105;
 uint32_t singleton=U(live(0x4690a30),0);
 if(!readable(singleton,4)||U(singleton,0)!=c->job_manager||!readable(c->job_manager,0x64)||!U(c->job_manager,0xc))return 106;
#endif
 if(!valid()||!functor_valid()||!in_signal()||U(c->functor,0x10)!=c->tick_entry)return 102;
#ifndef SEEK_SELF_TEST
 /* The supervisor supplies its own absolute diagnostic path; support relocated
  * workstations as well as the original research checkout. Never overwrite. */
 if(!memchr(c->fault_path,0,sizeof(c->fault_path))||
    !((c->fault_path[0]>='A'&&c->fault_path[0]<='Z')||(c->fault_path[0]>='a'&&c->fault_path[0]<='z'))||
    c->fault_path[1]!=':'||c->fault_path[2]!='\\')return 107;
 if(!observer){
  WCHAR diagnostic_path[260];
  if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,c->fault_path,-1,diagnostic_path,260))return 107;
  fault_file=CreateFileW(diagnostic_path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
  if(fault_file==INVALID_HANDLE_VALUE)return 108;
  memset(&fault,0,sizeof(fault));InterlockedExchange(&fault_claim,0);
  observer=AddVectoredExceptionHandler(1,first_fault);
  if(!observer){CloseHandle(fault_file);fault_file=INVALID_HANDLE_VALUE;return 109;}
 }
 h->observer=1;
#endif
 original_tick=(TickFn)(uintptr_t)c->tick_entry;h->status=1;
 if((uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)(c->functor+0x10),(LONG)(uintptr_t)tick_hook,c->tick_entry)!=c->tick_entry){h->error=5;h->status=-1;return 103;}
 return 0;
}
API DWORD WINAPI HookDetach(void*unused){
 (void)unused;Header*h=&g_shared.h;
 if(InterlockedCompareExchange(&h->status,-1,1)==1){h->error=6;restore_entry();}
 InterlockedCompareExchange(&h->status,-1,2);
#ifndef SEEK_SELF_TEST
 /* This export runs on the supervisor's remote thread, never the game thread. */
 DWORD begin=GetTickCount();
 while((h->active||h->queued)&&GetTickCount()-begin<1500)Sleep(5);
#endif
 /* The repaired component routines and first-fault observer stay resident
  * through render/pause/camera changes AND replay exit. Restart reverts them. */
 if(!h->active&&!h->queued&&!g_ui_repair.installed){
  if(observer){RemoveVectoredExceptionHandler(observer);observer=NULL;h->observer=0;}
  if(fault_file!=INVALID_HANDLE_VALUE){CloseHandle(fault_file);fault_file=INVALID_HANDLE_VALUE;}
 }
 return 0;
}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD why,LPVOID unused){(void)unused;if(why==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(dll);return TRUE;}
#ifdef SEEK_LAYOUT
int main(void){printf("{\"config_size\":%u,\"header_size\":%u,\"header_offset\":%u,\"shared_size\":%u,\"fault_size\":%u,\"ui_state_size\":%u,\"ui_event_size\":%u}\n",(unsigned)sizeof(Config),(unsigned)sizeof(Header),(unsigned)offsetof(Shared,h),(unsigned)sizeof(Shared),(unsigned)sizeof(Fault),(unsigned)sizeof(UiRepairState),(unsigned)sizeof(UiEvent));return 0;}
#endif
