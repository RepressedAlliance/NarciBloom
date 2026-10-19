"""Experimental page guard: retain story text, stage geometry and font size.

This source-only candidate needs game QA before becoming a support claim.
It preserves original CONSOLE_WROTE animation and adds after-event handlers.
The engine advances its cursor before CRLF and automatic-wrap WROTE events;
its next drawing pass otherwise clears an overflowing text rectangle.
"""
from build_font_settings import Builder, Script, emit, hash32

CONSOLE_SET = 0x403960F8       # (page, x, y, width, height)
CONSOLE_CLEAR = 0xB5A1E3C9     # () immediate native clear, retaining pending text
CURSOR_Y = 0x934D927B         # () -> current absolute console y
FONT_HEIGHT = 0x82FD765B      # () -> active console font height parameter
CLIENT_HEIGHT = 0x8C283F7F    # () -> logical game canvas height
LOCATE_FORCE = 0xF1F8A206     # (x, y), no redraw
EVENT_HOOK = 0x078A756E       # (event name, function hash)
EVENT_AFTER = 0x1295BBDA
PAUSE_INTER = 0x1FD318C6      # Existing input/auto/skip wait; does not send VOICE_END
PAGE_WAIT = hash32('$cdx_page_wait@NARCI_LAYOUT')
PAGE_MENU = hash32('$cdx_page_menu@NARCI_LAYOUT')
PAUSE_MENU = hash32('$pause_menu@CONSOLE')
HISTORY = hash32('$history@HISTORY')
CONFIG_MENU = hash32('$config_menu@CONFIG')
SAVE_POINT = 0xF8004993
DO_AUTOSAVE = hash32('$do_autosave@LOADSAVE')
IS_HISTORY = hash32('$is_history@HISTORY')
CON_MODE = hash32('@con_mode@CONSOLE')

STATE = {name:hash32('@cdx_page_'+name+'@NARCI_LAYOUT')
         for name in ('bottom','busy','last_x','last_y','last_valid')}
FUNCTIONS = {name:hash32('$cdx_page_'+name+'@NARCI_LAYOUT')
             for name in ('set','page','wrote','crlf','register')}
ARGUMENTS = {-2:hash32('_page@'),-3:hash32('_x@'),-4:hash32('_y@'),
             -5:hash32('_xl@'),-6:hash32('_yl@')}


def _load(builder,name):
    return builder.load(STATE[name],scope=1)


def _store(builder,name):
    return builder.store(STATE[name],scope=1)


def _signed(value):
    return value if value <= 0x7FFFFFFF else value-0x100000000


def pagination_functions():
    """Return appended functions using the active console rectangle and font."""
    # Majiro argument slots: page=-2, x=-3, y=-4, width=-5, height=-6.
    b=Builder('cp932').prologue(5)
    b.load(ARGUMENTS[-4],scope=3,slot=-4).load(ARGUMENTS[-6],scope=3,slot=-6).op('add.i')
    _store(b,'bottom')
    # Some stock reduced-font modes end at y=607 on a 600px canvas. Use the
    # visible boundary as well, without altering their rectangles or artwork.
    _load(b,'bottom').syscall(CLIENT_HEIGHT,0,result=True).op('cgt.i').branch('brfalse','bounded')
    b.syscall(CLIENT_HEIGHT,0,result=True);_store(b,'bottom')
    b.label('bounded')
    b.integer(0);_store(b,'last_valid')
    for slot in (-6,-5,-4,-3,-2): b.load(ARGUMENTS[slot],scope=3,slot=slot)
    b.syscall(CONSOLE_SET,5)
    set_code=b.ret().finish()

    b=Builder('cp932').prologue()
    _load(b,'busy').branch('brtrue','done')
    b.call(IS_HISTORY,result=True).branch('brtrue','done')
    _load(b,'last_valid').branch('brfalse','done')
    b.syscall(CURSOR_Y,0,result=True).syscall(FONT_HEIGHT,0,result=True).op('add.i')
    _load(b,'bottom').op('cgt.i').branch('brfalse','done')
    b.integer(1);_store(b,'busy')
    # WROTE reports the row just rendered even when the native cursor has
    # advanced outside the rectangle. Place the existing wait marker there.
    _load(b,'last_y');_load(b,'last_x');b.syscall(LOCATE_FORCE,2)
    b.call(PAGE_WAIT)
    # The MJO ctrl-w opcode is queued while native text is pending. This syscall
    # directly enters the native w handler instead, so reset precedes continuation.
    b.syscall(CONSOLE_CLEAR,0)
    b.integer(0);_store(b,'busy')
    b.label('done')
    page_code=b.ret().finish()

    b=Builder('cp932').prologue(6)
    _load(b,'busy').branch('brtrue','done')
    b.call(IS_HISTORY,result=True).branch('brtrue','done')
    # WROTE: page, x, y, width, height, zerotime.
    b.load(ARGUMENTS[-3],scope=3,slot=-3).load(ARGUMENTS[-5],scope=3,slot=-5).op('add.i');_store(b,'last_x')
    b.load(ARGUMENTS[-4],scope=3,slot=-4);_store(b,'last_y')
    b.integer(1);_store(b,'last_valid')
    b.call(FUNCTIONS['page']).label('done')
    wrote_code=b.ret().finish()

    crlf_code=Builder('cp932').prologue().call(FUNCTIONS['page']).ret().finish()
    b=Builder('cp932').prologue()
    b.integer(0);_store(b,'busy')
    for event,handler in [('CONSOLE_WROTE','wrote'),('CRLF','crlf')]:
        b.integer(_signed(FUNCTIONS[handler])).text(event).syscall(EVENT_AFTER,2)
    register_code=b.ret().finish()
    output={FUNCTIONS[name]:code for name,code in (
        ('set',set_code),('page',page_code),('wrote',wrote_code),
        ('crlf',crlf_code),('register',register_code))}
    return output


