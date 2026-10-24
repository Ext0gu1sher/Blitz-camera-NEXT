/* Offline x86 ABI/refcount/reentrancy tests. Never opens the game. */
#define SEEK_SELF_TEST
#include "replay_seek_phase_trial_1121.c"
#undef NDEBUG
#include <assert.h>
static uint32_t owner,component[3],callbacks,releases,destroyed,bits,scenario,relocations;
static uint32_t table[10];
static volatile uintptr_t clear_entry,remove_entry;
static int expect_invariant_failure;
static LONG CALLBACK test_failure(EXCEPTION_POINTERS*p){
 if(expect_invariant_failure&&p->ExceptionRecord->ExceptionCode==0xe0425549u&&
    g_ui_repair.last_stage==(0x80000000u|30)&&!callbacks&&!releases&&!destroyed){
  puts("PASS corrupt table stops the actual hook before any callback/Release and records boundary evidence");
  fflush(stdout);ExitProcess(0);
 }
 fprintf(stderr,"SELFTEST EXCEPTION code=%08lx ip=%p stage=%u owner=%08x component=%08x scenario=%u\n",
  p->ExceptionRecord->ExceptionCode,p->ExceptionRecord->ExceptionAddress,
  g_ui_repair.last_stage,g_ui_repair.last_owner,g_ui_repair.last_component,scenario);
 fflush(stderr);ExitProcess(90);return EXCEPTION_CONTINUE_SEARCH;
}
static uint32_t allocate(void){
 void*p=VirtualAlloc(NULL,0x1000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);assert(p);return(uint32_t)(uintptr_t)p;
}
static void relocate(void){
 uint32_t old=U(owner,0xe4),entries=U(old,0),h=allocate(),b=allocate();
 uint32_t length=U(old,4)-entries;memcpy((void*)(uintptr_t)b,(void*)(uintptr_t)entries,length);
 U(h,0)=b;U(h,4)=b+length;U(h,8)=b+12;
 U(owner,0xe4)=h;U(owner,0xe8)=U(owner,0xec)=h+12;
 assert(VirtualFree((void*)(uintptr_t)entries,0,MEM_RELEASE));
 assert(VirtualFree((void*)(uintptr_t)old,0,MEM_RELEASE));relocations++;
}
static void __thiscall retain_component(void*self){InterlockedIncrement((LONG*)((char*)self+4));}
static void __thiscall release_component(void*self){
 releases++;assert(U(self,4)>0);
 if(!InterlockedDecrement((LONG*)((char*)self+4))){
  assert(U(self,8)==0);UiSlot s;assert(!ui_find(owner,(uint32_t)(uintptr_t)self,&s));
  if(scenario==3&&!relocations)relocate();
  destroyed++;assert(VirtualFree(self,0,MEM_RELEASE));
 }
}
static unsigned char __thiscall property(void*self){
 (void)self;if(scenario==5&&!relocations)relocate();return 1;
}
static uint32_t __thiscall type_id(void*self){(void)self;return 0;}
static void __thiscall unregister_component(void*sys,void*o,void*c){
 (void)sys;assert((uint32_t)(uintptr_t)o==owner);assert(U(c,8)==owner);callbacks++;
 if(scenario==1&&!relocations)relocate();
 if(scenario==2&&callbacks==1){
  /* The current removal is coalesced; another component may be removed. */
  ui_remove(o,NULL,c);ui_remove(o,NULL,(void*)(uintptr_t)component[0]);ui_clear(o,NULL);
 }
 if(scenario==4&&callbacks==1)ui_clear(o,NULL);
}
static void __thiscall mark_bit(void*self,int bit){assert((uint32_t)(uintptr_t)self==owner+0xa8&&bit==5);bits++;}
static void __thiscall dirty(void*self,int bit){assert((uint32_t)(uintptr_t)self==owner&&bit==5);bits++;}
static unsigned char __thiscall test_bit(void*self,int bit){(void)self;(void)bit;assert(0);return 0;}
static void __thiscall notify(void*self,void*o,int bit){(void)self;(void)o;(void)bit;assert(0);}
static void fixture(uint32_t mode,uint32_t count){
 memset(&g_ui_repair,0,sizeof(g_ui_repair));ui_transactions=NULL;
 callbacks=releases=destroyed=bits=relocations=0;scenario=mode;owner=allocate();
 g_ui_repair.thread=GetCurrentThreadId();
 ui_retain=retain_component;ui_release=release_component;ui_unregister=unregister_component;
 ui_dirty=dirty;ui_set_bit=mark_bit;ui_test_bit=test_bit;ui_notify=notify;
 table[0x14/4]=(uint32_t)(uintptr_t)type_id;
 table[0x1c/4]=table[0x20/4]=table[0x24/4]=(uint32_t)(uintptr_t)property;
 uint32_t h=allocate(),b=allocate(),head=allocate();
 U(owner,0xe4)=h;U(owner,0xe8)=U(owner,0xec)=h+12;U(owner,0xac)=1;
 U(h,0)=b;U(h,4)=b+4*count;U(h,8)=b+12;
 U(owner,0x44)=head;U(head,0)=U(head,4)=head;
 for(uint32_t i=0;i<count;i++){
  component[i]=allocate();U(component[i],0)=(uint32_t)(uintptr_t)table;
  U(component[i],4)=1;U(component[i],8)=owner;U(b,4*i)=component[i];
 }
}
static void done(uint32_t count){
 UiSlot s;assert(!ui_find(owner,0,&s));
 assert(destroyed==count&&releases==2*count&&callbacks==count);
 assert(!g_ui_repair.active&&!ui_transactions&&!g_ui_repair.violations);
 assert(g_ui_repair.removed==count&&(B(owner,0x4d)&0x80));
}
int main(int argc,char**argv){
 typedef void(__thiscall*Clear)(void*);typedef void(__thiscall*Remove)(void*,void*);
 AddVectoredExceptionHandler(1,test_failure);clear_entry=(uintptr_t)ui_clear;remove_entry=(uintptr_t)ui_remove;
 if(argc==2&&!strcmp(argv[1],"--corrupt")){
  fixture(0,1);uint32_t h=U(owner,0xe4);U(h,4)=U(h,0)-4;expect_invariant_failure=1;
  ui_log=CreateFileA("D:\\wotb_cam\\output\\native-selftest-ui-corrupt.bin",GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
  assert(ui_log!=INVALID_HANDLE_VALUE);((Clear)clear_entry)((void*)(uintptr_t)owner);return 1;
 }
 fixture(0,3);((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);
 assert(bits==1&&(B(owner,0x4c)&0x20));puts("PASS clear thiscall ABI, native dirty notifications, exact owning/pin releases");
 fixture(1,3);
 ui_log=CreateFileA("D:\\wotb_cam\\output\\native-selftest-ui-relocation.bin",GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
 assert(ui_log!=INVALID_HANDLE_VALUE);((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);
 CloseHandle(ui_log);ui_log=INVALID_HANDLE_VALUE;
 assert(relocations==1&&g_ui_repair.relocated==1);puts("PASS unregister frees both old vector buffers; no stale header/slot access");
 fixture(2,3);((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);
 assert(g_ui_repair.coalesced==2);puts("PASS recursive same-component removal and clear coalesced; other removal completes");
 fixture(3,3);((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);
 assert(relocations==1);puts("PASS component destructor reallocates table after erase; no post-Release vector writes");
 fixture(0,3);((Remove)remove_entry)((void*)(uintptr_t)owner,(void*)(uintptr_t)component[1]);
 assert(destroyed==1&&U(U(U(owner,0xe4),0),0)==component[0]&&U(U(U(owner,0xe4),0),4)==component[2]);
 ((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);puts("PASS single-remove thiscall callee-pop ABI and stable order, then clear");
 fixture(4,3);((Remove)remove_entry)((void*)(uintptr_t)owner,(void*)(uintptr_t)component[1]);done(3);
 assert(g_ui_repair.coalesced==1);puts("PASS clear requested during single removal drains after that transaction commits");
 fixture(5,3);((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);
 assert(relocations==1);puts("PASS virtual property callback replaces storage; erase reacquires by identity");
 fixture(1,3);uint32_t stub=allocate();DWORD ignored=0;MEMORY_BASIC_INFORMATION mbi;
 memcpy((void*)(uintptr_t)stub,"\x55\x8b\xec\x83\xec\x0c",6);
 assert(VirtualProtect((void*)(uintptr_t)stub,0x1000,PAGE_EXECUTE_READ,&ignored));
 assert(ui_patch(stub,(void*)ui_clear,6)&&ui_patch_present(stub,(void*)ui_clear,6));
 assert(VirtualQuery((void*)(uintptr_t)stub,&mbi,sizeof(mbi))&&mbi.Protect==PAGE_EXECUTE_READ);
 clear_entry=stub;((Clear)clear_entry)((void*)(uintptr_t)owner);done(3);
 puts("PASS executable detour/rel32/NOP, instruction-cache flush, protection restoration, real thiscall entry");
 /* Mimic both real prologues and epilogues; verify the worker fallback
  * executes the displaced instructions and honors the native stack ABI. */
 uint32_t native_clear=allocate(),native_remove=allocate();
 static const unsigned char clear_code[]={0x55,0x8b,0xec,0x83,0xec,0x0c,0xc7,0x41,0x10,0x7b,0,0,0,0x8b,0xe5,0x5d,0xc3};
 static const unsigned char remove_code[]={0x55,0x8b,0xec,0x6a,0xff,0x8b,0x45,8,0x89,0x41,0x10,0x8b,0xe5,0x5d,0xc2,4,0};
 memcpy((void*)(uintptr_t)native_clear,clear_code,sizeof(clear_code));
 memcpy((void*)(uintptr_t)native_remove,remove_code,sizeof(remove_code));
 assert(VirtualProtect((void*)(uintptr_t)native_clear,0x1000,PAGE_EXECUTE_READ,&ignored));
 assert(VirtualProtect((void*)(uintptr_t)native_remove,0x1000,PAGE_EXECUTE_READ,&ignored));
 ui_original_clear=(UiVoid)ui_trampoline(native_clear,6);ui_original_remove=(UiRemoveOriginal)ui_trampoline(native_remove,5);
 assert(ui_original_clear&&ui_original_remove);g_ui_repair.thread=0;
 clear_entry=(uintptr_t)ui_clear;((Clear)clear_entry)((void*)(uintptr_t)owner);assert(U(owner,0x10)==123);
 ((Remove)remove_entry)((void*)(uintptr_t)owner,(void*)(uintptr_t)0x12345678);assert(U(owner,0x10)==0x12345678);
 puts("PASS original worker-thread trampolines preserve displaced prologues and thiscall/ret-4 ABI");
 fixture(0,1);uint32_t h=U(owner,0xe4),b=U(h,0);UiSlot s;
 U(h,4)=b-4;assert(ui_find(owner,0,&s)==-1);
 assert(!callbacks&&!releases&&!destroyed);U(h,4)=b+4;
 U(b,0)=0xfd99faee;assert(ui_find(owner,0,&s)==-1);
 assert(!callbacks&&!releases&&!destroyed);puts("PASS pre-corrupt end/garbage component rejected before callbacks or refcount writes");
 (void)first_fault;
 return 0;
}
