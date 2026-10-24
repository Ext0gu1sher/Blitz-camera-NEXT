/* One production owner of replay clock and camera hooks. Native calls only in tick. */
static int clock_identity(void){
 Config*c=&g_shared.cfg;
 return type(c->context,c->context_vft)&&type(c->player,c->player_vft)&&type(c->scene,c->scene_vft)&&type(c->scene_owner,c->scene_owner_vft)&&
 readable(c->player,0x10c)&&readable(c->scene,0x2ac)&&U(c->context,0x1b0)==c->player&&
 U(c->scene_owner,0x20)==c->context&&U(c->scene_owner,0x1c)==c->scene&&
 B(c->player,0x11)==1&&B(c->player,0x35)==1&&!B(c->player,0x2d)&&!B(c->player,0x2e)&&
 U(c->player,0x108)==0xffffffff&&F(c->player,0x64)==c->origin&&F(c->player,0x18)==g_shared.clock_raw;
}
static int clock_guard(void){
 Config*c=&g_shared.cfg;
 if(!clock_identity()||!readable(c->functor,0x18)||U(c->functor,0)!=c->functor_vft||U(c->functor,8)!=c->player||U(c->functor,0x14)!=0)return 26;
 if(U(c->functor,0x10)!=(clock_attached?(uint32_t)(uintptr_t)replay_tick_hook:c->tick_entry))return 26;
 if(B(c->player,0x12)!=g_shared.clock_paused||F(c->player,0x14)!=g_shared.current_rate)return 27;
 if(!B(c->scene,0x2a4)||F(c->scene,0x2a8)!=(g_shared.clock_paused?0:g_shared.current_rate))return 28;
 return 0;
}
static int validate_clock_config(void){
 Config*c=&g_shared.cfg;
 if(c->replay_mode>2||c->camera_clock>1||c->speed_smooth>1||c->speed_count<2||c->speed_count>64||!isfinite(c->play_seconds)||c->play_seconds<.5||c->play_seconds>120||!isfinite(c->initial_rate)||c->initial_rate<=0)return 0;
 /* Work in/out points select a slice of the authored schedule. They may also
    extend before/after it, where endpoint rates are held constant. */
 if(!isfinite(c->schedule_seconds)||c->schedule_seconds<=0||c->schedule_seconds>57600||!isfinite(c->schedule_offset)||fabs(c->schedule_offset)>57600)return 0;
 if(g_shared.speeds[0].progress!=0||g_shared.speeds[c->speed_count-1].progress!=1)return 0;
 for(uint32_t i=0;i<c->speed_count;i++){
  SpeedPoint*p=&g_shared.speeds[i];if(!isfinite(p->progress)||!isfinite(p->rate)||p->rate<.0625f||p->rate>1||(i&&p->progress<=g_shared.speeds[i-1].progress))return 0;
  if(p->custom_ease>1)return 0;
  if(p->custom_ease){for(int j=0;j<4;j++)if(!isfinite(p->ease[j])||(j%2?fabs(p->ease[j])>1e6:p->ease[j]<0||p->ease[j]>1))return 0;if(p->ease[0]>p->ease[2])return 0;
   if(i+1<c->speed_count)for(int j=1;j<4;j+=2){double r=p->rate+(g_shared.speeds[i+1].rate-p->rate)*p->ease[j];if(r<.06249||r>1.00001)return 0;}}
 }
#ifndef HOOK_SELF_TEST
 if(c->tick_entry!=live(0x140d100)||c->notify_entry!=live(0x140ec00)||c->pause_entry!=live(0x1402000)||c->functor_vft!=live(0x37c4674)||U(c->functor_vft,8)!=live(0x12f8310))return 0;
#endif
 return readable(c->functor,0x18)&&U(c->functor+0x10,0)==c->tick_entry&&clock_guard()==0&&B(c->player,0x12)==1;
}
static double clock_bezier_area(const float*e,double u){
 double x[4]={0,3.*e[0],3.*e[2]-6.*e[0],1.+3.*e[0]-3.*e[2]};
 double y[4]={0,3.*e[1],3.*e[3]-6.*e[1],1.+3.*e[1]-3.*e[3]},t=1.,sum=0;
 if(u<1){double lo=0,hi=1;for(int n=0;n<42;n++){t=(lo+hi)/2;if(t*(x[1]+t*(x[2]+t*x[3]))<u)lo=t;else hi=t;}t=(lo+hi)/2;}
 double powers[7]={1};for(int i=1;i<7;i++)powers[i]=powers[i-1]*t;
 for(int i=1;i<4;i++)for(int j=1;j<4;j++)sum+=y[i]*j*x[j]*powers[i+j]/(i+j);
 return sum;
}
static double clock_integral(double t){
 Config*c=&g_shared.cfg;double d=c->schedule_seconds,total=0;
 if(t<=0)return t*g_shared.speeds[0].rate;
 for(uint32_t i=1;i<c->speed_count;i++){
  SpeedPoint a=g_shared.speeds[i-1],b=g_shared.speeds[i];double lo=a.progress*d,span=(b.progress-a.progress)*d;
  double u=fmin(1.,fmax(0.,(t-lo)/span));if(u<=0)break;
  double area=a.custom_ease?clock_bezier_area(a.ease,u):c->speed_smooth?u*u*u-.5*u*u*u*u:.5*u*u;
  total+=span*(a.rate*u+(b.rate-a.rate)*area);
 }
 if(t>d)total+=(t-d)*g_shared.speeds[c->speed_count-1].rate;
 return total;
}
static void clock_finish(void){
 Config*c=&g_shared.cfg;
 if(g_shared.clock_started){
  g_shared.clock_restored=0;
  if(g_shared.clock_tid==(LONG)GetCurrentThreadId()&&clock_identity()&&F(c->player,0x14)==g_shared.current_rate){
   ((PauseFn)(uintptr_t)c->pause_entry)((void*)(uintptr_t)c->player,1);
   F(c->player,0x14)=c->initial_rate;
   ((NotifyFn)(uintptr_t)c->notify_entry)((void*)(uintptr_t)c->player);
   g_shared.current_rate=c->initial_rate;g_shared.clock_paused=1;
   g_shared.clock_restored=B(c->player,0x12)==1&&F(c->player,0x14)==c->initial_rate&&F(c->scene,0x2a8)==0;
  }
 }
 detach();
}
static void __fastcall replay_tick_hook(void*self,void*unused,float dt){
 (void)unused;Config*c=&g_shared.cfg;InterlockedIncrement(&g_shared.active);
 InterlockedCompareExchange(&g_shared.clock_tid,GetCurrentThreadId(),0);
 int valid=g_shared.status==1||g_shared.status==2;
 if(valid){
  int err=clock_guard();
  if(g_shared.clock_tid!=(LONG)GetCurrentThreadId())err=13;
  if(GetTickCount()-(DWORD)g_shared.heartbeat>1500)err=1;
  if(!isfinite(dt)||dt<0||dt>.15f)err=18;
  if(err)InterlockedCompareExchange(&g_shared.error,err,0);
  if(err||g_shared.command==9){clock_finish();valid=0;}
 }
 if(valid&&g_shared.command==3&&g_shared.clock_started){
  ((PauseFn)(uintptr_t)c->pause_entry)(self,1);g_shared.clock_paused=1;g_shared.command=0;
 }
 if(valid&&g_shared.command==4&&g_shared.clock_started){
  ((PauseFn)(uintptr_t)c->pause_entry)(self,0);g_shared.clock_paused=0;g_shared.command=0;
 }
 if(valid&&armed&&!g_shared.clock_started&&g_shared.last_elapsed>=c->approach_seconds){
  g_shared.clock_started=1;g_shared.clock_restored=0;g_shared.command=0;g_shared.clock_paused=0;
 }
 if(valid&&g_shared.clock_started&&!g_shared.clock_paused){
  double t=g_shared.shooting_elapsed+c->schedule_offset;
  float rate=dt>0?(float)((clock_integral(t+dt)-clock_integral(t))/dt):g_shared.current_rate;
  if(rate!=g_shared.current_rate){F(c->player,0x14)=rate;g_shared.current_rate=rate;((NotifyFn)(uintptr_t)c->notify_entry)(self);}
  if(B(c->player,0x12))((PauseFn)(uintptr_t)c->pause_entry)(self,0);
 }
 original_tick(self,dt);
 if(valid&&g_shared.clock_started&&!g_shared.clock_paused){
  float before=g_shared.clock_raw,expected=before+dt*g_shared.current_rate;
  float actual=F(c->player,0x18);
  if(actual!=expected){InterlockedCompareExchange(&g_shared.error,29,0);g_shared.command=9;}
  g_shared.clock_raw=actual;g_shared.replay_elapsed+=actual-before;g_shared.shooting_elapsed+=dt;
 }
 InterlockedDecrement(&g_shared.active);
}
