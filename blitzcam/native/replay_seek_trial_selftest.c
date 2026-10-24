/* Local fake objects only. Verify x86 ABI, ownership and destroyed-node case. */
#define SEEK_SELF_TEST
#include "replay_seek_trial_1121.c"
#undef NDEBUG
#include <assert.h>
static int ticks,seeks;
static uint32_t alloc(size_t n){void*p=VirtualAlloc(0,n,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);assert(p);return(uint32_t)(uintptr_t)p;}
static void __thiscall mock_tick(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.player);assert(dt==.016f);ticks++;}
static void __thiscall mock_seek(void*self,float delta){
 Config*c=&g_shared.cfg;assert((uintptr_t)self==c->player);assert(delta==c->delta);
 assert(U(c->functor,0x10)==c->tick_entry&&g_shared.h.detached==1);seeks++;
 F(c->player,0x28)=c->raw+delta;F(c->player,0x18)=c->raw+delta;
 if(delta<0){assert(VirtualFree((void*)(uintptr_t)c->node,0,MEM_RELEASE));c->node=c->functor=0;U(c->player,0x108)=123;B(c->player,0x11)=0;}
}
static void fixture(float delta){
 memset(&g_shared,0,sizeof(g_shared));ticks=seeks=0;Config*c=&g_shared.cfg;
 c->magic=MAGIC;c->size=sizeof(Config);c->raw=80;c->origin=9;c->rate=1;c->delta=delta;
 uint32_t*p=&c->context;for(int i=0;i<5;i++)p[i]=alloc(0x1000);
 p=&c->context_vft;for(int i=0;i<6;i++)p[i]=alloc(32);
 U(c->context,0)=c->context_vft;U(c->player,0)=c->player_vft;U(c->player,0xc)=c->secondary_vft;U(c->scene_owner,0)=c->scene_owner_vft;U(c->scene,0)=c->scene_vft;U(c->camera,0)=c->camera_vft;
 U(c->context,0x1b0)=c->player;U(c->scene_owner,0x20)=c->context;U(c->scene_owner,0x1c)=c->scene;U(c->scene_owner,0x94)=c->camera;U(c->scene,0x120)=U(c->scene,0x124)=c->camera;
 B(c->player,0x11)=B(c->player,0x12)=B(c->player,0x35)=1;U(c->player,0x108)=0xffffffff;U(c->player,0xa0)=1;F(c->player,0x18)=c->raw;F(c->player,0x64)=c->origin;F(c->player,0x14)=c->rate;
 c->engine=alloc(0x100);c->head=alloc(0x50);c->node=alloc(0x50);c->functor=c->node+0x20;c->functor_vft=alloc(32);
 U(c->engine+0x70,4)=c->head;U(c->head,0)=U(c->head,4)=c->node;U(c->node,0)=U(c->node,4)=c->head;U(c->node,0x48)=1;
 U(c->functor,0)=c->functor_vft;U(c->functor,8)=c->player;c->tick_entry=(uintptr_t)mock_tick;c->seek_entry=(uintptr_t)mock_seek;U(c->functor,0x10)=c->tick_entry;g_shared.h.heartbeat=GetTickCount();
}
static void frame(void){Config*c=&g_shared.cfg;((TickFn)(uintptr_t)U(c->functor,0x10))((void*)(uintptr_t)c->player,.016f);}
int main(void){
 fixture(2);assert(HookAttach(0)==0);frame();assert(seeks==1&&ticks==0&&g_shared.h.status==4&&!g_shared.h.active&&g_shared.h.detached);frame();HookDetach(0);assert(seeks==1&&ticks==1);puts("PASS forward thiscall float ABI, detach-before-call, exactly once");
 fixture(-2);assert(HookAttach(0)==0);frame();HookDetach(0);assert(seeks==1&&g_shared.h.status==4&&g_shared.h.task_after==123&&g_shared.h.active_after==0);puts("PASS rewind may destroy callback node, no later stale restoration");
 fixture(2);assert(HookAttach(0)==0);HookDetach(0);frame();assert(seeks==0&&ticks==1&&g_shared.h.detached&&g_shared.h.status==-1);puts("PASS cancellation cannot issue request");
 fixture(2);assert(HookAttach(0)==0);g_shared.h.heartbeat=GetTickCount()-2000;frame();assert(!seeks&&ticks==1&&g_shared.h.error==1&&g_shared.h.detached);puts("PASS stale heartbeat cancels request");
 fixture(2);assert(HookAttach(0)==0);F(g_shared.cfg.player,0x18)+=1;frame();assert(!seeks&&g_shared.h.error==2&&g_shared.h.detached);puts("PASS changed clock rejected");
 fixture(2);assert(HookAttach(0)==0);U(g_shared.cfg.node,0x48)=0;frame();assert(!seeks&&g_shared.h.error==2&&g_shared.h.detached);puts("PASS request requires emitting signal node");
 fixture(-65);assert(HookAttach(0)==0);frame();HookDetach(0);assert(seeks==1&&g_shared.h.detached&&g_shared.h.status==4);puts("PASS longer rewind preserves one-shot lifetime contract");
 fixture(121);assert(HookAttach(0)==100&&seeks==0);fixture(-100);assert(HookAttach(0)==100);fixture(2);B(g_shared.cfg.player,0x12)=0;assert(HookAttach(0)==102);puts("PASS bounds and paused replay prerequisite");
 return 0;
}