def clone_page_wait(script,function=PAUSE_INTER):
    """Retain native input behavior without changing the natural save point.

    Equal-length replacements preserve all relative branches and switch tables.
    The original pause retains its checkpoint and autosave. Manual saves at
    an inserted wait therefore use the preceding native paragraph checkpoint.
    """
    start=dict(script.functions)[function]
    end=min([o for _,o in script.functions if o>start]+[len(script.code)])
    code=bytearray(script.code[start:end])
    removed=[]
    for index,ins in enumerate(script.ins):
        if not start<=ins.offset<end:continue
        if ins.name=='syscallp' and ins.fields.get('h')==SAVE_POINT:
            assert ins.fields['a']==1 and len(ins.raw)==8, 'Unknown save_point signature'
            replacement=emit('pop')+emit('br',0)
        elif ins.name=='callp' and ins.fields.get('h')==DO_AUTOSAVE:
            assert ins.fields['a']==0 and len(ins.raw)==12, 'Unknown autosave signature'
            replacement=emit('br',0)*2
        elif ins.name=='callp' and ins.fields.get('h') in (HISTORY,CONFIG_MENU):
            # Both redraw the console and replace the native pending text.
            # Natural paragraph waits retain their original menus unchanged.
            assert ins.fields['a']==0 and len(ins.raw)==12, 'Unknown redraw menu signature'
            replacement=emit('br',0)*2
        elif ins.name in ('call','callp') and ins.fields.get('h')==PAUSE_MENU:
            assert ins.fields['a']==0 and len(ins.raw)==12, 'Unknown pause menu signature'
            if PAUSE_MENU in dict(script.functions):
                replacement=emit(ins.name,PAGE_MENU,0,0)
            else:
                # 1+2 loads its pause menu from a separate MJO. Its nested
                # callback must not target an unavailable console-local clone.
                replacement=(emit('ldc.i',0)+emit('br',0) if ins.name=='call'
                             else emit('br',0)*2)
                # In stock 1+2, case -2 also hides/restores the console before
                # and after opening the external menu. Skip the entire case,
                # not just the call, to retain the currently displayed page.
                previous=script.ins[max(0,index-32):index]
                cases=[n for n,i in enumerate(previous) if i.name=='bne.case']
                if cases:
                    case=previous[cases[-1]-1]
                    assert case.name=='ldc.i' and case.fields['i'] in (-2,4), 'Unknown external menu input case'
                    code[case.offset-start:case.offset-start+6]=emit('ldc.i',0x7FFFFFFF)
        else:continue
        offset=ins.offset-start
        code[offset:offset+len(ins.raw)]=replacement
        removed.append({'offset':ins.offset,'function':ins.fields['h']})
    if function==PAUSE_INTER:
        assert {SAVE_POINT,DO_AUTOSAVE}<={r['function'] for r in removed}, 'Expected native save/autosave calls'
    return bytes(code),removed


