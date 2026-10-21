/* Harness-owned fake native environment. Never loads game code or DLLs. */
typedef unsigned int u32;
typedef unsigned char u8;
typedef void *PTR;
__declspec(dllimport) PTR __stdcall VirtualAlloc(PTR,u32,u32,u32);
__declspec(dllimport) u32 __stdcall VirtualFree(PTR,u32,u32);
__declspec(dllimport) PTR __stdcall GetStdHandle(u32);
__declspec(dllimport) u32 __stdcall WriteFile(PTR,const void*,u32,u32*,PTR);
__declspec(dllimport) void __stdcall ExitProcess(u32);
#include "inputs.h"
extern void measure_stub(void);
extern u32 invoke_adjust(PTR,u32,PTR,PTR,PTR,PTR,u32,u32*);
typedef struct {u32 pending,measure,no_start,no_end,vertical,lexicon_rva,lexicon_bytes;} Profile;
typedef u32 (*Adjust)(u32,const Profile*,PTR,u8*,u8*,u32);
static u8 out_guard[1088],pending_guard[1088],out_before[1024],pending_before[1024];
static u8 other[1024];
/* Exactly the 108-byte native contract, with guards outside either end. */
static u32 rect_storage[31],rect_before[27],measure_calls;
static u32 *rect=rect_storage+2;
static u32 capture[10];
static const Case *current;
static void die(u32 n){ExitProcess(n);}
static void copy(u8*d,const u8*s,u32 n){while(n--)*d++=*s++;}
static u32 equal(const u8*a,const u8*b,u32 n){while(n--)if(*a++!=*b++)return 0;return 1;}
static u32 len(const u8*s){u32 n=0;while(n<1024 && s[n])++n;return n;}
static void emit_u32(u32 n){u8 s[12],t[12];u32 count=0,i,wrote;do{t[count++]=(u8)('0'+n%10);n/=10;}while(n);for(i=0;i<count;++i)s[i]=t[count-i-1];s[count++]=' ';WriteFile(GetStdHandle((u32)-11),s,count,&wrote,0);}
static void newline(void){u32 n;WriteFile(GetStdHandle((u32)-11),"\n",1,&n,0);}
static u32 text_width(const u8*s){u32 at=0,w=0;while(at<1024 && s[at]){if(s[at]<0x80){w+=5;at++;}else{if(!s[at+1])return 0x7fffffffu;w+=10;at+=2;}}return w;}
void fake_measure(u32 rc,const u8*text,u32 flag,u32*size){
    u32 bad,i,expected;u32 *probe=(u32*)rc;
    if(!probe||probe==rect||flag||!size)die(901);
    for(i=0;i<27;++i){
        expected=i==0x48/4?rect_before[0x50/4]+rect_before[0x60/4]:rect_before[i];
        if((i==0x64/4||i==0x68/4)&&measure_calls){
            u32 previous=(i==0x64/4?0xd0d00000u:0xe1e10000u)+measure_calls;
            if(probe[i]!=expected&&probe[i]!=previous)die(910+i);
        }else if(probe[i]!=expected)die(910+i);
    }
    ++measure_calls;
    /* The actual native helper mutates these fields even for a pure probe. */
    probe[0x64/4]=0xd0d00000u+measure_calls;
    probe[0x68/4]=0xe1e10000u+measure_calls;
    bad=measure_calls>=current->measure_fail_at;
    size[0]=(bad&&(current->flags&64))?0xffffffffu:((bad&&(current->flags&128))?0:text_width(text));size[1]=48;
}
static u32 is_member(const u8*s,const u8*list,u32 n){u32 i;for(i=0;i<n;i+=2)if(s[0]==list[i]&&s[1]==list[i+1])return 1;return 0;}
u32 __attribute__((thiscall)) no_start(const u8*s){return is_member(s,closing,sizeof(closing));}
u32 __attribute__((thiscall)) no_end(const u8*s){return is_member(s,opening,sizeof(opening));}
static void jump(u8*where,u32 destination){where[0]=0xb8;*(u32*)(where+1)=destination;where[5]=0xff;where[6]=0xe0;}
static void guards(u32 n){u32 i;for(i=0;i<32;i++)if(out_guard[i]!=0xc3||pending_guard[i]!=0xa7||out_guard[1056+i]!=0xc3||pending_guard[1056+i]!=0xa7)die(1000+n);}
static void test_base(u32 address){
    u8 *image=VirtualAlloc((PTR)address,0x1000000,0x3000,0x40);u8 *out=out_guard+32,*pending=pending_guard+32;
    Profile p={0x1000,0x2000,0x2100,0x2200,0x2300,0x4000,sizeof(lexicon)};
    u32 n,i,a,b,result,total,original,flags;Adjust adjust;
    if((u32)image!=address)die(900);
    copy(image+0x800000,payload,sizeof(payload));copy(image+p.lexicon_rva,lexicon,sizeof(lexicon));
    jump(image+p.measure,(u32)measure_stub);jump(image+p.no_start,(u32)no_start);jump(image+p.no_end,(u32)no_end);
    adjust=(Adjust)(image+0x800000);
    for(n=0;n<sizeof(cases)/sizeof(cases[0]);++n){
        current=cases+n;total=current->length;flags=current->flags;
        for(i=0;i<1088;++i){out_guard[i]=0xc3;pending_guard[i]=0xa7;}
        for(i=0;i<1024;++i){out[i]=0;pending[i]=0;other[i]=0;}
        copy(out,case_bytes+current->offset,current->cut);copy(pending,case_bytes+current->offset+current->cut,total-current->cut);
        copy(out_before,out,1024);copy(pending_before,pending,1024);copy(other,pending,1024);
        for(i=0;i<31;i++)rect_storage[i]=0xfeedface;
        for(i=0;i<27;i++)rect[i]=0x12340000u+i*0x101u;
        rect[0x48/4]=current->cursor_x;rect[0x50/4]=current->origin_x;
        rect[0x58/4]=current->width;rect[0x60/4]=current->indent;
        copy((u8*)rect_before,(u8*)rect,108);
        *(u32*)(image+p.pending)=(u32)((flags&256)?0:((flags&2)?other:pending));*(u32*)(image+p.vertical)=!!(flags&4);
        original=current->original_length;measure_calls=0;
        result=invoke_adjust((PTR)adjust,address,&p,(flags&8)?0:rect,(flags&16)?0:out,pending,original,capture);
        if(capture[0]!=0x11111111||capture[1]!=0x22222222||capture[2]!=0x33333333||
           capture[3]!=capture[4]||capture[5]!=capture[6]||capture[7]!=result||
           capture[8]!=0x13579bdf||capture[9]!=0x2468ace0)die(7000+n);
        guards(n);a=len(out);b=len(pending);
        if(!equal((u8*)rect,(u8*)rect_before,108)||rect_storage[0]!=0xfeedface||
           rect_storage[1]!=0xfeedface||rect_storage[29]!=0xfeedface||rect_storage[30]!=0xfeedface)die(8000+n);
        if(a>=1024||b>=1024||a+b!=total||!equal(out,case_bytes+current->offset,a)||!equal(pending,case_bytes+current->offset+a,b))die(2000+n);
        if((flags&1)&&(!equal(out,out_before,1024)||!equal(pending,pending_before,1024)))die(3000+n);
        /* A moved cut must remain in the original GBK/ASCII stream. */
        if(a&&case_bytes[current->offset+a-1]>=0x81){u32 at=0;while(at<a)at+=case_bytes[current->offset+at]<0x80?1:2;if(at!=a)die(4000+n);}
        /* Cosmetic balancing must not turn a valid two-line input into three. */
        if(text_width(out_before)<=current->width && text_width(pending_before)<=current->width &&
           (text_width(out)>current->width || text_width(pending)>current->width))die(5000+n);
        if(current->expected_cut!=0xffffffffu && a!=current->expected_cut)die(6000+n);
        if((flags&32) && b && is_member(pending,closing,sizeof(closing)))die(6500+n);
        emit_u32(address);emit_u32(n);emit_u32(result);emit_u32(a);emit_u32(b);emit_u32(measure_calls);newline();
    }
    if(!VirtualFree(image,0,0x8000))die(902);
}
void entry(void){test_base(0x18000000);test_base(0x28000000);ExitProcess(0);}
