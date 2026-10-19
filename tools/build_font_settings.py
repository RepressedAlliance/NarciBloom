"""Build a bounded font selector for all five Narcissu anthology executables.

Existing bytecode addresses are preserved. Hooks use jump trampolines; new
functions are appended. Dialogue, manual saves, and unlock flags are untouched.
"""
import copy
import hashlib
import json
import random
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from patch_narcissu_font import ROOT, TOOLS, entries, archive
from mjotool.crypt import crypt32, hash32
from mjotool.opcodes import Opcode

SIZES = (24, 28, 32, 36, 40, 44)
DEFAULT = 36
SIZE = hash32('#cdx_font_size@NARCI_DECK')
FONT = 0x391053C5
PAGE = 0x644BB6D2
OUT = TOOLS / 'staged'

# Menu encoding follows the active game/translation loader, not the PC locale.
# Keep the existing Chinese recipe byte-for-byte compatible by default.
MENUS = {
    'zh-CN': dict(encoding='gbk', back='返回', family='更换字体', size='字号：',
                  hint='  （点此选择大小）', current='  （当前）', entry='字体 / 字号',
                  heading='当前字号：', help='点选大小，返回剧情后生效  ·  推荐 36'),
    'ja': dict(encoding='cp932', back='戻る', family='フォント変更', size='サイズ：',
               hint='  （サイズ選択）', current='  （現在）', entry='文字サイズ',
               heading='文字サイズ：', help='本文に戻ると反映  /  推奨 36'),
    'en': dict(encoding='cp932', back='Back', family='Font', size='Size: ',
               hint='  (select size)', current='  (current)', entry='Font / Size',
               heading='Font size: ', help='Applies in story  /  Try 36'),
}


@dataclass
class Ins:
    offset: int
    name: str
    fields: dict
    raw: bytes


