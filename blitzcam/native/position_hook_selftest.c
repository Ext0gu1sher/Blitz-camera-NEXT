/* Runs ONLY in this stand-alone x86 process, against allocated fake objects. */
#define HOOK_SELF_TEST
#include "position_hook_1121.c"
#undef NDEBUG
#include <assert.h>
static int forwarded_update,forwarded_draw;
static float forwarded_dt;
static void __thiscall mock_update(void*self,float dt){assert((uintptr_t)self==g_shared.cfg.battle+0x128);forwarded_update++;forwarded_dt=dt;}
static void __thiscall mock_draw(void*self,void*render){assert((uintptr_t)self==g_shared.cfg.shadow);assert((uintptr_t)render==g_shared.cfg.render);forwarded_draw++;}
static void __thiscall mock_position(void*self,const Vec*p){*(Vec*)((char*)self+0x38)=*p;}
static void __thiscall mock_direction(void*self,const Vec*d){Vec p=*(Vec*)((char*)self+0x38);*(Vec*)((char*)self+0x44)=(Vec){p.x+d->x,p.y+d->y,p.z+d->z};}
static void __thiscall mock_fov(void*self,float fov){
 Config*c=&g_shared.cfg;assert((uintptr_t)self==c->camera);F(c->camera,0x268)=fov;
 F(c->camera,0x100)=(float)(1/tan(fov*c->fov_scale*PI/360));F(c->camera,0x114)=F(c->camera,0x100)*c->aspect;
}
static void* __thiscall mock_refresh(void*self,uint32_t mode){
 assert(mode==0);Config*c=&g_shared.cfg;Vec pos=*(Vec*)((char*)self+0x38),target=*(Vec*)((char*)self+0x44);Vec f={target.x-pos.x,target.y-pos.y,target.z-pos.z};float n=sqrtf(f.x*f.x+f.y*f.y+f.z*f.z);f=(Vec){f.x/n,f.y/n,f.z/n};float h=hypotf(f.x,f.y);Vec r={f.y/h,-f.x/h,0};Vec u={r.y*f.z,-r.x*f.z,r.x*f.y-r.y*f.x};
 float a=F(c->camera,0x5c)*(float)(PI/180),cs=cosf(a),sn=sinf(a);Vec p=*(Vec*)((char*)self+0x38);
 float*v=(float*)((char*)self+0xc0);memset(v,0,64);
 for(int i=0;i<3;i++){v[i*4]=((float*)&r)[i]*cs+((float*)&u)[i]*sn;v[i*4+1]=-((float*)&r)[i]*sn+((float*)&u)[i]*cs;v[i*4+2]=-((float*)&f)[i];}
 for(int j=0;j<3;j++)v[12+j]=-(p.x*v[j]+p.y*v[4+j]+p.z*v[8+j]);v[15]=1;
 return(char*)self+0x140;
}
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
 c->set_fov=(uintptr_t)mock_fov;c->fov_scale=1.25f;c->aspect=16.f/9;c->start_quaternion=(Quat){.5f,.5f,-.5f,-.5f};
 F(c->camera,0x264)=c->fov_scale;F(c->camera,0x28)=c->aspect;
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
 c->lower=(Vec){-1000,-1000,-1000};c->upper=(Vec){1000,1000,1000};*(Vec*)(uintptr_t)(c->spectator+0x30)=c->lower;*(Vec*)(uintptr_t)(c->spectator+0x3c)=c->upper;
 c->duration=8;c->point_count=3;g_shared.points[0]=(PathPoint){0,c->b,c->start_quaternion,80};g_shared.points[1]=(PathPoint){4,c->a,c->start_quaternion,80};g_shared.points[2]=(PathPoint){8,{0,0,80},c->start_quaternion,80};
 mock_fov((void*)(uintptr_t)c->camera,64);memcpy(c->projection,(void*)(uintptr_t)(c->camera+0x100),64);
 U(c->shadow,0x294)=3;uint32_t arr=allocate(24);U(c->shadow,0x288)=arr;
 for(int i=0;i<3;i++){U(arr,i*8)=allocate(0x200);F(c->shadow,0x550+i*4)=90+i*30;F(c->shadow,0x560+i*4)=.04f+i*.02f;}
 mock_direction((void*)(uintptr_t)c->camera,&c->setter_direction);mock_refresh((void*)(uintptr_t)c->camera,0);
 g_shared.heartbeat=GetTickCount();assert(guard()==0);assert(HookAttach(0)==0);
}
static void at(double seconds){LARGE_INTEGER now;QueryPerformanceCounter(&now);g_shared.start_qpc=now.QuadPart-(int64_t)(seconds*g_shared.frequency);g_shared.last_qpc=now.QuadPart;tick();}

