"""Reproduce a generic GBK word-frequency table from pinned MIT jieba data.

This developer tool does not run jieba/HMM or read game/translation resources.
The installer imports the generated module and never downloads these inputs.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import struct
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '67fa2e36e72f69d9134b8a1037b83fbb070b9775'
UPSTREAM = 'https://github.com/fxsjy/jieba'
RAW = f'https://raw.githubusercontent.com/fxsjy/jieba/{COMMIT}/'
DICT_SHA256 = '7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8'
LICENSE_SHA256 = '18ba0984839f85853b29fadaf992f7dba8fd0ca0fbeae34de2b8735222dc7a37'
MAX_UNITS = 8
SCALE = 256
HEADER = struct.Struct('<4sHH7I')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build_table(dictionary: bytes):
    """Return (NBLX bytes, generation stats), independent of network/files.

    Every record must have a positive integer frequency. Retain only GBK
    encodable Han words of 1..8 units. Equal GBK byte strings take their maximum
    frequency; total_freq is the sum AFTER filtering and deduplication.
    """
    if not isinstance(dictionary, bytes):
        raise TypeError('UTF-8 dictionary bytes required')
    words = {}
    stats = dict(source_records=0, non_han=0, over_max_units=0,
                 unencodable_gbk=0, duplicate_gbk=0)
    for line_number, line in enumerate(dictionary.decode('utf8').splitlines(), 1):
        fields = line.split()
        if len(fields) < 2:
            raise ValueError(f'Invalid dictionary record at line {line_number}')
        word = fields[0]
        try:
            frequency = int(fields[1])
        except ValueError as exc:
            raise ValueError(f'Invalid frequency at line {line_number}') from exc
        if not 1 <= frequency <= 0xffffffff:
            raise ValueError(f'Frequency out of range at line {line_number}')
        stats['source_records'] += 1
        if not word or not all('\u4e00' <= char <= '\u9fff' for char in word):
            stats['non_han'] += 1
            continue
        if len(word) > MAX_UNITS:
            stats['over_max_units'] += 1
            continue
        try:
            encoded = word.encode('gbk', errors='strict')
        except UnicodeEncodeError:
            stats['unencodable_gbk'] += 1
            continue
        if len(encoded) != 2 * len(word):
            raise ValueError('Unexpected GBK Han encoding width')
        if encoded in words:
            stats['duplicate_gbk'] += 1
        words[encoded] = max(frequency, words.get(encoded, 0))
    if not words:
        raise ValueError('Dictionary has no eligible GBK words')
    total = sum(words.values())
    if total > 0xffffffff:
        raise ValueError('Retained frequency sum exceeds the NBLX u32 field')
    fallback = round(math.log(total) * SCALE)
    if fallback > 0xffff:
        raise ValueError('Frequency costs exceed u16')
    pool = bytearray()
    offsets = bytearray(struct.pack('<I', 0))
    costs = bytearray()
    for word, frequency in sorted(words.items()):
        pool.extend(word)
        offsets.extend(struct.pack('<I', len(pool)))
        cost = round(math.log(total / frequency) * SCALE)
        if not 0 <= cost <= fallback:
            raise ValueError('Invalid generated word cost')
        costs.extend(struct.pack('<H', cost))
    count = len(words)
    offsets_off = HEADER.size
    costs_off = offsets_off + len(offsets)
    strings_off = costs_off + len(costs)
    size = strings_off + len(pool)
    blob = HEADER.pack(b'NBLX', 1, MAX_UNITS, count, fallback,
                       offsets_off, costs_off, strings_off, size, total)
    blob += offsets + costs + pool
    stats.update(word_count=count, single_unit_words=sum(len(word) == 2 for word in words),
                 total_freq=total, fallback_cost=fallback, cost_scale=SCALE,
                 table_bytes=len(blob), strings_bytes=len(pool), lexicon_sha256=sha(blob))
    return blob, stats


# This runtime reader is emitted alongside the data so players require only
# Python's existing base64/hashlib/struct/zlib standard-library modules.
READER = r'''
_HEADER_STRUCT = struct.Struct('<4sHH7I')
_MAX_BYTES = 16 * 1024 * 1024


def validate_lexicon(blob):
    """Validate the complete immutable NBLX v1 layout; return header fields.

    Offsets are relative to the string pool, strictly increasing, with N+1
    entries. Costs are precomputed unsigned fixed-point values (scale 256).
    This validates encoding and order too, not merely the magic/length.
    """
    if not isinstance(blob, bytes):
        raise TypeError('NBLX bytes required')
    if not _HEADER_STRUCT.size <= len(blob) <= _MAX_BYTES:
        raise ValueError('Invalid NBLX total size')
    magic, version, max_units, count, fallback, offsets, costs, strings, size, total = _HEADER_STRUCT.unpack_from(blob)
    if (magic != b'NBLX' or version != 1 or max_units != 8 or
            not 1 <= count <= 1_000_000 or not count <= total <= 0xffffffff or
            not 0 <= fallback <= 0xffff or offsets != 36 or
            costs != offsets + 4 * (count + 1) or
            strings != costs + 2 * count or size != len(blob) or strings >= size):
        raise ValueError('Invalid NBLX header/section layout')
    if struct.unpack_from('<I', blob, offsets)[0] != 0:
        raise ValueError('NBLX first string offset is not zero')
    end_of_pool = size - strings
    if struct.unpack_from('<I', blob, offsets + count * 4)[0] != end_of_pool:
        raise ValueError('NBLX final string offset differs')
    previous_word = None
    begin = 0
    for index in range(count):
        end = struct.unpack_from('<I', blob, offsets + (index + 1) * 4)[0]
        if not begin < end <= end_of_pool or not 2 <= end - begin <= max_units * 2 or (end - begin) % 2:
            raise ValueError('Invalid NBLX word offsets/GBK unit count')
        word = blob[strings + begin:strings + end]
        try:
            text = word.decode('gbk', errors='strict')
        except UnicodeError as exc:
            raise ValueError('Invalid NBLX GBK word') from exc
        if (len(text) * 2 != len(word) or
                not all('\u4e00' <= char <= '\u9fff' for char in text) or
                (previous_word is not None and word <= previous_word)):
            raise ValueError('NBLX words must be unique sorted GBK Han units')
        cost = struct.unpack_from('<H', blob, costs + index * 2)[0]
        if cost > fallback:
            raise ValueError('NBLX word cost exceeds frequency-one fallback')
        previous_word, begin = word, end
    return dict(version=version, max_units=max_units, count=count,
                fallback_cost=fallback, offsets_off=offsets, costs_off=costs,
                strings_off=strings, total_size=size, total_freq=total)


def _load():
    compressed = base64.b85decode(_PACKED_B85)
    reader = zlib.decompressobj()
    data = reader.decompress(compressed, _MAX_BYTES + 1)
    if (len(data) > _MAX_BYTES or not reader.eof or
            reader.unconsumed_tail or reader.unused_data):
        raise ValueError('Invalid compressed lexicon framing/size')
    if hashlib.sha256(data).hexdigest() != LEXICON_SHA256:
        raise ValueError('Generated lexicon fingerprint differs')
    return data


LEXICON = _load()
HEADER = validate_lexicon(LEXICON)
WORD_COUNT = HEADER['count']
MAX_UNITS = HEADER['max_units']
FALLBACK_COST = HEADER['fallback_cost']
_OFFSETS = HEADER['offsets_off']
_COSTS = HEADER['costs_off']
_STRINGS = HEADER['strings_off']
del _PACKED_B85


def lookup_cost(word: bytes):
    """Return the word's integer cost, or None if absent/not a GBK Han word.

    ASCII words/numeric runs are handled separately by the renderer. No text
    normalization, dictionary mutation, segmentation or filesystem I/O occurs.
    """
    if not isinstance(word, bytes):
        raise TypeError('Exact renderer GBK bytes required')
    if not 2 <= len(word) <= MAX_UNITS * 2 or len(word) % 2:
        return None
    low, high = 0, WORD_COUNT
    while low < high:
        middle = (low + high) // 2
        begin, end = struct.unpack_from('<II', LEXICON, _OFFSETS + middle * 4)
        candidate = LEXICON[_STRINGS + begin:_STRINGS + end]
        if candidate < word:
            low = middle + 1
        elif candidate > word:
            high = middle
        else:
            return struct.unpack_from('<H', LEXICON, _COSTS + middle * 2)[0]
    return None
'''


def render_module(blob, stats):
    source = dict(upstream=UPSTREAM, commit=COMMIT, dictionary_url=RAW + 'jieba/dict.txt',
                  dictionary_sha256=DICT_SHA256, dictionary_size_bytes=5071852,
                  license_url=RAW + 'LICENSE', license_sha256=LICENSE_SHA256,
                  license='MIT', copyright='Copyright (c) 2013 Sun Junyi',
                  license_file='LICENSE-jieba.txt',
                  filter='GBK-encodable U+4E00..U+9FFF Han words, 1..8 units',
                  duplicate_policy='maximum frequency for identical GBK byte strings',
                  total_frequency_policy='sum of retained distinct word frequencies',
                  cost_formula='round(ln(total_freq / frequency) * 256)',
                  unknown_frequency=1, **stats)
    packed = base64.b85encode(zlib.compress(blob, 9))
    lines = [repr(packed[index:index + 100]) for index in range(0, len(packed), 100)]
    header = '''"""Generated generic GBK word-frequency data; no game text or jieba runtime.

