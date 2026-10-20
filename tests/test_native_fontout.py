"""Synthetic instruction tests; no game or save resources are fixtures."""
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import native_fontout as ui


class NativeFontoutTests(unittest.TestCase):
    def fixture(self, instruction, language='ja', *, section_name=b'.text', executable=True):
        blob = b'prefix' + bytes.fromhex(instruction) + b'suffix'
        profile = ('synthetic-module', language, 0x401000, instruction)
        section = types.SimpleNamespace(Name=section_name,
                                        Characteristics=0x20000000 if executable else 0)
        image = types.SimpleNamespace(OPTIONAL_HEADER=types.SimpleNamespace(ImageBase=0x400000),
                                      get_section_by_rva=lambda _: section,
                                      get_offset_from_rva=lambda _: len(b'prefix'))
        return blob, {hashlib.sha256(blob).hexdigest(): profile}, image

    def apply(self, blob, profiles, image):
        with patch.object(ui, 'PROFILES', profiles), patch.object(ui.pefile, 'PE', return_value=image):
            return ui.stock_fontout(blob)

    def test_japanese_default_changes_only_the_charset_immediate(self):
        blob, profiles, image = self.fixture('c6050010400001')
        result, report = self.apply(blob, profiles, image)
        self.assertEqual([i for i, pair in enumerate(zip(blob, result)) if pair[0] != pair[1]], [12])
        self.assertEqual(result[12], 128)
        self.assertTrue(report['changed'])
        self.assertEqual(report['original_charset'], 1)

    def test_explicit_japanese_and_english_charsets_remain_unchanged(self):
        for language, opcode in [('ja', 'c7050010400000000080'), ('en', 'c7050010400000000000')]:
            with self.subTest(language=language):
                blob, profiles, image = self.fixture(opcode, language)
                result, report = self.apply(blob, profiles, image)
                self.assertEqual(result, blob)
                self.assertFalse(report['changed'])

    def test_unknown_and_modified_inputs_are_rejected_before_pe_parsing(self):
        with patch.object(ui.pefile, 'PE') as parser:
            with self.assertRaisesRegex(ValueError, 'Unsupported original stock'):
                ui.stock_fontout(b'unknown or Chinese engine')
            parser.assert_not_called()

    def test_wrong_instruction_or_non_code_section_is_rejected(self):
        blob, profiles, image = self.fixture('c6050010400001')
        broken = dict(profiles)
        key = next(iter(broken))
        broken[key] = (*broken[key][:3], 'c6050010400002')
        with self.assertRaisesRegex(ValueError, 'instruction differs'):
            self.apply(blob, broken, image)
        for section_name, executable in [(b'.data', True), (b'.text', False)]:
            blob, profiles, image = self.fixture('c6050010400001', section_name=section_name,
                                                  executable=executable)
            with self.assertRaisesRegex(ValueError, 'outside executable text'):
                self.apply(blob, profiles, image)

    def test_map_covers_only_the_ten_supported_stock_profiles(self):
        source = Path(__file__).resolve().parents[1] / 'docs/source-profiles.json'
        profiles = json.loads(source.read_text(encoding='utf8'))['profiles']
        self.assertEqual({p['exe_sha256'] for p in profiles}, set(ui.PROFILES))
        self.assertEqual(len(ui.PROFILES), 10)
        for p in profiles:
            self.assertEqual(ui.PROFILES[p['exe_sha256']][:2], (p['module'], p['language']))

    def test_backend_applies_charset_before_fixed_native_captions(self):
        import chinese_builder
        import installer_app_backend as backend
        with patch.object(ui, 'stock_fontout', return_value=(b'charset-patched', {'changed': True})) as charset, \
             patch.object(chinese_builder, 'native_dialogs', return_value=(b'final-engine', {})) as dialogs:
            result, report = backend._prepare_native_engine(b'original')
        charset.assert_called_once_with(b'original')
        dialogs.assert_called_once_with(b'charset-patched')
        self.assertEqual(result, b'final-engine')
        self.assertTrue(report['script_ui_charset']['changed'])


if __name__ == '__main__':
    unittest.main()
