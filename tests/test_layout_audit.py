"""Metadata audit checks from synthetic bytecode, without game text fixtures."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'tools'))
from build_font_settings import Builder, SIZES
from audit_layout import (audit_script, capacity, config_metadata, geometry,
                          parameter_capacity, translation_table_metadata)


def script(code):
    return (struct.pack('<16sIII',b'MajiroObjV1.000\0',0,1,1)
            + struct.pack('<II',0x1234,0) + struct.pack('<I',len(code)) + code)


class LayoutAuditTests(unittest.TestCase):
    def test_nominal_capacity_requires_entire_last_line(self):
        self.assertEqual([capacity(560,220,s)['rows'] for s in SIZES],[8,7,6,5,5,4])
        self.assertEqual(capacity(560,43,44)['rows'],0)
        self.assertEqual(capacity(560,44,44)['rows'],1)
        self.assertTrue(geometry(55,514,690,166)['outside_800x600'])

    def test_constant_geometry_and_unknown_operands_are_separated(self):
        b = Builder().op('line',42)
        for value in [60,560,356,180,123]: b.integer(value)
        b.syscall(0x403960F8,5)
        for value in [88,690,402]: b.integer(value)
        b.load(0x9876).integer(123).syscall(0x403960F8,5)
        result = audit_script(script(b.ret().finish()))
        first,second = result['console_rectangles']
        self.assertEqual((first['width'],first['height'],first['line']),(560,60,42))
        self.assertIn('unresolved_arguments_in_push_order',second)

    def test_report_does_not_return_literal_text(self):
        source = 'PRIVATE SYNTHETIC SENTENCE'
        result = audit_script(script(Builder().text(source).syscall(0x35A89417,1).ret().finish()))
        self.assertNotIn(source,str(result))
        self.assertEqual(result['longest_text_operands'][0]['bytes'],len(source))

    def test_config_reports_only_font_parameters(self):
        result = config_metadata(b'// CONFONT\r\nPrivate Face, 0 // face\r\n17, 8, 20 // size\r\n// OTHER\r\nPRIVATE\r\n')
        self.assertEqual(result,[{'marker':'CONFONT','line':1,'parameters':[17,8,20]}])

    def test_font_parameter_capacity_and_canvas_clipping_differ(self):
        self.assertEqual(parameter_capacity(690,88,40,20,44)['rows'],2)
        self.assertEqual(parameter_capacity(690,81,40,20,44)['rows'],1)
        b = Builder().op('line',2).integer(4).op('bne.case',0)
        for value in [88,690,490,90,123]: b.integer(value)
        b.syscall(0x403960F8,5)
        b.load(0xB5788291).load(0x65615B45).load(0x721A4F06).integer(2).op('sub.i')
        b.load(0x65615B45).integer(4).op('sub.i').load(0x391053C5,kind=2).syscall(0x06B3C8AC,5)
        result = audit_script(script(b.ret().finish()))
        rect = result['console_rectangles'][0]
        self.assertEqual(rect['nearest_case_constant'],4)
        self.assertEqual(rect['script_parameter_capacity'][-1]['declared_rectangle']['rows'],2)

    def test_opening_blocks_return_breaks_and_lengths_without_text(self):
        b = Builder().integer(4).call(0x35395C9F,1)
        b.op('text','合成'.encode('cp932')+b'\0').op('ctrl',b'n\0')
        b.op('text',b'ABC\0').op('ctrl',b'p\0').op('ctrl',b'w\0')
        block = audit_script(script(b.ret().finish()))['opening_text_blocks'][0]
        self.assertEqual(block['linear_mode_hint'],4)
        self.assertEqual([s['nominal_half_width_cells'] for s in block['text_operands']],[4,3])
        self.assertEqual([c['code'] for c in block['controls']],['n','p','w'])

    def test_rectangle_arithmetic_uses_result_rather_than_anchor_literal(self):
        b = Builder().integer(88).integer(690).integer(402).integer(14).op('add.i')
        b.integer(40).op('sub.i').integer(90).integer(123).syscall(0x403960F8,5)
        rect = audit_script(script(b.ret().finish()))['console_rectangles'][0]
        self.assertEqual((rect['y'],rect['bottom']),(376,464))

    def test_branch_does_not_reuse_values_from_a_different_path(self):
        b = Builder().integer(88).integer(690).integer(402).integer(90)
        b.op('br',0).integer(123).syscall(0x403960F8,5)
        rect = audit_script(script(b.ret().finish()))['console_rectangles'][0]
        self.assertIn('unresolved_arguments_in_push_order',rect)

    def test_translation_encoding_is_detected_per_table_without_text(self):
        for encoding in ('utf-16','gbk'):
            with self.subTest(encoding=encoding):
                report = translation_table_metadata('合成\r\nABC'.encode(encoding))
                self.assertEqual(report['encoding'],encoding)
                self.assertEqual(report['line_count'],2)
                self.assertEqual(report['first_eight_lines'][0]['full_width_characters'],2)
                self.assertNotIn('合成',str(report))


if __name__ == '__main__':
    unittest.main()
