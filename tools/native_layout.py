"""Apply display-only layout hooks to the five recognized Chinese v1.1 engines.

JA/EN engines are deliberately unsupported. The caller retains original restored
engine bytes for identity checks and may pass its localized executable as baseline.
No story/table/cache bytes, native waits, imports or entry points are replaced.
"""
from __future__ import annotations

import hashlib
import struct

import pefile

from native_layout_generated import SPACING, SPACING_SHA256, TAIL, TAIL_SHA256
from native_layout_x86 import build_payload
from native_lexicon import LEXICON_SHA256, WORD_COUNT, SOURCE as LEXICON_SOURCE
from native_oov import MODEL_SHA256, HEADER as MODEL_HEADER


_ORIGINALS = {
    '38819c6d3fd6a572a05a4b2c1bef18ba2a7411c43075e89675773851dda7c948': ('narci_onetwo', 'onetwo'),
    'cc634eec6b97538d508057b7cc81f4140d0d2a3df6fb70e0d585ebc559c108f9': ('narci_sumire', 'sumire'),
    '4a1b93637f41fda38f1bccacbaec5b81f841bc2ec87a4ff7ab09aa6d33e346f4': ('narci_iris', 'old3'),
    '7b6e5dad7dbbd8e7ac2dc4389e7b9a365bb6b9b8c2420a5e642a54a62e139618': ('narci_himeko', 'old3'),
    '07218e11bde45b98e50f0bf465aa8a91aa5f995b98a0c075d806c0148850709d': ('narci_zero', 'old3'),
}
_FAMILIES = {
    'onetwo': dict(family='onetwo', extract=0x45d60, extract_calls=(0x48e99,),
        measure=0x45c20, measure_calls=(0x46664, 0x475cc),
        measure_join=0x45d1d, extract_join=0x460d6,
        ascii_measure_trim=0x45d1c,
        measure_stolen='8b4d0c0101', extract_stolen='8b4de40145f8'),
    'sumire': dict(family='sumire', extract=0x42390, extract_calls=(0x44f5d,),
        pending=0x12cce4, measure=0x43fb0, measure_calls=(0x42f57, 0x466cc),
        no_start=0x43f00, no_end=0x43e50, vertical=0xc7e1c,
        measure_join=0x4409d, extract_join=0x426d7,
        ascii_measure_trim=0x4409c,
        measure_stolen='8b4d140101', extract_stolen='8b4dec0145fc'),
    'old3': dict(family='old3', handler=0x1e930, handler_calls=(0x1203f, 0x1dfc4),
        pending=0x118130, snapshot=0x1ed57, snapshot_stolen='c644246400',
        post=0x1f42e, post_stolen='8a44246484c0', measure=0x1a2e0,
        measure_calls=(0x1a201, 0x1a704), no_start=0x1f680, no_end=0x1f700,
        measure_join=0x1a3f2, extract_join=0x1efa1,
        ascii_measure_trim=0x1a3f1,
        measure_stolen='8b138b4c242c', extract_stolen='8b4c24388b742414'),
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _align(value, alignment):
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError('Invalid native PE alignment')
    return (value + alignment - 1) // alignment * alignment


def _sites(profile):
    """Enumerated callsites and complete, instruction-aligned stolen sequences."""
    outer = 'handler' if profile['family'] == 'old3' else 'extract'
    for site in profile[outer + '_calls']:
        yield site, 'entry', profile[outer], None
    for site in profile['measure_calls']:
        yield site, 'measure_wrapper', profile['measure'], None
    for stem in ('measure', 'extract'):
        yield profile[stem + '_join'], stem + '_join', None, bytes.fromhex(profile[stem + '_stolen'])
    if profile['family'] == 'old3':
        for stem in ('snapshot', 'post'):
            yield profile[stem], stem, None, bytes.fromhex(profile[stem + '_stolen'])


def _patch(original, baseline, module, profile):
    """Internal patcher separated from identity selection for synthetic PE tests."""
    source = pefile.PE(data=original, fast_load=True)
    image = pefile.PE(data=baseline, fast_load=True)
    for pe in (source, image):
        if (pe.FILE_HEADER.Machine != 0x14c or pe.OPTIONAL_HEADER.Magic != 0x10b
                or pe.OPTIONAL_HEADER.ImageBase != 0x400000):
            raise ValueError('Unsupported native layout PE architecture')
    if (len(original) != len(baseline)
            or source.OPTIONAL_HEADER.SizeOfHeaders != image.OPTIONAL_HEADER.SizeOfHeaders
            or original[:source.OPTIONAL_HEADER.SizeOfHeaders] != baseline[:image.OPTIONAL_HEADER.SizeOfHeaders]):
        raise ValueError('Localized native layout baseline changed PE structure')
    security = image.OPTIONAL_HEADER.DATA_DIRECTORY[4]
    if security.Size or security.VirtualAddress:
        raise ValueError('Signed native layout input is unsupported')
    if (_sha(TAIL) != TAIL_SHA256 or _sha(SPACING) != SPACING_SHA256):
        raise ValueError('Native layout generated payload differs')

    file_alignment = image.OPTIONAL_HEADER.FileAlignment
    section_alignment = image.OPTIONAL_HEADER.SectionAlignment
    rva = _align(max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData)
                     for s in image.sections), section_alignment)
    raw_offset = _align(len(baseline), file_alignment)
    payload, labels = build_payload(rva, profile, TAIL, SPACING)
    raw_size = _align(len(payload), file_alignment)
    header = image.sections[-1].get_file_offset() + 40
    first_raw = min(s.PointerToRawData for s in image.sections if s.PointerToRawData)
    if (header + 40 > first_raw or header + 40 > image.OPTIONAL_HEADER.SizeOfHeaders
            or baseline[header:header + 40] != b'\0' * 40):
        raise ValueError('No unused native PE section-header space')

    result = bytearray(baseline)
    records = []
    for site, label, call_target, stolen in _sites(profile):
        size = len(stolen) if stolen is not None else 5
        section = image.get_section_by_rva(site)
        if (section is None or not section.Characteristics & 0x20000000
                or site + size > section.VirtualAddress + section.Misc_VirtualSize):
            raise ValueError('Native layout hook is outside executable code')
        offset = image.get_offset_from_rva(site)
        before = baseline[offset:offset + size]
        if before != source.get_data(site, size):
            raise ValueError('Localized baseline changed a native layout hook')
        if call_target is not None:
            if (len(before) != 5 or before[0] != 0xe8
                    or site + 5 + struct.unpack_from('<i', before, 1)[0] != call_target):
                raise ValueError('Unexpected native layout call signature')
            opcode = b'\xe8'
        else:
            if before != stolen:
                raise ValueError('Unexpected native layout join signature')
            opcode = b'\xe9'
        target = rva + labels[label]
        after = opcode + struct.pack('<i', target - site - 5) + b'\x90' * (size - 5)
        result[offset:offset + size] = after
        records.append(dict(rva=hex(site), file_offset=offset, before=before.hex(),
                            after=after.hex(), target_rva=hex(target)))

    # Native redraw/probe decrements only an uncached scale-4 ASCII width;
    # extraction does not. Remove precisely that one-byte DEC, so all three
    # paths use the same cached/GDI advance. Cached and CJK paths bypass it.
    site = profile['ascii_measure_trim']
    offset = image.get_offset_from_rva(site)
    if source.get_data(site, 1) != b'\x48' or baseline[offset:offset + 1] != b'\x48':
        raise ValueError('Unexpected or altered native ASCII measurement decrement')
    result[offset] = 0x90
    records.append(dict(rva=hex(site), file_offset=offset, before='48', after='90',
                        kind='consistent-ascii-measurement'))

    result[header:header + 40] = struct.pack('<8sIIIIIIHHI', b'.nblay\0\0', len(payload),
        rva, raw_size, raw_offset, 0, 0, 0, 0, 0x60000020)
    struct.pack_into('<H', result, image.FILE_HEADER.get_field_absolute_offset('NumberOfSections'),
                     len(image.sections) + 1)
    struct.pack_into('<I', result, image.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),
                     _align(rva + len(payload), section_alignment))
    struct.pack_into('<I', result, image.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfCode'),
                     image.OPTIONAL_HEADER.SizeOfCode + raw_size)
    struct.pack_into('<I', result, image.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    result.extend(b'\0' * (raw_offset - len(result)))
    result.extend(payload)
    result.extend(b'\0' * (raw_size - len(payload)))
    patched = bytes(result)
    checked = pefile.PE(data=patched, fast_load=True)
    if checked.sections[-1].get_data()[:len(payload)] != payload:
        raise ValueError('Native layout section verification failed')
    for index in (1, 5, 12):  # imports, relocations, IAT; existing ASLR remains intact
        old, new = image.OPTIONAL_HEADER.DATA_DIRECTORY[index], checked.OPTIONAL_HEADER.DATA_DIRECTORY[index]
        if ((old.VirtualAddress, old.Size) != (new.VirtualAddress, new.Size)
                or (old.Size and image.get_data(old.VirtualAddress, old.Size)
                    != checked.get_data(new.VirtualAddress, new.Size))):
            raise ValueError('Native layout changed an existing PE directory')
    return patched, {
        'module': module, 'family': profile['family'], 'source_sha256': _sha(original),
        'baseline_sha256': _sha(baseline), 'sha256': _sha(patched), 'changed': True,
        'patches': records, 'payload_rva': hex(rva), 'payload_bytes': len(payload),
        'payload_sha256': _sha(payload), 'labels': {k: hex(rva + v) for k, v in labels.items()},
        'section': dict(name='.nblay', rva=hex(rva), file_offset=raw_offset,
                        virtual_size=len(payload), raw_size=raw_size, permissions='RX'),
        'new_imports': False, 'new_relocations': False, 'pending_capacity': 1024,
        'policy': 'horizontal spacing; suffix-stable dictionary and OOV word lattices; closing clusters; bounded short-tail preference',
        'lexicon': {'sha256': LEXICON_SHA256, 'words': WORD_COUNT,
                    'upstream_commit': LEXICON_SOURCE['commit'], 'max_word_units': 8},
        'oov_model': {'sha256': MODEL_SHA256, **MODEL_HEADER,
                      'policy': 'reset-start word costs; dictionary singleton runs; rare-character gate'},
        'max_plain_units': 512,
        'fallback_ascii_metrics_match_extraction': True,
        'old3_justification_bypass': profile['family'] == 'old3',
    }


def patch_chinese_native_layout(original_restored, *, baseline=None):
    """Return (patched PE, metadata), rejecting unknown or altered native inputs.

The source identity is checked before any localization. Baseline may contain
the builder's fixed native UI/font edits, but must retain the same PE structure
and every hook instruction. Runtime bridges keep original pending capacity,
actual glyph metrics, return state, explicit controls and native cache contents.
"""
    identity = _ORIGINALS.get(_sha(original_restored))
    if identity is None:
        raise ValueError('Unsupported original Chinese engine for native layout')
    module, family = identity
    return _patch(original_restored, original_restored if baseline is None else baseline,
                  module, _FAMILIES[family])
