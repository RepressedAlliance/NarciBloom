/* CN-only post-extractor display policy. No CRT/allocation/shared scratch.
   Moves one final CJK body cell to a one-CJK-plus-closing tail only.
   Does not decode controls, tokenize stories, or invoke the extractor again. */
typedef unsigned int u32;
typedef unsigned char u8;
typedef struct { u32 pending, measure, no_start, no_end, vertical; } NBProfile;

__attribute__((always_inline)) static inline u32 length(const u8 *s,u32 bound) {
    u32 n=0;
    if(!s) return 0xffffffffu;
    while(n<bound) { if(!s[n]) return n; ++n; }
    return 0xffffffffu;
}
__attribute__((always_inline)) static inline int pair(const u8 *s) {
    return s[0]>=0x81 && s[0]<=0xfc && s[1]>=0x40 && s[1]<=0xfe && s[1]!=0x7f;
}
__attribute__((always_inline)) static inline int body(const u8 *s) {
    /* Structural GBK regions only; symbols/kana/fullwidth alphabets excluded.
       This is not a complete Unicode Han classifier or word segmenter. */
    return pair(s) && (s[0]<=0xa0 || s[0]>=0xb0);
}
__attribute__((always_inline)) static inline int member(u32 fn,const u8 *s) {
    typedef u32 (__attribute__((thiscall)) *Classifier)(const u8*);
    return ((Classifier)fn)(s)!=0;
}
__attribute__((always_inline)) static inline int width(u32 fn,void *rect,const u8 *s) {
    int size[2];
    u32 target=fn;void *rc=rect;const u8 *text=s;
    __asm__ volatile("pushl %[size]\n\tpushl $0\n\tcall *%%eax\n\taddl $8,%%esp"
        : "+a"(target), "+c"(rc), "+d"(text)
        : [size] "r"(size)
        : "cc","memory");
    return size[0];
}

/* cdecl six args. Flags/status remain owned by the untouched native caller.
   Result is diagnostic only; wrapper restores original native EAX/flags. */
u32 nb_adjust(u32 base,const NBProfile *p,void *rectangle,u8 *out,
              u8 *original_pending,u32 original_length) {
    u32 *rect=(u32*)rectangle;
    u8 *pending=*(u8**)(base+p->pending);
    u32 a,b,at,last=0,previous=0,body_count=0,i;
    u8 scratch[20];
    int fit;
    if(!rect || !out || !pending || pending!=original_pending || original_length>1023)
        return 0;
    if(*(u32*)(base+p->vertical)!=0) return 0;
    a=length(out,1024);b=length(pending,20);
    if(a==0xffffffffu || b==0xffffffffu || a<4 || b<2 || b>16 || a+b!=original_length)
        return 0;
    if(!body(pending)) return 0;
    for(at=2;at<b;at+=2) {
        if(at+1>=b || !pair(pending+at) || !member(base+p->no_start,pending+at)) return 0;
    }
    for(at=0;at<a;) {
        u32 step=out[at]<0x80 ? 1 : 2;
        if(step==1) {
            if(out[at]<0x20 || out[at]==0x7f || out[at]=='|' || out[at]=='\\') return 0;
        } else if(at+1>=a || !pair(out+at)) return 0;
        previous=last;last=at;
        if(step==2 && body(out+at)) ++body_count;
        at+=step;
    }
    if(a-last!=2 || !body(out+last) || body_count<2) return 0;
    if(member(base+p->no_end,out+previous)) return 0;
    if(member(base+p->no_start,out+last)) return 0;
    /* Positive bounded next usable width, including native hanging indent. */
    if(rect[0x58/4]>0x7fffffff || rect[0x60/4]>rect[0x58/4]) return 0;
    fit=(int)(rect[0x58/4]-rect[0x60/4]);
    if(fit<=0) return 0;
    scratch[0]=out[last];scratch[1]=out[last+1];
    for(i=0;i<=b;++i) scratch[i+2]=pending[i];
    at=(u32)width(base+p->measure,rectangle,scratch);
    if(at>0x7fffffff || at>(u32)fit) return 0;
    /* No writes until every check passes. Output length shrinks by two;
       pending grows by two but cannot exceed its original string length. */
    if(b+2>original_length) return 0;
    for(i=b+1;i>0;--i) pending[i+1]=pending[i-1];
    pending[0]=out[last];pending[1]=out[last+1];out[last]=0;
    return 1;
}
