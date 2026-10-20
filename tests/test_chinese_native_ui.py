"""Synthetic native templates and x86 snippets; no game resources or text."""
from pathlib import Path
from types import SimpleNamespace
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import chinese_native_ui as ui


def wide(text):
    return text.encode('utf-16le') + b'\0\0'


def dialog(extended=False):
    if extended:
        data = struct.pack('<HHIIIHhhhh', 1, 0xffff, 0, 0, 0x40, 1, 0, 0, 80, 30)
    else:
        data = struct.pack('<IIHhhhh', 0x40, 0, 1, 0, 0, 80, 30)
    data += b'\0\0' * 2 + wide('测试窗口')
    data += struct.pack('<HHBB', 9, 400, 0, 134) if extended else struct.pack('<H', 9)
    data += wide('SimSun')
    data += b'\0' * (-len(data) % 4)
    if extended:
        data += struct.pack('<IIIhhhhI', 0, 0, 0x50010003, 1, 1, 50, 10, 1005)
    else:
        data += struct.pack('<IIhhhhH', 0x50010003, 0, 1, 1, 50, 10, 1005)
    return data + b'\xff\xff\x80\0' + wide('关闭语音') + b'\0\0'


class ChineseNativeUITests(unittest.TestCase):
    def test_parse_standard_and_extended_templates_without_changing_other_bytes(self):
        for extended in (False, True):
            with self.subTest(extended=extended):
                source = dialog(extended)
                fields = ui._dialog_fields(source)
                self.assertEqual([(ident, field[2]) for ident, field in fields],
                                 [(None, '测试窗口'), (1005, '关闭语音')])
                result = bytearray(source)
                offset, size, _ = fields[1][1]
                ui._put_text(result, offset, size, '静音')
                self.assertEqual(len(source), len(result))
                self.assertEqual(source[:offset], result[:offset])
                self.assertEqual(source[offset + size:], result[offset + size:])
                self.assertEqual(ui._dialog_fields(bytes(result))[1][1][2], '静音  ')

    def test_truncated_and_unsupported_resources_fail(self):
        for blob in (b'', dialog()[:-1], b'\0' * 17):
            with self.subTest(length=len(blob)), self.assertRaises(ValueError):
                ui._dialog_fields(blob)
        with self.assertRaises(ValueError):
            ui._menu_fields(struct.pack('<HH', 1, 0))

    def test_menu_nesting_and_shortcuts_survive_translation(self):
        source = (struct.pack('<HHH', 0, 0, 0x90) + wide('ファイル(&F)')
                  + struct.pack('<HH', 0x80, 77) + wide('セーブ(&S)\tF2'))
        fields = ui._menu_fields(source)
        self.assertEqual(fields[1][0], 77)
        self.assertEqual(ui._menu_translation(fields[0][1][2]), '文件(&F)')
        self.assertEqual(ui._menu_translation(fields[1][1][2]), '保存(&S)\tF2')
        self.assertEqual(ui._menu_translation('コンフィグ(F9)...'), '设置(F9)...')
        self.assertIsNone(ui._menu_translation('Unrelated label'))

    def test_oversized_caption_is_rejected_before_mutation(self):
        result = bytearray(b'abcdefgh')
        with self.assertRaises(ValueError):
            ui._put_text(result, 0, 4, '过长文本')
        self.assertEqual(result, b'abcdefgh')

    def test_volume_endpoints_fit_the_original_narrow_static_controls(self):
        self.assertEqual(ui._DIALOG_LABELS['最小'], '低')
        self.assertEqual(ui._DIALOG_LABELS['最大'], '高')
        for original in ('最小', '最大'):
            field = bytearray(wide(original))
            ui._put_text(field, 0, len(field), ui._DIALOG_LABELS[original])
            self.assertEqual(field.decode('utf-16le').rstrip('\0 '), ui._DIALOG_LABELS[original])

    def test_voice_guard_balances_stack_and_preserves_absolute_operands(self):
        pointer, iat = 0x4c0000, 0x4b0000
        for call in (b'\x57\xff\xd6', b'\x56\xff\xd7',
                     b'\x57\xff\x15' + struct.pack('<I', iat)):
            with self.subTest(call=call.hex()):
                original = (b'\x68' + struct.pack('<I', pointer) + b'\x68\xed\x03\0\0'
                            + call + b'\x90' * 8)
                result = bytearray(original)
                skip = ui._skip_voice_overwrite(original, result, 0, pointer, iat)
                self.assertEqual(skip, len(call))
                self.assertEqual(result[:5], original[:5])
                self.assertEqual(result[10:], original[10:])
                self.assertEqual(result[5:10], b'\x83\xc4\x04\xeb' + bytes([len(call)]))
                # PUSH pointer costs 4 bytes, ADD ESP,4 cancels exactly that
                # argument. JMP resumes after the untouched HWND push/call.
                self.assertEqual(10 + result[9], 10 + len(call))
                # Simulate relocation of both retained absolute operands.
                for operand in ([1, 13] if len(call) == 7 else [1]):
                    old = bytes(result[operand:operand + 4])
                    result[operand:operand + 4] = struct.pack('<I', struct.unpack('<I', old)[0] + 0x210000)
                self.assertEqual(result[5:10], b'\x83\xc4\x04\xeb' + bytes([len(call)]))

    def test_unknown_voice_arguments_or_call_are_rejected(self):
        original = b'\x68' + struct.pack('<I', 0x4c0000) + b'\x68\xed\x03\0\0\x57\xff\xd6'
        for wrong in (original[:5] + b'\x68\xec\x03\0\0' + original[10:],
                      original[:10] + b'\x57\xff\xd0'):
            with self.assertRaises(ValueError):
                ui._skip_voice_overwrite(wrong, bytearray(wrong), 0, 0x4c0000, 0x4b0000)

    def test_stock_or_unknown_engines_fail_before_parsing(self):
        with self.assertRaisesRegex(ValueError, 'unsupported restored Chinese'):
            ui.localize_chinese_native_ui(b'not a supported Chinese engine')

    def test_existing_native_dialogs_default_does_not_call_chinese_extension(self):
        import chinese_builder
        section = SimpleNamespace(Name=b'.rsrc', PointerToRawData=0, SizeOfRawData=0)
        with patch.object(chinese_builder.pefile, 'PE', return_value=SimpleNamespace(sections=[section])), \
             patch.object(ui, 'localize_chinese_native_ui', return_value=(b'CN', {'localized': True})) as localize:
            stock, report = chinese_builder.native_dialogs(b'')
            self.assertEqual(stock, b'')
            self.assertNotIn('localized', report)
            localize.assert_not_called()
            chinese, report = chinese_builder.native_dialogs(b'', chinese=True)
            self.assertEqual(chinese, b'CN')
            self.assertTrue(report['localized'])
            localize.assert_called_once_with(b'', baseline=b'')


if __name__ == '__main__':
    unittest.main()
