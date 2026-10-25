/* Isolated observer HUD visibility trial; derived from the validated freecamera
 * main-job scaffold. Only UI/entity SetVisibility is called; the camera is unchanged. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#define API __declspec(dllexport)
#define MAGIC 0x34485542u
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
 uint32_t battle_controller,battle,battle_screen,layers[5],layer_vfts[5],visible_entry,target_mask;
 uint32_t extra_count,extras[16][5]; /* control, parent, vft, name pointer, desired */
 uint32_t ghost_enabled,ghost_bpi,ghost_logic,ghost_vehicle,ghost_visual,ghost_entry,ghost_class,ghost_count;
 uint32_t ghost_nodes[256][8]; /* entity,parent,vft,children begin/end,old masks,desired visible */
 uint32_t opacity_count,opacity_type,opacity_index,opacity_get_entry,opacity_set_entry;
 uint32_t opacity_rows[16][7]; /* control,parent,vft,name,old component,old alpha bits,wanted bits */
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
static uint32_t visibility_mask(void){
 uint32_t mask=0;for(int i=0;i<5;i++)if(B(g_shared.cfg.layers[i],0x4c)&2)mask|=1u<<i;return mask;
}
static uint32_t opacity_component(uint32_t control){
 Config*c=&g_shared.cfg;
 if(!readable(control,0xf4)||c->opacity_index>255)return 0xffffffff;
 uint32_t table=U(control,0xf0);
 if(!readable(table,0x28))return 0xffffffff;
 uint32_t indices=U(table,0x24);
 if(!readable(indices,(c->opacity_index+1)*4))return 0xffffffff;
 uint32_t slot=U(indices,c->opacity_index*4);
 if(slot==0xffffffff)return 0;
 uint32_t begin=U(control,0xe4),end=U(control,0xe8);
 if(end<begin||end-begin>4096||(end-begin)%12||slot>=(end-begin)/12||!readable(begin,end-begin))return 0xffffffff;
 uint32_t first=U(begin,slot*12),last=U(begin,slot*12+4);
 if(first==last)return 0;
 if(last-first!=4||!readable(first,4))return 0xffffffff;
 return U(first,0);
}
static int opacity_valid(void){
 Config*c=&g_shared.cfg;if(c->opacity_count>16)return 0;
 for(uint32_t i=0;i<c->opacity_count;i++){
  uint32_t*r=c->opacity_rows[i];float before,wanted;
  memcpy(&before,&r[5],4);memcpy(&wanted,&r[6],4);
  if(!isfinite(before)||before<0||before>1||!isfinite(wanted)||wanted<0||wanted>1||
     (r[1]!=c->layers[0]&&r[1]!=c->layers[1])||!readable(r[0],0xf4)||U(r[0],0)!=r[2]||
     U(r[0],0x38)!=r[1]||U(r[0],0x30)!=r[3]||opacity_component(r[0])!=r[4])return 0;
  if(r[4]&&(!readable(r[4],24)||U(r[4],0)!=live(0x3781ee4)||U(r[4],8)!=r[0]||U(r[4],0x14)!=r[5]))return 0;
  if(!r[4]&&r[5]!=0x3f800000)return 0;
 }
 return 1;
}
static int ghost_tree(uint32_t a,uint32_t parent,uint32_t depth,uint32_t*index){
 Config*c=&g_shared.cfg;
 if(depth>=32||*index>=c->ghost_count||!readable(a,0x50))return 0;
 uint32_t*r=c->ghost_nodes[(*index)++];
 if(r[0]!=a||r[1]!=parent||U(a,0x18)!=parent||U(a,0)!=r[2]||U(a,8)!=r[3]||U(a,12)!=r[4]||
    U(a,0x48)!=r[5]||U(a,0x4c)!=r[6]||r[7]>1||r[4]<r[3]||(r[4]-r[3])%4||r[4]-r[3]>1024)return 0;
 if(r[4]>r[3]&&!readable(r[3],r[4]-r[3]))return 0;
 for(uint32_t p=r[3];p<r[4];p+=4)if(!ghost_tree(U(p,0),a,depth+1,index))return 0;
 return 1;
}
static int ghost_valid(void){
 Config*c=&g_shared.cfg;if(!c->ghost_enabled)return c->ghost_count==0;
 if(c->ghost_enabled!=1||!c->ghost_count||c->ghost_count>256||!readable(c->context,0x1b0)||
    !readable(c->ghost_bpi,0x20)||!readable(c->ghost_logic,0x78)||!readable(c->ghost_vehicle,4)||
    !readable(c->ghost_visual,0x5c)||!readable(c->ghost_class,9))return 0;
 if(U(c->context,0x1ac)!=c->ghost_bpi||U(c->ghost_bpi,0xc)!=0x70000001||U(c->ghost_bpi,0x10)!=c->ghost_logic||
    U(c->ghost_bpi,0x18)!=2||U(c->ghost_logic,0)!=live(0x38023d4)||U(c->ghost_logic,4)!=c->ghost_vehicle||
    U(c->ghost_logic,0x74)!=c->ghost_visual||U(c->ghost_vehicle,0)!=live(0x37f7d8c)||
    U(c->ghost_visual,0)!=live(0x3713afc)||U(c->ghost_visual,0x58)!=0x70000001||
    U(c->ghost_class,0)!=0||memcmp((void*)(uintptr_t)(c->ghost_class+4),"User",5))return 0;
 uint32_t index=0;
 return ghost_tree(c->ghost_visual,c->ghost_nodes[0][1],0,&index)&&index==c->ghost_count;
}
static int visibility_valid(void){
 Config*c=&g_shared.cfg;static const uint32_t offsets[]={0x5c,0x60,0x68,0x6c};
 if(!readable(c->battle_controller,0x15c)||!readable(c->battle,0x3c)||!readable(c->battle_screen,0x70))return 0;
 if(U(c->battle_controller,0)!=live(0x37f8f70)||U(c->battle_controller,0x120)!=c->context||
    U(c->battle_controller,0x150)!=c->battle||U(c->battle,0x38)!=c->battle_screen||
    U(c->battle_controller,0x158)!=0||B(c->battle,0x18)!=1)return 0;
 for(int i=0;i<5;i++)if(!readable(c->layers[i],0xb0)||U(c->layers[i],0)!=c->layer_vfts[i])return 0;
 for(int i=0;i<4;i++)if(U(c->battle_screen,offsets[i])!=c->layers[i])return 0;
 if(c->extra_count>16)return 0;
 for(uint32_t i=0;i<c->extra_count;i++){
  uint32_t*e=c->extras[i];
  if(e[4]>1||(e[1]!=c->layers[0]&&e[1]!=c->layers[1])||!readable(e[0],0x50)||
     U(e[0],0)!=e[2]||U(e[0],0x38)!=e[1]||U(e[0],0x30)!=e[3])return 0;
 }
 return readable(c->layers[1],0x264)&&U(c->layers[1],0)==live(0x384cec4)&&
 U(c->layers[1],0x180)==2&&U(c->layers[1],0x260)==c->layers[4]&&mode()==1;
}
static int valid(void){
 Config*c=&g_shared.cfg;
 if(!visibility_valid()||!ghost_valid()||!opacity_valid())return 0;
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
 /* One-shot UIControl::SetVisibility on the already existing observer UI.
  * No camera dispatch, counter edits, persistent patch, or new model is used. */
 if(c->execute){
  typedef void (__thiscall *VisibleFn)(void*,unsigned char);
  typedef uint32_t (__thiscall *ComponentFn)(void*,uint32_t,uint32_t);
  typedef void (__thiscall *OpacityFn)(void*,float);
  for(uint32_t i=0;i<c->opacity_count;i++){
   uint32_t*r=c->opacity_rows[i];
   uint32_t q=((ComponentFn)(uintptr_t)c->opacity_get_entry)((void*)(uintptr_t)r[0],c->opacity_type,0);
   if(!readable(q,24)||U(q,0)!=live(0x3781ee4)||U(q,8)!=r[0]||opacity_component(r[0])!=q){h->error=18;goto reject;}
   float wanted;memcpy(&wanted,&r[6],4);
   ((OpacityFn)(uintptr_t)c->opacity_set_entry)((void*)(uintptr_t)q,wanted);h->requests++;
   if(U(q,0x14)!=r[6]){h->error=19;goto reject;}
  }
  for(int i=0;i<5;i++){
   unsigned char wanted=(c->target_mask>>i)&1;
   if(((B(c->layers[i],0x4c)>>1)&1)!=wanted){
    ((VisibleFn)(uintptr_t)c->visible_entry)((void*)(uintptr_t)c->layers[i],wanted);h->requests++;
   }
  }
  for(uint32_t i=0;i<c->extra_count;i++){
   uint32_t*e=c->extras[i];
   if(((B(e[0],0x4c)>>1)&1)!=e[4]){
    ((VisibleFn)(uintptr_t)c->visible_entry)((void*)(uintptr_t)e[0],(unsigned char)e[4]);h->requests++;
   }
  }
  /* Native DAVA::Entity user visibility recursively updates render objects.
   * Preorder replay also restores each child's original user-visibility state. */
  for(uint32_t i=0;i<c->ghost_count;i++){
   uint32_t*r=c->ghost_nodes[i];
   if((U(r[0],0x48)&1)!=(r[7]?0u:1u)){
    ((VisibleFn)(uintptr_t)c->ghost_entry)((void*)(uintptr_t)r[0],(unsigned char)r[7]);h->requests++;
   }
  }
 }
 if(c->execute&&visibility_mask()!=c->target_mask){h->error=15;goto reject;}
 if(c->execute)for(uint32_t i=0;i<c->extra_count;i++)if(((B(c->extras[i][0],0x4c)>>1)&1)!=c->extras[i][4]){h->error=16;goto reject;}
 if(c->execute)for(uint32_t i=0;i<c->ghost_count;i++){
  uint32_t*r=c->ghost_nodes[i];
  if(U(r[0],0x48)!=((r[5]&~1u)|(r[7]?0u:1u))||U(r[0],0x4c)!=r[6]){h->error=17;goto reject;}
 }
 h->after_mode=mode();h->status=4;goto done;
 reject:h->status=-1;
 done:InterlockedExchange(&h->queued,0);InterlockedDecrement(&h->active);
}
static void* __fastcall job_clone(Job*self,void*unused,void*dest){(void)unused;memcpy(dest,self,sizeof(Job));InterlockedIncrement(&g_shared.h.clones);return dest;}
static void* __fastcall job_type(Job*self,void*unused){(void)self;(void)unused;return(void*)"BlitzCamObserverHud1121";}
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
 if(c->magic!=MAGIC||c->size!=sizeof(Config)||c->want_free!=1||c->execute>1||c->target_mask>31||h->status||h->active||h->queued||
    !isfinite(c->raw)||!isfinite(c->origin)||!isfinite(c->rate)||c->rate<=0)return 100;
#ifndef CAMERA_SELF_TEST
 if((uint32_t)(uintptr_t)GetModuleHandleW(L"wotblitz.exe")!=c->base||c->tick_entry!=live(0x140d100)||c->queue_entry!=live(0x91d090)||
    c->action_entry!=live(0x1e173e0)||c->any_entry!=live(0x717250)||c->destroy_entry!=live(0x6a4720)||c->visible_entry!=live(0xd05020))return 101;
 if(!readable(live(0x4690a30),4))return 105;
 if(c->ghost_enabled&&(c->ghost_entry!=live(0xd71ef0)||!readable(live(0x471ef94),4)||
    U(live(0x471ef94),0)!=c->ghost_class))return 107;
 if(c->opacity_count&&(c->opacity_get_entry!=live(0xce2d60)||c->opacity_set_entry!=live(0x102ab30)||
    !readable(live(0x4695104),4)||!readable(live(0x4696d94),4)||
    U(live(0x4695104),0)!=c->opacity_type||U(live(0x4696d94),0)!=c->opacity_index))return 108;
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
