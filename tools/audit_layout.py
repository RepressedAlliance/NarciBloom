"""Read-only Majiro layout inventory. Reports metadata, never scenario strings.

Capacity is a nominal geometric estimate, not a renderer or a proof that a
story fits. Glyph metrics, wrapping, ruby, spacing and animation need game QA.
Input and output locations are supplied by the caller; use ignored work/ for
reports containing personal paths. This tool never installs or runs a game.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct

from build_font_settings import SIZES, Script, original_sources, patch_console_bounded
from mjotool.known_hashes import SYSCALLS, FUNCTIONS, VARIABLES

CONSOLE_SET = 0x403960F8
LAYOUT_SYSCALLS = {h for h, name in SYSCALLS.items()
                   if name.startswith(('$console_', '$fontout', '$voicerect_', '$histbuff_'))}


def capacity(width, height, size, line_gap=4):
    """Nominal full/half-width columns and fully fitting rows; no font metrics."""
    return {'size': size, 'full_width_columns': max(0, width // size),
            'half_width_columns': max(0, width // (size // 2)),
            'rows': max(0, 1 + (height-size) // (size+line_gap)) if height >= size else 0}


def geometry(x, y, width, height, sizes=SIZES):
    return {'x': x, 'y': y, 'width': width, 'height': height,
            'right': x+width, 'bottom': y+height,
            'outside_800x600': x < 0 or y < 0 or x+width > 800 or y+height > 600,
            'nominal_capacity': [capacity(width, height, size) for size in sizes]}


def parameter_capacity(width, height, glyph_height, half_width, pitch):
    """Capacity from script font parameters, still without measuring glyph ink."""
    if min(glyph_height,half_width,pitch) <= 0:
        return None
    rows = 1+(height-glyph_height)//pitch if height >= glyph_height else 0
    return {'glyph_height_parameter':glyph_height,'half_width_parameter':half_width,
            'line_pitch_parameter':pitch,'rows':max(0,rows),
            'full_width_columns':max(0,width//(2*half_width)),
            'half_width_columns':max(0,width//half_width)}


def character_metrics(value):
    half = sum(ord(c) < 128 or 0xFF61 <= ord(c) <= 0xFF9F for c in value if c not in '\r\n')
    full = sum(not (ord(c) < 128 or 0xFF61 <= ord(c) <= 0xFF9F) for c in value if c not in '\r\n')
    return {'characters':len(value),
            'half_width_characters':half,'full_width_characters':full,
            'nominal_half_width_cells':half+2*full}


def text_metrics(raw):
    value = raw.rstrip(b'\0').decode('cp932',errors='replace')
    return {'bytes':len(raw.rstrip(b'\0')),'cp932_characters':len(value),
            **character_metrics(value),'crlf_pairs':raw.count(b'\r\n')}


def translation_table_metadata(blob):
    encoding = 'utf-16' if blob.startswith((b'\xff\xfe',b'\xfe\xff')) else 'gbk'
    lines = blob.decode(encoding).splitlines()
    rows = [{'table_line':n+1,**character_metrics(value)} for n,value in enumerate(lines)]
    return {'encoding':encoding,'line_count':len(lines),
            'first_eight_lines':rows[:8],
            'longest_lines':sorted(rows,key=lambda r:r['characters'],reverse=True)[:10],
            'mapping_to_source_instructions':'not established; no sequential correspondence assumed'}


def opening_text_blocks(script, calls, limit=8):
    """First blocks separated by ctrl-w, with source locations and no content.

    Control bytes are metadata, not a claim that all versions implement the
    same pause/clear behavior. A preceding mode is a linear hint, not CFG proof.
    """
    modes = {c['offset']:c['arguments_in_push_order'] for c in calls if c['hash']=='35395c9f'}
    blocks, operands, controls = [], [], []
    line = None
    mode = None
    for ins in script.ins:
        if ins.name == 'line': line = ins.fields.get('l')
        if ins.offset in modes:
            args = modes[ins.offset]
            mode = args[-1] if args else None
        if ins.name == 'text':
            operands.append({'offset':ins.offset,'line':line,**text_metrics(ins.fields['s'])})
        elif ins.name == 'ctrl':
            raw = ins.fields['s'].rstrip(b'\0')
            controls.append({'offset':ins.offset,'code':raw.decode('ascii') if raw in
                             (b'n',b'p',b'w',b's',b'x',b'd',b'z',b'o',b'r') else None,'bytes':len(raw)})
            if raw == b'w' and operands:
                blocks.append({'linear_mode_hint':mode,'text_operands':operands,'controls':controls})
                operands, controls = [], []
                if len(blocks) == limit: break
    return blocks


def constant_calls(script, selected_size=None):
    """Track literal stack values within straight-line basic blocks.

    Unknown operands remain None. Reset at branches and their targets so values
    from a different path cannot be mistaken for proven call arguments.
    Arguments retain bytecode push order (Majiro calls them right-to-left).
    """
    stack = []
    selected_globals = {} if selected_size is None else {
        0x65615B45:selected_size, 0x99EE010B:selected_size,
        0x721A4F06:selected_size//2, 0x8E951548:selected_size//2,
        0xBDDD7DA2:selected_size+4}
    targets = set()
    for ins in script.ins:
        if 'j' in ins.fields:
            targets.add(ins.offset+len(ins.raw)+ins.fields['j'])
        for n, delta in enumerate(ins.fields.get('c', [])):
            targets.add(ins.offset+8+4*n+delta)
    line = None
    function = None
    nearest_case = None
    line_variables = set()
    functions = {offset: hashed for hashed, offset in script.functions}
    calls = []
    binary = {'add.i': lambda a,b:a+b, 'sub.i':lambda a,b:a-b,
              'mul.i':lambda a,b:a*b, 'div.i':lambda a,b:int(a/b)}
    for ins in script.ins:
        if ins.offset in targets or ins.offset in functions:
            stack = []
        if ins.offset in functions:
            function = f'{functions[ins.offset]:08x}'
            nearest_case = None
        name = ins.name
        if name == 'line':
            line = ins.fields.get('l')
            line_variables = set()
        elif name == 'ldc.i':
            stack.append(ins.fields['i'])
        elif name.startswith(('ld', 'text')):
            # text emits dialogue rather than a stack value.
            if not name.startswith('text'):
                stack.append(selected_globals.get(ins.fields.get('h')) if name == 'ld' else None)
            if name == 'ld': line_variables.add(ins.fields['h'])
        elif name in binary:
            b = stack.pop() if stack else None
            a = stack.pop() if stack else None
            try:
                stack.append(binary[name](a,b) if a is not None and b is not None else None)
            except ZeroDivisionError:
                stack.append(None)
        elif name == 'pop':
            if stack: stack.pop()
        elif name in ('syscall', 'syscallp', 'call', 'callp'):
            count = ins.fields['a']
            args = ([None] * max(0, count-len(stack)) + stack[-count:]) if count else []
            if count: del stack[max(0,len(stack)-count):]
            calls.append({'offset': ins.offset, 'line': line, 'function': function,
                          'opcode': name, 'hash': f"{ins.fields['h']:08x}",
                          'name': (SYSCALLS if name.startswith('syscall') else FUNCTIONS).get(ins.fields['h']),
                          'nearest_case_constant': nearest_case,
                          'line_variable_reads': [{'hash':f'{h:08x}','name':VARIABLES.get(h)} for h in sorted(line_variables)],
                          'arguments_in_push_order': args})
            if name in ('syscall', 'call'): stack.append(None)
        elif name == 'bne.case':
            nearest_case = stack[-1] if stack else None
            stack = []
        elif name in ('argcheck', 'alloca', 'nop') or name.startswith('st'):
            pass
        else:
            # Do not carry a possibly invalid stack through unsupported math,
            # branches, control codes, or renderer instructions.
            stack = []
    return calls


def audit_script(blob):
    script = Script(blob)
    calls = constant_calls(script)
    layout = [c for c in calls if int(c['hash'],16) in LAYOUT_SYSCALLS and c['opcode'].startswith('syscall')]
    rectangles = []
    for call in layout:
        if int(call['hash'],16) != CONSOLE_SET: continue
        args = call['arguments_in_push_order']
        record = {k: call[k] for k in ('offset', 'line', 'function', 'nearest_case_constant')}
        if len(args) == 5 and all(v is not None for v in args[:4]):
            height, width, y, x = args[:4]
            record.update(geometry(x,y,width,height))
        else:
            record['unresolved_arguments_in_push_order'] = args
        rectangles.append(record)
    parameter_substitutions = []
    for size in SIZES:
        substituted = constant_calls(script,size)
        for call in substituted:
            if call['hash'] not in ('06b3c8ac','e186d19a') or not call['opcode'].startswith('syscall'): continue
            parameter_substitutions.append({'selected_size':size,'offset':call['offset'],'line':call['line'],
                                            'nearest_case_constant':call['nearest_case_constant'],'name':call['name'],
                                            'arguments_in_push_order':call['arguments_in_push_order']})
        for rect in rectangles:
            if 'width' not in rect: continue
            following = next((c for c in substituted if c['offset'] > rect['offset'] and c['hash']=='06b3c8ac'
                              and c['function']==rect['function']
                              and c['nearest_case_constant']==rect['nearest_case_constant']),None)
            if following is None: continue
            args = following['arguments_in_push_order']
            if len(args)!=5 or any(n is None for n in args[1:4]): continue
            pitch,half_width,glyph_height = args[1:4]
            declared = parameter_capacity(rect['width'],rect['height'],glyph_height,half_width,pitch)
            visible = parameter_capacity(max(0,min(rect['width'],800-rect['x'])),
                                         max(0,min(rect['height'],600-rect['y'])),glyph_height,half_width,pitch)
            rect.setdefault('script_parameter_capacity',[]).append({
                'size':size,'font_call_offset':following['offset'],'declared_rectangle':declared,
                'clipped_to_800x600':visible})
    lengths = []
    line = None
    for ins in script.ins:
        if ins.name == 'line': line = ins.fields.get('l')
        # Keep only lengths and locations, including undecodable strings.
        for field in ('s', 't'):
            value = ins.fields.get(field)
            if isinstance(value, bytes):
                raw = value.rstrip(b'\0')
                lengths.append({'offset': ins.offset, 'line': line, 'opcode': ins.name,**text_metrics(raw)})
    return {'code_bytes': len(script.code), 'functions': len(script.functions),
            'instruction_count': len(script.ins), 'console_rectangles': rectangles,
            'console_mode_calls': [c for c in calls if c['hash'] == '35395c9f' and c['opcode'].startswith('call')],
            'font_parameter_substitutions':parameter_substitutions,
            'opening_text_blocks':opening_text_blocks(script,calls),
            'layout_calls': layout, 'text_operand_count': len(lengths),
            'longest_text_operands': sorted(lengths,key=lambda r:r['bytes'],reverse=True)[:10]}


def config_metadata(blob):
    """Extract only named font sections, leaving unrelated config text private."""
    text = blob.decode('cp932',errors='replace')
    result = []
    lines = text.splitlines()
    for index, value in enumerate(lines):
        marker = re.match(r'\s*//\s*([A-Z][A-Z0-9_]*)\b', value)
        if not marker: continue
        if not marker[1].endswith('FONT') and marker[1] not in ('CONAREA','CONALL_ALLMODE','NAMEALL'):
            continue
        section = {'marker': marker[1], 'line': index+1}
        for tail in lines[index+1:index+25]:
            if re.match(r'\s*//\s*[A-Z][A-Z0-9_]*\b', tail): break
            numeric = re.match(r'^\s*(-?\d+(?:\s*,\s*-?\d+)+)\s*(?://|$)',tail)
            if numeric:
                section['parameters'] = [int(n.strip()) for n in numeric[1].split(',')]
                if len(section['parameters']) == 4 and not marker[1].endswith('FONT'):
                    section['geometry'] = geometry(*section['parameters'])
                break
        result.append(section)
    return result


def audit_folder(folder, loose=None):
    files, _, _, _ = original_sources(folder)
    if loose:
        # Caller identifies the extracted tree. Do not infer that a Chinese
        # executable's embedded archive represents its virtual overrides.
        for path in Path(loose).rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.mjo','.cfg'):
                files[path.name] = path.read_bytes()
    report = audit_files(files)
    report.update({'input': str(folder), 'loose_override_input': str(loose) if loose else None})
    return report


def audit_files(files, translation_tables=None):
    """Audit caller-resolved effective resources without extracting files.

    The caller owns archive and virtual override precedence. Translation tables
    are measured independently, since loader correspondence is not established.
    """
    report = {
              'estimate': 'Nominal full/half-width glyph cells; size+4 line pitch. Not measured rendering.',
              'font_substitution_basis': 'Conditional substitution of apply_function globals; not execution of intervening calls or a renderer.',
              'scripts': {}, 'configs': {}, 'parse_errors': [], 'patched_console': None}
    for name, blob in sorted(files.items()):
        if name.lower().endswith('.mjo'):
            try: report['scripts'][name] = audit_script(blob)
            except (AssertionError, KeyError, ValueError, IndexError, struct.error) as error:
                report['parse_errors'].append({'file':name,'type':type(error).__name__})
        elif name.lower().endswith('.cfg'):
            fonts = config_metadata(blob)
            if fonts: report['configs'][name] = fonts
    if 'console.mjo' in files:
        patched, changes = patch_console_bounded(files['console.mjo'])
        report['patched_console'] = {'changes':changes,'audit':audit_script(patched)}
    counts = Counter()
    for script in report['scripts'].values():
        for call in script['layout_calls']: counts[call['name']] += 1
    report['layout_call_counts'] = dict(counts)
    report['translation_tables'] = {name:translation_table_metadata(blob)
                                    for name,blob in (translation_tables or {}).items()}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='One module folder containing its executable and archives')
    parser.add_argument('--loose', type=Path, help='Optional explicitly selected extracted virtual file tree')
    parser.add_argument('--output', required=True, type=Path, help='Metadata JSON; personal paths belong in ignored work/')
    args = parser.parse_args()
    report = audit_folder(args.folder,args.loose)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'scripts':len(report['scripts']),'parse_errors':len(report['parse_errors']),
                      'configs':len(report['configs'])}))


if __name__ == '__main__':
    main()
