"""Synthetic environment fields; no full game resource fixtures."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from window_title import TITLES, patch_titlebar


class WindowTitleTests(unittest.TestCase):
    originals = {
        'narci_onetwo': ('ナルキッソス1+2', 'Narcissu 1 & 2'),
        'narci_himeko': ('雨のマージナル', "Narcissu - Himeko's Epilgoue"),
        'narci_iris': ('ナルキッソス外伝－小さなイリス－', 'Narcissu : A Little Iris'),
        'narci_sumire': ('ナルキッソス－スミレ－', 'Narcissu : Sumire'),
        'narci_zero': ('ナルキッソス０－ZERO－', 'Narcissu : Zero'),
    }

    def test_all_five_japanese_and_english_inputs_use_complete_ascii_tokens(self):
        for game, variants in self.originals.items():
            for original in variants:
                with self.subTest(game=game, original=original):
                    source = b'TITLEBAR\t\t' + original.encode('cp932') + b'\r\n'
                    result, report = patch_titlebar(game, source)
                    token = result.split(b'\t\t', 1)[1].rstrip(b'\r\n')
                    self.assertNotIn(b' ', token)
                    self.assertEqual(token.decode('ascii').replace('|', ' '), TITLES[game])
                    self.assertEqual(report['title_ascii'], TITLES[game])

    def test_only_value_changes_registry_save_fields_comments_and_line_endings_stay(self):
        for newline in (b'\r\n', b'\n'):
            prefix = newline.join([b'// TITLEBAR fake', b'REG_LOCAL\tunchanged-save-key',
                                    b'REG_GLOBAL\tunchanged-global-key']) + newline
            suffix = newline + b'SAVEDIR\tsave_chs' + newline + b'OTHER\tuntouched\xff'
            original = 'ナルキッソス外伝－小さなイリス－'.encode('cp932')
            source = prefix + b'TITLEBAR \t' + original + suffix
            result, _ = patch_titlebar('narci_iris', source)
            self.assertEqual(result, prefix + b'TITLEBAR \tNarcissu|:|A|Little|Iris' + suffix)

    def test_already_normalized_input_is_idempotent_and_no_final_newline_is_needed(self):
        source = b'TITLEBAR\tNarcissu|:|A|Little|Iris'
        result, report = patch_titlebar('narci_iris', source)
        self.assertEqual(result, source)
        self.assertFalse(report['changed'])

    def test_unknown_missing_duplicate_and_malformed_fields_fail(self):
        valid = b'TITLEBAR\tNarcissu : A Little Iris\r\n'
        invalid = [b'', b'REG_LOCAL\tNarcissu\r\n', valid + valid,
                   valid + b' TITLEBAR\tNarcissu\r\n', b'TITLEBAR\r\n',
                   b' TITLEBAR\tNarcissu : A Little Iris\r\n',
                   b'TITLEBAR\tCustom title\r\n', valid + b'TITLEBAR\r\n']
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                patch_titlebar('narci_iris', source)
        with self.assertRaises(ValueError):
            patch_titlebar('unknown', valid)
        with self.assertRaises(ValueError):
            patch_titlebar('narci_iris', None)


if __name__ == '__main__':
    unittest.main()
