/* Bounded CN display line selection. Words come from the generic frequency
   lexicon in the same RX section, never a list of game sentences. The native
   extractor is called once; only its byte boundary may retreat. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef struct {
    u32 pending, measure, no_start, no_end, vertical, lexicon, lexicon_bytes;
} NBProfile;
#define INLINE __attribute__((always_inline)) static inline
#define NONE 0xffffffffu
#define LIMIT 512

INLINE u32 length(const u8 *s,u32 bound) {
    u32 n=0;if(!s)return NONE;
    while(n<bound){if(!s[n])return n;++n;}return NONE;
}
INLINE int pair(const u8 *s) {
    return s[0]>=0x81 && s[0]<=0xfe && s[1]>=0x40 && s[1]<=0xfe && s[1]!=0x7f;
}
INLINE u32 code(const u8 *s) {return s[0]<0x80?s[0]:((u32)s[0]<<8)|s[1];}
INLINE int body(u32 c) {return c>=0x8140 && ((c>>8)<=0xa0 || (c>>8)>=0xb0);}
INLINE int close_cell(u32 c) {
    return c=='!'||c=='?'||c==','||c=='.'||c==';'||c==':'||c=='%'||c==')'||c==']'||c=='}'
        ||c==0xa1a2||c==0xa1a3||c==0xa3ac||c==0xa3ae||c==0xa3bf||c==0xa3a1
        ||c==0xa3ba||c==0xa3bb||c==0xa3a9||c==0xa1b3||c==0xa3dd||c==0xa3fd
        ||c==0xa1b5||c==0xa1b7||c==0xa1b9||c==0xa1bb||c==0xa1bf||c==0xa1bd
        ||c==0xa1b1||c==0xa1af||c==0xa1ab||c==0xa1ad||c==0xa1aa;
}
INLINE int open_cell(u32 c) {
    return c=='('||c=='['||c=='{'||c==0xa3a8||c==0xa1b2||c==0xa3db||c==0xa3fb
        ||c==0xa1b4||c==0xa1b6||c==0xa1b8||c==0xa1ba||c==0xa1be||c==0xa1bc
        ||c==0xa1b0||c==0xa1ae;
}
INLINE int ascii_token(u32 c) {
    return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')
        ||c=='_'||c=='\''||c=='-'||c=='+'||c=='.'||c==','||c==':'||c=='/'||c=='%';
}
INLINE int width(u32 fn,void *rect,const u8 *s) {
    int size[2];u32 target=fn;void *rc=rect;const u8 *text=s;
    __asm__ volatile("pushl %[size]\n\tpushl $0\n\tcall *%%eax\n\taddl $8,%%esp"
        : "+a"(target), "+c"(rc), "+d"(text) : [size] "r"(size) : "cc","memory");
    return size[0];
}
INLINE int valid_lexicon(const u8 *l,u32 size) {
    const u32 *h=(const u32*)l;u32 n;
    if(size<36||h[0]!=0x584c424e||h[1]!=0x00080001||h[7]!=size)return 0;
    n=h[2];if(!n||n>400000||h[3]>65535)return 0;
    if(h[4]<36||h[4]>size||(n+1)*4>size-h[4])return 0;
    if(h[5]<h[4]+(n+1)*4||h[5]>size||n*2>size-h[5])return 0;
    if(h[6]<h[5]+n*2||h[6]>=size)return 0;
    return *(const u32*)(l+h[4])==0
        && *(const u32*)(l+h[4]+n*4)==size-h[6];
}
INLINE u32 cost(const u8 *l,const u8 *word,u32 bytes) {
    const u32 *h=(const u32*)l,*offsets=(const u32*)(l+h[4]);
    u32 lo=0,hi=h[2],m,a,b,k,common;int cmp;
    while(lo<hi){
        m=lo+(hi-lo)/2;a=offsets[m];b=offsets[m+1];
        if(a>b||b>h[7]-h[6])return NONE;
        common=b-a<bytes?b-a:bytes;cmp=0;
        for(k=0;k<common;++k){if(l[h[6]+a+k]!=word[k]){cmp=l[h[6]+a+k]<word[k]?-1:1;break;}}
        if(!cmp)cmp=b-a<bytes?-1:(b-a>bytes?1:0);
        if(!cmp)return *(const u16*)(l+h[5]+m*2);
        if(cmp<0)lo=m+1;else hi=m;
    }
    return NONE;
}
INLINE u32 span_width(u32 fn,void *rect,u8 *text,u32 begin,u32 end) {
    u8 saved=text[end];u32 w;text[end]=0;
    w=(u32)width(fn,rect,text+begin);text[end]=saved;
    return !w&&end>begin?NONE:w;
}

/* All scratch is local and below one page. Selection never writes native
   buffers, cursor, control state, history, saves, or lexicon data. */
