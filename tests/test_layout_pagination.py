"""Candidate paging behavior with an independent synthetic engine model."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_font_settings import Builder,Script,SIZES
from layout_candidate import (FUNCTIONS,STATE,CON_MODE,IS_HISTORY,PAUSE_INTER,PAGE_WAIT,PAGE_MENU,PAUSE_MENU,HISTORY,CONFIG_MENU,SAVE_POINT,DO_AUTOSAVE,
                              CONSOLE_SET,CURSOR_Y,FONT_HEIGHT,LOCATE_FORCE,
                              CONSOLE_CLEAR,CLIENT_HEIGHT,EVENT_HOOK,EVENT_AFTER,pagination_functions,
                              patch_console_pagination,patch_sensitive_menu_entry)


class EngineModel:
    """Models only relevant event/cursor effects, not Majiro rendering."""
    def __init__(self,size=44,mode=4,history=False):
        self.code=pagination_functions()
        self.variables={(1,CON_MODE):mode}
        self.cursor=[90,490]
        self.origin=[90,490]
        self.glyph=size-4
        self.history=history
        self.pauses=0
        self.clears=0
        self.registrations=[]
        self.menu_calls=[]
        self.on_pause=None
        self.depth=0

    def run(self,function,args=()):
        if function==IS_HISTORY:return int(self.history)
        if function in (HISTORY,CONFIG_MENU):
            self.menu_calls.append(function)
            return 0
        if function==PAGE_WAIT:
            self.pauses+=1
            if self.on_pause:self.on_pause()
            return 0
        self.depth+=1
        assert self.depth<12
        ins=Script.parse(self.code[function]);lookup={i.offset:i for i in ins}
        stack=[];pc=0;steps=0
        while True:
            steps+=1;assert steps<2000
            i=lookup[pc];pc+=len(i.raw);f=i.fields;n=i.name
            if n=='argcheck':assert len(args)>=len(f['t'])
            elif n=='alloca':pass
            elif n=='ldc.i':stack.append(f['i'])
            elif n=='ldstr':stack.append(f['s'].rstrip(b'\0').decode('ascii'))
            elif n=='ld':
                scope=(f['f']>>5)&7
                stack.append(args[-f['o']-2] if scope==3 else self.variables.get((scope,f['h']),0))
            elif n=='st.i':self.variables[((f['f']>>5)&7,f['h'])]=stack[-1]
            elif n=='pop':stack.pop()
            elif n in ('add.i','ceq.i','cgt.i'):
                right,left=stack.pop(),stack.pop()
                stack.append(left+right if n=='add.i' else int(left==right) if n=='ceq.i' else int(left>right))
            elif n in ('br','brtrue','brfalse'):
                take=True if n=='br' else bool(stack.pop())==(n=='brtrue')
                if take:pc+=f['j']
            elif n in ('call','callp','syscall','syscallp'):
                count=f['a'];assert len(stack)>=count
                params=list(reversed(stack[-count:])) if count else []
                if count:del stack[-count:]
                if n.startswith('call'):result=self.run(f['h'],params)
                else:
                    result=0
                    if f['h']==CURSOR_Y:result=self.cursor[1]
                    elif f['h']==FONT_HEIGHT:result=self.glyph
                    elif f['h']==CLIENT_HEIGHT:result=600
                    elif f['h']==LOCATE_FORCE:self.cursor=list(params)
                    elif f['h']==CONSOLE_SET:
                        _,x,y,_,_=params;self.origin=[x,y];self.cursor=[x,y]
                    elif f['h']==CONSOLE_CLEAR:
                        self.clears+=1
                        self.cursor=self.origin.copy()
                        self.run(FUNCTIONS['set'],[123,*self.origin,690,88])
                    elif f['h']==EVENT_AFTER:self.registrations.append(params)
                    else:raise AssertionError(hex(f['h']))
                if n in ('call','syscall'):stack.append(result)
            elif n=='ret':
                assert len(stack)==1
                self.depth-=1
                return stack.pop()
            else:raise AssertionError(n)


def synthetic_console(existing_after=False,external_case=False):
    b=Builder('cp932').prologue().integer(0x1234).text('CRLF').syscall(EVENT_HOOK,2)
    if existing_after:b.integer(0x5678).text('CONSOLE_WROTE').syscall(EVENT_AFTER,2)
    for value in [88,690,490,90,123]:b.integer(value)
    b.syscall(CONSOLE_SET,5).ret()
    first=b.finish()
    p=(Builder().prologue().text('checkpoint').syscall(SAVE_POINT,1)
       .branch('br','end').call(DO_AUTOSAVE).call(HISTORY).call(CONFIG_MENU))
    if external_case:p.integer(0).op('br.case',0).integer(-2).branch('bne.case','end')
    pause=p.call(PAUSE_MENU,result=True).op('pop').call(PAUSE_MENU).label('end').ret().finish()
    menu=Builder().prologue().call(HISTORY).call(CONFIG_MENU).ret().finish()
    code=first+pause+menu
    return (struct.pack('<16sIII',b'MajiroObjV1.000\0',0,1,3)
            +struct.pack('<II',0x1234,0)+struct.pack('<II',PAUSE_INTER,len(first))
            +struct.pack('<II',PAUSE_MENU,len(first)+len(pause))
            +struct.pack('<I',len(code))+code)


class PaginationTests(unittest.TestCase):
    def configured(self,size=44,mode=4,history=False):
        vm=EngineModel(size,mode,history)
        vm.run(FUNCTIONS['set'],[123,90,490,690,88])
        return vm

    def test_all_six_sizes_wait_only_when_next_glyph_exceeds_bottom(self):
        for size in SIZES:
            for excess in (0,1):
                with self.subTest(size=size,excess=excess):
                    vm=self.configured(size)
                    vm.cursor[1]=578-vm.glyph+excess
                    vm.run(FUNCTIONS['wrote'],[123,90,490,200,vm.glyph,0])
                    self.assertEqual((vm.pauses,vm.clears),(excess,excess))

    def test_manual_break_reuses_last_row_without_waiting_twice(self):
        vm=self.configured()
        vm.run(FUNCTIONS['wrote'],[123,90,534,400,40,0])
        vm.cursor=[90,578]
        vm.run(FUNCTIONS['crlf'])
        vm.run(FUNCTIONS['crlf'])
        self.assertEqual((vm.pauses,vm.clears),(1,1))
        self.assertEqual(vm.cursor,[90,490])

    def test_history_and_empty_pages_do_not_pause(self):
        for mode,history,valid in [(4,True,True),(6,True,True),(4,False,False)]:
            vm=self.configured(mode=mode,history=history)
            vm.variables[(1,STATE['last_valid'])]=int(valid)
            vm.cursor[1]=1000
            vm.run(FUNCTIONS['crlf'])
            self.assertEqual((vm.pauses,vm.clears),(0,0))

    def test_modes_use_captured_rectangles_including_onetwo_narration(self):
        for mode,height,size in [(0,105,44),(4,88,44),(6,220,44),(8,166,36),(99,517,32)]:
            with self.subTest(mode=mode,height=height,size=size):
                vm=EngineModel(size,mode)
                vm.run(FUNCTIONS['set'],[123,180,356,560,height])
                vm.cursor[1]=min(356+height,600)-vm.glyph
                vm.run(FUNCTIONS['wrote'],[123,180,356,100,vm.glyph,0])
                self.assertEqual(vm.pauses,0)
                vm.cursor[1]+=1
                vm.run(FUNCTIONS['crlf'])
                self.assertEqual((vm.pauses,vm.clears),(1,1))

    def test_stock_rectangle_below_canvas_uses_visible_boundary(self):
        vm=EngineModel()
        vm.run(FUNCTIONS['set'],[123,90,519,690,88])
        self.assertEqual(vm.variables[(1,STATE['bottom'])],600)
        vm.cursor[1]=563  # Second 40px glyph box would end at 603.
        vm.run(FUNCTIONS['wrote'],[123,90,519,400,40,0])
        self.assertEqual((vm.pauses,vm.clears),(1,1))

    def test_pause_reentry_cannot_recurse_or_replace_last_row(self):
        vm=self.configured()
        vm.cursor[1]=578
        vm.on_pause=lambda:vm.run(FUNCTIONS['wrote'],[999,0,900,50,40,0])
        vm.run(FUNCTIONS['wrote'],[123,90,534,400,40,0])
        self.assertEqual((vm.pauses,vm.clears),(1,1))
        self.assertEqual(vm.variables[(1,STATE['last_y'])],534)
        self.assertEqual(vm.variables[(1,STATE['busy'])],0)

    def test_registration_adds_after_handlers_and_set_preserves_argument_order(self):
        vm=EngineModel()
        vm.run(FUNCTIONS['register'])
        self.assertEqual([r[0] for r in vm.registrations],['CONSOLE_WROTE','CRLF'])
        vm.run(FUNCTIONS['set'],[7,20,80,560,220])
        self.assertEqual(vm.origin,[20,80])
        self.assertEqual(vm.variables[(1,STATE['bottom'])],300)

    def test_patch_preserves_original_addresses_and_rejects_reapplication(self):
        source=synthetic_console();before=Script(source)
        patched,report=patch_console_pagination(source);after=Script(patched)
        self.assertEqual(before.functions,after.functions[:len(before.functions)])
        self.assertTrue({i.offset for i in before.ins}<={i.offset for i in after.ins})
        self.assertIn('current bounds',report['enabled_console_modes'])
        self.assertEqual(after.finish(),patched)
        with self.assertRaises(AssertionError):patch_console_pagination(patched)

    def test_existing_after_handler_is_not_overwritten(self):
        with self.assertRaisesRegex(AssertionError,'Existing after handler'):
            patch_console_pagination(synthetic_console(existing_after=True))

    def test_cross_callback_menu_guard_allows_only_natural_wait(self):
        source=synthetic_console()
        # Reuse a zero-argument synthetic function as the public entry.
        original=Script(source);original.functions=[(HISTORY if h==PAUSE_MENU else h,o) for h,o in original.functions]
        guarded,report=patch_sensitive_menu_entry(original.finish(),HISTORY)
        s=Script(guarded);start=dict(s.functions)[HISTORY]
        vm=EngineModel();vm.code[HISTORY]=bytes(s.code[start:])
        body=report['body'];vm.code[body]=Builder().prologue().integer(37).op('ret').finish()
        # Bypass only the model's normal original-HISTORY shortcut.
        wrapper=0x12345678;vm.code[wrapper]=vm.code[HISTORY]
        for busy in (1,0):
            vm.variables[(1,STATE['busy'])]=busy
            self.assertEqual(vm.run(wrapper),0 if busy else 37)
        self.assertEqual(s.code[:len(original.code)],original.code)

    def test_cloned_wait_removes_checkpoints_without_moving_branches(self):
        source=synthetic_console();before=Script(source)
        patched,report=patch_console_pagination(source);after=Script(patched)
        original_start=dict(before.functions)[PAUSE_INTER]
        original_end=dict(before.functions)[PAUSE_MENU]
        for original_ins in Script.parse(before.code[original_start:original_end]):
            if original_ins.fields.get('h') in (HISTORY,CONFIG_MENU):continue
            at=original_start+original_ins.offset
            self.assertEqual(after.code[at:at+len(original_ins.raw)],original_ins.raw)
        start=dict(after.functions)[PAGE_WAIT]
        clone=Script.parse(after.code[start:start+original_end-original_start])
        original=Script.parse(before.code[original_start:original_end])
        for ins in original:
            if 'j' in ins.fields:
                same=next(i for i in clone if i.offset==ins.offset)
                self.assertEqual(same.raw,ins.raw)
        self.assertFalse(any(i.fields.get('h') in (SAVE_POINT,DO_AUTOSAVE,HISTORY,CONFIG_MENU,PAUSE_MENU) for i in clone))
        self.assertTrue(any(i.name=='call' and i.fields.get('h')==PAGE_MENU for i in clone))
        self.assertEqual(len(report['cloned_wait_removed_calls']),6)
        menu_start=dict(after.functions)[PAGE_MENU]
        self.assertFalse(any(i.fields.get('h') in (HISTORY,CONFIG_MENU)
                             for i in Script.parse(after.code[menu_start:])))
        source_instructions={i.offset:i for i in before.ins}
        target_instructions={i.offset:i for i in after.ins}
        for new,old in report['translation_source_aliases'].items():
            self.assertEqual(target_instructions[new].name,'ldstr')
            self.assertEqual(target_instructions[new].raw,source_instructions[old].raw)

    def test_external_onetwo_menu_never_calls_missing_local_clone(self):
        s=Script(synthetic_console(external_case=True))
        menu_start=dict(s.functions)[PAUSE_MENU]
        functions=[(h,o) for h,o in s.functions if h!=PAUSE_MENU]
        code=bytes(s.code[:menu_start])
        source=(struct.pack('<16sIII',s.signature,s.main,s.lines,len(functions))
                +b''.join(struct.pack('<II',h,o) for h,o in functions)
                +struct.pack('<I',len(code))+code)
        patched,_=patch_console_pagination(source);after=Script(patched)
        self.assertNotIn(PAGE_MENU,dict(after.functions))
        start=dict(after.functions)[PAGE_WAIT]
        clone=Script.parse(after.code[start:])
        self.assertFalse(any(i.fields.get('h')==PAGE_MENU for i in clone))
        self.assertTrue(any(i.name=='ldc.i' and i.fields['i']==0x7FFFFFFF for i in clone))
        pause_start=dict(s.functions)[PAUSE_INTER]
        for i in s.ins:
            if pause_start<=i.offset<menu_start and i.fields.get('h')==PAUSE_MENU:
                at=start+i.offset-pause_start
                replacement=Script.parse(after.code[at:at+12])
                self.assertEqual([j.name for j in replacement],
                                 ['ldc.i','br'] if i.name=='call' else ['br','br'])


if __name__=='__main__':unittest.main()
