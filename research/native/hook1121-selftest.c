/* Runs ONLY in this stand-alone x86 process, against allocated fake objects. */
#define HOOK_SELF_TEST
#include "hook1121.c"
#undef NDEBUG
#include <assert.h>
static int forwarded_update,forwarded_draw;
static float forwarded_dt;
static void __thiscall mock_update(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.battle+0x128);forwarded_update++;forwarded_dt=dt;}
static void __thiscall mock_draw(void*self,void*render){assert((uintptr_t)self==g_shared.cfg.shadow);assert((uintptr_t)render==g_shared.cfg.render);forwarded_draw++;}
static void __thiscall mock_position(void*self,const Vec*p){*(Vec*)((char*)self+0x38)=*p;}
static void __thiscall mock_direction(void*self,const Vec*d){*(Vec*)((char*)self+0x50)=*d;}
static void* __thiscall mock_refresh(void*self,void*optional){assert(optional==NULL);return(char*)self+0x140;}
static uint32_t allocate(size_t n){void*p=VirtualAlloc(0,n,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);assert(p);return(uint32_t)(uintptr_t)p;}
static void tick(void){g_shared.heartbeat=GetTickCount();((UpdateFn)(uintptr_t)U(U(g_shared.cfg.battle,0x128),12))((void*)(uintptr_t)(g_shared.cfg.battle+0x128),.016f);((DrawFn)(uintptr_t)U(U(g_shared.cfg.shadow,0),12))((void*)(uintptr_t)g_shared.cfg.shadow,(void*)(uintptr_t)g_shared.cfg.render);}
static void fixture(void){
 memset(&g_shared,0,sizeof(g_shared));armed=0;forwarded_update=forwarded_draw=0;
 Config*c=&g_shared.cfg;uint32_t*start=&c->battle;
 for(int i=0;i<12;i++)start[i]=allocate(0x1000);
 c->magic=MAGIC;c->size=sizeof(Config);
 uint32_t*vs=&c->battle_vft;for(int i=0;i<13;i++)vs[i]=0x100000+i*4;
 c->update_vft=allocate(28)+4;c->shadow_vft=allocate(32)+4;
 U(c->update_vft,12)=(uintptr_t)mock_update;U(c->shadow_vft,12)=(uintptr_t)mock_draw;
 c->set_position=(uintptr_t)mock_position;c->set_direction=(uintptr_t)mock_direction;c->refresh=(uintptr_t)mock_refresh;
 U(c->battle,0)=c->battle_vft;U(c->battle,0x128)=c->update_vft;U(c->shadow,0)=c->shadow_vft;
 U(c->context,0)=c->context_vft;U(c->player,0)=c->player_vft;U(c->camera,0)=c->camera_vft;
 U(c->spectator,0)=c->spectator_vft;U(c->render,0)=c->render_vft;U(c->scene,0)=c->scene_vft;
 U(c->scene_owner,0)=c->scene_owner_vft;U(c->replay_controller,0)=c->replay_vft;U(c->game_camera,0)=c->game_vft;
 U(c->battle,0x120)=c->context;U(c->battle,0x150)=c->owner;U(c->owner,0x68)=c->spectator;
 U(c->context,0x1b0)=c->player;U(c->player,0xc)=c->player_secondary_vft;
 U(c->scene,0xa8)=c->render;U(c->scene,0x120)=U(c->scene,0x124)=c->camera;
 U(c->render,0xb4)=U(c->render,0xb8)=c->camera;U(c->render,0x8c)=c->shadow;
 U(c->scene_owner,0x1c)=c->scene;U(c->scene_owner,0x20)=c->context;U(c->scene_owner,0x8c)=c->game_camera;
 U(c->scene_owner,0x94)=c->camera;U(c->scene_owner,0x9c)=c->replay_controller;
 U(c->spectator,0xc)=c->camera;U(c->replay_controller,0x28)=c->game_camera;U(c->game_camera,0x5b8)=c->replay_controller;
 B(c->player,0x11)=B(c->player,0x12)=B(c->player,0x35)=1;U(c->player,0xa0)=1;U(c->player,0x108)=0xffffffff;
 c->raw_time=32;F(c->player,0x18)=32;c->origin=9;F(c->player,0x64)=9;
 U(c->spectator,0x10c)=0xffffffff;c->fov=64;F(c->spectator,0x114)=F(c->spectator,0x118)=F(c->camera,0x268)=64;
 c->direction=(Vec){1,0,0};c->setter_direction=c->direction;*(Vec*)(uintptr_t)(c->camera+0x50)=c->direction;
 c->a=(Vec){-142,-129,31};c->b=(Vec){-103,-122,45};*(Vec*)(uintptr_t)(c->camera+0x38)=c->b;*(Vec*)(uintptr_t)(c->spectator+0xac)=c->b;
 U(c->shadow,0x294)=3;uint32_t arr=allocate(24);U(c->shadow,0x288)=arr;
 for(int i=0;i<3;i++){U(arr,i*8)=allocate(0x200);F(c->shadow,0x550+i*4)=90+i*30;F(c->shadow,0x560+i*4)=.04f+i*.02f;}
 g_shared.heartbeat=GetTickCount();assert(guard()==0);assert(HookAttach(0)==0);
}
static void at(double seconds){LARGE_INTEGER now;QueryPerformanceCounter(&now);g_shared.start_qpc=now.QuadPart-(int64_t)(seconds*g_shared.frequency);g_shared.last_qpc=now.QuadPart;tick();}
int main(void){
 fixture();for(int i=0;i<20;i++)tick();assert(forwarded_update==20&&forwarded_draw==20&&fabsf(forwarded_dt-.016f)<1e-9f);assert(g_shared.position_applies==0&&g_shared.events==40);assert(HookDetach(0)==0);assert(g_shared.detach_mask==3);puts("PASS observe forwarding, x86 ABI, counters and detach");
 fixture();g_shared.command=1;tick();at(8.5);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.a)==0);at(11);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.a)<.001);at(19.5);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.b)==0);at(22.01);assert(g_shared.detach_mask==3&&g_shared.error==0);assert(F(g_shared.cfg.camera,0x268)==64);puts("PASS path endpoints, finite timeline, fixed FOV and automatic detach");
 fixture();B(g_shared.cfg.player,0x12)=0;tick();assert(g_shared.error==6&&g_shared.position_applies==0&&g_shared.detach_mask==3);puts("PASS pause guard prevents position writes");
 fixture();g_shared.command=1;tick();F(g_shared.cfg.spectator,0xac)+=1;tick();assert(g_shared.error==19&&g_shared.detach_mask==3);puts("PASS native target alteration aborts");
 fixture();g_shared.heartbeat=GetTickCount()-2000;((UpdateFn)(uintptr_t)U(U(g_shared.cfg.battle,0x128),12))((void*)(uintptr_t)(g_shared.cfg.battle+0x128),.016f);assert(g_shared.error==1&&g_shared.detach_mask==3);puts("PASS watchdog detaches without external controller");
 fixture();F(g_shared.cfg.camera,0x100)=1;tick();assert(g_shared.error==11&&g_shared.position_applies==0);puts("PASS projection change aborts");
 return 0;
}
