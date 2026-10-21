"""Generic dictionary data only; no translated scenarios or game fixtures."""
import hashlib
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_native_lexicon as builder
import native_lexicon as lexicon


def records(blob):
    """Independent reader for the published C-facing binary contract."""
    magic, version, units, count, fallback, offsets, costs, strings, size, total = struct.unpack_from('<4sHH7I', blob)
    assert magic == b'NBLX' and version == 1 and units == 8 and size == len(blob)
    result = {}
    for index in range(count):
        begin, end = struct.unpack_from('<II', blob, offsets + index * 4)
        result[blob[strings + begin:strings + end]] = struct.unpack_from('<H', blob, costs + index * 2)[0]
    return result


def segment(text):
    """Dictionary-only shortest path, used to exercise data beyond exact lookup."""
    units = [char.encode('gbk') for char in text]
    best = [(0, []) for _ in range(len(units) + 1)]
    for start in range(len(units) - 1, -1, -1):
        candidates = []
        for end in range(start + 1, min(len(units), start + 8) + 1):
            cost = lexicon.lookup_cost(b''.join(units[start:end]))
            if cost is None and end != start + 1:
                continue
            suffix_cost, suffix = best[end]
            candidates.append(((lexicon.FALLBACK_COST if cost is None else cost) + suffix_cost,
                               -(end - start), [text[start:end]] + suffix))
        cost, _negative_length, tokens = min(candidates)
        best[start] = cost, tokens
    return best[0][1]


