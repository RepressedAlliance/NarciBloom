"""Owned neutral GBK cases, independent of story resources and C implementation."""
import random

def units(data):
    result = []
    at = 0
    while at < len(data):
        step = 1 if data[at] < 0x80 else 2
        result.append((at, step))
        at += step
    return result


def case(name, text, limit, cut_units=None, **extra):
    data = text.encode('gbk') if isinstance(text, str) else text
    cells = units(data)
    if cut_units is None:
        total = 0
        cut_units = 0
        for _, step in cells:
            advance = 5 if step == 1 else 10
            if total + advance > limit:
                break
            total += advance
            cut_units += 1
    cut = cells[cut_units][0] if cut_units < len(cells) else len(data)
    return dict(name=name, hex=data.hex(), width=limit, cut=cut,
                oracle='invariants', **extra)


def build_cases():
    cases = [
        case('closing_only_tail', '甲乙丙丁。', 40, forbid_closing_start=True),
        case('multiple_closing_tail', '甲乙丙丁。）', 40, forbid_closing_start=True),
        case('single_han_tail', '甲乙丙丁戊。', 40),
        case('multiple_han_tail', '甲乙丙丁戊己庚。', 40),
        case('single_character_answer', '好。', 40, unchanged=True),
        case('two_character_answer', '可以。', 40, unchanged=True),
        case('question_particle', '今天阅读文字可以吗？', 80, expected_cut=12),
        case('question_particle_ne', '测试页面现在正常呢？', 80, expected_cut=12),
        case('common_word_temperature', '检查空气温度是否稳定。', 50, expected_cut=8),
        case('common_word_button', '这里显示按钮状态。', 50, expected_cut=8),
        case('common_word_reading', '继续阅读文字内容。', 50, expected_cut=8),
        case('common_word_library', '打开图书馆测试页面。', 50),
        case('common_word_natural', '这里使用自然语言样本。', 60),
        case('unlisted_word_colour', '样例采用黯蓝天空背景。', 50, expected_cut=8),
        case('unlisted_word_cold', '测试冷冽微风吹过窗口。', 30, expected_cut=4),
        case('unlisted_word_distant', '测试疏淡色彩映在纸上。', 30, expected_cut=4),
        case('unlisted_word_moss', '测试苔痕爬满了石阶。', 30, expected_cut=4),
        case('unlisted_word_name', '测试祈月回到了这里。', 30, expected_cut=4),
        case('unlisted_word_window', '测试窗边摆放阅读材料。', 30, expected_cut=4),
        case('common_singletons_not_joined', '我们中出了一个叛徒。', 30, expected_cut=6),
        case('ascii_word', '测试 alpha 页面。', 65, expected_cut=10),
        case('ascii_sentence_spaces', 'A short neutral sentence.', 60, expected_cut=8),
        case('ascii_digit_mix', '项目 version2026 状态正常。', 70),
        case('numeric_run', '当前值为1234567890。', 70, expected_cut=8),
        case('decimal_number', '读数为123.45单位。', 55),
        case('ascii_overwide_word', 'abcdefghijklmnopqrstuvwx。', 30),
        case('narrow_cjk', '甲乙丙丁。', 10),
        case('overwide_glyph', '甲乙丙丁。', 5),
        case('no_cosmetic_third_line', '甲乙丙丁戊己庚辛。', 50),
        case('existing_three_lines', '甲乙丙丁戊己庚辛壬癸子丑。', 50),
        case('open_bracket', '甲乙（测试文字）。', 50),
        case('closing_cluster', '甲乙丙丁戊。】）', 60),
        case('leading_ascii_space', ' 甲乙丙丁戊。', 45),
        case('fullwidth_space', '甲乙\u3000丙丁戊。', 50),
        case('pipe_control', '甲乙|丙丁戊。', 40, unchanged=True),
        case('backslash_control', '甲乙\\丙丁戊。', 40, unchanged=True),
        case('linefeed_control', '甲乙\n丙丁戊。', 40, unchanged=True),
        case('invalid_gbk_trail', bytes.fromhex('bcd7d2d2817fb6a1a1a3'), 40, unchanged=True),
        case('dangling_gbk_lead', bytes.fromhex('bcd7d2d2b1fb81'), 30, unchanged=True),
        case('pending_pointer_mismatch', '甲乙丙丁戊。', 40, pointer_mismatch=True, unchanged=True),
        case('length_mismatch', '甲乙丙丁戊。', 40, length_delta=1, unchanged=True),
        case('length_over_capacity', '甲乙丙丁戊。', 40, original_length=1024, unchanged=True),
        case('null_rectangle', '甲乙丙丁戊。', 40, null_rectangle=True, unchanged=True),
        case('vertical_layout', '甲乙丙丁戊。', 40, vertical=True, unchanged=True),
        case('indent_over_width', '甲乙丙丁戊。', 40, indent=41, unchanged=True),
        case('zero_usable_width', '甲乙丙丁戊。', 40, indent=40, unchanged=True),
        case('null_output', '甲乙丙丁戊。', 40, null_output=True, unchanged=True),
        case('capacity_1023', '甲' * 510 + 'a。', 100),
    ]
    # The odd-sized 1023-byte original exercises capacity without invalid GBK.
    assert len(bytes.fromhex(cases[-1]['hex'])) == 1023
    cases.extend([
        case('native_width_negative', '甲乙丙丁。', 40, width_negative=True, unchanged=True),
        case('native_width_zero', '甲乙丙丁。', 40, width_zero=True, unchanged=True),
        case('long_pending_closing_cluster_too_wide', '甲乙丙丁' + '。' * 5 + '戊' * 10, 40, unchanged=True),
        case('long_pending_closing_cluster_fits', '甲乙丙丁。' + '戊' * 10, 40, forbid_closing_start=True),
        case('null_pending_global', '甲乙丙丁戊。', 40, null_pending=True, unchanged=True),
        case('probe_shadow_rect_distinct_origin_cursor_indent', '检查空气温度是否稳定。',
             57, indent=7, origin_x=321, cursor_x=654, expected_cut=8),
        case('probe_shadow_rect_all_27_fields', '甲乙丙丁。', 40,
             origin_x=705, cursor_x=777, forbid_closing_start=True),
    ])
    for fail_at in (2, 3, 4, 5):
        cases.append(case(f'native_width_negative_call_{fail_at}', '甲乙丙丁。', 40,
                          width_negative=True, measure_fail_at=fail_at, unchanged=True))
        cases.append(case(f'native_width_zero_call_{fail_at}', '甲乙丙丁。', 40,
                          width_zero=True, measure_fail_at=fail_at, unchanged=True))
    rng = random.Random(20261022)
    tokens = ['甲', '乙', '丙', '丁', '阅读', '文字', '页面', '测试',
              'alpha', 'beta', '2026', '123.45', ' ', '。', '？', '）', '（']
    for number in range(256):
        text = ''.join(rng.choice(tokens) for _ in range(rng.randint(2, 40)))
        cases.append(case(f'property_{number:03}', text, rng.choice([15, 25, 40, 55, 70, 100])))
    for item in cases:
        item['max_buffer'] = 1024
    return cases
