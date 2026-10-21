"""Reproduce the owned, freestanding x86 layout payloads with Zig 0.16.0.

Example: python tools/regenerate_native_layout.py --compiler /path/to/zig
    --build-dir work/native-layout-build --check

Objects/reports stay in the selected build directory; no game input is needed.
The installer uses native_layout_generated.py and never invokes this tool.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess


FLAGS = ['cc', '-target', 'x86-windows-gnu', '-Os', '-ffreestanding', '-fno-builtin',
         '-fno-stack-protector', '-fno-ident', '-fno-jump-tables',
         '-fno-asynchronous-unwind-tables', '-fno-unwind-tables',
         '-mno-sse', '-mno-sse2', '-mno-mmx', '-c']


def source_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def coff_text(data, entry):
    """Accept only self-contained i386 text: no relocations/data/externals."""
    machine, count, _time, symbols_at, symbol_count, optional, _flags = struct.unpack_from('<HHIIIHH', data)
    if machine != 0x14c or optional:
        raise ValueError('Expected i386 COFF object')
    text = None
    text_section = None
    sections = []
    for index in range(count):
        offset = 20 + 40 * index
        name = data[offset:offset + 8].rstrip(b'\0').decode('ascii')
        _virtual, _rva, size, raw, _reloc, _line, relocations, _lines, _characteristics = struct.unpack_from('<IIIIIIHHI', data, offset + 8)
        if relocations or (name in ('.data', '.bss') and size):
            raise ValueError('Layout object requires data or relocation')
        sections.append(dict(name=name, bytes=size, relocations=relocations))
        if name == '.text':
            text = data[raw:raw + size]
            text_section = index + 1
    strings = data[symbols_at + 18 * symbol_count:]
    index = 0
    found = False
    while index < symbol_count:
        offset = symbols_at + 18 * index
        raw = data[offset:offset + 8]
        if raw[:4] == b'\0' * 4:
            start = struct.unpack_from('<I', raw, 4)[0]
            name = strings[start:strings.index(b'\0', start)].decode('ascii')
        else:
            name = raw.rstrip(b'\0').decode('ascii')
        value, section, _type, storage, auxiliaries = struct.unpack_from('<IhHBB', data, offset + 8)
        if storage == 2 and section == 0:
            raise ValueError('Layout object requires an external symbol')
        if name == entry:
            found = value == 0 and section == text_section
        index += auxiliaries + 1
    if not text or not found:
        raise ValueError('Layout function must start at text offset zero')
    return text, sections


def generate(compiler, build_dir):
    if subprocess.check_output([str(compiler), 'version'], text=True).strip() != '0.16.0':
        raise ValueError('Reproduction requires Zig 0.16.0')
    root = Path(__file__).resolve().parent
    build_dir.mkdir(parents=True, exist_ok=True)
    result = ('"""Generated own-code x86 payloads; see regenerate_native_layout.py.\n\n'
              'No game code or resources are embedded here. Runtime patching needs no compiler.\n'
              '"""\nimport base64\n\n')
    report = {'compiler': 'Zig 0.16.0', 'flags': FLAGS, 'payloads': {}}
    for name, filename, entry in [('TAIL', 'native_layout_tail.c', '_nb_adjust'),
                                  ('SPACING', 'native_layout_spacing.c', '_nb_advance')]:
        source = root / filename
        obj = build_dir / (source.stem + '.obj')
        subprocess.run([str(compiler), *FLAGS, str(source), '-o', str(obj)], check=True,
                       capture_output=True)
        code, sections = coff_text(obj.read_bytes(), entry)
        digest = hashlib.sha256(code).hexdigest()
        encoded = base64.b64encode(code).decode('ascii')
        literal = '\n'.join('    ' + repr(encoded[i:i + 88]) for i in range(0, len(encoded), 88))
        result += (f'{name}_SOURCE_SHA256 = {source_hash(source)!r}\n'
                   f'{name}_SHA256 = {digest!r}\n'
                   f'{name} = base64.b64decode(\n{literal}\n)\n\n')
        (build_dir / (source.stem + '.bin')).write_bytes(code)
        report['payloads'][name] = dict(source_sha256=source_hash(source), sha256=digest,
                                        bytes=len(code), sections=sections, entry_offset=0)
    return result.rstrip() + '\n', report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = parser.parse_args()
    text, report = generate(args.compiler, args.build_dir)
    target = Path(__file__).with_name('native_layout_generated.py')
    matches = target.read_text(encoding='utf-8') == text
    report['generated_module_matches'] = matches
    (args.build_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if args.write:
        target.write_text(text, encoding='utf-8', newline='\n')
    elif not matches:
        raise SystemExit('Generated native layout payload differs; review before using --write')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
