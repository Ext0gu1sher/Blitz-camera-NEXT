/* Experimental extension, inserted into a copy of position_hook_1121.c.
 * The production source and DLL are never edited. Z-up world, row-vector TRS.
 * Follows a scene-bound TankVisual root or its validated gunFireJoint chain.
 */
#define TRACK_CAP 4096
#pragma pack(push,4)
typedef struct {
 uint32_t magic,size,visual,transform,eid,preset,lag_frames,phase;
 float distance,height,anchor[3],orbit_degrees,smooth_seconds;
 uint32_t part_entity,part_transform,part_parents[4];
} TrackConfig;
typedef struct {
 volatile LONG commit;
 uint32_t kind,updates,valid;
 float raw_time;
 Vec root,anchor,used_anchor;
 float matrix[16];
} TrackEvent;
typedef struct {TrackConfig cfg;TrackEvent records[TRACK_CAP];} Tracking;
#pragma pack(pop)
_Static_assert(sizeof(TrackConfig)==84,"tracking config ABI");
_Static_assert(sizeof(TrackEvent)==120,"tracking event ABI");
API Tracking g_tracking;
static Vec tracking_previous,tracking_used,tracking_position;
static int tracking_has_previous,tracking_has_position;
static double tracking_previous_t;

static int tracking_matrix(uint32_t transform,float*matrix){
 memcpy(matrix,(void*)(uintptr_t)(transform+0x60),64);
 for(int i=0;i<16;i++)if(!isfinite(matrix[i]))return 0;
 if(fabsf(matrix[3])+fabsf(matrix[7])+fabsf(matrix[11])+fabsf(matrix[15]-1)>1e-5)return 0;
 for(int i=0;i<3;i++){
  double len=0;for(int j=0;j<3;j++)len+=(double)matrix[i*4+j]*matrix[i*4+j];
  if(fabs(len-1)>.002)return 0;
  for(int k=i+1;k<3;k++){
   double dot=0;for(int j=0;j<3;j++)dot+=(double)matrix[i*4+j]*matrix[k*4+j];
   if(fabs(dot)>.002)return 0;
  }
 }
 return 1;
}

static int tracking_read(float*matrix,Vec*root,Vec*anchor){
 TrackConfig*t=&g_tracking.cfg;Config*c=&g_shared.cfg;
 if(!readable(t->visual,0x60)||!readable(t->transform,0xa8)||
    U(t->visual,0)!=live(0x3713afc)||U(t->visual,0x14)!=c->scene||
    U(t->visual,0x58)!=t->eid||U(t->visual,0x3c)!=t->transform||
    U(t->transform,0)!=live(0x3724564)||U(t->transform,8)!=t->visual||
    !tracking_matrix(t->transform,matrix))return 0;
 *root=(Vec){matrix[12],matrix[13],matrix[14]};
 if(t->preset==3){
  /* gunFireJoint -> gunJoint -> maskJoint -> turretJoint -> hullJoint -> TankVisual. */
  uint32_t entity=t->part_entity;
  for(int i=0;i<5;i++){
   uint32_t parent=i==4?t->visual:t->part_parents[i];
   if(!readable(entity,0x40)||U(entity,0)!=live(0x3762c90)||
      U(entity,0x14)!=c->scene||U(entity,0x18)!=parent)return 0;
   entity=parent;
  }
  if(!readable(t->part_transform,0xa8)||U(t->part_entity,0x3c)!=t->part_transform||
     U(t->part_transform,0)!=live(0x3724564)||U(t->part_transform,8)!=t->part_entity||
     !tracking_matrix(t->part_transform,matrix))return 0;
 }
 *anchor=(Vec){matrix[12],matrix[13],matrix[14]};
 for(int j=0;j<3;j++)for(int i=0;i<3;i++)((float*)anchor)[j]+=t->anchor[i]*matrix[i*4+j];
 return 1;
}

/* Closed form yaw/pitch -> quaternion, matching pose.quaternion_from_angles.
 * Keep roll zero and aim again AFTER position damping, so damping cannot make
 * the look-at target stale. No target prediction or smoothing by default. */
static Quat tracking_look(Vec p,Vec a){
 double dx=a.x-p.x,dy=a.y-p.y,dz=a.z-p.z;
 double yaw=atan2(dy,dx),pitch=atan2(dz,hypot(dx,dy));
 double heading=(yaw-PI/2)/2,tilt=(PI/2+pitch)/2;
 return qnormalize((Quat){(float)(cos(heading)*cos(tilt)),
  (float)(cos(heading)*sin(tilt)),(float)(sin(heading)*sin(tilt)),(float)(sin(heading)*cos(tilt))});
}

