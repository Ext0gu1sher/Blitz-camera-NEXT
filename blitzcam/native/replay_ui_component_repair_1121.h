/* Exact-build experimental UIControl component removal. Runtime only.
 * All offsets and native notifications are from repair-layout-51.txt.
 * Never carry a vector/header/slot across a game call. Keep the component
 * alive separately, commit the vector erase, then release its owning ref.
 * A malformed table is evidence against this hypothesis, not an empty table.
 */
typedef void (__thiscall *UiVoid)(void*);
typedef void (__thiscall *UiRemoveOriginal)(void*,void*);
typedef unsigned char (__thiscall *UiBool)(void*);
typedef uint32_t (__thiscall *UiType)(void*);
typedef void (__thiscall *UiUnregister)(void*,void*,void*);
typedef void (__thiscall *UiInt)(void*,int);
typedef unsigned char (__thiscall *UiTest)(void*,int);
typedef void (__thiscall *UiNotify)(void*,void*,int);
typedef struct {
 uint32_t installed,base,thread,active,clear_calls,remove_calls,removed;
 uint32_t relocated,coalesced,violations,last_stage,last_owner,last_component,sequence;
 char fault_path[260];
} UiRepairState;
API UiRepairState g_ui_repair;
typedef struct {
 uint32_t sequence,stage,owner,component,outer_begin,outer_end;
 uint32_t header,begin,end,capacity,refs,component_owner;
} UiEvent;
typedef struct {uint32_t header,slot,begin,end,capacity,outer_begin,outer_end;} UiSlot;
typedef struct UiTxn {
 uint32_t owner,component,clearing,pending_clear;
 struct UiTxn *previous;
} UiTxn;
static UiTxn *ui_transactions;
static uint32_t ui_invalid_component;
static HANDLE ui_log=INVALID_HANDLE_VALUE;
static UiVoid ui_retain,ui_release;
static UiVoid ui_original_clear;
static UiRemoveOriginal ui_original_remove;
static UiUnregister ui_unregister;
static UiNotify ui_notify;
static UiInt ui_dirty,ui_set_bit;
static UiTest ui_test_bit;
static void __fastcall ui_clear(void*,void*);
static void __fastcall ui_remove(void*,void*,void*);

/* Stages: 1/2 clear/remove entry, 3 before unregister, 4 after unregister,
 * 5 after erase/before Release, 6 complete, 7 reentrant request coalesced.
 * High bit = invariant failure; low bits identify the failing boundary.
 */
static void ui_record(uint32_t stage,uint32_t owner,uint32_t component,const UiSlot*s){
 UiEvent e={0};e.sequence=++g_ui_repair.sequence;e.stage=stage;e.owner=owner;e.component=component;
 if(s){e.outer_begin=s->outer_begin;e.outer_end=s->outer_end;e.header=s->header;
  e.begin=s->begin;e.end=s->end;e.capacity=s->capacity;}
 if(component&&stage!=6&&readable(component,12)){e.refs=U(component,4);e.component_owner=U(component,8);}
 g_ui_repair.last_stage=stage;g_ui_repair.last_owner=owner;g_ui_repair.last_component=component;
 if(ui_log!=INVALID_HANDLE_VALUE){DWORD n=0;
  if(!WriteFile(ui_log,&e,sizeof(e),&n,NULL)||n!=sizeof(e))g_ui_repair.violations++;
 }
}
__attribute__((noreturn)) static void ui_fail(uint32_t stage,uint32_t owner,uint32_t component){
 g_ui_repair.violations++;ui_record(0x80000000u|stage,owner,component,NULL);
 if(ui_log!=INVALID_HANDLE_VALUE)FlushFileBuffers(ui_log);
 /* Deliberately do not continue cleanup, swallow an AV, or pretend success. */
 ULONG_PTR args[3]={stage,owner,component};
 RaiseException(0xe0425549u,EXCEPTION_NONCONTINUABLE,3,args);
 TerminateProcess(GetCurrentProcess(),0xe0425549u);
 __builtin_unreachable();
}
static void ui_thread(uint32_t owner,uint32_t component){
 if(GetCurrentThreadId()!=g_ui_repair.thread)ui_fail(10,owner,component);
}
static int ui_vector(uint32_t b,uint32_t e,uint32_t cap,uint32_t stride,uint32_t limit){
 if(!b)return !e&&!cap;
 return !(b%4)&&b<=e&&e<=cap&&!( (e-b)%stride )&&!( (cap-b)%stride )&&
        (cap-b)/stride<=limit&&readable(b,cap-b);
}
/* Does not call the game. Thus its returned slot is usable until our next
 * game call, and never after one. Also rejects duplicates of the target. */
