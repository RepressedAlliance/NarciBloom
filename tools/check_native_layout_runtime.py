"""Execute generated layout bytes in an owned x86 harness on Windows x64.

No game files, UI, GDI or network access are needed. This optional maintainer
check requires an explicit existing Zig 0.16.0 compiler and a new output folder;
it is not part of the default unit-test/compiler requirements.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from native_layout_generated import TAIL, TAIL_SHA256
from native_lexicon import LEXICON, LEXICON_SHA256, validate_lexicon

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'native_layout_runtime'


def _array(name, data):
    return f'static const unsigned char {name}[]={{' + ','.join(map(str, data)) + '};\n'


def _cases():
    spec = importlib.util.spec_from_file_location('native_layout_runtime_cases', FIXTURES / 'cases.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_cases()


def run(compiler: Path, output: Path):
    """Build and execute the frozen generated payload; never overwrite output."""
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64') or sys.maxsize <= 2**32:
        raise ValueError('This actual WOW64 check supports only a Windows x64 host with 64-bit Python')
    if sys.flags.optimize:
        raise ValueError('Run this validation without Python -O')
    compiler = compiler.resolve(strict=True)
    if subprocess.check_output([str(compiler), 'version'], text=True).strip() != '0.16.0':
        raise ValueError('This check requires Zig 0.16.0')
    output = output.resolve()
    if output.exists():
        raise ValueError('Output must be a new directory; existing evidence is never overwritten')
    if hashlib.sha256(TAIL).hexdigest() != TAIL_SHA256:
        raise ValueError('Generated TAIL fingerprint differs')
    if hashlib.sha256(LEXICON).hexdigest() != LEXICON_SHA256:
        raise ValueError('Generated lexicon fingerprint differs')
    lexicon_info = validate_lexicon(LEXICON)
    if not 0 < len(TAIL) < 0x100000 or not 0 < len(LEXICON) < 0x7fc000:
        raise ValueError('Payload exceeds the fake image regions')
    cases = _cases()
    header = ('typedef struct {unsigned int offset,length,cut,width,indent,flags,'
              'original_length,expected_cut,measure_fail_at,origin_x,cursor_x;} Case;\n')
    header += _array('payload', TAIL)
    header += f'extern const unsigned char lexicon[{len(LEXICON)}];\n'
    header += _array('closing', '，。！？；：、）】》」』～'.encode('gbk'))
    header += _array('opening', '（【《「『'.encode('gbk'))
    data = bytearray()
    rows = []
    for case in cases:
        raw = bytes.fromhex(case['hex'])
        if not 0 <= case['cut'] <= len(raw) <= 1023:
            raise ValueError('Harness case exceeds its string bounds')
        flags = sum(bit for key, bit in [('unchanged', 1), ('pointer_mismatch', 2),
            ('vertical', 4), ('null_rectangle', 8), ('null_output', 16),
            ('forbid_closing_start', 32), ('width_negative', 64),
            ('width_zero', 128), ('null_pending', 256)] if case.get(key))
        rows.append([len(data), len(raw), case['cut'], case['width'], case.get('indent', 0), flags,
            case.get('original_length', len(raw) + case.get('length_delta', 0)),
            case.get('expected_cut', 0xffffffff), case.get('measure_fail_at', 1),
            case.get('origin_x', 180), case.get('cursor_x', 247)])
        data.extend(raw)
    header += _array('case_bytes', data)
    header += ('static const Case cases[]={' + ','.join('{' + ','.join(str(value)+'u'
                for value in row) + '}' for row in rows) + '};\n')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'inputs.h').write_text(header, encoding='ascii')
    (output / 'lexicon-input.bin').write_bytes(LEXICON)
    # Relative incbin is resolved under cwd=output, including non-ASCII paths.
    (output / 'lexicon.S').write_text('.section .rdata,"dr"\n.globl _lexicon\n_lexicon:\n'
                                    '.incbin "lexicon-input.bin"\n', encoding='ascii')
    (output / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    exe = output / 'native_layout_harness.exe'
    command = [str(compiler), 'cc', '-target', 'x86-windows-gnu', '-Os', '-ffreestanding',
        '-fno-builtin', '-fno-stack-protector', '-mno-sse', '-mno-sse2', '-nostdlib',
        '-Wl,--entry,entry', '-I', str(output), str(FIXTURES / 'harness.c'),
        str(FIXTURES / 'measure.S'), str(FIXTURES / 'invoke.S'), str(output / 'lexicon.S'),
        '-lkernel32', '-o', str(exe)]
    build = subprocess.run(command, cwd=output, capture_output=True, text=True)
    (output / 'build.log').write_text(build.stdout + build.stderr, encoding='utf-8')
    build.check_returncode()
    result = subprocess.run([str(exe)], cwd=output, capture_output=True, text=True, timeout=20)
    (output / 'harness-output.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    actual = [list(map(int, row.split())) for row in result.stdout.splitlines()]
    report = dict(scope='Actual x86 TAIL execution with fake native metrics/classifiers; no game/GDI/UI',
        compiler_version='0.16.0', payload_sha256=TAIL_SHA256, payload_bytes=len(TAIL),
        lexicon={**lexicon_info, 'sha256': LEXICON_SHA256, 'bytes': len(LEXICON)},
        cases_per_base=len(cases), bases=['0x18000000', '0x28000000'],
        expected_cut_assertions=sum('expected_cut' in case for case in cases),
        nonclosing_tail_assertions=sum(bool(case.get('forbid_closing_start')) for case in cases),
        native_rectangle_bytes=108, probe_shadow_writes_checked=True,
        original_rectangle_preserved=result.returncode == 0 and len(actual) == 2 * len(cases),
        exit_code=result.returncode, completed_calls=len(actual), outcomes=[])
    for address, number, diagnostic, out_len, pending_len, measures in actual:
        report['outcomes'].append(dict(base=hex(address), name=cases[number]['name'],
            diagnostic=diagnostic, original_cut=cases[number]['cut'], new_cut=out_len,
            pending_bytes=pending_len, native_measure_calls=measures,
            exact_boundary_asserted='expected_cut' in cases[number]))
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'outcomes'}, indent=2))
    result.check_returncode()
    if len(actual) != 2 * len(cases):
        raise ValueError('Harness completed an unexpected number of calls')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True, help='Existing Zig 0.16.0 executable')
    parser.add_argument('--output', type=Path, required=True, help='New private output directory')
    args = parser.parse_args()
    try:
        run(args.compiler, args.output)
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