Reproduce with build_native_lexicon.py. Dictionary derived from pinned jieba
MIT data; retain LICENSE-jieba.txt and its attribution when redistributing.
NBLX: 36-byte header, (N+1) relative u32 offsets, N u16 costs, raw GBK words.
"""
import base64
import hashlib
import struct
import zlib

'''
    header += 'SOURCE = ' + repr(source) + '\n'
    header += 'LEXICON_SHA256 = ' + repr(sha(blob)) + '\n'
    header += '_PACKED_B85 = (\n    ' + '\n    '.join(lines) + '\n)\n'
    return header + READER


def read_source(path, relative, expected):
    if path is None:
        request = urllib.request.Request(RAW + relative, headers={'User-Agent': 'NarciBloom-lexicon-builder'})
        with urllib.request.urlopen(request, timeout=30) as response:
            blob = response.read(8 * 1024 * 1024 + 1)
    else:
        blob = path.read_bytes()
    if len(blob) > 8 * 1024 * 1024 or sha(blob) != expected:
        raise ValueError(f'Pinned source fingerprint differs: {relative}')
    return blob


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dictionary', type=Path, help='Offline exact pinned dict.txt')
    parser.add_argument('--license', type=Path, help='Offline exact pinned upstream LICENSE')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('native_lexicon.py'))
    parser.add_argument('--license-output', type=Path, default=ROOT / 'LICENSE-jieba.txt')
    parser.add_argument('--check', action='store_true', help='Compare generated files without writing')
    args = parser.parse_args()
    dictionary = read_source(args.dictionary, 'jieba/dict.txt', DICT_SHA256)
    license_data = read_source(args.license, 'LICENSE', LICENSE_SHA256)
    blob, stats = build_table(dictionary)
    module = render_module(blob, stats).encode('utf8')
    if args.check:
        if args.output.read_bytes().replace(b'\r\n', b'\n') != module or args.license_output.read_bytes() != license_data:
            raise ValueError('Generated lexicon/module license differs')
    else:
        args.output.write_bytes(module)
        args.license_output.write_bytes(license_data)
    print(json.dumps(dict(stats, module_bytes=len(module), output=str(args.output), checked=args.check), indent=2))


if __name__ == '__main__':
    main()
