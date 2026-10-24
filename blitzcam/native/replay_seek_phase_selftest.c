/* Local fake objects, no game access. Test inline native-function ABI and phase. */
#define SEEK_SELF_TEST
#include "replay_seek_phase_trial_1121.c"
#undef NDEBUG
#include <assert.h>
static int ticks,seeks;
static Function pending;
static uint32_t alloc(size_t n){void*p=VirtualAlloc(0,n,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);assert(p);return(uint32_t)(uintptr_t)p;}
static void __thiscall mock_tick(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.player);assert(dt==.016f);ticks++;}
static void __thiscall mock_seek(void*self,float delta){
 Config*c=&g_shared.cfg;assert((uintptr_t)self==c->player);assert(delta==c->delta);
 assert(emitting()==1&&!(U(c->node,0x48)&1)&&U(c->functor,0x10)==c->tick_entry&&g_shared.h.detached);seeks++;
 F(c->player,0x28)=c->raw+delta;F(c->player,0x18)=c->raw+delta;
 if(delta<0){assert(VirtualFree((void*)(uintptr_t)c->node,0,MEM_RELEASE));c->node=c->functor=0;U(c->player,0x108)=123;B(c->player,0x11)=0;}
}
static uint32_t __thiscall mock_queue(void*self,Function*fn,uint32_t force){
 assert((uintptr_t)self==g_shared.cfg.job_manager&&force==1);
 assert(g_shared.h.queued&&g_shared.h.status==2&&emitting()==1);
 assert(fn->ptr&&fn->ptr->cookie==MAGIC);
 typedef void*(__thiscall*Clone)(void*,void*);
 Function temp={0};temp.ptr=((Clone)fn->ptr->vft[0])(fn->ptr,temp.storage);
 memset(&pending,0,sizeof(pending));pending.ptr=((Clone)temp.ptr->vft[0])(temp.ptr,pending.storage);
 typedef void(__thiscall*Destroy)(void*,int);((Destroy)temp.ptr->vft[4])(temp.ptr,0);
 return 123;
}
static void fixture(float delta,int mode){
 memset(&g_shared,0,sizeof(g_shared));memset(&pending,0,sizeof(pending));ticks=seeks=0;Config*c=&g_shared.cfg;
 c->magic=MAGIC;c->size=sizeof(Config);c->raw=80;c->origin=9;c->rate=1;c->delta=delta;c->mode=mode;
 uint32_t*p=&c->context;for(int i=0;i<5;i++)p[i]=alloc(0x1000);
 p=&c->context_vft;for(int i=0;i<6;i++)p[i]=alloc(32);
 U(c->context,0)=c->context_vft;U(c->player,0)=c->player_vft;U(c->player,0xc)=c->secondary_vft;U(c->scene_owner,0)=c->scene_owner_vft;U(c->scene,0)=c->scene_vft;U(c->camera,0)=c->camera_vft;
 U(c->context,0x1b0)=c->player;U(c->scene_owner,0x20)=c->context;U(c->scene_owner,0x1c)=c->scene;U(c->scene_owner,0x94)=c->camera;U(c->scene,0x120)=U(c->scene,0x124)=c->camera;
 B(c->player,0x11)=B(c->player,0x12)=B(c->player,0x35)=1;U(c->player,0x108)=0xffffffff;U(c->player,0xa0)=1;F(c->player,0x18)=c->raw;F(c->player,0x64)=c->origin;F(c->player,0x14)=c->rate;
 c->engine=alloc(0x100);c->head=alloc(0x50);c->node=alloc(0x50);c->functor=c->node+0x20;c->functor_vft=alloc(32);
 U(c->engine+0x70,4)=c->head;U(c->head,0)=U(c->head,4)=c->node;U(c->node,0)=U(c->node,4)=c->head;U(c->node,0x48)=1;
 U(c->functor,0)=c->functor_vft;U(c->functor,8)=c->player;c->tick_entry=(uintptr_t)mock_tick;c->seek_entry=(uintptr_t)mock_seek;U(c->functor,0x10)=c->tick_entry;g_shared.h.heartbeat=GetTickCount();
 c->queue_entry=(uintptr_t)mock_queue;c->job_manager=alloc(0x100);
}
static void frame(void){Config*c=&g_shared.cfg;((TickFn)(uintptr_t)U(c->functor,0x10))((void*)(uintptr_t)c->player,.016f);}
static void pump(int clear_emitting){
 Config*c=&g_shared.cfg;uint32_t jobnode=alloc(0x50);
 U(jobnode,0)=c->node;U(jobnode,4)=c->head;U(c->head,0)=jobnode;U(c->node,4)=jobnode;
 U(jobnode,0x48)=1;U(jobnode,0x20)=live(0x372ab00);U(jobnode,0x24)=c->job_manager;U(jobnode,0x28)=live(0x92aec0);
 if(clear_emitting)U(g_shared.cfg.node,0x48)=0;
 typedef void(__thiscall*Invoke)(void*);typedef void(__thiscall*Destroy)(void*,int);
 assert(pending.ptr);((Invoke)pending.ptr->vft[2])(pending.ptr);((Destroy)pending.ptr->vft[4])(pending.ptr,0);pending.ptr=0;
}
int main(void){
 fixture(3601,1);assert(HookAttach(0)==100);assert(!seeks&&!pending.ptr);
 fixture(300,1);assert(HookAttach(0)==0);frame();pump(1);HookDetach(0);assert(seeks==1&&g_shared.h.status==4);
 puts("PASS project-wide seek bound and single forward jump beyond 120 seconds");
 fixture(-2,0);assert(HookAttach(0)==0);frame();assert(!seeks&&ticks==1&&g_shared.h.queued&&g_shared.h.detached);pump(1);assert(!seeks&&g_shared.h.status==4&&g_shared.h.job_calls==1&&g_shared.h.clones==2&&g_shared.h.destroys==2);puts("PASS no-op queued phase, thiscall clone/invoke/destroy ABI");
 fixture(-2,1);assert(HookAttach(0)==0);frame();assert(!seeks);pump(1);HookDetach(0);assert(seeks==1&&g_shared.h.status==4&&!g_shared.h.active&&!g_shared.h.queued);puts("PASS only verified native job pump emits, Replay does not; destroyed old node untouched");
 fixture(-2,1);assert(HookAttach(0)==0);frame();pump(0);assert(!seeks&&g_shared.h.error==13);puts("PASS emitting job phase rejected");
 fixture(-2,1);assert(HookAttach(0)==0);frame();HookDetach(0);pump(1);assert(!seeks&&!g_shared.h.queued);puts("PASS queued cancellation never seeks");
 fixture(-2,1);assert(HookAttach(0)==0);frame();F(g_shared.cfg.player,0x18)+=1;pump(1);assert(!seeks&&g_shared.h.error==12);puts("PASS changed replay rejects queued job");
 fixture(-2,1);assert(HookAttach(0)==0);frame();g_shared.h.thread++;pump(1);assert(!seeks&&g_shared.h.error==10);puts("PASS wrong thread rejects job");
 fixture(-2,1);assert(HookAttach(0)==0);frame();g_shared.h.heartbeat=GetTickCount()-2000;pump(1);assert(!seeks&&g_shared.h.error==11);puts("PASS queued watchdog");
 fixture(-2,1);assert(HookAttach(0)==0);HookDetach(0);frame();assert(!pending.ptr&&!seeks&&ticks==1);puts("PASS cancellation before queue restores original tick");
 g_shared.h.error=0;job_destroy(NULL,NULL,0x123400);assert(g_shared.h.error==0);puts("PASS native bool byte ignores unspecified upper parameter bits");
 EXCEPTION_RECORD er;CONTEXT cx;memset(&er,0,sizeof(er));memset(&cx,0,sizeof(cx));
 er.ExceptionCode=EXCEPTION_ACCESS_VIOLATION;cx.Esi=5;cx.Edi=6;cx.Esp=7;
 EXCEPTION_POINTERS xp={&er,&cx};fault_claim=0;
 fault_file=CreateFileA("D:\\wotb_cam\\output\\native-selftest-first-fault.bin",GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
 assert(fault_file!=INVALID_HANDLE_VALUE);assert(first_fault(&xp)==EXCEPTION_CONTINUE_SEARCH);
 assert(GetFileSize(fault_file,NULL)==sizeof(Fault));assert(g_shared.h.faults==1);
 assert(first_fault(&xp)==EXCEPTION_CONTINUE_SEARCH&&g_shared.h.faults==1);
 CloseHandle(fault_file);fault_file=INVALID_HANDLE_VALUE;puts("PASS first AV recording, absent memory safe, never swallows exception, bounded one-shot");
 return 0;
}
