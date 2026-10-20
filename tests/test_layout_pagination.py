"""Candidate paging behavior with an independent synthetic engine model."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_font_settings import Builder,Script,SIZES,emit
from layout_candidate import (FUNCTIONS,STATE,CON_MODE,IS_HISTORY,PAUSE_INTER,PAGE_WAIT,PAGE_MENU,PAUSE_MENU,HISTORY,CONFIG_MENU,SAVE_POINT,DO_AUTOSAVE,
                              CONSOLE_SET,CURSOR_Y,FONT_HEIGHT,LOCATE_FORCE,
                              CONSOLE_CLEAR,CLIENT_HEIGHT,EVENT_HOOK,EVENT_AFTER,pagination_functions,
                              patch_console_pagination,patch_sensitive_menu_entry,
                              clone_page_wait,IS_AUTO_MODE,_auto_history_cases,
                              HISTBUFF_DISABLE,HISTBUFF_ENABLE,CONSOLE_REDRAW,HOT_RESET)

MK_READ=0x892E9B20
VOICE_STAT=0xD0C1FAEB  # Synthetic boundary; the model does not emulate native audio.
WAIT=0xCF35F0E3
IS_FAST_MODE=0xA62AA5EB
SET_AUTO_MODE=0xFAC4F361
RESET_FAST_MODE=0x818A4B92
VOICE_END=0x12340001
MANUAL_WAIT=0x12340002
CS=0x12340003
REMAINING=0x12340004


def auto_input_cases(builder,count=2):
    """Structural auto region for the existing geometry-only fixture."""
    builder.syscall(IS_AUTO_MODE,0,result=True).op('pop')
    for n in range(count):
        builder.integer(0).op('br.case',0).integer(8).branch('bne.case','auto_case_'+str(n))
        builder.label('auto_case_'+str(n))
    return builder.syscall(IS_AUTO_MODE,0,result=True).op('pop')


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
        self.on_redraw=None
        self.history_depth=0
        self.recorded_controls=[]
        self.replaying=False
        self.visible=''
        self.depth=0

    def run(self,function,args=()):
        execution=self.execute(function,args)
        while True:
            try:next(execution)
            except StopIteration as result:return result.value

    def execute(self,function,args=()):
        """Retain call frames/locals across a simulated native redraw yield."""
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
        stack=[];locals_=[];args=list(args);pc=0;steps=0
        while True:
            steps+=1;assert steps<2000
            i=lookup[pc];pc+=len(i.raw);f=i.fields;n=i.name
            if n=='argcheck':assert len(args)>=len(f['t'])
            elif n=='alloca':
                assert all(t==0 for t in f['t'])
                locals_=[0]*len(f['t'])
            elif n=='ldc.i':stack.append(f['i'])
            elif n=='ldstr':stack.append(f['s'].rstrip(b'\0').decode('ascii'))
            elif n=='ld':
                scope=(f['f']>>5)&7
                stack.append((args[-f['o']-2] if f['o']<0 else locals_[f['o']])
                             if scope==3 else self.variables.get((scope,f['h']),0))
            elif n=='st.i':
                scope=(f['f']>>5)&7
                if scope==3:
                    if f['o']<0:args[-f['o']-2]=stack[-1]
                    else:locals_[f['o']]=stack[-1]
                else:self.variables[(scope,f['h'])]=stack[-1]
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
                if n.startswith('call'):result=yield from self.execute(f['h'],params)
                else:
                    result=0
                    if f['h']==CURSOR_Y:result=self.cursor[1]
                    elif f['h']==FONT_HEIGHT:result=self.glyph
                    elif f['h']==CLIENT_HEIGHT:result=600
                    elif f['h']==LOCATE_FORCE:self.cursor=list(params)
                    elif f['h']==CONSOLE_SET:
                        _,x,y,_,_=params;self.origin=[x,y];self.cursor=[x,y]
                    elif f['h']==CONSOLE_CLEAR:
                        # Native console_cls ignores its w during replay. The
                        # history counter controls recording, not drawing.
                        if not self.replaying:
                            if not self.history_depth:self.recorded_controls.append('w')
                            self.visible=''
                            self.clears+=1
                            self.cursor=self.origin.copy()
                            self.run(FUNCTIONS['set'],[123,*self.origin,690,88])
                    elif f['h']==HISTBUFF_DISABLE:self.history_depth+=1
                    elif f['h']==HISTBUFF_ENABLE:self.history_depth-=1
                    elif f['h']==CONSOLE_REDRAW:
                        if self.on_redraw:yield from self.on_redraw(params)
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
    b.syscall(CONSOLE_SET,5)
    first=b.integer(0).syscall(CONSOLE_REDRAW,1).ret().finish()
    hot=(Builder().prologue(3).syscall(HISTBUFF_DISABLE,0).integer(-1)
         .syscall(CONSOLE_REDRAW,1).syscall(HISTBUFF_ENABLE,0).ret().finish())
    p=(Builder().prologue().text('checkpoint').syscall(SAVE_POINT,1)
       .branch('br','end'))
    auto_input_cases(p)
    p.call(DO_AUTOSAVE).call(HISTORY).call(CONFIG_MENU)
    if external_case:p.integer(0).op('br.case',0).integer(-2).branch('bne.case','end')
    pause=p.call(PAUSE_MENU,result=True).op('pop').call(PAUSE_MENU).label('end').ret().finish()
    menu=Builder().prologue().call(HISTORY).call(CONFIG_MENU).ret().finish()
    code=first+hot+pause+menu
    return (struct.pack('<16sIII',b'MajiroObjV1.000\0',0,1,4)
            +struct.pack('<II',0x1234,0)+struct.pack('<II',HOT_RESET,len(first))
            +struct.pack('<II',PAUSE_INTER,len(first)+len(hot))
            +struct.pack('<II',PAUSE_MENU,len(first)+len(hot)+len(pause))
            +struct.pack('<I',len(code))+code)


def synthetic_timed_wait():
    """Two polled auto loops and common history/cancel exit, like stock waits."""
    b=Builder('cp932').prologue().text('checkpoint').syscall(SAVE_POINT,1).call(DO_AUTOSAVE)
    b.syscall(IS_AUTO_MODE,0,result=True).branch('brfalse','normal')
    b.integer(0).store(CS,scope=3)
    b.syscall(VOICE_STAT,0,result=True).branch('brfalse','timer_start')
    b.label('voice_loop').syscall(VOICE_STAT,0,result=True).branch('brfalse','voice_done')
    for phase in ('voice','timer'):
        if phase=='timer':
            b.label('voice_done').call(VOICE_END).label('timer_start')
            b.integer(150).store(REMAINING,scope=3)
            b.label('timer_loop').load(REMAINING,scope=3).integer(0).op('cgt.i').branch('brfalse','finish')
        b.syscall(MK_READ,0,result=True).op('br.case',0)
        b.integer(8).branch('bne.case',phase+'_cancel').integer(1).store(CS,scope=3)
        if phase=='voice':b.call(VOICE_END)
        b.branch('br','finish').label(phase+'_cancel')
        b.integer(16).branch('bne.case',phase+'_tick').integer(2).store(CS,scope=3)
        if phase=='voice':b.call(VOICE_END)
        b.branch('br','finish').label(phase+'_tick').integer(50).syscall(WAIT,1)
        if phase=='timer':b.load(REMAINING,scope=3).integer(50).op('sub.i').store(REMAINING,scope=3)
        b.branch('br',phase+'_loop')
    b.label('finish').load(CS,scope=3).integer(1).op('ceq.i').branch('brfalse','cancel_check')
    b.call(HISTORY).syscall(SET_AUTO_MODE,0)
    b.label('cancel_check').load(CS,scope=3).integer(2).op('ceq.i').branch('brfalse','auto_check')
    b.syscall(RESET_FAST_MODE,0)
    b.label('auto_check').syscall(IS_AUTO_MODE,0,result=True).branch('brfalse','normal').ret()
    b.label('normal').syscall(IS_FAST_MODE,0,result=True).branch('brfalse','manual')
    b.integer(0).syscall(WAIT,1).ret().label('manual').call(MANUAL_WAIT).ret()
    return b.finish()


def script_with_wait(code):
    return Script(struct.pack('<16sIII',b'MajiroObjV1.000\0',0,1,1)
                  +struct.pack('<II',PAUSE_INTER,0)+struct.pack('<I',len(code))+code)


class TimedWaitModel:
    """Executes test bytecode/branches; not native scheduling or rendering."""
    def __init__(self,auto=True,fast=False,voice_ticks=0,inputs=None):
        self.auto=auto;self.fast=fast;self.voice_ticks=voice_ticks
        self.inputs={name:iter(values) for name,values in (inputs or {}).items()}
        self.phase='timer';self.elapsed=0;self.waits=[];self.history=0;self.manual=0;self.voice_end=0

    def run(self,code):
        lookup={i.offset:i for i in Script.parse(code)}
        stack=[];variables={};pc=0;selector=None
        for _ in range(2000):
            i=lookup[pc];pc+=len(i.raw);n=i.name;f=i.fields
            if n in ('argcheck','alloca'):pass
            elif n=='ldc.i':stack.append(f['i'])
            elif n=='ldstr':stack.append(f['s'])
            elif n=='ld':stack.append(variables.get(f['h'],0))
            elif n=='st.i':variables[f['h']]=stack[-1]
            elif n=='pop':stack.pop()
            elif n in ('sub.i','cgt.i','ceq.i'):
                right,left=stack.pop(),stack.pop()
                stack.append(left-right if n=='sub.i' else int(left>right) if n=='cgt.i' else int(left==right))
            elif n=='br.case':selector=stack.pop();pc+=f['j']
            elif n=='bne.case':
                if selector!=stack.pop():pc+=f['j']
            elif n in ('br','brfalse','brtrue'):
                if n=='br' or bool(stack.pop())==(n=='brtrue'):pc+=f['j']
            elif n in ('call','callp','syscall','syscallp'):
                args=[stack.pop() for _ in range(f['a'])];h=f['h'];result=0
                if h==IS_AUTO_MODE:result=int(self.auto)
                elif h==IS_FAST_MODE:result=int(self.fast)
                elif h==VOICE_STAT:
                    result=int(self.voice_ticks>0);self.phase='voice' if result else 'timer'
                elif h==MK_READ:result=next(self.inputs.get(self.phase,iter(())),0)
                elif h==WAIT:
                    self.waits.append(args[0]);self.elapsed+=args[0]
                    if self.phase=='voice':self.voice_ticks=max(0,self.voice_ticks-1)
                elif h==SET_AUTO_MODE:self.auto=True
                elif h==RESET_FAST_MODE:self.auto=self.fast=False
                elif h==HISTORY:self.history+=1
                elif h==MANUAL_WAIT:self.manual+=1
                elif h==VOICE_END:self.voice_end+=1
                elif h not in (SAVE_POINT,DO_AUTOSAVE):raise AssertionError(hex(h))
                if n in ('call','syscall'):stack.append(result)
            elif n=='ret':
                result=stack.pop();assert not stack;return result
            else:raise AssertionError(n)
        raise AssertionError('wait bytecode did not terminate')


class PaginationTests(unittest.TestCase):
    def test_page_clear_preserves_nested_history_recording_depth(self):
        for depth in (0,1,3):
            with self.subTest(depth=depth):
                vm=self.configured();vm.history_depth=depth;vm.visible='FULL'
                vm.cursor[1]=1000
                vm.run(FUNCTIONS['wrote'],[123,90,534,400,40,0])
                self.assertEqual((vm.pauses,vm.clears,vm.visible),(1,1,''))
                self.assertEqual(vm.history_depth,depth)
                self.assertEqual(vm.recorded_controls,[])

    def test_inserted_clear_does_not_erase_the_saved_text_on_replay(self):
        # The engine records the whole text operand before its render callbacks.
        # Replaying a subsequent recorded w therefore erases the entire operand,
        # rather than reproducing a page boundary inside it. This tiny cache
        # interpreter deliberately does not emulate font layout or input.
        def replay(controls):
            visible='TAIL'  # Native overflow leaves the last visible text.
            for control in controls+['p']:
                if control=='w':visible=''
                elif control=='p':return visible
                else:raise AssertionError(control)
        original=pagination_functions()[FUNCTIONS['page']]
        legacy=bytearray(original)
        for i in Script.parse(original):
            if i.fields.get('h') in (HISTBUFF_DISABLE,HISTBUFF_ENABLE):
                legacy[i.offset:i.offset+8]=emit('ldc.i',0)+emit('pop')
        results=[]
        for code in (legacy,original):
            vm=self.configured();vm.code[FUNCTIONS['page']]=code;vm.cursor[1]=1000
            vm.run(FUNCTIONS['wrote'],[123,90,534,400,40,0])
            results.append(replay(vm.recorded_controls))
            self.assertEqual(vm.clears,1)
        self.assertEqual(results,['','TAIL'])

    def patched_model(self):
        patched,report=patch_console_pagination(synthetic_console())
        script=Script(patched);vm=self.configured()
        # Suffixes preserve relative branches into appended trampolines and back.
        vm.code.update({h:bytes(script.code[o:]) for h,o in script.functions})
        return vm,script,report

    def test_snapshot_redraw_yields_with_page_callbacks_suppressed(self):
        for old_busy in (0,7):
            with self.subTest(old_busy=old_busy):
                vm,script,report=self.patched_model()
                vm.run(FUNCTIONS['wrote'],[123,90,490,100,40,0])
                vm.variables[(1,STATE['busy'])]=old_busy
                def redraw(args):
                    self.assertEqual(args,[-1])
                    # Each native continuation can dispatch render callbacks.
                    # The wrapper frame/local must survive all these yields.
                    for phase in ('text','wrap','paragraph'):
                        vm.cursor[1]=1000
                        vm.run(FUNCTIONS['wrote'],[123,90,534,400,40,1])
                        vm.run(FUNCTIONS['crlf'])
                        yield phase
                vm.on_redraw=redraw
                execution=vm.execute(HOT_RESET,[0,0,1])
                for phase in ('text','wrap','paragraph'):
                    self.assertEqual(next(execution),phase)
                    self.assertEqual(vm.variables[(1,STATE['busy'])],1)
                    self.assertEqual((vm.pauses,vm.clears,vm.history_depth),(0,0,1))
                with self.assertRaises(StopIteration):next(execution)
                self.assertEqual(vm.variables[(1,STATE['busy'])],old_busy)
                self.assertEqual(vm.history_depth,0)
                vm.run(FUNCTIONS['crlf'])
                self.assertEqual(vm.pauses,0 if old_busy else 1)
                start=dict(script.functions)[FUNCTIONS['redraw']]
                native=next(i for i in script.ins if i.offset>=start and
                            i.name=='syscallp' and i.fields['h']==CONSOLE_REDRAW)
                self.assertEqual(len(native.raw),8) # Native PC-8 re-enters itself.

    def test_redraw_saved_busy_uses_a_frame_local_across_nested_calls(self):
        vm,_,_=self.patched_model()
        def redraw(args):
            vm.on_redraw=None
            vm.run(FUNCTIONS['redraw'],args)
            self.assertEqual(vm.variables[(1,STATE['busy'])],1)
            yield 'nested complete'
        vm.on_redraw=redraw
        execution=vm.execute(FUNCTIONS['redraw'],[-1])
        self.assertEqual(next(execution),'nested complete')
        with self.assertRaises(StopIteration):next(execution)
        self.assertEqual(vm.variables[(1,STATE['busy'])],0)

    def test_only_hot_reset_redraw_is_wrapped_and_unknown_shapes_fail(self):
        source=synthetic_console();before=Script(source)
        patched,report=patch_console_pagination(source);after=Script(patched)
        hot=dict(before.functions)[HOT_RESET]
        redraws=[i for i in before.ins if i.fields.get('h')==CONSOLE_REDRAW]
        self.assertEqual(len(redraws),2)
        site=report['snapshot_replay_guard']['redraw_offset']
        for i in redraws:
            if i.offset!=site:self.assertEqual(after.code[i.offset:i.offset+8],i.raw)
        self.assertGreaterEqual(site,hot)
        self.assertEqual(before.functions,after.functions[:len(before.functions)])
        self.assertGreater(report['snapshot_replay_guard']['trampoline_offset'],dict(after.functions)[PAGE_MENU])
        for h in (PAUSE_INTER,PAUSE_MENU):
            a=dict(before.functions)[h]
            b=min([o for _,o in before.functions if o>a]+[len(before.code)])
            self.assertEqual(before.code[a:b],after.code[a:b])
        for mutation,message in [('missing','one original hot_reset'),('argc','redraw signature'),
                                 ('result','redraw signature'),('index','redraw index'),
                                 ('duplicate','one hot_reset snapshot'),('history','history recording')]:
            with self.subTest(mutation=mutation):
                s=Script(source)
                i=next(i for i in s.ins if i.offset==site)
                if mutation=='missing':s.functions=[(0x98765432 if h==HOT_RESET else h,o) for h,o in s.functions]
                elif mutation in ('argc','result'):
                    s.code[site:site+8]=emit('syscall' if mutation=='result' else 'syscallp',CONSOLE_REDRAW,0 if mutation=='argc' else 1)
                elif mutation=='index':s.code[site-6:site]=emit('ldc.i',0)
                else:
                    target=next(i for i in s.ins if i.fields.get('h')==HISTBUFF_ENABLE)
                    s.code[target.offset:target.offset+8]=emit('syscallp',CONSOLE_REDRAW,1) if mutation=='duplicate' else emit('syscallp',HISTBUFF_ENABLE,1)
                with self.assertRaisesRegex(AssertionError,message):patch_console_pagination(s.finish())

    def test_auto_history_input_retains_both_voice_and_timer_waits(self):
        original=synthetic_timed_wait();script=script_with_wait(original)
        fixed,_=clone_page_wait(script)
        # Reconstruct the previous released clone, whose history call was
        # removed but whose input case still exited the timer immediately.
        legacy=bytearray(fixed)
        for case in _auto_history_cases(script.ins):
            legacy[case.offset:case.offset+len(case.raw)]=case.raw
        for phase,voice_ticks,expected_ms in [('timer',0,150),('voice',3,300)]:
            with self.subTest(phase=phase):
                old=TimedWaitModel(voice_ticks=voice_ticks,inputs={phase:[8]})
                old.run(legacy)
                self.assertEqual((old.elapsed,old.history,old.manual),(0,0,0))
                new=TimedWaitModel(voice_ticks=voice_ticks,inputs={phase:[8]})
                new.run(fixed)
                baseline=TimedWaitModel(voice_ticks=voice_ticks)
                baseline.run(original)
                self.assertEqual(new.elapsed,expected_ms)
                self.assertEqual((new.waits,new.voice_end,new.auto),
                                 (baseline.waits,baseline.voice_end,baseline.auto))
                self.assertEqual((new.history,new.manual),(0,0))
        self.assertEqual(bytes(script.code),original)

    def test_auto_cancel_and_fast_return_still_follow_native_paths(self):
        original=synthetic_timed_wait();fixed,_=clone_page_wait(script_with_wait(original))
        for phase,ticks in [('timer',0),('voice',3)]:
            states=[]
            for code in (original,fixed):
                vm=TimedWaitModel(voice_ticks=ticks,inputs={phase:[16]});vm.run(code)
                states.append((vm.elapsed,vm.manual,vm.auto,vm.voice_end,vm.history))
            self.assertEqual(states[0],states[1])
            self.assertEqual(states[1][:3],(0,1,False))
        for code in (original,fixed):
            vm=TimedWaitModel(auto=False,fast=True);vm.run(code)
            self.assertEqual((vm.waits,vm.elapsed,vm.manual),([0],0,0))

    def test_auto_history_change_is_only_two_equal_length_case_operands(self):
        original=synthetic_timed_wait();s=script_with_wait(original)
        fixed,_=clone_page_wait(s);cases=_auto_history_cases(s.ins)
        # Every branch and instruction address survives, including timer,
        # voice, cancellation and fast paths outside the two comparisons.
        before={i.offset:i for i in s.ins};after={i.offset:i for i in Script.parse(fixed)}
        self.assertTrue(before.keys()<=after.keys())
        for offset,i in before.items():
            if 'j' in i.fields:self.assertEqual(i.raw,after[offset].raw)
        self.assertEqual([after[i.offset].fields['i'] for i in cases],[0x7fffffff]*2)
        # The same body cloned as PAGE_MENU must not receive this rule.
        s.functions=[(PAUSE_MENU,0)]
        menu,_=clone_page_wait(s,PAUSE_MENU)
        self.assertEqual([i.fields['i'] for i in _auto_history_cases(Script.parse(menu))],[8,8])

    def test_unknown_auto_wait_shapes_are_rejected(self):
        for count in (0,1,3):
            with self.subTest(count=count):
                code=auto_input_cases(Builder().prologue(),count).ret().finish()
                with self.assertRaisesRegex(AssertionError,'two automatic history'):
                    _auto_history_cases(Script.parse(code))
        s=script_with_wait(synthetic_timed_wait())
        case=_auto_history_cases(s.ins)[0]
        s.code[case.offset:case.offset+len(case.raw)]=emit('ldc.i',9)
        malformed=script_with_wait(s.code)
        with self.assertRaisesRegex(AssertionError,'two automatic history'):
            clone_page_wait(malformed)

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
