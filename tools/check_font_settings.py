"""Offline checks of generated VM code, UI bounds and untouched story scripts."""
import json
import struct
from collections import deque
from build_font_settings import *


class VM:
    def __init__(self,functions,variables=None,choices=(),encoding='gbk'):
        self.encoding=encoding
        self.functions=functions
        self.variables=dict(variables or {})
        self.variables.setdefault(FONT,'Noto Sans CJK')
        self.variables.setdefault((1,PAGE),123)
        self.choices=deque(choices)
        self.operations=[]
        self.depth=0

    def run(self,hashed,args=()):
        self.depth+=1
        assert self.depth<10
        instructions=Script.parse(self.functions[hashed])
        lookup={i.offset:i for i in instructions}
        pc=0;stack=[];locals_={};limit=0
        while True:
            limit+=1;assert limit<10000
            i=lookup[pc];f=i.fields;pc+=len(i.raw);name=i.name
            if name=='argcheck':assert len(args)>=len(f['t'])
            elif name=='alloca':pass
            elif name=='ldc.i':stack.append(f['i'])
            elif name=='ldstr':stack.append(f['s'].rstrip(b'\0').decode(self.encoding))
            elif name=='ld':
                scope=(f['f']>>5)&7
                if scope==3:
                    stack.append(args[-f['o']-2] if f['o']<0 else locals_.get(f['o'],0))
                else:stack.append(self.variables.get(f['h'] if scope==0 else (scope,f['h']),0))
            elif name in ('st.i','st.s'):
                scope=(f['f']>>5)&7
                if scope==3:locals_[f['o']]=stack[-1]
                else:self.variables[f['h'] if scope==0 else (scope,f['h'])]=stack[-1]
            elif name=='pop':stack.pop()
            elif name in ('ceq.i','div.i','add.i','add.s'):
                right,left=stack.pop(),stack.pop()
                stack.append({'ceq.i':lambda:int(left==right),'div.i':lambda:left//right,
                              'add.i':lambda:left+right,'add.s':lambda:left+right}[name]())
            elif name in ('br','brfalse','brtrue'):
                take=True if name=='br' else bool(stack.pop())==(name=='brtrue')
                if take:pc+=f['j']
            elif name in ('syscall','syscallp','call','callp'):
                count=f['a'];assert len(stack)>=count,(name,f,stack)
                params=list(reversed(stack[-count:])) if count else []
                if count:del stack[-count:]
                if name.startswith('call'):value=self.run(f['h'],params)
                else:
                    self.operations.append((f['h'],params))
                    if f['h']==0x6F769889:value=str(params[0])
                    elif f['h']==0x95FF28F2:value='Selected test font'
                    else:value=0
                if name in ('call','syscall'):stack.append(value)
            elif name=='ret':
                assert len(stack)==1,(hashed,pc,stack)
                self.depth-=1
                return stack.pop()
            else:raise AssertionError(name)

    def menu_run(self,hashed,args=()):
        # Reuse the instruction evaluator, substituting the original MENU
        # function with a deterministic choice and retaining its real signature.
        select=0x0A7A489C
        original=self.run
        def dispatch(function,parameters=()):
            if function==select:
                assert self.choices,'Unexpected extra menu'
                self.operations.append((select,list(parameters)))
                return self.choices.popleft()
            return original(function,parameters)
        self.run=dispatch
        return self.run(hashed,args)


def check_vm(functions,hashes,language='zh-CN'):
    menu=MENUS[language]
    for size in [0,-100,999,26,*SIZES]:
        vm=VM(functions,{SIZE:size})
        vm.run(hashes['apply'])
        expected=size if size in SIZES else DEFAULT
        assert vm.variables[SIZE]==expected
        assert vm.variables[0x65615B45]==expected
        assert vm.variables[0x721A4F06]==expected//2
        assert vm.variables[0xBDDD7DA2]==expected+4
        assert vm.variables[0x99EE010B]==expected
        assert vm.variables[0x8E951548]==expected//2
        assert vm.operations[-1]==(0x098399F2,['Noto Sans CJK',expected,expected//2])
    if 'init' in hashes:
        for index,size in enumerate(SIZES):
            vm=VM(functions,encoding=menu['encoding'])
            vm.run(hashes['init'])
            vm.run(hashes['click'],[3100+index,120+100*index,534,88,36])
            assert vm.variables[SIZE]==size
            registrations=[args for h,args in vm.operations if h==0xF8D18340]
            assert len(registrations)==6
            for n,rect in enumerate(registrations):
                ident,x,y,w,h,on,off,click=rect
                assert ident==3100+n and x==120+100*n
                assert (y,w,h)==(534,88,36) and x+w<=800 and y+h<=600
                assert on==hashes['noop'] and off==hashes['noop'] and click==hashes['click']
            text=[args[0] for h,args in vm.operations if h==0x35A89417]
            assert menu['heading']+str(size) in text
            for hashed,args in vm.operations:
                if hashed==0xD01BE374:
                    _,x,y,w,h,_=args
                    assert 0<=x<x+w<=800 and 0<=y<y+h<=600
    else:
        for index,size in enumerate(SIZES):
            vm=VM(functions,{SIZE:32},choices=[1,index+1,3],encoding=menu['encoding'])
            result=vm.menu_run(hashes['selector'],['Noto Sans CJK',0])
            assert result=='Noto Sans CJK' and vm.variables[SIZE]==size
            menus=[args for h,args in vm.operations if h==0x0A7A489C]
            assert len(menus)==3 and len(menus[1])==6
            assert [int(label.split()[0]) for label in menus[1]]==list(SIZES)
            assert str(size) in menus[-1][0]
        vm=VM(functions,{SIZE:36},choices=[2],encoding=menu['encoding'])
        assert vm.menu_run(hashes['selector'],['Noto Sans CJK',0])=='Selected test font'
        vm=VM(functions,{SIZE:36},choices=[-1],encoding=menu['encoding'])
        assert vm.menu_run(hashes['selector'],['Noto Sans CJK',0])=='Noto Sans CJK'