static void __thiscall mock_replay_tick(void*self,float dt){
 Config*c=&g_shared.cfg;assert((uintptr_t)self==c->player);
 if(!B(c->player,0x12))F(c->player,0x18)+=dt*F(c->player,0x14);
}
static void __thiscall mock_notify(void*self){assert((uintptr_t)self==g_shared.cfg.player);F(g_shared.cfg.scene,0x2a8)=B(g_shared.cfg.player,0x12)?0:F(g_shared.cfg.player,0x14);}
static void __thiscall mock_pause(void*self,uint32_t pause){B(g_shared.cfg.player,0x12)=pause;mock_notify(self);}
static void clock_fixture(int curve,int replay_clock){
 fixture();HookDetach(0);g_shared.status=0;g_shared.detach_mask=0;g_shared.command=0;
 g_shared.last_elapsed=0;g_shared.shooting_elapsed=0;g_shared.replay_elapsed=0;g_shared.clock_started=0;
 Config*c=&g_shared.cfg;c->replay_mode=curve?2:1;c->camera_clock=replay_clock;c->initial_rate=1;
 c->play_seconds=replay_clock?32:8;c->speed_count=curve?4:2;c->speed_smooth=1;
 c->schedule_seconds=c->play_seconds;c->schedule_offset=0;
 if(curve){g_shared.speeds[0]=(SpeedPoint){0,1};g_shared.speeds[1]=(SpeedPoint){.25f,.25f};g_shared.speeds[2]=(SpeedPoint){.75f,.25f};g_shared.speeds[3]=(SpeedPoint){1,1};}
 else{g_shared.speeds[0]=(SpeedPoint){0,.25f};g_shared.speeds[1]=(SpeedPoint){1,.25f};}
 c->functor=allocate(0x30);c->functor_vft=allocate(0x30);U(c->functor,0)=c->functor_vft;U(c->functor,8)=c->player;U(c->functor,0x14)=0;
 c->tick_entry=(uintptr_t)mock_replay_tick;c->notify_entry=(uintptr_t)mock_notify;c->pause_entry=(uintptr_t)mock_pause;
 U(c->functor,0x10)=c->tick_entry;F(c->player,0x14)=1;B(c->scene,0x2a4)=1;F(c->scene,0x2a8)=0;
 assert(HookAttach(0)==0);assert(g_shared.clock_restored==1);
}
static void clock_frame(void){
 g_shared.heartbeat=GetTickCount();Config*c=&g_shared.cfg;
 ((UpdateFn)(uintptr_t)U(c->functor,0x10))((void*)(uintptr_t)c->player,.016f);tick();
}
static void clock_tests(void){
 clock_fixture(0,0);g_shared.command=1;clock_frame();for(int i=0;i<125;i++)clock_frame();
 assert(g_shared.error==0&&fabs(g_shared.replay_elapsed-.5)<.001&&fabs(g_shared.last_elapsed-2)<.001);
 g_shared.command=3;clock_frame();double pos=g_shared.last_elapsed,raw=g_shared.replay_elapsed;
 for(int i=0;i<20;i++)clock_frame();assert(g_shared.clock_paused&&g_shared.last_elapsed==pos&&g_shared.replay_elapsed==raw);
 g_shared.command=4;clock_frame();assert(!g_shared.clock_paused&&g_shared.replay_elapsed>raw);
 HookDetach(0);clock_frame();assert(g_shared.error==0&&g_shared.detach_mask==7&&g_shared.clock_restored&&B(g_shared.cfg.player,0x12)==1&&F(g_shared.cfg.player,0x14)==1);puts("PASS linked fixed rate, shooting clock, pause/resume and native restoration");
 clock_fixture(0,1);g_shared.command=1;clock_frame();for(int i=0;i<500;i++)clock_frame();
 assert(g_shared.error==0&&fabs(g_shared.replay_elapsed-2)<.002&&fabs(g_shared.last_elapsed-2)<.002);
 HookDetach(0);clock_frame();assert(g_shared.detach_mask==7&&g_shared.clock_restored);puts("PASS replay-driven camera clock differs from shooting time");
 clock_fixture(1,0);assert(fabs(clock_integral(2)-1.25)<1e-9&&fabs(clock_integral(6)-2.25)<1e-9&&fabs(clock_integral(8)-3.5)<1e-9);
 g_shared.command=1;clock_frame();for(int i=0;i<505&&g_shared.status==2;i++)clock_frame();
 assert(g_shared.error==0&&g_shared.detach_mask==7&&g_shared.clock_restored&&fabs(g_shared.replay_elapsed-3.5)<.02);puts("PASS curve integration, full-frame endpoint and all entries restored");
 clock_fixture(1,0);g_shared.cfg.speed_smooth=0;g_shared.cfg.speed_count=3;g_shared.speeds[0]=(SpeedPoint){0,1};g_shared.speeds[1]=(SpeedPoint){.5f,.25f};g_shared.speeds[2]=(SpeedPoint){1,.5f};
 assert(fabs(clock_integral(2)-1.625)<1e-9&&fabs(clock_integral(8)-4)<1e-9);
 g_shared.command=1;clock_frame();for(int i=0;i<505&&g_shared.status==2;i++)clock_frame();
 assert(g_shared.error==0&&g_shared.clock_restored&&fabs(g_shared.replay_elapsed-4)<.02);puts("PASS custom linear speed knots and integrated frame rate");
 for(int smooth=0;smooth<=1;smooth++){
  clock_fixture(1,1);g_shared.cfg.speed_smooth=smooth;
  /* Resume at 2 s of an 8 s schedule: 2.25 replay seconds remain. */
  g_shared.cfg.schedule_seconds=8;g_shared.cfg.schedule_offset=2;g_shared.cfg.play_seconds=6;
  g_shared.cfg.duration=2.25f;g_shared.points[1].time=1;g_shared.points[2].time=2.25f;
  g_shared.command=1;clock_frame();clock_frame();
  assert(g_shared.current_rate<.251f); /* Original curve is already at its slow part. */
  for(int i=0;i<500&&g_shared.status==2;i++)clock_frame();
  assert(g_shared.error==0&&g_shared.detach_mask==7&&g_shared.clock_restored&&fabs(g_shared.replay_elapsed-2.25)<.03);
  assert(fabs(g_shared.shooting_elapsed-6)<.08);
 }
 puts("PASS mid-curve continuation preserves smooth and linear schedule progress");
 for(int smooth=0;smooth<=1;smooth++){
  const double ranges[][2]={{2,5},{-2,1},{7,10},{9,11}};
  for(int i=0;i<4;i++){
   clock_fixture(1,1);g_shared.cfg.speed_smooth=smooth;
   double from=ranges[i][0],to=ranges[i][1];g_shared.cfg.schedule_seconds=8;
   double distance=clock_integral(to)-clock_integral(from);
   g_shared.cfg.schedule_offset=(float)from;g_shared.cfg.play_seconds=(float)(to-from);
   g_shared.cfg.duration=(float)distance;g_shared.points[1].time=(float)(distance*.4);g_shared.points[2].time=(float)distance;
   g_shared.command=1;clock_frame();
   for(int j=0;j<800&&g_shared.status==2;j++)clock_frame();
   assert(g_shared.error==0&&g_shared.detach_mask==7&&g_shared.clock_restored);
   assert(fabs(g_shared.replay_elapsed-distance)<.03&&fabs(g_shared.shooting_elapsed-(to-from))<.08);
  }
 }
 puts("PASS trimmed out points and endpoint rate holds preserve the authored schedule");
 clock_fixture(1,0);g_shared.cfg.speed_count=2;g_shared.cfg.schedule_seconds=8;
 g_shared.speeds[0]=(SpeedPoint){0,1,{1.f/3,0,2.f/3,0},1};g_shared.speeds[1]=(SpeedPoint){1,.25f};
 assert(fabs(clock_integral(4)-3.90625)<1e-6&&fabs(clock_integral(8)-6.5)<1e-6);
 g_shared.cfg.duration=8;g_shared.points[1].time=4;g_shared.points[2].time=8;
 g_shared.command=1;clock_frame();for(int i=0;i<600&&g_shared.status==2;i++)clock_frame();
 assert(g_shared.error==0&&g_shared.clock_restored&&g_shared.detach_mask==7&&fabs(g_shared.replay_elapsed-6.5)<.03);
 clock_fixture(1,0);g_shared.cfg.speed_count=2;g_shared.cfg.schedule_seconds=8;
 g_shared.speeds[0]=(SpeedPoint){0,1,{0,0,1,0},1};g_shared.speeds[1]=(SpeedPoint){1,.25f};
 assert(fabs(clock_integral(4)-3.86875)<1e-8&&fabs(clock_integral(8)-6.8)<1e-8);
 HookDetach(0);clock_frame();assert(validate_clock_config());g_shared.speeds[0].ease[0]=1;g_shared.speeds[0].ease[2]=0;assert(!validate_clock_config());
 g_shared.speeds[0].ease[0]=NAN;assert(!validate_clock_config());
 puts("PASS Bezier rate integrals, nonuniform time handles, playback and invalid handles");
 clock_fixture(1,1);g_shared.cfg.speed_count=2;g_shared.cfg.schedule_seconds=8;
 g_shared.speeds[0]=(SpeedPoint){0,1,{0,0,1,0},1};g_shared.speeds[1]=(SpeedPoint){1,.25f};
 double bezier_distance=clock_integral(6)-clock_integral(2);
 g_shared.cfg.schedule_offset=2;g_shared.cfg.play_seconds=4;g_shared.cfg.duration=(float)bezier_distance;
 g_shared.points[1].time=(float)(bezier_distance*.4);g_shared.points[2].time=(float)bezier_distance;
 g_shared.command=1;clock_frame();for(int i=0;i<400&&g_shared.status==2;i++)clock_frame();
 assert(g_shared.error==0&&g_shared.detach_mask==7&&g_shared.clock_restored&&fabs(g_shared.replay_elapsed-bezier_distance)<.03&&fabs(g_shared.shooting_elapsed-4)<.08);
 puts("PASS Bezier work-area slice and replay-driven camera finish together");
 clock_fixture(1,0);HookDetach(0);clock_frame();
 assert(validate_clock_config());
 g_shared.cfg.schedule_offset=-1;assert(validate_clock_config());
 g_shared.cfg.schedule_offset=2;assert(validate_clock_config());
 g_shared.cfg.schedule_offset=57601;assert(!validate_clock_config());
 g_shared.cfg.schedule_offset=0;g_shared.cfg.schedule_seconds=NAN;assert(!validate_clock_config());
 g_shared.cfg.schedule_seconds=0;assert(!validate_clock_config());
 g_shared.cfg.schedule_seconds=57601;assert(!validate_clock_config());
 puts("PASS invalid continuation schedules rejected");
 clock_fixture(0,0);g_shared.command=1;clock_frame();clock_frame();g_shared.heartbeat=GetTickCount()-2000;
 replay_tick_hook((void*)(uintptr_t)g_shared.cfg.player,0,.016f);assert(g_shared.error==1&&g_shared.clock_restored&&g_shared.detach_mask==7);puts("PASS linked watchdog restores clock on game thread");
 clock_fixture(0,0);g_shared.command=1;clock_frame();clock_frame();F(g_shared.cfg.player,0x64)+=1;clock_frame();assert(g_shared.error==26&&!g_shared.clock_restored&&g_shared.detach_mask==7);puts("PASS seek/origin change blocks stale clock restoration");
 clock_fixture(0,0);g_shared.command=1;clock_frame();clock_frame();F(g_shared.cfg.player,0x14)=.5f;clock_frame();assert(g_shared.error==27&&!g_shared.clock_restored&&F(g_shared.cfg.player,0x14)==.5f);puts("PASS foreign multiplier is not overwritten");
}