def patch_console_pagination(blob):
    """Return (patched MJO, metadata report); never install or write assets.

    Input must not already contain this candidate. All active console modes
    use their own captured bounds; no mode is assigned a different rectangle.
    The font selector and existing bounded-rectangle patch are independent.
    """
    s=Script(blob)
    assert PAUSE_INTER in {h for h,_ in s.functions}, 'Original pause_inter function missing'
    assert not ((set(FUNCTIONS.values())|{PAGE_WAIT,PAGE_MENU}) & {h for h,_ in s.functions}), 'Already patched pagination candidate'
    wait_code,removed=clone_page_wait(s)
    menu_code,menu_removed=(clone_page_wait(s,PAUSE_MENU)
                            if PAUSE_MENU in dict(s.functions) else (None,[]))
    registrations=[]
    for index,ins in enumerate(s.ins):
        if ins.name=='syscallp' and ins.fields.get('h')==EVENT_AFTER:
            previous=s.ins[max(0,index-2):index]
            assert not any(p.name=='ldstr' and p.fields['s'].rstrip(b'\0') in (b'CRLF',b'CONSOLE_WROTE')
                           for p in previous), 'Existing after handler order is not supported'
        if ins.name=='syscallp' and ins.fields.get('h')==EVENT_HOOK:
            previous=s.ins[max(0,index-2):index]
            if any(p.name=='ldstr' and p.fields['s'].rstrip(b'\0')==b'CRLF' for p in previous):
                registrations.append(ins)
    assert len(registrations)==1, 'Expected one original CRLF event registration'
    set_calls=[i for i in s.ins if i.name=='syscallp' and i.fields.get('h')==CONSOLE_SET]
    assert set_calls and all(i.fields['a']==5 and len(i.raw)==8 for i in set_calls)
    for ins in set_calls:
        trampoline=len(s.code)
        s.code.extend(emit('callp',FUNCTIONS['set'],0,5))
        s.code.extend(emit('br',ins.offset+8-(len(s.code)+6)))
        s.code[ins.offset:ins.offset+8]=emit('br',trampoline-(ins.offset+6))+emit('ret')
    s.hook_after(registrations[0],FUNCTIONS['register'])
    for hashed,code in pagination_functions().items(): s.add(hashed,code)
    aliases={}
    for original,hashed,code in ((PAUSE_INTER,PAGE_WAIT,wait_code),(PAUSE_MENU,PAGE_MENU,menu_code)):
        if code is None:continue
        source_start=dict(s.functions)[original]
        target_start=len(s.code)
        aliases.update({target_start+i.offset:source_start+i.offset
                        for i in Script.parse(code) if i.name=='ldstr'})
        s.add(hashed,code)
    report={'experimental':True,'enabled_console_modes':'all; current bounds captured from console_set',
            'font_sizes_changed':False,'stage_geometry_changed':False,
            'page_boundary':'min(console y + height, client_height)',
            'clear_method':'immediate console_cls syscall; no queued ctrl opcode',
            'save_behavior':'inserted waits retain preceding natural paragraph save point; no exact mid-page resume',
            'cloned_wait_removed_calls':removed,
            'cloned_menu_removed_calls':menu_removed,
            'translation_source_aliases':aliases,
            'inserted_wait_restrictions':'history and config ignored until natural paragraph wait; both replace pending text',
            'busy_state':'SAVEFILE shared across callbacks; inserted waits never create save checkpoints; natural checkpoint must retain zero',
            'after_events':['CONSOLE_WROTE','CRLF'],
            'console_set_wrappers':[i.offset for i in set_calls],
            'registration_hook':s.hooks,'functions':FUNCTIONS,
            'runtime_validation':'required; source checks do not prove rendering, auto/skip or save behavior'}
    return s.finish(),report


def patch_sensitive_menu_entry(blob,target_hash):
    """Guard the shared menu entry, including native shortcut callbacks.

    Both supported stock entries have zero arguments and an integer return.
    The original body and addresses remain intact; a new function hash names
    it while the original public hash resolves to the appended wrapper.
    """
    assert target_hash in (HISTORY,CONFIG_MENU,PAUSE_MENU), 'Unsupported menu entry'
    s=Script(blob)
    start=dict(s.functions)[target_hash]
    prologue=next(i for i in s.ins if i.offset>=start and i.name=='argcheck')
    assert prologue.offset<=start+4 and not prologue.fields['t'], 'Unknown menu arguments'
    body_hash=hash32('$cdx_page_body_'+format(target_hash,'08x')+'@NARCI_LAYOUT')
    assert body_hash not in dict(s.functions), 'Already guarded menu'
    s.functions=[(body_hash if h==target_hash else h,o) for h,o in s.functions]
    b=Builder('cp932').prologue()
    _load(b,'busy').branch('brtrue','blocked')
    b.call(body_hash,result=True).op('ret').label('blocked').ret()
    wrapper_start=len(s.code)
    s.add(target_hash,b.finish())
    return s.finish(),{'target':target_hash,'body':body_hash,'body_offset':start,
                       'wrapper_offset':wrapper_start,'arguments':0,'new_strings':0}
