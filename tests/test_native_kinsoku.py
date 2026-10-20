"""Raw config and native byte-class tests; no GDI/rendering simulation claim."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from native_kinsoku import chinese_kinsoku_env


# Independent encoding of the documented native defaults. Synthetic config;
# no extracted game configuration or story resource is included in this test.
ORIGINAL_START = 'ー、。，．」』）？！ぁぃぅぇぉっゃゅょゎァィゥェォャュョヮヵヶ゛゜ゝゞヽヾ\u301f・…：；‐】〕］｝〉》'
ORIGINAL_END = '「『（【‘“〔［｛〈《'


def environment(eol=b'\r\n'):
    return eol.join([
        b'; GYOUTOUKINSOKU ignored-comment',
        b'OTHER\t' + '無関係'.encode('cp932'),
        b'KINSOKU_TYPE\t\t0',
        b'GYOUTOUKINSOKU\t\t' + ORIGINAL_START.encode('cp932'),
        b'GYOUMATUKINSOKU \t' + ORIGINAL_END.encode('cp932'),
        b'UNRELATED  unchanged\x80\xff', b'',
    ])


def values(blob):
    return {key: re.search(rb'(?m)^' + key.encode() + rb'[ \t]+([^\r\n]*)', blob).group(1)
            for key in ('KINSOKU_TYPE', 'GYOUTOUKINSOKU', 'GYOUMATUKINSOKU')}


def native_member(table, character):
    """Independent CN1+2 MBCS membership walk (native 482a10 / lead81..fc).

    Only tests character-boundary membership. It does not emulate glyph widths,
    the line extractor's limited lookback, animation or pagination.
    """
    at = 0
    while at < len(table):
        if table.startswith(character, at):
            return True
        at += 2 if 0x81 <= table[at] <= 0xfc and at + 1 < len(table) else 1
    return False


class NativeKinsokuTests(unittest.TestCase):
    def test_reported_gbk_punctuation_and_bracket_roles(self):
        original = values(environment())
        patched, _ = chinese_kinsoku_env(environment())
        adapted = values(patched)
        for opening, closing in (('『', '』'), ('「', '」'), ('（', '）'), ('【', '】')):
            self.assertTrue(native_member(adapted['GYOUMATUKINSOKU'], opening.encode('gbk')))
            self.assertFalse(native_member(adapted['GYOUTOUKINSOKU'], opening.encode('gbk')))
            self.assertTrue(native_member(adapted['GYOUTOUKINSOKU'], closing.encode('gbk')))
        for character in '。』」？！、，':
            with self.subTest(character=character):
                self.assertFalse(native_member(original['GYOUTOUKINSOKU'], character.encode('gbk')))
                self.assertTrue(native_member(adapted['GYOUTOUKINSOKU'], character.encode('gbk')))

    def test_preserves_all_bytes_outside_two_values_and_is_idempotent(self):
        for eol in (b'\n', b'\r\n'):
            with self.subTest(eol=eol):
                original = environment(eol)
                patched, report = chinese_kinsoku_env(original)
                before, after = values(original), values(patched)
                reconstructed = patched
                for key in ('GYOUTOUKINSOKU', 'GYOUMATUKINSOKU'):
                    reconstructed = reconstructed.replace(after[key], before[key], 1)
                    self.assertLess(len(after[key]), 0x100)
                    self.assertEqual(after[key].replace(b'\xff', b'').decode('gbk').encode('gbk'),
                                     after[key].replace(b'\xff', b''))
                self.assertEqual(reconstructed, original)
                self.assertEqual(report['changed_line_one_based'], [4, 5])
                self.assertEqual(after['KINSOKU_TYPE'], b'0')
                again, repeated = chinese_kinsoku_env(patched)
                self.assertEqual(again, patched)
                self.assertTrue(repeated['already_patched'])
                self.assertEqual(repeated['changed_line_one_based'], [])

    def test_normal_letters_and_cross_cell_substring_do_not_match(self):
        adapted = values(chinese_kinsoku_env(environment())[0])
        for character in ('A', 'B', 'z', '1', ' ', '甲', '乙', '中', '文', '…', '—'):
            for key in ('GYOUTOUKINSOKU', 'GYOUMATUKINSOKU'):
                self.assertFalse(native_member(adapted[key], character.encode('gbk')))
        table, cross = '。」'.encode('gbk'), '！'.encode('gbk')
        self.assertIn(cross, table)  # Naive byte substring would misclassify it.
        self.assertFalse(native_member(table, cross))

    def test_all_valid_gbk_cells_match_only_expected_punctuation_in_both_engines(self):
        adapted = values(chinese_kinsoku_env(environment())[0])
        expected = {'GYOUTOUKINSOKU': set('、。，．？！：；）〕］｝〉》」』】〗”’'),
                    'GYOUMATUKINSOKU': set('（〔［｛〈《「『【〖“‘')}
        tested = 0
        for first in range(256):
            for cell in [bytes([first])] + [bytes([first, second]) for second in range(256)]:
                try:
                    character = cell.decode('gbk')
                except UnicodeDecodeError:
                    continue
                if len(character) != 1:
                    continue
                tested += 1
                for key, table in adapted.items():
                    if key not in expected:
                        continue
                    wanted = character in expected[key]
                    # Older Iris/Himeko/Zero use raw byte strstr. The newer
                    # onetwo/Sumire search visits MBCS character boundaries.
                    self.assertEqual(cell in table, wanted, (key, cell.hex(), 'strstr'))
                    self.assertEqual(native_member(table, cell), wanted, (key, cell.hex(), 'mbcs'))
        self.assertEqual(tested, 21919)

    def test_unknown_mode_tables_mixed_pair_and_duplicate_keys_are_rejected(self):
        original = environment()
        patched = chinese_kinsoku_env(original)[0]
        old, new = values(original), values(patched)
        candidates = [original.replace(b'KINSOKU_TYPE\t\t0', b'KINSOKU_TYPE\t\t1'),
                      original.replace(old['GYOUTOUKINSOKU'], b'custom'),
                      original.replace(old['GYOUMATUKINSOKU'], b'custom'),
                      original.replace(old['GYOUTOUKINSOKU'], new['GYOUTOUKINSOKU'])]
        for key in old:
            candidates.append(original + key.encode() + b' duplicate\r\n')
            candidates.append(original.replace(key.encode(), b'UNKNOWNKEY'))
        for candidate in candidates:
            with self.subTest(candidate_bytes=len(candidate)):
                with self.assertRaises(ValueError):
                    chinese_kinsoku_env(candidate)


if __name__ == '__main__':
    unittest.main()
