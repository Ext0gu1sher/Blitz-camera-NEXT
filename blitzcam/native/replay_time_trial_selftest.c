/* Stand-alone x86 fake objects; never loads or accesses a game. */
#define REPLAY_SELF_TEST
#include "replay_time_trial_1121.c"
#undef NDEBUG
#include <assert.h>
static int tick_calls,scene_calls,draw_calls,notify_calls,pause_calls;
static float effective_dt;
static uint32_t allocate(size_t n){void*p=VirtualAlloc(0,n,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);assert(p);return(uint32_t)(uintptr_t)p;}
static void __thiscall mock_tick(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.player);tick_calls++;if(!B(g_shared.cfg.player,0x12))F(g_shared.cfg.player,0x18)+=dt*F(g_shared.cfg.player,0x14);}
static void __thiscall mock_scene(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.scene);scene_calls++;effective_dt=dt*F(g_shared.cfg.scene,0x2a8);}
static void __thiscall mock_draw(void*self,void*render){assert((uintptr_t)self==g_shared.cfg.shadow);assert((uintptr_t)render==g_shared.cfg.render);draw_calls++;}
static void __thiscall mock_notify(void*self){assert((uintptr_t)self==g_shared.cfg.player);notify_calls++;F(g_shared.cfg.scene,0x2a8)=B(g_shared.cfg.player,0x12)?0:F(g_shared.cfg.player,0x14);}
static void __thiscall mock_pause(void*self,uint32_t p){assert((uintptr_t)self==g_shared.cfg.player);pause_calls++;B(g_shared.cfg.player,0x12)=p;mock_notify(self);}
static void frame(float dt){
 Config*c=&g_shared.cfg;g_shared.h.heartbeat=GetTickCount();
 ((TickFn)(uintptr_t)U(c->functor,0x10))((void*)(uintptr_t)c->player,dt);
 ((TickFn)(uintptr_t)U(U(c->scene,0),0x54))((void*)(uintptr_t)c->scene,dt);
 ((DrawFn)(uintptr_t)U(U(c->shadow,0),12))((void*)(uintptr_t)c->shadow,(void*)(uintptr_t)c->render);
}
static void fixture(int mode){
 memset(&g_shared,0,sizeof(g_shared));owned_speed=0;tick_calls=scene_calls=draw_calls=notify_calls=pause_calls=0;
 Config*c=&g_shared.cfg;c->magic=MAGIC;c->size=sizeof(Config);c->rate=.25f;c->duration=1;c->mode=mode;c->raw=20;c->origin=9;c->initial_rate=1;
 uint32_t*p=&c->context;for(int i=0;i<8;i++)p[i]=allocate(0x1000);
 p=&c->context_vft;for(int i=0;i<9;i++)p[i]=allocate(0x100)+4;
 U(c->context,0)=c->context_vft;U(c->player,0)=c->player_vft;U(c->player,0xc)=c->secondary_vft;
 U(c->scene_owner,0)=c->scene_owner_vft;U(c->scene,0)=c->scene_vft;U(c->render,0)=c->render_vft;U(c->shadow,0)=c->shadow_vft;U(c->camera,0)=c->camera_vft;U(c->spectator,0)=c->spectator_vft;
 U(c->context,0x1b0)=c->player;U(c->scene_owner,0x1c)=c->scene;U(c->scene_owner,0x20)=c->context;U(c->scene_owner,0x94)=c->camera;
 U(c->scene,0xa8)=c->render;U(c->scene,0x120)=U(c->scene,0x124)=c->camera;U(c->render,0xb4)=U(c->render,0xb8)=c->camera;U(c->render,0x8c)=c->shadow;U(c->spectator,0xc)=c->camera;
 F(c->player,0x18)=c->raw;F(c->player,0x64)=c->origin;F(c->player,0x14)=1;B(c->player,0x11)=B(c->player,0x12)=B(c->player,0x35)=1;U(c->player,0xa0)=1;U(c->player,0x108)=0xffffffff;B(c->scene,0x2a4)=1;
 c->engine=allocate(0x100);c->head=allocate(0x50);c->node=allocate(0x50);c->functor=c->node+0x20;c->functor_vft=allocate(32);
 U(c->engine+0x70,4)=c->head;U(c->head,0)=U(c->head,4)=c->node;U(c->node,0)=U(c->node,4)=c->head;U(c->functor,0)=c->functor_vft;U(c->functor,8)=c->player;
 c->tick_entry=(uintptr_t)mock_tick;c->scene_entry=(uintptr_t)mock_scene;c->draw_entry=(uintptr_t)mock_draw;c->notify_entry=(uintptr_t)mock_notify;c->pause_entry=(uintptr_t)mock_pause;
 U(c->functor,0x10)=c->tick_entry;U(c->scene_vft,0x54)=c->scene_entry;U(c->shadow_vft,12)=c->draw_entry;g_shared.h.heartbeat=GetTickCount();assert(HookAttach(0)==0);
}
int main(void){
 fixture(0);for(int i=0;i<20;i++)frame(.016f);assert(tick_calls==20&&scene_calls==20&&draw_calls==20&&g_shared.h.events==100&&g_shared.h.writes==0&&F(g_shared.cfg.player,0x18)==20);HookDetach(0);frame(.016f);assert(g_shared.h.detached==7&&g_shared.h.restored);puts("PASS observe forwards all x86 ABIs without clock changes");
 fixture(1);g_shared.h.command=1;for(int i=0;i<11;i++)frame(.1f);assert(g_shared.h.status==4&&g_shared.h.error==0&&g_shared.h.restored&&g_shared.h.detached==7&&B(g_shared.cfg.player,0x12)==1&&F(g_shared.cfg.player,0x14)==1);assert(fabsf(F(g_shared.cfg.player,0x18)-20.25f)<.0001f);puts("PASS 1/4 speed advances and automatically restores pause/rate");
 fixture(1);g_shared.h.command=1;frame(.1f);assert(fabsf(effective_dt-.025f)<1e-7f);HookDetach(0);frame(.1f);assert(g_shared.h.sum_dt<1&&g_shared.h.restored&&g_shared.h.detached==7);puts("PASS stop restores scene scale and original state on update thread");
 fixture(1);g_shared.h.command=1;frame(.1f);g_shared.h.heartbeat=GetTickCount()-2000;((TickFn)(uintptr_t)U(g_shared.cfg.functor,0x10))((void*)(uintptr_t)g_shared.cfg.player,.1f);assert(g_shared.h.error==1&&g_shared.h.restored&&g_shared.h.detached==7);puts("PASS missing supervisor heartbeat restores state");
 fixture(0);g_shared.h.command=1;frame(.1f);assert(g_shared.h.writes==0&&g_shared.h.status==1);HookDetach(0);frame(.1f);puts("PASS observe mode cannot arm speed changes");
 fixture(1);g_shared.h.command=1;frame(.3f);assert(g_shared.h.error==7&&g_shared.h.writes==0&&g_shared.h.detached==7);puts("PASS invalid frame dt cannot start playback");
 fixture(1);g_shared.h.command=1;frame(.1f);mock_pause((void*)(uintptr_t)g_shared.cfg.player,1);frame(.1f);assert(g_shared.h.error==5&&g_shared.h.restored&&g_shared.h.detached==7);puts("PASS manual pause interrupts and remains paused");
 fixture(1);g_shared.h.command=1;frame(.1f);F(g_shared.cfg.player,0x14)=.75f;frame(.1f);assert(g_shared.h.error==5&&!g_shared.h.restored&&F(g_shared.cfg.player,0x14)==.75f&&g_shared.h.detached==7);puts("PASS foreign speed changes are not overwritten");
 fixture(1);g_shared.h.command=1;frame(.1f);B(g_shared.cfg.player,0x2d)=1;frame(.1f);assert(g_shared.h.error==3&&!g_shared.h.restored&&g_shared.h.detached==7);puts("PASS seeking blocks state restoration into obsolete clock context");
 fixture(0);for(int i=0;i<1000;i++)frame(.001f);assert(g_shared.h.events==5000);HookDetach(0);frame(.1f);assert(g_shared.h.detached==7);puts("PASS ring buffer wrap and owned-entry restoration");
 fixture(1);g_shared.h.command=1;frame(.1f);g_shared.h.thread++;((TickFn)(uintptr_t)U(g_shared.cfg.functor,0x10))((void*)(uintptr_t)g_shared.cfg.player,.1f);assert(g_shared.h.error==6&&!g_shared.h.restored&&g_shared.h.detached==7);puts("PASS foreign callback thread cannot invoke game state setters");
 fixture(1);g_shared.h.command=1;for(int i=0;i<10;i++)frame(.1f);assert(g_shared.h.status==2&&effective_dt==.025f&&g_shared.h.events==50);frame(.1f);assert(g_shared.h.status==4&&g_shared.h.detached==7);puts("PASS endpoint finishes after complete replay/scene/draw frame");
 fixture(2);g_shared.cfg.duration=8;g_shared.h.command=1;assert(fabs(mapped_time(8)-3.5)<1e-12);assert(fabs(mapped_time(2)-1.25)<1e-12&&fabs(mapped_time(6)-2.25)<1e-12);for(int i=0;i<81;i++)frame(.1f);assert(g_shared.h.status==4&&g_shared.h.restored&&g_shared.h.detached==7);assert(fabsf(F(g_shared.cfg.player,0x18)-23.5f)<.001f&&g_shared.h.writes>20);puts("PASS smooth time mapping, per-frame rate and automatic restore");
 return 0;
}