class Script:
    def __init__(self, blob):
        self.signature, self.main, self.lines, count = struct.unpack_from('<16sIII', blob)
        assert self.signature in (b'MajiroObjX1.000\0', b'MajiroObjV1.000\0')
        self.functions = list(struct.iter_unpack('<II', blob[28:28+8*count]))
        length = struct.unpack_from('<I', blob, 28+8*count)[0]
        self.code = bytearray(blob[32+8*count:])
        assert len(self.code) == length
        if self.signature[9:10] == b'X':
            self.code = bytearray(crypt32(self.code))
        self.original = bytes(self.code)
        self.ins = self.parse(self.code)
        self.hooks = []

    @staticmethod
    def parse(code):
        pos = 0
        result = []
        for_limit = len(code)+1
        while pos < len(code):
            start = pos
            op = Opcode.BYVALUE[struct.unpack_from('<H', code, pos)[0]]
            pos += 2
            fields = {}
            for field in op.encoding:
                if field in 'tsc':
                    count = struct.unpack_from('<H', code, pos)[0]
                    pos += 2
                    width = {'t':1, 's':1, 'c':4}[field]
                    size = count*width
                    assert pos+size <= len(code)
                    data = bytes(code[pos:pos+size])
                    fields[field] = (list(struct.unpack('<'+str(count)+'i', data)) if field=='c' else data)
                    pos += size
                else:
                    fmt = {'f':'H','h':'I','o':'h','0':'I','i':'i','r':'f','a':'H','j':'i','l':'H'}[field]
                    fields[field] = struct.unpack_from('<'+fmt, code, pos)[0]
                    pos += struct.calcsize(fmt)
            result.append(Ins(start,op.mnemonic,fields,bytes(code[start:pos])))
            assert len(result) < for_limit
        assert pos == len(code)
        return result

    def hook_after(self, inst, function):
        # Keep original addresses, including all original branch targets.
        assert len(inst.raw) in (8,12)
        trampoline = len(self.code)
        self.code.extend(inst.raw)
        self.code.extend(emit('callp', function, 0, 0))
        self.code.extend(emit('br', inst.offset+len(inst.raw)-(len(self.code)+6)))
        replacement=emit('br',trampoline-(inst.offset+6))
        replacement += emit('ret')*((len(inst.raw)-6)//2)
        self.code[inst.offset:inst.offset+len(inst.raw)] = replacement
        self.hooks.append({'offset':inst.offset,'name':inst.name,'function':function})

    def replace_syscall(self, inst, function):
        assert len(inst.raw)==8 and inst.name=='syscall'
        trampoline=len(self.code)
        self.code.extend(emit('call',function,0,inst.fields['a']))
        self.code.extend(emit('br',inst.offset+8-(len(self.code)+6)))
        self.code[inst.offset:inst.offset+8]=emit('br',trampoline-(inst.offset+6))+emit('ret')
        self.hooks.append({'offset':inst.offset,'name':inst.name,'function':function,'replaces':inst.fields['h']})

    def add(self, function, code):
        assert function not in {h for h,_ in self.functions}
        self.functions.append((function,len(self.code)))
        self.code.extend(code)

    def finish(self):
        instructions = self.parse(self.code)
        boundaries={x.offset for x in instructions}
        original_boundaries={x.offset for x in self.ins}
        assert original_boundaries <= boundaries
        assert self.main in boundaries
        assert len({h for h,_ in self.functions})==len(self.functions)
        assert all(o in boundaries for _,o in self.functions)
        for i in instructions:
            if 'j' in i.fields:
                assert i.offset+len(i.raw)+i.fields['j'] in boundaries, (i,'branch')
            if 'c' in i.fields:
                for n,delta in enumerate(i.fields['c']):
                    assert i.offset+8+4*n+delta in boundaries, (i,'switch')
        data=bytes(self.code)
        if self.signature[9:10] == b'X':
            data=crypt32(data)
        blob=struct.pack('<16sIII',self.signature,self.main,self.lines,len(self.functions))
        blob+=b''.join(struct.pack('<II',h,o) for h,o in self.functions)
        blob+=struct.pack('<I',len(data))+data
        check=Script(blob)
        assert check.code==self.code
        return blob


def emit(name,*values):
    op=Opcode.fromname(name)
    out=bytearray(struct.pack('<H',op.value))
    assert len(values)==len(op.encoding),(name,values,op.encoding)
    for field,value in zip(op.encoding,values):
        if field in 'ts':
            raw=bytes(value)
            out.extend(struct.pack('<H',len(raw)))
            out.extend(raw)
        else:
            fmt={'f':'H','h':'I','o':'h','0':'I','i':'i','r':'f','a':'H','j':'i','l':'H'}[field]
            out.extend(struct.pack('<'+fmt,value))
    return bytes(out)


class Builder:
    def __init__(self, encoding='gbk'):
        self.encoding=encoding
        self.code=bytearray();self.labels={};self.refs=[]
    def op(self,name,*args):self.code.extend(emit(name,*args));return self
    def integer(self,value):return self.op('ldc.i',value)
    def text(self,value):return self.op('ldstr',value.encode(self.encoding)+b'\0')
    def load(self,hashed,scope=0,kind=0,slot=0):return self.op('ld',(scope<<5)|(kind<<8),hashed,slot)
    def store(self,hashed,scope=0,kind=0,slot=0):return self.op('st.i' if kind==0 else 'st.s',(scope<<5)|(kind<<8),hashed,slot).op('pop')
    def syscall(self,hashed,count,result=False):return self.op('syscall' if result else 'syscallp',hashed,count)
    def call(self,hashed,count=0,result=False):return self.op('call' if result else 'callp',hashed,0,count)
    def label(self,name):self.labels[name]=len(self.code);return self
    def branch(self,name,target):
        self.refs.append((len(self.code),target));return self.op(name,0)
    def prologue(self,count=0):return self.op('argcheck',bytes([0]*count)).op('alloca',b'')
    def ret(self):return self.integer(0).op('ret')
    def finish(self):
        for off,label in self.refs:struct.pack_into('<i',self.code,off+2,self.labels[label]-(off+6))
        return bytes(self.code)


def apply_function():
    b=Builder().prologue()
    for size in SIZES:
        b.load(SIZE).integer(size).op('ceq.i').branch('brtrue','valid')
    b.integer(DEFAULT).store(SIZE)
    b.label('valid')
    for hashed in [0x65615B45,0x99EE010B]:b.load(SIZE).store(hashed)
    for hashed in [0x721A4F06,0x8E951548]:b.load(SIZE).integer(2).op('div.i').store(hashed)
    b.load(SIZE).integer(4).op('add.i').store(0xBDDD7DA2)
    b.load(0x721A4F06).load(0x65615B45).load(FONT,kind=2).syscall(0x098399F2,3)
    return b.ret().finish()


def draw_function(language='zh-CN'):
    menu=MENUS[language]
    b=Builder(menu['encoding']).prologue()
    def box(x,y,w,h,color):
        for value in [color,h,w,y,x]:b.integer(value)
        b.load(PAGE,scope=1).syscall(0xD01BE374,6)
    def font(height):
        b.integer(0).integer(height//2).integer(height).load(FONT,kind=2).syscall(0xE186D19A,4)
        b.integer(0x01000000).integer(0xFFFFFF).syscall(0x90816C6E,2)
    def locate(x,y):b.integer(y).integer(x).load(PAGE,scope=1).syscall(0x57F6310D,3)
    box(105,493,638,81,0x225785)
    font(28);locate(120,499)
    b.text(menu['heading']).load(SIZE).syscall(0x6F769889,1,result=True).op('add.s').syscall(0x35A89417,1)
    font(20);locate(350,503)
    b.text(menu['help']).syscall(0x35A89417,1)
    for index,size in enumerate(SIZES):
        x=120+index*100
        box(x,534,88,36,0x78B9DF)
        b.load(SIZE).integer(size).op('ceq.i').branch('brfalse','normal'+str(size))
        box(x+2,536,84,32,0x946C0F)
        b.branch('br','label'+str(size)).label('normal'+str(size))
        box(x+2,536,84,32,0x205E90)
        b.label('label'+str(size))
        font(28);locate(x+27,535);b.text(str(size)).syscall(0x35A89417,1)
    return b.ret().finish()


def click_function(apply_hash,draw_hash):
    b=Builder().prologue(5)
    for index,size in enumerate(SIZES):
        b.load(0x64DA103A,scope=3,slot=-2).integer(3100+index).op('ceq.i').branch('brfalse','next'+str(size))
        b.integer(size).store(SIZE).branch('br','selected').label('next'+str(size))
    b.ret().label('selected').call(apply_hash).call(draw_hash)
    b.text('push').syscall(0xED84E320,1)
    return b.ret().finish()


def init_function(apply_hash,draw_hash,click_hash,noop_hash):
    b=Builder().prologue().call(apply_hash).call(draw_hash)
    for index,_ in enumerate(SIZES):
        for value in [click_hash,noop_hash,noop_hash,36,88,534,120+100*index,3100+index]:
            if value>0x7FFFFFFF:value-=0x100000000
            b.integer(value)
        b.syscall(0xF8D18340,8)
    return b.ret().finish()


def patch_config(blob, language='zh-CN'):
    s=Script(blob)
    hashes={name:hash32('$cdx_font_'+name+'@NARCI_CONFIG') for name in ['apply','draw','click','noop','init']}
    targets=[]
    for index,i in enumerate(s.ins):
        if i.name=='syscallp' and i.fields.get('h')==0xA7C6E918:
            prev=s.ins[max(0,index-2):index]
            if {x.fields.get('i',0)&0xFFFFFFFF for x in prev}=={0xCEFFEFDA,0x801E45B0}:
                targets.append(i)
    assert len(targets)==1,len(targets)
    s.hook_after(targets[0],hashes['init'])
    new={hashes['apply']:apply_function(),hashes['draw']:draw_function(language),
         hashes['click']:click_function(hashes['apply'],hashes['draw']),
         hashes['noop']:Builder().prologue(5).ret().finish(),
         hashes['init']:init_function(hashes['apply'],hashes['draw'],hashes['click'],hashes['noop'])}
    for h,code in new.items():s.add(h,code)
    return s.finish(),s.hooks,new,hashes


def patch_loader(blob):
    s=Script(blob);h=hash32('$cdx_font_apply@NARCI_LOAD')
    matches=[i for i in s.ins if i.name=='syscallp' and i.fields.get('h')==0x098399F2]
    assert len(matches)==1,len(matches)
    s.hook_after(matches[0],h);s.add(h,apply_function())
    return s.finish(),s.hooks


def pause_selector_function(apply_hash, language='zh-CN'):
    """1+2 uses a text pause/settings menu instead of the later CONFIG page."""
    choice=hash32('_cdx_choice@')
    menu=MENUS[language]
    b=Builder(menu['encoding']).op('argcheck',bytes([2,0])).op('alloca',bytes([0]))
    b.call(apply_hash).label('menu')
    # Majiro passes arguments right-to-left; select returns a one-based index.
    b.text(menu['back']).text(menu['family'])
    b.text(menu['size']).load(SIZE).syscall(0x6F769889,1,result=True).op('add.s')
    b.text(menu['hint']).op('add.s').call(0x0A7A489C,3,result=True)
    b.store(choice,scope=3,slot=0)
    b.load(choice,scope=3,slot=0).integer(1).op('ceq.i').branch('brfalse','family')
    for size in reversed(SIZES):
        b.load(SIZE).integer(size).op('ceq.i').branch('brfalse','plain'+str(size))
        b.text(str(size)+menu['current']).branch('br','ready'+str(size))
        b.label('plain'+str(size)).text(str(size)).label('ready'+str(size))
    b.call(0x0A7A489C,6,result=True).store(choice,scope=3,slot=0)
    for index,size in enumerate(SIZES):
        b.load(choice,scope=3,slot=0).integer(index+1).op('ceq.i').branch('brfalse','skip'+str(size))
        b.integer(size).store(SIZE).call(apply_hash).branch('br','menu').label('skip'+str(size))
    b.branch('br','menu').label('family')
    b.load(choice,scope=3,slot=0).integer(2).op('ceq.i').branch('brfalse','done')
    b.load(0xB5788291).load(FONT,kind=2).syscall(0x95FF28F2,2,result=True).op('ret')
    b.label('done').load(FONT,kind=2).op('ret')
    return b.finish()


def patch_pause(blob, language='zh-CN'):
    s=Script(blob)
    hashes={'apply':hash32('$cdx_font_apply@NARCI_PAUSE'),
            'selector':hash32('$cdx_font_selector$@NARCI_PAUSE')}
    targets=[i for i in s.ins if i.name=='syscall' and i.fields.get('h')==0x95FF28F2]
    assert len(targets)==1
    s.replace_syscall(targets[0],hashes['selector'])
    # Reuse the existing font settings entry; do not move the other controls.
    font_labels={'フォント設定'.encode('cp932'), b'Font settings'}
    labels=[i for i in s.ins if i.name=='ldstr' and i.fields['s'].rstrip(b'\0') in font_labels]
    assert len(labels)==1
    menu=MENUS[language]
    label=labels[0];raw=menu['entry'].encode(menu['encoding'])+b'\0'
    assert len(raw)<=len(label.fields['s'])
    s.code[label.offset+4:label.offset+len(label.raw)]=raw.ljust(len(label.fields['s']),b'\0')
    functions={hashes['apply']:apply_function(),hashes['selector']:pause_selector_function(hashes['apply'],language)}
    for h,code in functions.items():s.add(h,code)
    return s.finish(),s.hooks,functions,hashes


def patch_console_bounded(blob):
    s=Script(blob);changes=[]
    for idx,i in enumerate(s.ins):
        if i.name!='syscallp' or i.fields.get('h')!=0x403960F8:continue
        previous=s.ins[max(0,idx-12):idx]
        start=max((j for j,x in enumerate(previous) if x.name=='line'),default=-1)
        args=previous[start+1:]
        if len(args)<5 or args[0].name!='ldc.i':continue
        ints=[x for x in args if x.name=='ldc.i']
        if len(ints)<4:continue
        height,width,y=ints[0].fields['i'],ints[1].fields['i'],ints[2].fields['i']
        # Original 1+2 letterbox narration uses a different, 60px-high box.
        # At 36/44px this fits only one line, making the engine clear it on
        # every CRLF. The scene ends at y=350, so use the empty margin below.
        if (height,width,y)==(60,560,356):
            struct.pack_into('<i',s.code,args[0].offset+2,220)
            changes.append({'offset':args[0].offset,'height':220,'y':356,'bottom':576})
            continue
        if height!=88 or width!=690:continue
        # Only extend text below the 402px scene band. Do not grow rectangles
        # that already start at 514px, where they would overflow the screen.
        if y==402:
            struct.pack_into('<i',s.code,args[0].offset+2,166)
            changes.append({'offset':args[0].offset,'height':166,'bottom':582})
    return s.finish(),changes


def config_fonts(blob,size=DEFAULT,font_family=None):
    if font_family is not None and (not font_family.strip() or any(c in font_family for c in ',\r\n')):
        raise ValueError('Font family must be a nonempty single config field')
    text=blob.decode('cp932');changes=[]
    for marker,width in [('CONFONT',3),('NAMEFONT',2)]:
        at=text.index('// '+marker)
        head,tail=text[:at],text[at:]
        replacement=f'{size}, {size//2}, {size+4}' if width==3 else f'{size}, {size//2}'
        pattern=r'^\d+,\s*\d+'+(r',\s*\d+' if width==3 else '')+r'(?=\s*//)'
        tail,count=re.subn(pattern,replacement,tail,count=1,flags=re.M)
        assert count==1,(marker,count)
        if font_family is not None:
            tail,count=re.subn(r'^[^/\r\n,][^\r\n,]*(?=,\s*[01]\s*//)',
                               lambda match:font_family,tail,count=1,flags=re.M)
            assert count==1,(marker,'font family',count)
        text=head+tail;changes.append(marker)
    return text.encode('cp932')


def original_sources(folder):
    files={};embedded=[]
    for name in ['scenario.arc','fastdata.arc','update.arc']+[f'update{i}.arc' for i in range(1,12)]:
        p=folder/name
        if p.exists():files.update({n:r[2] for n,r in entries(p.read_bytes()).items()})
    exe=next(folder.glob('*.exe'));blob=exe.read_bytes()
    for m in re.finditer(rb'MajiroArcV[13]\.000\x00',blob):
        try:e=entries(blob,m.start())
        except (AssertionError,ValueError,struct.error):continue
        files.update({n:r[2] for n,r in e.items()})
        embedded.append((m.start(),e))
    return files,exe,blob,embedded


def build_overrides(game, files, language='zh-CN', font_family=None):
    """Compile local overrides without reading or writing a game directory."""
    override={}
    for name in ['sysdata.cfg','sysdata27.cfg','ナルキ１全画面中央.cfg','プロダクツ用設定.cfg']:
        if name in files:override[name]=config_fonts(files[name],font_family=font_family)
    if game=='narci_onetwo':
        setting_script='pausemenu.mjo'
        config,hooks,new_functions,hashes=patch_pause(files[setting_script],language)
    else:
        setting_script='config.mjo'
        config,hooks,new_functions,hashes=patch_config(files[setting_script],language)
    loader,load_hooks=patch_loader(files['load_sysdata.mjo'])
    console,rects=patch_console_bounded(files['console.mjo'])
    from layout_candidate import patch_console_pagination,patch_sensitive_menu_entry,CONFIG_MENU,HISTORY,PAUSE_MENU
    console,pagination=patch_console_pagination(console)
    override.update({setting_script:config,'load_sysdata.mjo':loader,'console.mjo':console})
    menu_guards={}
    for name,target in [('config.mjo',CONFIG_MENU),('history.mjo',HISTORY)]:
        if name in files:
            override[name],menu_guards[name]=patch_sensitive_menu_entry(override.get(name,files[name]),target)
    if game=='narci_onetwo':
        override[setting_script],menu_guards[setting_script]=patch_sensitive_menu_entry(override[setting_script],PAUSE_MENU)
    pagination['menu_entry_guards']=menu_guards
    # 1+2 virtual files are handled by the separate repair recipe.
    renames=[]
    report={'game':game,
            'menu_language':language,'menu_encoding':MENUS[language]['encoding'],
            'font_family_override':font_family,
            'override_files':list(override),'config_hooks':hooks,'loader_hooks':load_hooks,
            'text_rectangles':rects,'embedded_directory_renames':renames,
            'pagination':pagination,
            'font_sizes':SIZES,'default_font_size':DEFAULT,'ui_functions':hashes,
            'settings_script':setting_script,
            'archive_bytes':len(archive(override))}
    return override,report,new_functions,hashes


def build(game, language='zh-CN', font_family=None):
    folder=ROOT/game;files,exe,exe_blob,embedded=original_sources(folder)
    override,report,new_functions,hashes=build_overrides(game,files,language,font_family)
    dest=OUT/game;dest.mkdir(parents=True,exist_ok=True)
    (dest/'update12.arc').write_bytes(archive(override))
    report.update(source_exe=str(exe),source_sha256=hashlib.sha256(exe_blob).hexdigest())
    (dest/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report,new_functions,hashes


if __name__=='__main__':
    import argparse
    games=['narci_iris','narci_onetwo','narci_himeko','narci_zero','narci_sumire']
    parser=argparse.ArgumentParser(description='Stage font overrides; never install into the game')
    parser.add_argument('--game', choices=games, action='append')
    parser.add_argument('--menu-language', choices=MENUS, default='zh-CN',
                        help='New menu text only: ja/en use the stock CP932 engine; zh-CN uses the Chinese loader')
    parser.add_argument('--font-family', help='Optional installed font family for config defaults; otherwise preserve the source font')
    args=parser.parse_args()
    if not ROOT.is_dir():parser.error('Set NARCIBLOOM_GAME_DIR to the anthology installation directory')
    OUT.mkdir(parents=True,exist_ok=True)
    for game in args.game or games:
        report,_,_=build(game,args.menu_language,args.font_family)
        print(json.dumps(report,ensure_ascii=False))
