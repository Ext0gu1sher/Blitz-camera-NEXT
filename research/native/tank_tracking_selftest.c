#define HOOK_SELF_TEST
#include "tracking_generated.c"
#include <assert.h>
#include <stdlib.h>
int main(void){
 for(int y=-180;y<=180;y+=15)for(int p=-75;p<=75;p+=15){
  Vec pos={123,-231,30};double yaw=y*PI/180,pitch=p*PI/180;
  Vec anchor={pos.x+(float)(20*cos(pitch)*cos(yaw)),pos.y+(float)(20*cos(pitch)*sin(yaw)),pos.z+(float)(20*sin(pitch))};
  Vec direction;float angles[3];assert(orientation(tracking_look(pos,anchor),&direction,angles));
  Vec expected={(float)(cos(pitch)*cos(yaw)),(float)(cos(pitch)*sin(yaw)),(float)sin(pitch)};
  assert(dist(direction,expected)<2e-6);assert(fabs(angles[2])<1e-3);
 }
 /* An unrelated entity or bad transform must be rejected before attachment. */
 memset(&g_tracking,0,sizeof(g_tracking));assert(!tracking_validate());
 g_tracking.cfg.magic=0x31544b42;g_tracking.cfg.size=sizeof(TrackConfig);
 g_tracking.cfg.distance=15;assert(!tracking_validate());
 uint32_t v=(uint32_t)(uintptr_t)calloc(1,0x60),tc=(uint32_t)(uintptr_t)calloc(1,0xa8);
 assert(v&&tc);Config*c=&g_shared.cfg;TrackConfig*t=&g_tracking.cfg;c->base=0x400000;c->scene=0x123456;
 U(v,0)=0x3713afc;U(v,0x14)=c->scene;U(v,0x58)=123;U(v,0x3c)=tc;U(tc,0)=0x3724564;U(tc,8)=v;
 float*m=(float*)(uintptr_t)(tc+0x60);m[0]=m[5]=m[10]=m[15]=1;m[12]=30;m[13]=-20;m[14]=10;
 t->visual=v;t->transform=tc;t->eid=123;t->height=6;t->anchor[2]=1.5;c->lower=(Vec){-1000,-1000,-1000};c->upper=(Vec){1000,1000,1000};
 assert(tracking_validate());PathPoint p={0};assert(tracking_pose(&p,0)==0);
 assert(dist(p.position,(Vec){30,-35,16})<1e-5);
 m[12]+=2;assert(tracking_pose(&p,.016)==0);assert(fabs(tracking_used.x-32)<1e-6);
 t->lag_frames=1;m[12]+=2;assert(tracking_pose(&p,.032)==0);assert(fabs(tracking_used.x-32)<1e-6);
 t->lag_frames=0;t->smooth_seconds=.2;m[12]+=2;assert(tracking_pose(&p,.048)==0);
 assert(p.position.x<36&&tracking_used.x==36); /* damping must not delay aim */
 U(v,0x58)=999;assert(tracking_pose(&p,.064)==30);U(v,0x58)=123;
 U(tc,8)=0;assert(!tracking_validate());U(tc,8)=v;
 m[0]=2;assert(!tracking_validate());m[0]=1;
 c->upper.x=31;assert(tracking_pose(&p,.080)==31);
 free((void*)(uintptr_t)v);free((void*)(uintptr_t)tc);
 printf("tracking native math: 275 headings/pitches; target identity, matrix, lag, damping, bounds passed; config=%u event=%u shared=%u\n",(unsigned)sizeof(TrackConfig),(unsigned)sizeof(TrackEvent),(unsigned)sizeof(Tracking));
 return 0;
}
