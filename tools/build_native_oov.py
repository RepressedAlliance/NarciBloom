"""Reproduce bounded GBK character-position data from pinned MIT jieba data.

Read probability literals with ast.literal_eval; never import downloaded code.
The native reader proposes words only inside dictionary-singleton runs. Each
word has a reset start score, making the right-to-left route suffix-stable.
This is an adapted word lattice, not jieba's whole-run Viterbi decoder.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import math
from pathlib import Path
import struct
import zlib

from build_native_lexicon import COMMIT, RAW, read_source

FINGERPRINTS = {
    'start': '14c5706ced5cd3b42eb4873d4b88f7f52a7bdf80fbd767bc4423d361e20c5330',
    'trans': '54dfbc252ed71480d4f0cdfdf516ecfbe44efd0f6c3c64b158e7039f2906c91b',
    'emit': '27d46b1c9efe4dd148fde8be042a21be40e3562d0c7f1273f9de7abae12ebb8d',
}
STATES = 'BMES'
HEADER = struct.Struct('<4s7I')
CELLS = 126 * 190
MISSING = 0xffff
SCALE = 256
MAX_UNITS = 8
# At least one constituent must occur less often than 1/4096 in the generic
# dictionary. Common grammatical singletons cannot be joined just by the model.
MIN_RARE_COST = round(math.log(4096) * SCALE)


def probability_literals(raw):
    tree = ast.parse(raw.decode('utf8'))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'P' for t in node.targets)]
    if len(values) != 1:
        raise ValueError('Expected one probability literal')
    return ast.literal_eval(values[0])


def fixed_cost(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value > 0:
        raise ValueError('Expected finite nonpositive log probability')
    return MISSING if value < -255 else min(MISSING - 1, round(-value * SCALE))


def cell(word):
    raw = word.encode('gbk')
    if len(raw) != 2 or not '\u4e00' <= word <= '\u9fff':
        raise ValueError('Expected one GBK Han character')
    a, b = raw
    return (a - 0x81) * 190 + b - 0x40 - (b > 0x7f)


def build_table(models):
    start, trans, emit = (models[k] for k in ('start', 'trans', 'emit'))
    if any(set(value) != set(STATES) for value in (start, trans, emit)):
        raise ValueError('Unexpected states')
    values = [fixed_cost(start[s]) for s in STATES]
    values += [fixed_cost(trans[a][b]) if b in trans[a] else MISSING
               for a in STATES for b in STATES]
    dense = [MISSING] * (CELLS * 4)
    for state, label in enumerate(STATES):
        for char, value in emit[label].items():
            cost = fixed_cost(value)
            try:
                index = cell(char)
            except (ValueError, UnicodeError):
                continue
            dense[index * 4 + state] = cost
    values += dense
    size = HEADER.size + len(values) * 2
    return HEADER.pack(b'NBHM', 1, CELLS, 4, MAX_UNITS, MIN_RARE_COST, size, SCALE) + struct.pack('<' + str(len(values)) + 'H', *values)


READER = '''
def validate_model(blob):
    if not isinstance(blob, bytes):
        raise TypeError('NBHM bytes required')
    if len(blob) != 72 + 23940 * 8:
        raise ValueError('Invalid NBHM size')
    if struct.unpack_from('<4s7I', blob) != (b'NBHM', 1, 23940, 4, 8, 2129, len(blob), 256):
        raise ValueError('Invalid NBHM header')
    values = struct.unpack_from('<20H', blob, 32)
    if values[1:3] != (65535, 65535) or values[0] == 65535 or values[3] == 65535:
        raise ValueError('Invalid NBHM start states')
    allowed = {(0, 1), (0, 2), (1, 1), (1, 2), (2, 0), (2, 3), (3, 0), (3, 3)}
    if any((values[4 + a * 4 + b] != 65535) != ((a, b) in allowed)
           for a in range(4) for b in range(4)):
        raise ValueError('Invalid NBHM transitions')
    return dict(version=1, cells=23940, states='BMES', max_units=8,
                min_rare_cost=2129, scale=256, bytes=len(blob))


def _load():
    reader = zlib.decompressobj()
    data = reader.decompress(base64.b85decode(_PACKED_B85), 191593)
    if (not reader.eof or reader.unconsumed_tail or reader.unused_data or
            hashlib.sha256(data).hexdigest() != MODEL_SHA256):
        raise ValueError('Generated NBHM framing/fingerprint differs')
    validate_model(data)
    return data


MODEL = _load()
HEADER = validate_model(MODEL)
_VALUES = struct.unpack_from('<' + str((len(MODEL) - 32) // 2) + 'H', MODEL, 32)
del _PACKED_B85


def word_cost(word):
    """Model word cost, independent of preceding text; None for missing data."""
    if not isinstance(word, str) or not 1 <= len(word) <= 8:
        return None
    states = [3] if len(word) == 1 else [0] + [1] * (len(word) - 2) + [2]
    values = [_VALUES[states[0]]]
    try:
        for char, state in zip(word, states):
            raw = char.encode('gbk')
            if len(raw) != 2 or not '\\u4e00' <= char <= '\\u9fff':
                return None
            a, b = raw
            index = (a - 0x81) * 190 + b - 0x40 - (b > 0x7f)
            values.append(_VALUES[20 + index * 4 + state])
    except UnicodeError:
        return None
    values.extend(_VALUES[4 + a * 4 + b] for a, b in zip(states, states[1:]))
    return None if 65535 in values else sum(values)


def refine_tokens(tokens, lookup_cost):
    """Offline reference for the native lattice, preserving known words."""
    result = []
    at = 0
    while at < len(tokens):
        if len(tokens[at]) != 1 or not '\\u4e00' <= tokens[at] <= '\\u9fff':
            result.append(tokens[at]); at += 1; continue
        end = at + 1
        while end < len(tokens) and len(tokens[end]) == 1 and '\\u4e00' <= tokens[end] <= '\\u9fff':
            end += 1
        text = ''.join(tokens[at:end])
        costs = [lookup_cost(c.encode('gbk')) for c in text]
        best = [(0, []) for _ in range(len(text) + 1)]
        for i in range(len(text) - 1, -1, -1):
            single = word_cost(text[i])
            choices = [((65535 if single is None else single) + best[i + 1][0], -1, [text[i]] + best[i + 1][1])]
            for j in range(i + 2, min(len(text), i + 8) + 1):
                if not any(value is None or value >= 2129 for value in costs[i:j]):
                    continue
                value = word_cost(text[i:j])
                if value is not None:
                    choices.append((value + best[j][0], -(j - i), [text[i:j]] + best[j][1]))
            value, _tie, route = min(choices)
            best[i] = value, route
        result.extend(best[0][1]); at = end
    return result
'''


def render_module(blob):
    packed = base64.b85encode(zlib.compress(blob, 9))
    source = dict(commit=COMMIT, license='MIT', license_file='LICENSE-jieba.txt',
                  data={k: dict(url=RAW + f'jieba/finalseg/prob_{k}.py', sha256=v)
                        for k, v in FINGERPRINTS.items()},
                  policy='reset-start bounded word lattice in dictionary singleton runs; rare-character gate')
    output = ('"""Generated generic GBK character-position data, not game text.\n'
              'Adapted word lattice; retain LICENSE-jieba.txt. See build_native_oov.py.\n"""\n'
              'import base64\nimport hashlib\nimport struct\nimport zlib\n\n')
    output += f'SOURCE = {source!r}\nMODEL_SHA256 = {hashlib.sha256(blob).hexdigest()!r}\n'
    output += '_PACKED_B85 = (\n' + ''.join('    ' + repr(packed[i:i+100]) + '\n' for i in range(0, len(packed), 100)) + ')\n'
    return output + READER


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('native_oov.py'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    models = {k: probability_literals(read_source(
        args.source_dir / f'prob_{k}.py' if args.source_dir else None,
        f'jieba/finalseg/prob_{k}.py', fingerprint)) for k, fingerprint in FINGERPRINTS.items()}
    data = render_module(build_table(models)).encode('utf8')
    if args.check:
        if args.output.read_bytes().replace(b'\r\n', b'\n') != data:
            raise ValueError('Generated NBHM differs')
    else:
        args.output.write_bytes(data)
    print(f'NBHM generated/checked: {len(data)} module bytes')


if __name__ == '__main__':
    main()
