"""Generic word-boundary cases, not scenario fixtures or a model benchmark."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_native_oov as builder
import native_oov as model
from native_lexicon import lookup_cost
from test_native_lexicon import segment


def refine(text):
    return model.refine_tokens(segment(text), lookup_cost)


class NativeOOVTests(unittest.TestCase):
    def test_pinned_model_contract_and_attribution(self):
        self.assertEqual(hashlib.sha256(model.MODEL).hexdigest(), model.MODEL_SHA256)
        self.assertEqual(model.MODEL_SHA256, 'd7fa1203be4dad8e8313a81d10138cea599c278f5e5d63c1a0b66a659c0d788e')
        self.assertEqual(model.HEADER['bytes'], 191592)
        self.assertEqual(model.SOURCE['commit'], builder.COMMIT)
        self.assertEqual({k: v['sha256'] for k, v in model.SOURCE['data'].items()}, builder.FINGERPRINTS)
        self.assertIn('MIT', model.SOURCE['license'])
        self.assertIn('Copyright (c) 2013 Sun Junyi', (ROOT / model.SOURCE['license_file']).read_text())

    def test_unlisted_words_and_new_contexts_are_not_a_word_override_list(self):
        # These are absent in the fixed lexicon. Different words and contexts
        # exercise generic data; this is not an independent accuracy benchmark.
        for word in ('黯蓝', '暗蓝', '冷冽', '疏淡', '苔痕', '窗边', '灰蓝', '霜白', '祈月'):
            with self.subTest(word=word):
                self.assertIsNone(lookup_cost(word.encode('gbk')))
                self.assertEqual(refine(word), [word])
        for text, word in [('界面采用黯蓝配色', '黯蓝'), ('窗边的灯亮了', '窗边'),
                           ('冷冽微风吹过', '冷冽'), ('苔痕已经干了', '苔痕')]:
            with self.subTest(text=text):
                self.assertIn(word, refine(text))
                self.assertEqual(''.join(refine(text)), text)

    def test_common_grammatical_singletons_are_not_glued(self):
        for text, expected in [('我们中出了一个叛徒', ['我们', '中', '出', '了', '一个', '叛徒']),
                               ('她什么也没说', ['她', '什么', '也', '没', '说']),
                               ('你和我都在这里', ['你', '和', '我', '都', '在', '这里']),
                               ('她的神情冷冽而疏淡', ['她', '的', '神情', '冷冽', '而', '疏淡'])]:
            with self.subTest(text=text):
                self.assertEqual(refine(text), expected)

    def test_word_boundaries_are_stable_as_complete_words_leave_the_line(self):
        texts = ['黯蓝天空', '她的神情冷冽而疏淡', '苔痕爬满了石阶',
                 '她在窗边阅读', '霜白灰蓝黯蓝', '祈月回到了这里',
                 '你和我都在这里', '南京市长江大桥', '浅碧雪乃']
        for text in texts:
            expected = refine(text)
            for index in range(len(expected)):
                suffix = ''.join(expected[index:])
                with self.subTest(text=text, suffix=suffix):
                    self.assertEqual(refine(suffix), expected[index:])

    def test_preserves_known_words_ascii_controls_and_missing_emissions(self):
        tokens = ['南京市', '长江大桥', 'alpha', ' ', '黯', '蓝', '。', '\\n', '𠀀']
        self.assertEqual(model.refine_tokens(tokens, lookup_cost),
                         ['南京市', '长江大桥', 'alpha', ' ', '黯蓝', '。', '\\n', '𠀀'])
        for text in ('', 'ASCII', '𠀀', '。', '一二三四五六七八九'):
            self.assertIsNone(model.word_cost(text))
        self.assertEqual(refine('研究生命起源'), ['研究', '生命', '起源'])
        self.assertEqual(refine('商品和服务行业'), ['商品', '和', '服务行业'])

    def test_literal_reader_does_not_execute_source(self):
        source = b"raise RuntimeError('must not execute')\nP = {'B': -0.5}\n"
        self.assertEqual(builder.probability_literals(source), {'B': -0.5})
        for source in (b'P = eval("1")', b'P = {}\nP = {}', b'X = {}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                builder.probability_literals(source)
        for value in (1, float('nan'), float('inf'), 'x'):
            with self.assertRaises(ValueError):
                builder.fixed_cost(value)

    def test_malformed_model_header_and_state_contract_rejected(self):
        for offset in range(0, 32, 4):
            changed = bytearray(model.MODEL)
            struct.pack_into('<I', changed, offset, 0)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                model.validate_model(bytes(changed))
        for offset in (32, 34, 40, 42):
            changed = bytearray(model.MODEL)
            original = struct.unpack_from('<H', changed, offset)[0]
            struct.pack_into('<H', changed, offset, 0 if original == 65535 else 65535)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                model.validate_model(bytes(changed))
        with self.assertRaises(TypeError):
            model.validate_model(bytearray(model.MODEL))


if __name__ == '__main__':
    unittest.main()