class NativeLexiconTests(unittest.TestCase):
    def test_pinned_binary_contract_and_license(self):
        self.assertEqual(builder.HEADER.size, 36)
        self.assertEqual(hashlib.sha256(lexicon.LEXICON).hexdigest(), lexicon.LEXICON_SHA256)
        self.assertEqual(lexicon.LEXICON_SHA256,
                         'ee573bf889071287db397f5f4836cc32c9d5819b44c9886a2ceaad91cc32f7ad')
        self.assertEqual(lexicon.HEADER, dict(version=1, max_units=8, count=348436,
                         fallback_cost=4585, offsets_off=36, costs_off=1393784,
                         strings_off=2090656, total_size=4111764, total_freq=60075045))
        self.assertEqual(lexicon.SOURCE['single_unit_words'], 11580)
        self.assertEqual(lexicon.SOURCE['commit'], builder.COMMIT)
        license_data = (ROOT / 'LICENSE-jieba.txt').read_bytes()
        self.assertEqual(hashlib.sha256(license_data).hexdigest(), builder.LICENSE_SHA256)
        self.assertIn(b'Copyright (c) 2013 Sun Junyi', license_data)

    def test_full_table_independent_reader_and_sampled_binary_search(self):
        table = records(lexicon.LEXICON)
        self.assertEqual(len(table), lexicon.WORD_COUNT)
        words = list(table)
        self.assertEqual(words, sorted(words))
        for word in [words[0], words[-1]] + words[::997]:
            with self.subTest(word=word):
                self.assertEqual(lexicon.lookup_cost(word), table[word])
        for word in ('我', '医院', '前往', '南京市', '长江大桥'):
            self.assertIsInstance(lexicon.lookup_cost(word.encode('gbk')), int)

    def test_lookup_does_not_accept_non_words_or_normalize_bytes(self):
        for word in (b'', b'ASCII', b'123456', b'\x81', b'\xff\xff',
                     b'\x00\x00', '。'.encode('gbk'), '甲'.encode('gbk') * 9):
            with self.subTest(word=word):
                self.assertIsNone(lexicon.lookup_cost(word))
        for word in ('医院', bytearray('医院'.encode('gbk')), None):
            with self.subTest(word=word), self.assertRaises(TypeError):
                lexicon.lookup_cost(word)

    def test_generic_dictionary_only_dp_examples(self):
        examples = {
            '他是个恶人': ['他', '是', '个', '恶人'],
            '我想前往医院': ['我', '想', '前往', '医院'],
            '允许角色起来': ['允许', '角色', '起来'],
            '研究生命起源': ['研究', '生命', '起源'],
            '南京市长江大桥': ['南京市', '长江大桥'],
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                tokens = segment(text)
                self.assertEqual(tokens, expected)
                self.assertEqual(''.join(tokens).encode('gbk'), text.encode('gbk'))

    def test_generation_keeps_singletons_deduplicates_and_filters(self):
        lines = ['甲 3 n', '乙 4 n', '甲乙 7 n', '甲 5 n',
                 'ASCII 100 x', '𠀀 200 x', '一二三四五六七八九 500 n']
        blob, stats = builder.build_table(('\n'.join(lines) + '\n').encode('utf8'))
        self.assertEqual(lexicon.validate_lexicon(blob)['count'], 3)
        self.assertEqual(stats['single_unit_words'], 2)
        self.assertEqual(stats['total_freq'], 16)
        self.assertEqual(stats['duplicate_gbk'], 1)
        self.assertEqual(stats['non_han'], 2)
        self.assertEqual(stats['over_max_units'], 1)
        self.assertEqual(records(blob), {word.encode('gbk'): round(math.log(16 / frequency) * 256)
                                      for word, frequency in [('甲', 5), ('乙', 4), ('甲乙', 7)]})
        reverse_blob, reverse_stats = builder.build_table(('\n'.join(reversed(lines)) + '\n').encode('utf8'))
        self.assertEqual(blob, reverse_blob)
        self.assertEqual(stats, reverse_stats)
        self.assertEqual(builder.render_module(blob, stats), builder.render_module(reverse_blob, reverse_stats))

    def test_zero_cost_singleton_and_maximum_word_size(self):
        blob, stats = builder.build_table('一二三四五六七八 1 n\n'.encode('utf8'))
        self.assertEqual(lexicon.validate_lexicon(blob)['fallback_cost'], 0)
        self.assertEqual(list(records(blob).values()), [0])
        self.assertEqual(stats['total_freq'], 1)

    def test_reject_malformed_source_and_frequency_overflow(self):
        cases = [b'', b'ASCII 1 x', b'bad', '甲 0 n'.encode(), '甲 -1 n'.encode(),
                 '甲 invalid n'.encode(), '甲 4294967296 n'.encode(),
                 '甲 4294967295 n\n乙 1 n'.encode(), b'\xff']
        for data in cases:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                builder.build_table(data)
        with self.assertRaises(TypeError):
            builder.build_table('甲 1 n')

    def test_reject_header_section_and_frequency_corruption(self):
        blob, _stats = builder.build_table('甲 10 n\n乙 20 n\n甲乙 30 n\n'.encode())
        fields = list(struct.unpack_from('<4sHH7I', blob))
        corruptions = {0: b'NOPE', 1: 2, 2: 9, 3: 0, 4: 65536,
                       5: 40, 6: fields[6] + 1, 7: fields[7] + 2,
                       8: len(blob) - 1, 9: 2}
        for field, value in corruptions.items():
            changed = fields.copy()
            changed[field] = value
            invalid = struct.pack('<4sHH7I', *changed) + blob[36:]
            with self.subTest(field=field), self.assertRaises(ValueError):
                lexicon.validate_lexicon(invalid)
        for invalid in (b'', blob[:35], blob[:-1], blob + b'\0'):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                lexicon.validate_lexicon(invalid)
        with self.assertRaises(TypeError):
            lexicon.validate_lexicon(bytearray(blob))

    def test_reject_offset_word_order_encoding_and_cost_corruption(self):
        blob, _stats = builder.build_table('甲 10 n\n乙 20 n\n丙 30 n\n'.encode())
        header = lexicon.validate_lexicon(blob)
        mutations = []
        for offset, value in [(36, 1), (40, 0), (40, 1), (40, 8), (48, 7)]:
            changed = bytearray(blob)
            struct.pack_into('<I', changed, offset, value)
            mutations.append(bytes(changed))
        changed = bytearray(blob)
        struct.pack_into('<H', changed, header['costs_off'], header['fallback_cost'] + 1)
        mutations.append(bytes(changed))
        for word in (b'\xff\xff', b'\x00\x00', '。'.encode('gbk')):
            changed = bytearray(blob)
            changed[header['strings_off']:header['strings_off'] + 2] = word
            mutations.append(bytes(changed))
        changed = bytearray(blob)
        start = header['strings_off']
        changed[start:start + 2] = changed[start + 2:start + 4]
        mutations.append(bytes(changed))
        changed = bytearray(blob)
        changed[start:start + 6] = changed[start:start + 6][::-1]
        mutations.append(bytes(changed))
        for index, invalid in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                lexicon.validate_lexicon(invalid)

    def test_offline_source_fingerprint_rejects_unpinned_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'dictionary.txt'
            source.write_bytes('甲 10 n\n'.encode())
            with patch.object(builder.urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')):
                with self.assertRaisesRegex(ValueError, 'Pinned source fingerprint'):
                    builder.read_source(source, 'jieba/dict.txt', builder.DICT_SHA256)


if __name__ == '__main__':
    unittest.main()
