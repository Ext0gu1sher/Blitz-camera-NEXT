static uint32_t live(uint32_t va){return g_shared.cfg.base+va-0x400000;}
static int readable(uint32_t p,size_t n){
 MEMORY_BASIC_INFORMATION m;
 if(p<0x10000||n>0xffffffffu-p||!VirtualQuery((void*)(uintptr_t)p,&m,sizeof(m)))return 0;
 return m.State==MEM_COMMIT&&!(m.Protect&(PAGE_NOACCESS|PAGE_GUARD))&&p+n<=(uintptr_t)m.BaseAddress+m.RegionSize;
}
static int functor_valid(void){
 Config*c=&g_shared.cfg;
 return readable(c->node,0x50)&&c->functor==c->node+0x20&&U(c->functor,0)==c->functor_vft&&U(c->functor,8)==c->player&&U(c->functor,0x14)==0;
}
static int in_signal(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->engine+0x70,16)||U(c->engine+0x70,4)!=c->head||!readable(c->head,8))return 0;
 uint32_t p=U(c->head,0),prev=c->head;int found=0;
 for(int i=0;p!=c->head&&i<64;i++){
  if(!readable(p,0x50)||U(p,4)!=prev)return 0;
  if(p==c->node)found=1;prev=p;p=U(p,0);
 }
 return p==c->head&&U(c->head,4)==prev&&found;
}
static int valid(void){
 Config*c=&g_shared.cfg;
 if(!readable(c->context,0x1b4)||!readable(c->player,0x10c)||!readable(c->scene_owner,0xa0)||!readable(c->scene,0x128)||!readable(c->camera,4))return 0;
 return U(c->context,0)==c->context_vft&&U(c->player,0)==c->player_vft&&U(c->player,0xc)==c->secondary_vft&&
 U(c->scene_owner,0)==c->scene_owner_vft&&U(c->scene,0)==c->scene_vft&&U(c->camera,0)==c->camera_vft&&
 U(c->context,0x1b0)==c->player&&U(c->scene_owner,0x20)==c->context&&U(c->scene_owner,0x1c)==c->scene&&U(c->scene_owner,0x94)==c->camera&&U(c->scene,0x120)==c->camera&&U(c->scene,0x124)==c->camera&&
 B(c->player,0x11)==1&&B(c->player,0x12)==1&&B(c->player,0x35)==1&&!B(c->player,0x2d)&&!B(c->player,0x2e)&&U(c->player,0x108)==0xffffffff&&U(c->player,0xa0)&&
 F(c->player,0x18)==c->raw&&F(c->player,0x64)==c->origin&&F(c->player,0x14)==c->rate;
}