static int ui_find(uint32_t owner,uint32_t target,UiSlot*out){
 memset(out,0,sizeof(*out));
 ui_invalid_component=0;
 if(!readable(owner,0xf4))return -1;
 uint32_t b=U(owner,0xe4),e=U(owner,0xe8),cap=U(owner,0xec);
 out->outer_begin=b;out->outer_end=e;
 if(!ui_vector(b,e,cap,12,4096))return -1;
 int found=0;
 for(uint32_t h=b;h<e;h+=12){
  uint32_t ib=U(h,0),ie=U(h,4),ic=U(h,8);
  if(!ui_vector(ib,ie,ic,4,65536)){
   out->header=h;out->begin=ib;out->end=ie;out->capacity=ic;return -1;
  }
  for(uint32_t p=ib;p<ie;p+=4){
   uint32_t c=U(p,0);
   if(!readable(c,12)||!readable(U(c,0),0x28)||!U(c,4)){
    ui_invalid_component=c;out->header=h;out->slot=p;out->begin=ib;out->end=ie;out->capacity=ic;return -1;
   }
   if((target&&c==target)||(!target&&!found&&p==ie-4)){
    if(target&&found)return -1;
    found=1;out->header=h;out->slot=p;out->begin=ib;out->end=ie;out->capacity=ic;
   }
  }
 }
 return found;
}
static int ui_locate(uint32_t owner,uint32_t c,UiSlot*s,uint32_t stage){
 int found=ui_find(owner,c,s);
 if(found<0){uint32_t bad=ui_invalid_component?ui_invalid_component:c;
  ui_record(0x40000000u|stage,owner,bad,s);ui_fail(stage,owner,bad);}
 return found;
}
static UiTxn* ui_owner_txn(uint32_t owner){
 for(UiTxn*t=ui_transactions;t;t=t->previous)if(t->owner==owner)return t;
 return NULL;
}
static int ui_busy_component(uint32_t owner,uint32_t component){
 for(UiTxn*t=ui_transactions;t;t=t->previous)
  if(t->owner==owner&&t->component==component)return 1;
 return 0;
}
static void ui_pop(UiTxn*t){
 ui_transactions=t->previous;g_ui_repair.active--;
 if(t->pending_clear){UiTxn*other=ui_owner_txn(t->owner);
  if(other)other->pending_clear=1;else ui_clear((void*)(uintptr_t)t->owner,NULL);}
}
static unsigned char ui_query(uint32_t c,uint32_t offset){
 if(!readable(c,12)||!readable(U(c,0),0x28))ui_fail(11,0,c);
 return ((UiBool)(uintptr_t)U(U(c,0),offset))((void*)(uintptr_t)c);
}
static void ui_render_dirty(uint32_t owner){
 B(owner,0x4c)|=0x20;uint32_t sys=U(owner,0x34);
 if(sys){uint32_t render=U(sys,0xb4);
  ui_notify((void*)(uintptr_t)render,(void*)(uintptr_t)owner,3);B(render,0xb9)=1;}
}
static void ui_children_dirty(uint32_t owner){
 /* This is the unchanged notification logic from cf ac1f / cf b0ff.
  * It operates on the distinct child list, not the component vectors. */
 uint32_t head=U(owner,0x44),node=U(head,0);uint32_t bound=0;
 while(node!=head){
  if(++bound>65536||!readable(node,12))ui_fail(12,owner,0);
  uint32_t child=U(node,8);B(child,0x4d)|=4;
  ui_set_bit((void*)(uintptr_t)(child+0xa8),0x11);
  if(B(child,0x4e)&1){uint32_t parent=U(child,0x38);
   if(parent&&!ui_test_bit((void*)(uintptr_t)(parent+0xa8),0xe))ui_dirty((void*)(uintptr_t)parent,0xe);}
  node=U(node,0);
 }
}
static void ui_clear_notifications(uint32_t owner,unsigned char children){
 ui_render_dirty(owner);B(owner,0x4d)|=4;ui_set_bit((void*)(uintptr_t)(owner+0xa8),5);
 if(B(owner,0x4e)&1){uint32_t parent=U(owner,0x38);
  if(parent&&!ui_test_bit((void*)(uintptr_t)(parent+0xa8),0xe))ui_dirty((void*)(uintptr_t)parent,0xe);}
 if(children)ui_children_dirty(owner);B(owner,0x4d)|=0x80;
}
static void ui_unregister_component(uint32_t owner,uint32_t component){
 UiSlot before,after;
 if(!ui_locate(owner,component,&before,20))return;
 ui_record(3,owner,component,&before);
 if((int32_t)U(owner,0xac)>=1)
  ui_unregister((void*)(uintptr_t)U(owner,0x34),(void*)(uintptr_t)owner,(void*)(uintptr_t)component);
 int found=ui_locate(owner,component,&after,21);
 if(before.outer_begin!=after.outer_begin||before.outer_end!=after.outer_end||
    (found&&(before.header!=after.header||before.begin!=after.begin||before.end!=after.end)))g_ui_repair.relocated++;
 ui_record(4,owner,component,&after);
}
static int ui_erase(uint32_t owner,uint32_t component){
 UiSlot s;if(!ui_locate(owner,component,&s,22))return 0;
 if(U(component,8)&&U(component,8)!=owner)ui_fail(23,owner,component);
 /* No game calls until the entire erase has committed. Other component
  * pointers move as raw owning pointers; their refcounts do not change. */
 U(component,8)=0;
 memmove((void*)(uintptr_t)s.slot,(void*)(uintptr_t)(s.slot+4),s.end-s.slot-4);
 U(s.end-4,0)=0;U(s.header,4)=s.end-4;g_ui_repair.removed++;
 s.end-=4;ui_record(5,owner,component,&s);
 ui_release((void*)(uintptr_t)component);
 /* Nothing from s may be touched here: Release can destroy/reallocate it. */
 return 1;
}
static void __fastcall ui_clear(void*self,void*unused){
 if(GetCurrentThreadId()!=g_ui_repair.thread){ui_original_clear(self);return;}
 (void)unused;uint32_t owner=(uint32_t)(uintptr_t)self;ui_thread(owner,0);g_ui_repair.clear_calls++;
 UiTxn*other=ui_owner_txn(owner);
 if(other){other->pending_clear=1;g_ui_repair.coalesced++;ui_record(7,owner,0,NULL);return;}
 UiTxn txn={owner,0,1,0,ui_transactions};ui_transactions=&txn;g_ui_repair.active++;
 UiSlot s;ui_locate(owner,0,&s,30);ui_record(1,owner,0,&s);unsigned char children=0;
 uint32_t iterations=0;
 while(ui_locate(owner,0,&s,31)){
  if(++iterations>65536)ui_fail(32,owner,0);
  uint32_t c=U(s.slot,0);txn.component=c;
  if(U(c,8)!=owner)ui_fail(33,owner,c);
  ui_retain((void*)(uintptr_t)c);
  ui_unregister_component(owner,c);
  if(ui_locate(owner,c,&s,34)){
   if(U(c,8)&&U(c,8)!=owner)ui_fail(35,owner,c);
   U(c,8)=0;children|=ui_query(c,0x24);
   ui_erase(owner,c);
  }
  ui_release((void*)(uintptr_t)c);txn.component=0;
 }
 /* A nested clear was satisfied by draining the table. */
 txn.pending_clear=0;ui_clear_notifications(owner,children);ui_record(6,owner,0,NULL);ui_pop(&txn);
}
static void __fastcall ui_remove(void*self,void*unused,void*component){
 if(GetCurrentThreadId()!=g_ui_repair.thread){ui_original_remove(self,component);return;}
 (void)unused;uint32_t owner=(uint32_t)(uintptr_t)self,c=(uint32_t)(uintptr_t)component;
 ui_thread(owner,c);g_ui_repair.remove_calls++;
 if(ui_busy_component(owner,c)){g_ui_repair.coalesced++;ui_record(7,owner,c,NULL);return;}
 UiSlot s;if(!ui_locate(owner,c,&s,40))return;
 UiTxn txn={owner,c,0,0,ui_transactions};ui_transactions=&txn;g_ui_repair.active++;
 ui_record(2,owner,c,&s);if(U(c,8)!=owner)ui_fail(41,owner,c);
 ui_retain(component);
 /* Preserve native query order, but derive the actual slot by identity. */
 ((UiType)(uintptr_t)U(U(c,0),0x14))(component);
 unsigned char dirty=ui_query(c,0x1c),children=ui_query(c,0x24),render=ui_query(c,0x20);
 ui_unregister_component(owner,c);int erased=ui_erase(owner,c);
 ui_release(component);
 if(erased){if(render)ui_render_dirty(owner);if(dirty)ui_dirty(self,5);
  if(children)ui_children_dirty(owner);B(owner,0x4d)|=0x80;}
 ui_record(6,owner,c,NULL);ui_pop(&txn);
}
static void* ui_trampoline(uint32_t address,size_t length){
 unsigned char*p=VirtualAlloc(NULL,32,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
 if(!p)return NULL;
 memcpy(p,(void*)(uintptr_t)address,length);p[length]=0xe9;
 uint32_t back=address+length-(uint32_t)(uintptr_t)(p+length+5);memcpy(p+length+1,&back,4);
 DWORD ignored=0;
 if(!VirtualProtect(p,32,PAGE_EXECUTE_READ,&ignored)||!FlushInstructionCache(GetCurrentProcess(),p,32)){
  VirtualFree(p,0,MEM_RELEASE);return NULL;
 }
 return p;
}
static int ui_patch_present(uint32_t address,void*entry,size_t length){
 unsigned char patch[6]={0xe9,0,0,0,0,0x90};
 uint32_t displacement=(uint32_t)(uintptr_t)entry-address-5;memcpy(patch+1,&displacement,4);
 return readable(address,length)&&!memcmp((void*)(uintptr_t)address,patch,length);
}
static int ui_patch(uint32_t address,void*entry,size_t length){
 unsigned char patch[6]={0xe9,0,0,0,0,0x90};DWORD old=0,ignored=0;
 uint32_t displacement=(uint32_t)(uintptr_t)entry-address-5;memcpy(patch+1,&displacement,4);
 if(!VirtualProtect((void*)(uintptr_t)address,length,PAGE_EXECUTE_READWRITE,&old))return 0;
 memcpy((void*)(uintptr_t)address,patch,length);
 if(!FlushInstructionCache(GetCurrentProcess(),(void*)(uintptr_t)address,length))ui_fail(52,0,0);
 if(!VirtualProtect((void*)(uintptr_t)address,length,old,&ignored))ui_fail(50,0,0);
 return 1;
}
#ifndef SEEK_SELF_TEST
static int ui_install(void){
 if(g_ui_repair.installed)return g_ui_repair.base==g_shared.cfg.base&&g_ui_repair.thread==GetCurrentThreadId()&&
   ui_patch_present(live(0xcfab30),(void*)ui_clear,6)&&ui_patch_present(live(0xcfaf90),(void*)ui_remove,5);
 uint32_t clear=live(0xcfab30),remove=live(0xcfaf90);
 static const unsigned char a[]={0x55,0x8b,0xec,0x83,0xec,0x0c},b[]={0x55,0x8b,0xec,0x6a,0xff};
 if(!readable(clear,0x15b)||!readable(remove,0x1de)||memcmp((void*)(uintptr_t)clear,a,6)||memcmp((void*)(uintptr_t)remove,b,5))return 0;
 char path[280];int n=snprintf(path,sizeof(path),"%s.ui.bin",g_shared.cfg.fault_path);
 if(n<0||n>=(int)sizeof(path))return 0;
 ui_log=CreateFileA(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
 if(ui_log==INVALID_HANDLE_VALUE)return 0;
 /* Other threads retain their native behavior. Copy complete instructions;
  * these two prologues contain no relative instructions or absolute pointers. */
 ui_original_clear=(UiVoid)ui_trampoline(clear,6);
 ui_original_remove=(UiRemoveOriginal)ui_trampoline(remove,5);
 if(!ui_original_clear||!ui_original_remove){
  if(ui_original_clear)VirtualFree((void*)ui_original_clear,0,MEM_RELEASE);
  if(ui_original_remove)VirtualFree((void*)ui_original_remove,0,MEM_RELEASE);
  CloseHandle(ui_log);ui_log=INVALID_HANDLE_VALUE;return 0;
 }
 g_ui_repair.base=g_shared.cfg.base;g_ui_repair.thread=GetCurrentThreadId();
 memcpy(g_ui_repair.fault_path,g_shared.cfg.fault_path,sizeof(g_ui_repair.fault_path));
 ui_retain=(UiVoid)(uintptr_t)live(0x93e9d0);ui_release=(UiVoid)(uintptr_t)live(0x93e4c0);
 ui_unregister=(UiUnregister)(uintptr_t)live(0xd08840);ui_notify=(UiNotify)(uintptr_t)live(0xd09b30);
 ui_dirty=(UiInt)(uintptr_t)live(0xcfec30);ui_set_bit=(UiInt)(uintptr_t)live(0x10e2f30);ui_test_bit=(UiTest)(uintptr_t)live(0x10e8d30);
 /* Installed only from the verified main-job pump. No worker patches UI. */
 if(!ui_patch(clear,(void*)ui_clear,6)){
  VirtualFree((void*)ui_original_clear,0,MEM_RELEASE);VirtualFree((void*)ui_original_remove,0,MEM_RELEASE);
  ui_original_clear=NULL;ui_original_remove=NULL;CloseHandle(ui_log);ui_log=INVALID_HANDLE_VALUE;return 0;
 }
 if(!ui_patch(remove,(void*)ui_remove,5))ui_fail(51,0,0);
 g_ui_repair.installed=1;return 1;
}
#endif