static int tracking_validate(void){
 TrackConfig*t=&g_tracking.cfg;
 if(t->magic!=0x31544b42||t->size!=sizeof(TrackConfig)||t->preset>3||t->lag_frames>1||t->phase>1||
    !isfinite(t->distance)||t->distance<3||t->distance>100||
    !isfinite(t->height)||fabsf(t->height)>30||
    !isfinite(t->orbit_degrees)||fabsf(t->orbit_degrees)>90||
    !isfinite(t->smooth_seconds)||t->smooth_seconds<0||t->smooth_seconds>2)return 0;
 for(int i=0;i<3;i++)if(!isfinite(t->anchor[i])||fabsf(t->anchor[i])>10)return 0;
 float matrix[16];Vec root,anchor;
 tracking_has_previous=tracking_has_position=0;tracking_previous_t=0;
 return tracking_read(matrix,&root,&anchor);
}

static int tracking_pose(PathPoint*pose,double elapsed){
 Config*c=&g_shared.cfg;TrackConfig*t=&g_tracking.cfg;
 float matrix[16];Vec root,anchor;
 if(!tracking_read(matrix,&root,&anchor))return 30;
 if(elapsed<c->approach_seconds){tracking_used=anchor;return 0;}
 double local=elapsed-c->approach_seconds;
 /* Tank local +Y is forward. Use yaw only for a level camera rail. */
 double heading=atan2(matrix[5],matrix[4]);
 double angle=heading+(t->preset==1?PI/2:PI)+(t->preset==2?local*t->orbit_degrees*PI/180:0);
 Vec p={root.x+(float)(cos(angle)*t->distance),root.y+(float)(sin(angle)*t->distance),root.z+t->height};
 if(t->preset==3){
  /* For a muzzle shot orbit_degrees is a fixed side angle about the barrel. */
  double side=t->orbit_degrees*PI/180;
  for(int j=0;j<3;j++)((float*)&p)[j]=((float*)&anchor)[j]+
      matrix[j]*t->distance*(float)sin(side)+matrix[4+j]*t->distance*(float)cos(side)+matrix[8+j]*t->height;
 }
 if(t->smooth_seconds>0&&tracking_has_position){
  double dt=fmax(0,elapsed-tracking_previous_t),a=-expm1(-dt/t->smooth_seconds);
  p=(Vec){(float)(tracking_position.x+(p.x-tracking_position.x)*a),
   (float)(tracking_position.y+(p.y-tracking_position.y)*a),(float)(tracking_position.z+(p.z-tracking_position.z)*a)};
 }
 tracking_position=p;tracking_previous_t=elapsed;tracking_has_position=1;
 tracking_used=t->lag_frames&&tracking_has_previous?tracking_previous:anchor;
 tracking_previous=anchor;tracking_has_previous=1;
 for(int j=0;j<3;j++)if(!isfinite(((float*)&p)[j])||((float*)&p)[j]<((float*)&c->lower)[j]+.1f||((float*)&p)[j]>((float*)&c->upper)[j]-.1f)return 31;
 if(dist(p,tracking_used)<.1f)return 32;
 pose->position=p;pose->quaternion=tracking_look(p,tracking_used);
 return 0;
}

static void tracking_record(LONG index,uint32_t kind){
 TrackEvent*e=&g_tracking.records[index%TRACK_CAP];InterlockedExchange(&e->commit,0);
 e->kind=kind;e->updates=g_shared.updates;e->raw_time=F(g_shared.cfg.player,0x18);
 e->valid=tracking_read(e->matrix,&e->root,&e->anchor);e->used_anchor=tracking_used;
 if(!e->valid)fail(30);
 InterlockedExchange(&e->commit,index+1);
}

static UpdateFn tracking_original_scene;
static void tracking_camera_update(float dt);
static int tracking_type_match(uint32_t p,uint32_t v){
 return p==g_shared.cfg.scene&&v==g_shared.cfg.scene_vft&&
        U(p,0)==(uint32_t)(uintptr_t)(tracking_scene_table+1);
}
static void __fastcall tracking_scene_hook(void*self,void*unused,float dt){
 (void)unused;InterlockedIncrement(&g_shared.active);
 tracking_original_scene(self,dt);
 if(g_shared.status==1||g_shared.status==2)tracking_camera_update(dt);
 InterlockedDecrement(&g_shared.active);
}
static int tracking_attach(void){
 if(!g_tracking.cfg.phase)return 1;
 Config*c=&g_shared.cfg;
 if(U(c->scene,0)!=c->scene_vft||U(c->scene_vft,0x54)!=live(0x7c46f0))return 0;
 memcpy(tracking_scene_table,(void*)(uintptr_t)(c->scene_vft-4),sizeof(tracking_scene_table));
 tracking_original_scene=(UpdateFn)tracking_scene_table[22];
 tracking_scene_table[22]=(uintptr_t)tracking_scene_hook;
 return (uint32_t)InterlockedCompareExchange((LONG*)(uintptr_t)c->scene,
    (LONG)(uintptr_t)(tracking_scene_table+1),c->scene_vft)==c->scene_vft;
}
static void tracking_detach(void){
 Config*c=&g_shared.cfg;
 if(readable(c->scene,4))InterlockedCompareExchange((LONG*)(uintptr_t)c->scene,
    c->scene_vft,(LONG)(uintptr_t)(tracking_scene_table+1));
}
