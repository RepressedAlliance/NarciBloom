"""Synthetic UI bytecode tests; no story scripts or game binaries are fixtures."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import chinese_builder as chinese
from build_font_settings import Builder, Script
from patch_narcissu_font import archive, entries


def ui_script(*labels):
    builder = Builder('cp932')
    for label in labels:
        builder.text(label).op('pop')
    code = builder.ret().finish()
    return (struct.pack('<16sIII', b'MajiroObjV1.000\0', 0, 1, 1)
            + struct.pack('<II', 123, 0) + struct.pack('<I', len(code)) + code)


def add_menu(original):
    script = Script(original)
    script.add(456, Builder('gbk').text('返回').op('pop').text('字号：').op('pop').ret().finish())
    return script.finish()


class ChineseBuilderTests(unittest.TestCase):
    def test_utf16_table_preserves_original_markers_and_appends_chinese(self):
        original = ui_script('フォント設定')
        patched = add_menu(original)
        changed = Script(patched)
        label = next(i for i in changed.ins if i.name == 'ldstr')
        replacement = '字体 / 字号'.encode('gbk') + b'\0'
        changed.code[label.offset + 4:label.offset + len(label.raw)] = replacement.ljust(len(label.fields['s']), b'\0')
        patched = changed.finish()
        source_table = '字体设置\r\n'.encode('utf-16')
        result, table, report = chinese.prepare_menu_translation(
            original, patched, source_table, replacements={'フォント設定': '字体 / 字号'})
        decoded = Script(result)
        first = next(i for i in decoded.ins if i.name == 'ldstr')
        self.assertEqual(first.fields['s'], 'フォント設定'.encode('cp932') + b'\0')
        self.assertEqual(table.decode('utf-16').splitlines(), ['字体 / 字号', '返回', '字号：'])
        self.assertEqual(report['added_records'], 2)
        for instruction in decoded.ins:
            if instruction.name == 'ldstr':
                instruction.fields['s'].rstrip(b'\0').decode('cp932')

    def test_table_encoding_is_detected_per_file_and_preserved(self):
        original = ui_script('設定')
        for encoding, table in [('gbk', '原菜单\r\n'.encode('gbk')),
                                ('utf-16-be', b'\xfe\xff' + '原菜单\r\n'.encode('utf-16-be'))]:
            with self.subTest(encoding=encoding):
                _, result, report = chinese.prepare_menu_translation(original, add_menu(original), table)
                records, actual = chinese._translation_lines(result)
                self.assertEqual(actual, encoding)
                self.assertEqual(records, ['原菜单', '返回', '字号：'])
                self.assertEqual(report['existing_records'], 1)

    def test_missing_config_table_retains_original_entries_and_adds_translations(self):
        original = ui_script('音量', '速度')
        _, table, report = chinese.prepare_menu_translation(original, add_menu(original))
        self.assertEqual(table.decode('utf-16').splitlines(), ['音量', '速度', '返回', '字号：'])
        self.assertEqual(report['existing_records'], 2)

    def test_loader_skips_ascii_prefixed_japanese_and_keeps_repeated_markers(self):
        original = ui_script(' / 音量 : ', '[ config.cfg ]パラメータ', '文字速度 : ', '文字速度 : ')
        result, table, report = chinese.prepare_menu_translation(original, add_menu(original))
        self.assertEqual(table.decode('utf-16').splitlines(), ['文字速度 : ', '文字速度 : ', '返回', '字号：'])
        self.assertEqual(report['existing_records'], 2)
        self.assertEqual(len(chinese._loader_literals(Script(result))), 4)
        self.assertEqual(Script(result).code[:len(Script(original).code)], Script(original).code)

    def test_rejects_mismatched_ui_table_and_story_text(self):
        original = ui_script('設定')
        with self.assertRaisesRegex(ValueError, 'count'):
            chinese.prepare_menu_translation(original, add_menu(original), b'')
        script = Script(original)
        script.add(789, Builder().op('text', '物語'.encode('cp932') + b'\0').ret().finish())
        story = script.finish()
        with self.assertRaisesRegex(ValueError, 'dialogue'):
            chinese.prepare_menu_translation(story, add_menu(story))

    def test_resource_precedence_preserves_stock_and_uses_loose_scripts_last(self):
        stock = {'config.mjo': b'stock config', 'console.mjo': b'stock console'}
        virtual = {'update.arc': archive({'console.mjo': b'arc console', 'other': b'a'}),
                   'update1.arc': archive({'other': b'b'}), '#mjo/console.mjo': b'loose console'}
        effective = chinese.effective_chinese_sources(stock, virtual)
        self.assertEqual(effective, {'config.mjo': b'stock config', 'console.mjo': b'loose console', 'other': b'b'})
        self.assertEqual(stock['console.mjo'], b'stock console')

    def test_payload_updates_loose_and_archive_with_the_same_bytecode(self):
        original = ui_script('設定')
        virtual = {'#mjo/config.mjo': original, '#txt/config.txt': '菜单\r\n'.encode('utf-16'),
                   'Narcissu_cn.dll': b'dll', 'update.arc': archive({'unrelated': b'original bytes'})}
        patched = add_menu(original)
        overrides = {'config.mjo': patched, 'console.mjo': original, 'load_sysdata.mjo': original}
        stock = {'config.mjo': original, 'console.mjo': original, 'load_sysdata.mjo': original}
        with patch.object(chinese, 'extract_virtual_files', return_value=virtual), \
             patch.object(chinese, 'restore_virtual_pe', return_value=b'PE'), \
             patch.object(chinese, 'native_dialogs', return_value=(b'PE', {})), \
             patch.object(chinese, '_caption_assignment', return_value=b'patched dll'), \
             patch.object(chinese, 'build_overrides', return_value=(overrides, {}, {}, {})):
            result = chinese.build_chinese_payload('narci_iris', b'packed', stock)
        self.assertIsInstance(result, chinese.ChineseBuild)
        self.assertEqual(result.executable, b'PE')
        self.assertEqual(result.payload['update.arc'], virtual['update.arc'])
        self.assertEqual(result.payload['Narcissu_cn.dll'], b'patched dll')
        generated = entries(result.payload['update12.arc'])
        for name in overrides:
            self.assertEqual(result.payload['#mjo/' + name], generated[name][2])
        self.assertEqual(result.payload['#txt/config.txt'].decode('utf-16').splitlines(), ['菜单', '返回', '字号：'])

    def test_caption_skip_preserves_operand_relocations_and_forwarding(self):
        data = b'prefix' + bytes.fromhex('c74510484203105dff254cb10310') + b'trailer'
        digest = chinese.hashlib.sha256(data).hexdigest()
        class Image:
            def get_offset_from_rva(self, rva):
                return 6
        with patch.object(chinese.pefile, 'PE', return_value=Image()):
            result = chinese._caption_assignment(data, digest, 0x3473, 'c7451048420310')
            self.assertEqual(result, data[:6] + b'\xeb\x05' + data[8:])
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                chinese._caption_assignment(data, 'wrong', 0x3473, 'c7451048420310')
            with self.assertRaisesRegex(ValueError, 'hook'):
                chinese._caption_assignment(data, digest, 0x3473, 'c7451000000000')

    def test_native_dialogs_keep_field_sizes_and_do_not_modify_archive_overlay(self):
        resource = ('フォント名\0セーブ(&S)\0').encode('utf-16le')
        prompt = '終了してよろしいですか？'.encode('cp932') + b'\0'
        preview = '文字サンプルです。１２３４'.encode('cp932') + b'\0'
        constants = b'\0' + prompt + preview
        overlay = b'ARCHIVE' + prompt + preview
        source = b'CODE' + resource + constants + overlay
        class Section:
            def __init__(self, name, start, size):
                self.Name, self.PointerToRawData, self.SizeOfRawData = name, start, size
        class Image:
            sections = [Section(b'.rsrc', 4, len(resource)),
                        Section(b'.rdata', 4 + len(resource), len(constants))]
        with patch.object(chinese.pefile, 'PE', return_value=Image()):
            result, report = chinese.native_dialogs(source)
        self.assertEqual(len(result), len(source))
        self.assertEqual(result[:4], b'CODE')
        self.assertEqual(result[-len(overlay):], overlay)
        self.assertIn('Font '.encode('utf-16le'), result)
        self.assertIn('&Save'.encode('utf-16le'), result)
        self.assertIn(b'Exit the game?', result)
        self.assertEqual(report['native_prompt_fields'], 1)
        self.assertEqual(report['native_caption_fields'], 2)
        self.assertEqual(report['native_preview_fields'], 1)


if __name__ == '__main__':
    unittest.main()
