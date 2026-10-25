/* Fake local objects exercise the native ABI and cancellation/identity guards. */
#define CAMERA_SELF_TEST
#include "observer_hud_visibility_1121.c"
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
static void base_fixture(int initial,int wanted,int execute){
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

static void __thiscall mock_visible(void*self,unsigned char wanted){
 assert(in_signal(1)&&g_shared.h.detached);calls++;
 B(self,0x4c)=(B(self,0x4c)&~2)|(wanted?2:0);
}
static void fixture(uint32_t target,int execute){
 base_fixture(1,1,execute);Config*c=&g_shared.cfg;
 c->battle_controller=alloc(0x1000);c->battle=alloc(0x1000);c->battle_screen=alloc(0x1000);
 U(c->battle_controller,0)=live(0x37f8f70);U(c->battle_controller,0x120)=c->context;
 U(c->battle_controller,0x150)=c->battle;U(c->battle,0x38)=c->battle_screen;B(c->battle,0x18)=1;
 static const uint32_t offsets[]={0x5c,0x60,0x68,0x6c};
 for(int i=0;i<5;i++){c->layers[i]=alloc(0x1000);c->layer_vfts[i]=i==1?live(0x384cec4):1000+i;U(c->layers[i],0)=c->layer_vfts[i];}
 for(int i=0;i<4;i++)U(c->battle_screen,offsets[i])=c->layers[i];
 U(c->layers[1],0x180)=2;U(c->layers[1],0x260)=c->layers[4];
 c->visible_entry=(uintptr_t)mock_visible;c->target_mask=target;
}
static uint32_t extra_fixture(int wanted){
 Config*c=&g_shared.cfg;uint32_t a=alloc(0x1000),name=alloc(64);strcpy((char*)(uintptr_t)name,"AimContainer");
 c->extra_count=1;c->extras[0][0]=a;c->extras[0][1]=c->layers[0];c->extras[0][2]=12345;c->extras[0][3]=name;c->extras[0][4]=wanted;
 U(a,0)=12345;U(a,0x38)=c->layers[0];U(a,0x30)=name;B(a,0x4c)=2;return a;
}
static void mock_entity_recursive(uint32_t a,unsigned char wanted){
 U(a,0x48)=(U(a,0x48)&~1u)|(wanted?0u:1u);
 for(uint32_t p=U(a,8);p<U(a,12);p+=4)mock_entity_recursive(U(p,0),wanted);
}
static void __thiscall mock_entity_visible(void*self,unsigned char wanted){
 assert(in_signal(1)&&g_shared.h.detached);calls++;
 mock_entity_recursive((uintptr_t)self,wanted);
}
static void ghost_fixture(void){
 Config*c=&g_shared.cfg;c->ghost_enabled=1;c->ghost_count=3;
 c->ghost_bpi=alloc(0x1000);c->ghost_logic=alloc(0x1000);c->ghost_vehicle=alloc(0x1000);c->ghost_visual=alloc(0x1000);c->ghost_class=alloc(64);
 memcpy((void*)(uintptr_t)(c->ghost_class+4),"User",5);c->ghost_entry=(uintptr_t)mock_entity_visible;
 U(c->context,0x1ac)=c->ghost_bpi;U(c->ghost_bpi,0xc)=0x70000001;U(c->ghost_bpi,0x10)=c->ghost_logic;U(c->ghost_bpi,0x18)=2;
 U(c->ghost_logic,0)=live(0x38023d4);U(c->ghost_logic,4)=c->ghost_vehicle;U(c->ghost_logic,0x74)=c->ghost_visual;
 U(c->ghost_vehicle,0)=live(0x37f7d8c);U(c->ghost_visual,0)=live(0x3713afc);U(c->ghost_visual,0x58)=0x70000001;
 uint32_t children=alloc(8);U(c->ghost_visual,8)=children;U(c->ghost_visual,12)=children+8;
 for(int i=1;i<3;i++){uint32_t a=alloc(0x1000);U(children,(i-1)*4)=a;U(a,0x18)=c->ghost_visual;U(a,0x48)=i;}
 for(int i=0;i<3;i++){
  uint32_t a=i?U(children,(i-1)*4):c->ghost_visual,*r=c->ghost_nodes[i];
  r[0]=a;r[1]=U(a,0x18);r[2]=U(a,0);r[3]=U(a,8);r[4]=U(a,12);r[5]=U(a,0x48);r[6]=U(a,0x4c);r[7]=0;
 }
}
static uint32_t __thiscall mock_opacity_get(void*self,uint32_t type,uint32_t index){
 Config*c=&g_shared.cfg;uint32_t a=(uintptr_t)self;
 assert(type==123&&index==0&&in_signal(1)&&g_shared.h.detached);
 uint32_t q=opacity_component(a);if(q)return q;
 q=alloc(24);U(q,0)=live(0x3781ee4);U(q,8)=a;F(q,0x14)=1;
 uint32_t entries=alloc(12),items=alloc(4);U(items,0)=q;U(entries,0)=items;U(entries,4)=items+4;U(entries,8)=items+4;
 U(a,0xe4)=entries;U(a,0xe8)=entries+12;U(U(U(a,0xf0),0x24),c->opacity_index*4)=0;return q;
}
static void __thiscall mock_opacity_set(void*self,float value){
 assert(in_signal(1)&&g_shared.h.detached);F(self,0x14)=value;calls++;
}
static uint32_t opacity_fixture(void){
 Config*c=&g_shared.cfg;uint32_t a=alloc(0x1000),name=alloc(32),table=alloc(0x40),indices=alloc(16);
 strcpy((char*)(uintptr_t)name,"EnemyMarker");U(a,0)=1234;U(a,0x38)=c->layers[0];U(a,0x30)=name;
 U(a,0xf0)=table;U(table,0x24)=indices;U(indices,8)=0xffffffff;
 c->opacity_count=1;c->opacity_type=123;c->opacity_index=2;
 c->opacity_get_entry=(uintptr_t)mock_opacity_get;c->opacity_set_entry=(uintptr_t)mock_opacity_set;
 uint32_t row[]={a,c->layers[0],1234,name,0,0x3f800000,0};memcpy(c->opacity_rows[0],row,sizeof(row));return a;
}
int main(void){
 fixture(31,0);assert(!HookAttach(0));frame();pump(1);assert(!calls&&g_shared.h.status==4&&mode()==1);puts("PASS no-op");
 fixture(31,1);assert(!HookAttach(0));frame();assert(!calls);pump(1);assert(calls==5&&visibility_mask()==31&&mode()==1&&g_shared.h.status==4);puts("PASS show via main-thread UI setter; unchanged camera");
 fixture(0,1);for(int i=0;i<5;i++)B(g_shared.cfg.layers[i],0x4c)=2;assert(!HookAttach(0));frame();pump(1);assert(calls==5&&visibility_mask()==0);puts("PASS reversible hide");
 fixture(31,1);for(int i=0;i<5;i++)B(g_shared.cfg.layers[i],0x4c)=2;assert(!HookAttach(0));frame();pump(1);assert(!calls);puts("PASS idempotent");
 fixture(31,1);assert(!HookAttach(0));frame();F(g_shared.cfg.player,0x18)+=1;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS changed clock");
 fixture(31,1);assert(!HookAttach(0));frame();U(g_shared.cfg.layers[1],0x180)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS ordinary HUD rejected");
 fixture(31,1);assert(!HookAttach(0));frame();U(g_shared.cfg.battle_screen,0x60)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS stale layer rejected");
 fixture(31,1);assert(!HookAttach(0));frame();pump(0);assert(!calls&&g_shared.h.error==12);puts("PASS signal phase");
 fixture(31,1);assert(!HookAttach(0));frame();g_shared.h.thread++;pump(1);assert(!calls&&g_shared.h.error==10);puts("PASS wrong thread");
 fixture(31,1);assert(!HookAttach(0));frame();g_shared.h.heartbeat-=2000;pump(1);assert(!calls&&g_shared.h.error==11);puts("PASS watchdog");
 fixture(31,1);assert(!HookAttach(0));frame();HookDetach(0);pump(1);assert(!calls&&!g_shared.h.queued);puts("PASS queued cancellation");
 fixture(31,1);assert(!HookAttach(0));HookDetach(0);frame();assert(!pending.ptr&&!calls&&ticks==1&&g_shared.h.detached);puts("PASS armed cancellation");
 fixture(31,1);B(g_shared.cfg.player,0x12)=0;assert(HookAttach(0)==102);puts("PASS unpaused rejected");
 fixture(3,1);uint32_t x=extra_fixture(0);assert(!HookAttach(0));frame();pump(1);assert(calls==3&&visibility_mask()==3&&!(B(x,0x4c)&2)&&g_shared.h.status==4);puts("PASS selected layers with personal root hidden");
 fixture(3,0);x=extra_fixture(0);assert(!HookAttach(0));frame();pump(1);assert(!calls&&(B(x,0x4c)&2));puts("PASS cleanup probe changes nothing");
 fixture(0,1);x=extra_fixture(1);B(x,0x4c)=0;assert(!HookAttach(0));frame();pump(1);assert(calls==1&&(B(x,0x4c)&2));puts("PASS restore personal visibility");
 fixture(3,1);x=extra_fixture(0);assert(!HookAttach(0));frame();U(x,0x38)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS reparented personal control rejected");
 fixture(3,1);x=extra_fixture(0);assert(!HookAttach(0));frame();U(x,0x30)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS changed control name identity rejected");
 fixture(3,1);g_shared.cfg.extra_count=17;assert(HookAttach(0)==102);puts("PASS oversized extra table rejected");
 fixture(0,0);ghost_fixture();assert(!HookAttach(0));frame();pump(1);assert(!calls&&U(g_shared.cfg.ghost_visual,0x48)==0);puts("PASS ghost probe preserves render flags");
 fixture(0,1);ghost_fixture();assert(!HookAttach(0));frame();pump(1);assert(calls==1&&g_shared.h.status==4&&U(g_shared.cfg.ghost_nodes[2][0],0x48)==3);puts("PASS recursive ghost hide preserves other visibility classes");
 fixture(0,1);ghost_fixture();for(int i=0;i<3;i++){uint32_t*r=g_shared.cfg.ghost_nodes[i];r[7]=!(r[5]&1);U(r[0],0x48)|=1;r[5]=U(r[0],0x48);}assert(!HookAttach(0));frame();pump(1);assert(calls==2&&g_shared.h.status==4&&U(g_shared.cfg.ghost_nodes[1][0],0x48)==1&&U(g_shared.cfg.ghost_nodes[2][0],0x48)==2);puts("PASS restore mixed original child visibility");
 fixture(0,1);ghost_fixture();U(g_shared.cfg.ghost_visual,0x58)=136616900;assert(HookAttach(0)==102);puts("PASS original player cannot be ghost target");
 fixture(0,1);ghost_fixture();assert(!HookAttach(0));frame();U(g_shared.cfg.ghost_nodes[1][0],0x18)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS reparented ghost child rejected");
 fixture(0,1);ghost_fixture();assert(!HookAttach(0));frame();U(g_shared.cfg.ghost_nodes[2][0],0x48)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS changed child flags rejected");
 fixture(0,1);ghost_fixture();g_shared.cfg.ghost_count=2;assert(HookAttach(0)==102);puts("PASS incomplete ghost tree rejected");
 fixture(0,1);ghost_fixture();B(g_shared.cfg.ghost_class,0)=1;assert(HookAttach(0)==102);puts("PASS wrong visibility class rejected");
 fixture(0,0);x=opacity_fixture();assert(!HookAttach(0));frame();pump(1);assert(!calls&&!opacity_component(x));puts("PASS opacity probe creates nothing");
 fixture(0,1);x=opacity_fixture();assert(!HookAttach(0));frame();pump(1);assert(calls==1&&g_shared.h.status==4&&F(opacity_component(x),0x14)==0);B(x,0x4c)=2;assert(F(opacity_component(x),0x14)==0);puts("PASS native component created with independent zero opacity");
 fixture(0,1);x=opacity_fixture();assert(!HookAttach(0));frame();U(x,0x38)=0;pump(1);assert(!calls&&g_shared.h.error==12);puts("PASS opacity target reparent rejection");
 fixture(0,1);x=opacity_fixture();g_shared.cfg.opacity_rows[0][6]=0x7fc00000;assert(HookAttach(0)==102);puts("PASS nonfinite opacity rejected");
 fixture(0,1);x=opacity_fixture();assert(!HookAttach(0));frame();pump(1);uint32_t q=opacity_component(x);
 g_shared.cfg.opacity_rows[0][4]=q;g_shared.cfg.opacity_rows[0][5]=0;g_shared.cfg.opacity_rows[0][6]=0x3f800000;
 memset(&g_shared.h,0,sizeof(g_shared.h));g_shared.h.heartbeat=GetTickCount();U(g_shared.cfg.node,0x48)=1;
 U(g_shared.cfg.head,0)=U(g_shared.cfg.head,4)=g_shared.cfg.node;U(g_shared.cfg.node,0)=U(g_shared.cfg.node,4)=g_shared.cfg.head;
 assert(!HookAttach(0));frame();pump(1);assert(F(q,0x14)==1&&g_shared.h.status==4);puts("PASS original opacity restored on same component");
 fixture(0,1);x=opacity_fixture();g_shared.cfg.opacity_count=17;assert(HookAttach(0)==102);puts("PASS oversized opacity table rejected");
 return 0;
}
