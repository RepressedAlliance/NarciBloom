"""Owned synthetic PEs/payloads only; no game, translation or save fixtures."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import native_layout as layout
import native_layout_generated as generated


def synthetic_pe(profile):
    """Minimal actual PE with caller-owned neighboring bytes and a relocation."""
    raw_size = 0x50000
    data = bytearray(b'\0' * 0x200 + b'\xcc' * raw_size)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x14c, 1, 0, 0, 0, 0xe0, 0x102)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x10b)
    struct.pack_into('<IIII', data, opt + 4, raw_size, 0, 0, 0x1000)
    struct.pack_into('<III', data, opt + 20, 0x1000, 0, 0x400000)
    struct.pack_into('<II', data, opt + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, opt + 56, 0x51000, 0x200)
    struct.pack_into('<HH', data, opt + 68, 2, 0x140)
    struct.pack_into('<IIIIII', data, opt + 72, 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    struct.pack_into('<II', data, opt + 96 + 5 * 8, 0x4f000, 12)
    struct.pack_into('<8sIIIIIIHHI', data, 0x178, b'.text\0\0\0', raw_size, 0x1000,
                     raw_size, 0x200, 0, 0, 0, 0, 0x60000020)
    struct.pack_into('<IIHH', data, 0x200 + 0x4e000, 0x1000, 12, 0x3100, 0)
    for site, _label, call_target, stolen in layout._sites(profile):
        instruction = stolen if stolen is not None else b'\xe8' + struct.pack('<i', call_target - site - 5)
        offset = 0x200 + site - 0x1000
        data[offset:offset + len(instruction)] = instruction
    return bytes(data) + b'OWNED SYNTHETIC OVERLAY'


def run_spacing_x86(arguments):
    """Small instruction interpreter for the *generated* freestanding policy.

    This executes moves/arithmetic/branches from its bytes, not a second policy
    implementation. An unsupported instruction fails instead of being ignored.
    """
    code = generated.SPACING
    regs = dict(eax=0xaaaaaaaa, ecx=0xbbbbbbbb, edx=0xcccccccc,
                esi=0x12345678, ebp=0, esp=0x10000)
    memory = {0x10000: 0}
    memory.update({0x10004 + 4 * n: value for n, value in enumerate(arguments)})
    initial_esi = regs['esi']
    zero = False
    pc = 0
    def push(value):
        regs['esp'] -= 4
        memory[regs['esp']] = value
    def pop():
        value = memory[regs['esp']]
        regs['esp'] += 4
        return value
    for _ in range(100):
        if code[pc] == 0x55:
            push(regs['ebp']); pc += 1
        elif code[pc] == 0x56:
            push(regs['esi']); pc += 1
        elif code[pc:pc + 2] == b'\x89\xe5':
            regs['ebp'] = regs['esp']; pc += 2
        elif code[pc:pc + 2] in (b'\x8b\x45', b'\x8b\x4d', b'\x8b\x55'):
            target = {0x45: 'eax', 0x4d: 'ecx', 0x55: 'edx'}[code[pc + 1]]
            regs[target] = memory[regs['ebp'] + code[pc + 2]]; pc += 3
        elif code[pc:pc + 2] == b'\x83\x7d':
            zero = memory[regs['ebp'] + code[pc + 2]] == code[pc + 3]; pc += 4
        elif code[pc] in (0x74, 0x75, 0xeb):
            opcode, delta = code[pc], struct.unpack_from('<b', code, pc + 1)[0]
            pc += 2
            if opcode == 0xeb or (zero if opcode == 0x74 else not zero): pc += delta
        elif code[pc:pc + 2] == b'\x81\xf9':
            zero = regs['ecx'] == struct.unpack_from('<I', code, pc + 2)[0]; pc += 6
        elif code[pc:pc + 2] == b'\x89\xc1':
            regs['ecx'] = regs['eax']; pc += 2
        elif code[pc:pc + 2] == b'\xd1\xe9':
            regs['ecx'] >>= 1; zero = regs['ecx'] == 0; pc += 2
        elif code[pc:pc + 2] == b'\x29\xc8':
            regs['eax'] = (regs['eax'] - regs['ecx']) & 0xffffffff; zero = regs['eax'] == 0; pc += 2
        elif code[pc:pc + 2] == b'\x83\xf1':
            regs['ecx'] ^= code[pc + 2]; zero = regs['ecx'] == 0; pc += 3
        elif code[pc:pc + 2] == b'\x33\x55':
            regs['edx'] ^= memory[regs['ebp'] + code[pc + 2]]; zero = regs['edx'] == 0; pc += 3
        elif code[pc:pc + 2] == b'\x0b\x4d':
            regs['ecx'] |= memory[regs['ebp'] + code[pc + 2]]; zero = regs['ecx'] == 0; pc += 3
        elif code[pc:pc + 2] == b'\x31\xf6':
            regs['esi'] = 0; zero = True; pc += 2
        elif code[pc:pc + 2] == b'\x09\xd1':
            regs['ecx'] |= regs['edx']; zero = regs['ecx'] == 0; pc += 2
        elif code[pc:pc + 3] == b'\x0f\x44\xc6':
            if zero: regs['eax'] = regs['esi']
            pc += 3
        elif code[pc] == 0x5e:
            regs['esi'] = pop(); pc += 1
        elif code[pc] == 0x5d:
            regs['ebp'] = pop(); pc += 1
        elif code[pc] == 0xc3:
            if regs['esp'] != 0x10000 or regs['esi'] != initial_esi:
                raise AssertionError('Spacing policy failed its stack/nonvolatile ABI')
            return regs['eax']
        else:
            raise AssertionError(f'Unsupported generated instruction at {pc:x}')
    raise AssertionError('Generated spacing policy did not return')


class NativeLayoutTests(unittest.TestCase):
    def test_generated_sources_and_payload_hashes_match(self):
        for name, filename in [('TAIL', 'native_layout_tail.c'), ('SPACING', 'native_layout_spacing.c')]:
            source = (ROOT / 'tools' / filename).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(source).hexdigest(), getattr(generated, name + '_SOURCE_SHA256'))
            self.assertEqual(hashlib.sha256(getattr(generated, name)).hexdigest(), getattr(generated, name + '_SHA256'))

    def test_actual_spacing_machine_code_obeys_horizontal_origin_and_rounding(self):
        for width in range(0, 65):
            for horizontal in (0, 1):
                with self.subTest(width=width, horizontal=horizontal):
                    self.assertEqual(run_spacing_x86([width, 0xa1a1, 0, 180, 180, horizontal]),
                                     (width + 1) // 2 if horizontal else width)
                    self.assertEqual(run_spacing_x86([width, 0x20, 0, 180, 180, horizontal]),
                                     0 if horizontal else width)
                    # A new chunk in the middle of a line retains its English space.
                    self.assertEqual(run_spacing_x86([width, 0x20, 0, 200, 180, horizontal]), width)
                    self.assertEqual(run_spacing_x86([width, 0x20, 1, 180, 180, horizontal]), width)
                    self.assertEqual(run_spacing_x86([width, 0xa3ac, 0, 180, 180, horizontal]), width)

    def test_actual_pe_patch_preserves_localization_overlay_relocations_and_neighbors(self):
        for family, profile in layout._FAMILIES.items():
            with self.subTest(family=family):
                original = synthetic_pe(profile)
                baseline = bytearray(original); baseline[0x205] = 0x90
                result, report = layout._patch(original, bytes(baseline), 'synthetic', profile)
                old, new = pefile.PE(data=baseline, fast_load=True), pefile.PE(data=result, fast_load=True)
                self.assertEqual(new.OPTIONAL_HEADER.AddressOfEntryPoint, old.OPTIONAL_HEADER.AddressOfEntryPoint)
                self.assertEqual(new.OPTIONAL_HEADER.DllCharacteristics, old.OPTIONAL_HEADER.DllCharacteristics)
                self.assertEqual(new.sections[-1].Name.rstrip(b'\0'), b'.nblay')
                self.assertEqual(new.sections[-1].Characteristics, 0x60000020)
                self.assertEqual(result[0x205], 0x90)
                self.assertEqual(result[len(original) - 23:len(original)], original[-23:])
                self.assertEqual(new.get_data(0x4f000, 12), old.get_data(0x4f000, 12))
                allowed = set(range(0x80, 0x200))
                for item in report['patches']:
                    offset = item['file_offset']; size = len(bytes.fromhex(item['after']))
                    allowed.update(range(offset, offset + size))
                    for load_base in (0x400000, 0x18000000, 0x28000000):
                        delta = struct.unpack_from('<i', result, offset + 1)[0]
                        self.assertEqual(load_base + int(item['rva'], 16) + 5 + delta,
                                         load_base + int(item['target_rva'], 16))
                changed = {n for n, (a, b) in enumerate(zip(baseline, result)) if a != b}
                self.assertFalse(changed - allowed)

    def test_unknown_and_altered_inputs_fail_closed(self):
        with patch.object(layout.pefile, 'PE') as parse:
            with self.assertRaisesRegex(ValueError, 'Unsupported original Chinese'):
                layout.patch_chinese_native_layout(b'JA EN unknown')
            parse.assert_not_called()
        profile = layout._FAMILIES['onetwo']; original = synthetic_pe(profile)
        baseline = bytearray(original); baseline[0x200 + 0x48e99 - 0x1000] ^= 1
        with self.assertRaisesRegex(ValueError, 'changed a native layout hook'):
            layout._patch(original, bytes(baseline), 'synthetic', profile)
        baseline = bytearray(original); baseline[0x84 + 4] = 1
        with self.assertRaisesRegex(ValueError, 'changed PE structure'):
            layout._patch(original, bytes(baseline), 'synthetic', profile)

    def test_no_section_header_space_and_noncode_hook_are_rejected(self):
        profile = layout._FAMILIES['onetwo']; original = bytearray(synthetic_pe(profile))
        original[0x1a0] = 1
        with self.assertRaisesRegex(ValueError, 'section-header space'):
            layout._patch(bytes(original), bytes(original), 'synthetic', profile)
        original = bytearray(synthetic_pe(profile))
        struct.pack_into('<I', original, 0x178 + 36, 0x40000040)
        with self.assertRaisesRegex(ValueError, 'outside executable code'):
            layout._patch(bytes(original), bytes(original), 'synthetic', profile)

    def test_recognition_is_exactly_five_chinese_profiles(self):
        self.assertEqual(len(layout._ORIGINALS), 5)
        self.assertEqual({m for m, _ in layout._ORIGINALS.values()},
                         {'narci_onetwo', 'narci_iris', 'narci_himeko', 'narci_zero', 'narci_sumire'})


if __name__ == '__main__':
    unittest.main()
