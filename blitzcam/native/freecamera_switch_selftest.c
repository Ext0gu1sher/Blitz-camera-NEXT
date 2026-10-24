/* Fake local objects exercise the native ABI and cancellation/identity guards. */
#define CAMERA_SELF_TEST
#include "freecamera_switch_1121.c"
#undef NDEBUG
#include <assert.h>
static Function pending;
static int calls,ticks,anys,cleanups;
static uint32_t alloc(size_t n){void*p=VirtualAlloc(0,n,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);assert(p);return(uintptr_t)p;}
static void __thiscall mock_tick(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.player&&dt==.016f);ticks++;}
static void* __thiscall mock_any(void*self,const unsigned char*w,uint32_t flag){assert(flag==1);U(self,0)=123;U(self,4)=*w;anys++;return self;}
static void __thiscall mock_destroy(void*self){assert(U(self,-4)==123);cleanups++;}
static void __thiscall mock_action(void*self,const void*arg){
 Config*c=&g_shared.cfg;assert((uintptr_t)self==c->hud&&U(arg,4)==c->want_free);
 assert(in_signal(1)&&g_shared.h.detached&&U(c->functor,0x10)==c->tick_entry);calls++;
 uint32_t camera=mode()?c->game_camera:c->free_camera;
 U(c->scene,0x120)=U(c->scene,0x124)=U(c->render,0xb4)=U(c->render,0xb8)=camera;
 B(c->context,0x190)=c->want_free;
}
static uint32_t __thiscall mock_queue(void*self,Function*fn,uint32_t force){
 assert((uintptr_t)self==g_shared.cfg.job_manager&&force==1&&in_signal(0));
 typedef void*(__thiscall*Clone)(void*,void*);typedef void(__thiscall*Destroy)(void*,int);
 Function tmp={0};tmp.ptr=((Clone)fn->ptr->vft[0])(fn->ptr,tmp.storage);
 memset(&pending,0,sizeof(pending));pending.ptr=((Clone)tmp.ptr->vft[0])(tmp.ptr,pending.storage);
 ((Destroy)tmp.ptr->vft[4])(tmp.ptr,0);return 123;
}
static void fixture(int initial,int wanted,int execute){
 memset(&g_shared,0,sizeof(g_shared));calls=ticks=anys=cleanups=0;memset(&pending,0,sizeof(pending));Config*c=&g_shared.cfg;
 c->magic=MAGIC;c->size=sizeof(Config);c->raw=80;c->origin=4;c->rate=1;c->want_free=wanted;c->execute=execute;
 uint32_t*p=&c->context;for(int i=0;i<14;i++)p[i]=alloc(0x1000);
 U(c->context,0)=live(0x37f8a00);U(c->player,0)=live(0x37c1f44);U(c->player,0xc)=live(0x37c1f4c);
 U(c->scene_owner,0)=live(0x3853fd4);U(c->scene,0)=live(0x3713a60);U(c->render,0)=live(0x3777120);
 U(c->game_camera,0)=live(0x382da70);U(c->free_camera,0)=live(0x385402c);
 U(c->hud,0)=live(0x3853e68);U(c->model,0)=live(0x385332c);
 U(c->context,0x1b0)=c->player;U(c->scene_owner,0x20)=c->context;U(c->scene_owner,0x1c)=c->scene;
 U(c->scene_owner,0x8c)=c->game_camera;U(c->scene_owner,0x94)=c->free_camera;U(c->scene,0xa8)=c->render;
 U(c->hud,0x120)=c->context;U(c->hud,0x148)=c->model;
 c->initial_camera=initial?c->free_camera:c->game_camera;
 B(c->context,0x190)=initial;
 U(c->scene,0x120)=U(c->scene,0x124)=U(c->render,0xb4)=U(c->render,0xb8)=c->initial_camera;
 B(c->player,0x11)=B(c->player,0x12)=B(c->player,0x35)=1;U(c->player,0x108)=0xffffffff;U(c->player,0xa0)=1;
 F(c->player,0x18)=c->raw;F(c->player,0x64)=c->origin;F(c->player,0x14)=c->rate;
 c->functor=c->node+0x20;U(c->functor,0)=live(0x37c4674);U(c->functor,8)=c->player;
 c->tick_entry=(uintptr_t)mock_tick;c->queue_entry=(uintptr_t)mock_queue;c->any_entry=(uintptr_t)mock_any;
 c->action_entry=(uintptr_t)mock_action;c->destroy_entry=(uintptr_t)mock_destroy;U(c->functor,0x10)=c->tick_entry;
 U(c->engine,0x74)=c->head;U(c->head,0)=U(c->head,4)=c->node;U(c->node,0)=U(c->node,4)=c->head;U(c->node,0x48)=1;
 g_shared.h.heartbeat=GetTickCount();
}
static void frame(void){Config*c=&g_shared.cfg;((TickFn)(uintptr_t)U(c->functor,0x10))((void*)(uintptr_t)c->player,.016f);}
static void pump(int clear){
 Config*c=&g_shared.cfg;uint32_t job=alloc(0x50);U(job,0)=c->node;U(job,4)=c->head;U(c->head,0)=job;U(c->node,4)=job;
 U(job,0x48)=1;U(job,0x20)=live(0x372ab00);U(job,0x24)=c->job_manager;U(job,0x28)=live(0x92aec0);if(clear)U(c->node,0x48)=0;
 typedef void(__thiscall*Invoke)(void*);typedef void(__thiscall*Destroy)(void*,int);
 assert(pending.ptr);((Invoke)pending.ptr->vft[2])(pending.ptr);((Destroy)pending.ptr->vft[4])(pending.ptr,0);pending.ptr=0;
}
int main(void){
 fixture(0,1,0);assert(!HookAttach(0));frame();pump(1);assert(!calls&&mode()==0&&g_shared.h.status==4);puts("PASS no-op pump probe");
 fixture(0,1,1);assert(!HookAttach(0));frame();assert(!calls);pump(1);HookDetach(0);
 assert(calls==1&&anys==1&&cleanups==1&&mode()==1&&g_shared.h.status==4&&g_shared.h.requests==1);
 assert(g_shared.h.clones==2&&g_shared.h.destroys==2&&ticks==1);puts("PASS tracked -> free; full native function and bool Any ABI; exactly once");
 fixture(1,0,1);assert(!HookAttach(0));frame();pump(1);assert(calls==1&&mode()==0);puts("PASS controlled free -> tracked test fixture");
 fixture(1,1,1);assert(!HookAttach(0));frame();pump(1);assert(!calls&&!anys&&mode()==1);puts("PASS already free never toggles off");
 fixture(0,1,1);assert(!HookAttach(0));frame();F(g_shared.cfg.player,0x18)+=1;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS changed clock rejected");
 fixture(0,1,1);assert(!HookAttach(0));frame();U(g_shared.cfg.hud,0x120)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS stale HUD context rejected");
 fixture(0,1,1);assert(!HookAttach(0));frame();pump(0);assert(!calls&&g_shared.h.error==12);puts("PASS emitting Replay phase rejected");
 fixture(0,1,1);assert(!HookAttach(0));frame();g_shared.h.thread++;pump(1);assert(!calls&&g_shared.h.error==10);puts("PASS wrong thread rejected");
 fixture(0,1,1);assert(!HookAttach(0));frame();g_shared.h.heartbeat-=2000;pump(1);assert(!calls&&g_shared.h.error==11);puts("PASS stale supervisor rejected");
 fixture(0,1,1);assert(!HookAttach(0));frame();HookDetach(0);pump(1);assert(!calls&&!g_shared.h.queued);puts("PASS queued cancellation");
 fixture(0,1,1);assert(!HookAttach(0));HookDetach(0);frame();assert(!pending.ptr&&!calls&&ticks==1&&g_shared.h.detached);puts("PASS armed cancellation restores tick");
 fixture(0,1,1);B(g_shared.cfg.player,0x12)=0;assert(HookAttach(0)==102&&!calls);puts("PASS unpaused replay rejected");
 fixture(0,1,1);B(g_shared.cfg.context,0x190)=1;assert(HookAttach(0)==102&&!calls);puts("PASS mismatched context free-mode flag rejected");
 return 0;
}