int main(void){
 /* Production guard compares the configured exact type; it must not force Spectator. */
 const uint32_t controller_types[]={0x4180f9c,0x4194c48};
 for(int i=0;i<2;i++){
  fixture();HookDetach(0);g_shared.status=0;g_shared.detach_mask=0;g_shared.command=0;
  Config*c=&g_shared.cfg;c->spectator_vft=controller_types[i];U(c->spectator,0)=c->spectator_vft;
  assert(HookAttach(0)==0);assert(U(c->spectator,0)==c->spectator_vft);
  g_shared.command=1;tick();at(4);
  assert(g_shared.error==0&&g_shared.position_applies>0&&dist(*(Vec*)(uintptr_t)(c->camera+0x38),c->a)<.05);
  assert(U(c->spectator,0)==c->spectator_vft);
  LONG applies=g_shared.position_applies;Vec position=*(Vec*)(uintptr_t)(c->camera+0x38);
  U(c->spectator,0)=controller_types[1-i];tick();
  assert(g_shared.error==4&&g_shared.detach_mask==3&&g_shared.position_applies==applies);
  assert(dist(position,*(Vec*)(uintptr_t)(c->camera+0x38))==0);
 }
 puts("PASS configured Cinema/Spectator types preserved; a mid-playback type change stops before writes");
 for(int i=0;i<2;i++){
  clock_fixture(1,1);HookDetach(0);clock_frame();
  g_shared.status=0;g_shared.detach_mask=0;g_shared.command=0;
  Config*c=&g_shared.cfg;c->spectator_vft=controller_types[i];U(c->spectator,0)=c->spectator_vft;
  c->orientation_enabled=c->fov_enabled=1;
  g_shared.points[1].quaternion=(Quat){.5648927512f,.7344985298f,-.2175683766f,-.3067117389f};
  g_shared.points[1].horizontal_fov=70;
  Vec initial_direction=view_direction(c->camera);
  assert(HookAttach(0)==0);g_shared.command=1;clock_frame();
  for(int j=0;j<125;j++)clock_frame();
  assert(g_shared.error==0&&g_shared.replay_elapsed>0&&g_shared.position_applies>0);
  assert(dist(initial_direction,view_direction(c->camera))>.01f&&F(c->camera,0x268)<63.99f);
  assert(U(c->spectator,0)==c->spectator_vft);
  HookDetach(0);clock_frame();
  assert(g_shared.error==0&&g_shared.detach_mask==7&&g_shared.clock_restored);
  assert(B(c->player,0x12)==1&&F(c->player,0x14)==1&&U(c->spectator,0)==c->spectator_vft);
 }
 puts("PASS Cinema/Spectator linked replay, orientation, FOV and clock restoration");
 fixture();for(int i=0;i<20;i++)tick();assert(forwarded_update==20&&forwarded_draw==20&&fabsf(forwarded_dt-.016f)<1e-9f);assert(g_shared.position_applies==0&&g_shared.events==40);assert(HookDetach(0)==0);assert(g_shared.detach_mask==3);puts("PASS observe forwarding, x86 ABI, counters and detach");
 fixture();g_shared.command=1;tick();at(4);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.a)<.05);at(8.01);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.points[2].position)==0);assert(g_shared.detach_mask==3&&g_shared.error==0);assert(F(g_shared.cfg.camera,0x268)==64);puts("PASS multiple keyframes, finite timeline, fixed FOV and automatic detach");
 fixture();g_shared.cfg.reverse=1;g_shared.cfg.b=g_shared.points[2].position;*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38)=g_shared.cfg.b;g_shared.command=1;tick();at(4);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.cfg.a)<.05);at(8.01);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38),g_shared.points[0].position)==0);assert(g_shared.detach_mask==3);puts("PASS reverse playback");
 fixture();g_shared.command=1;tick();at(2);Vec stopped=*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38);assert(HookDetach(0)==0);tick();assert(dist(stopped,*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x38))==0&&g_shared.detach_mask==3);puts("PASS stop keeps current position and restores entries");
 fixture();for(int i=0;i<CAP+100;i++)tick();assert(g_shared.error==0&&g_shared.events==2*(CAP+100));assert(HookDetach(0)==0);puts("PASS telemetry ring wraps without stopping playback");
 fixture();B(g_shared.cfg.player,0x12)=0;tick();assert(g_shared.error==6&&g_shared.position_applies==0&&g_shared.detach_mask==3);puts("PASS pause guard prevents position writes");
 fixture();g_shared.command=1;tick();F(g_shared.cfg.spectator,0xac)+=1;tick();assert(g_shared.error==19&&g_shared.detach_mask==3);puts("PASS native target alteration aborts");
 fixture();g_shared.heartbeat=GetTickCount()-2000;((UpdateFn)(uintptr_t)U(U(g_shared.cfg.battle,0x128),12))((void*)(uintptr_t)(g_shared.cfg.battle+0x128),.016f);assert(g_shared.error==1&&g_shared.detach_mask==3);puts("PASS watchdog detaches without external controller");
 fixture();F(g_shared.cfg.camera,0x100)=1;tick();assert(g_shared.error==11&&g_shared.position_applies==0);puts("PASS projection change aborts");
 fixture();g_shared.cfg.orientation_enabled=g_shared.cfg.fov_enabled=1;
 g_shared.points[1].quaternion=(Quat){.5648927512f,.7344985298f,-.2175683766f,-.3067117389f};g_shared.points[1].horizontal_fov=65;
 g_shared.points[2].quaternion=(Quat){.812144085f,.5686694104f,-.0748667482f,.1069207972f};g_shared.points[2].horizontal_fov=95;
 g_shared.command=1;tick();at(4);assert(g_shared.error==0);assert(fabsf(F(g_shared.cfg.spectator,0x58)-45)<.1);assert(fabsf(F(g_shared.cfg.spectator,0x5c)+10)<.1);assert(fabsf(F(g_shared.cfg.camera,0x5c)+12)<.1);assert(fabsf(F(g_shared.cfg.camera,0x268)-52)<.1);
 at(8.01);assert(g_shared.error==0&&g_shared.detach_mask==3);assert(fabsf(F(g_shared.cfg.spectator,0x58))<.0001);assert(fabsf(F(g_shared.cfg.spectator,0x5c)-20)<.0001);assert(fabsf(F(g_shared.cfg.camera,0x5c)-15)<.0001);assert(F(g_shared.cfg.camera,0x268)==76);puts("PASS synchronized position, yaw/pitch/roll, FOV and endpoint detach");
 fixture();g_shared.cfg.orientation_enabled=1;g_shared.cfg.approach_seconds=1;g_shared.points[0].position=g_shared.cfg.b;g_shared.points[0].quaternion=(Quat){.5648927512f,.7344985298f,-.2175683766f,-.3067117389f};g_shared.command=1;tick();at(.5);assert(F(g_shared.cfg.camera,0x40)==g_shared.cfg.b.z);assert(g_shared.error==0);assert(HookDetach(0)==0);puts("PASS stationary orientation-only approach does not lift position");
 Vec d;float angles[3];Quat qa={.5,.5,-.5,-.5},qb={-.5,-.5,.5,.5};Quat midpoint=qslerp(qa,qb,.5);assert(orientation(midpoint,&d,angles)&&dist(d,(Vec){1,0,0})<.00001);puts("PASS antipodal quaternion shortest rotation");
 fixture();g_shared.cfg.fov_enabled=1;g_shared.points[1].horizontal_fov=70;g_shared.command=1;tick();at(2);float stopped_fov=F(g_shared.cfg.camera,0x268);assert(stopped_fov<64);assert(HookDetach(0)==0);tick();assert(F(g_shared.cfg.camera,0x268)==stopped_fov);puts("PASS FOV-only stop retains lens state");
 fixture();g_shared.command=1;tick();F(g_shared.cfg.camera,0x264)+=.1f;tick();assert(g_shared.error==25&&g_shared.detach_mask==3);puts("PASS viewport and FOV scale guard");
 fixture();g_shared.cfg.orientation_enabled=1;g_shared.points[1].quaternion=(Quat){.5648927512f,.7344985298f,-.2175683766f,-.3067117389f};g_shared.command=1;tick();at(4);assert(g_shared.error==0);assert(dist(*(Vec*)(uintptr_t)(g_shared.cfg.camera+0x50),view_direction(g_shared.cfg.camera))>.1f);assert(guard()==0);F(g_shared.cfg.camera,0xc8)+=.01f;assert(guard()==12);HookDetach(0);puts("PASS lazy direction cache accepted, actual render-view changes rejected");
 fixture();HookDetach(0);g_shared.status=0;g_shared.detach_mask=0;g_shared.command=0;
 g_shared.cfg.duration=7200;g_shared.points[1].time=3600;g_shared.points[2].time=7200;
 assert(HookAttach(0)==0);g_shared.command=1;tick();at(3600);assert(g_shared.error==0&&g_shared.status==2);at(7200.01);assert(g_shared.error==0&&g_shared.detach_mask==3);puts("PASS independent camera duration exceeds replay limits and finishes");
 fixture();HookDetach(0);g_shared.status=0;g_shared.cfg.duration=7200;g_shared.cfg.replay_mode=1;assert(HookAttach(0)==108);puts("PASS replay mode retains duration bound");
 clock_tests();return 0;
}