u32 nb_adjust(u32 base,const NBProfile *p,void *rectangle,u8 *out,
              u8 *original_pending,u32 original_length) {
    u32 *rect=(u32*)rectangle;
    u8 *pending=*(u8**)(base+p->pending);
    const u8 *lex=(const u8*)(base+p->lexicon);
    u8 text[1024],route[LIMIT+1];u16 ends[LIMIT+1];u32 scores[9],probe_rect[27];
    u32 a,b,at,n=0,cut=0,i,j,k,c,v,best,bestlen,score,fit,after_width;
    u32 chosen,quality,best_quality,retreat,word_first,word_end,split,probe_end,w;
    u32 suffix_bodies=0,suffix_plain=1,tail,violations,initial_fits;
    if(!rect||!out||!pending||pending!=original_pending||original_length>1023)return 0;
    if(*(u32*)(base+p->vertical))return 0;
    if(!valid_lexicon(lex,p->lexicon_bytes))return 0;
    a=length(out,1024);b=length(pending,1024);
    if(a==NONE||b==NONE||!a||!b||a+b!=original_length)return 0;
    for(i=0;i<a;++i)text[i]=out[i];for(i=0;i<=b;++i)text[a+i]=pending[i];
    ends[0]=0;
    for(at=0;at<original_length;){
        if(n==LIMIT)return 0;
        c=text[at];k=c<0x80?1:2;
        if(k==1){if(c<0x20||c==0x7f||c=='|'||c=='\\')return 0;}
        else if(at+1>=original_length||!pair(text+at))return 0;
        at+=k;ends[++n]=(u16)at;if(at==a)cut=n;
    }
    if(!cut||cut==n)return 0;
    if(rect[0x58/4]>0x7fffffff||rect[0x60/4]>rect[0x58/4])return 0;
    fit=rect[0x58/4]-rect[0x60/4];if(!fit)return 0;
    if(rect[0x50/4]>0x7fffffffu-rect[0x60/4])return 0;
    /* Native measurement writes its two metric scratch fields. Isolate those
       and probe from the next line's physical origin, not the old cursor. */
    for(i=0;i<27;++i)probe_rect[i]=rect[i];
    probe_rect[0x48/4]=rect[0x50/4]+rect[0x60/4];
    rectangle=probe_rect;
    /* Fixed-point dictionary-DAG route, as opposed to overlapping longest
       matches. Single-character frequencies participate in the same route. */
    scores[n%9]=0;route[n]=0x80;
    for(i=n;i>0;){
        --i;c=code(text+ends[i]);bestlen=1;
        if(!body(c)){scores[i%9]=scores[(i+1)%9];route[i]=1;continue;}
        v=cost(lex,text+ends[i],ends[i+1]-ends[i]);
        if(v==NONE)v=((const u32*)lex)[3];
        best=v+scores[(i+1)%9];
        for(j=2;j<=8&&i+j<=n;++j){
            if(!body(code(text+ends[i+j-1])))break;
            v=cost(lex,text+ends[i],ends[i+j]-ends[i]);if(v==NONE)continue;
            score=v+scores[(i+j)%9];
            if(score<best||(score==best&&j>bestlen)){best=score;bestlen=j;}
        }
        scores[i%9]=best;route[i]=(u8)bestlen;
    }
    for(i=0;i<n;){k=route[i];route[i]|=0x80;i+=k;}
    for(i=cut;i<n;++i){c=code(text+ends[i]);if(body(c))++suffix_bodies;
        else if(!close_cell(c))suffix_plain=0;}
    after_width=span_width(base+p->measure,rectangle,text,a,original_length);
    if(after_width>0x7fffffff)return 0;
    initial_fits=after_width<=fit;
    probe_end=cut;
    while(probe_end<n&&close_cell(code(text+ends[probe_end])))++probe_end;
    chosen=cut;best_quality=NONE;
    /* Every earlier candidate is no wider on the current line. In a final
       two-line block no candidate may create a third line for appearance. */
    for(i=cut;i>0;--i){
        retreat=cut-i;
        if(retreat){c=code(text+ends[i]);if(body(c))++suffix_bodies;else if(!close_cell(c))suffix_plain=0;}
        if(initial_fits){
            after_width=span_width(base+p->measure,rectangle,text,ends[i],original_length);
            if(after_width>0x7fffffff)return 0;
            if(after_width>fit)break;
        }else if(probe_end>i){
            w=span_width(base+p->measure,rectangle,text,ends[i],ends[probe_end]);
            if(w>0x7fffffff)return 0;
            if(w>fit)continue;
        }
        violations=close_cell(code(text+ends[i]))+open_cell(code(text+ends[i-1]));
        split=0;
        if(!(route[i]&0x80)&&body(code(text+ends[i-1]))&&body(code(text+ends[i]))){
            word_first=i;while(word_first&&!(route[word_first]&0x80))--word_first;
            word_end=word_first+(route[word_first]&0x7f);
            w=span_width(base+p->measure,rectangle,text,ends[word_first],ends[word_end]);
            if(w>0x7fffffff)return 0;
            split=w<=fit;
        }
        if(ascii_token(code(text+ends[i-1]))&&ascii_token(code(text+ends[i]))){
            word_first=i;word_end=i;
            while(word_first&&ascii_token(code(text+ends[word_first-1])))--word_first;
            while(word_end<n&&ascii_token(code(text+ends[word_end])))++word_end;
            w=span_width(base+p->measure,rectangle,text,ends[word_first],ends[word_end]);
            if(w>0x7fffffff)return 0;
            split=w<=fit;
        }
        tail=initial_fits&&suffix_plain&&suffix_bodies<3?3-suffix_bodies:0;
        quality=violations*0x1000000u+split*0x100000u+tail*0x10000u+retreat;
        if(quality<best_quality){best_quality=quality;chosen=i;}
        if(!violations&&!split&&!tail)break;
    }
    if(chosen==cut)return 0;
    /* No mutation until all selection and native measurement have succeeded.
       The combined original byte length and its terminating NUL are exact. */
    at=ends[chosen];j=a-at;
    for(i=b+1;i>0;--i)pending[i+j-1]=pending[i-1];
    for(i=0;i<j;++i)pending[i]=out[at+i];out[at]=0;
    return 1;
}
