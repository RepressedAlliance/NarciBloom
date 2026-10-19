"""Generated EVB/PE fixtures only; no game or translated text is included."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import translation_adapter as adapter
from translation_adapter import TranslationFormatError, extract_virtual_files, restore_virtual_pe
import pefile


def file_node(name, data, *, stored=None, count=0):
    stored = data if stored is None else stored
    node = (struct.pack('<I8sI', 0, b'', count) + name.encode('utf-16le') + b'\0\0\x02'
            + struct.pack('<2sI4s8s8s8s15sI', b'', len(data), b'', b'', b'', b'', b'', len(stored)))
    return node, stored


def folder_node(name, children):
    return (struct.pack('<I8sI', 0, b'', children)
            + name.encode('utf-16le') + b'\0\0\x03' + b'\0' * 25)


def virtual_image(files, *, folder='%DEFAULT FOLDER%', child_count=None):
    records = [file_node(name, data, stored=stored) for name, data, stored in files]
    table = (folder_node(folder, len(files) if child_count is None else child_count)
             + b''.join(record[0] for record in records) + b'\0' * 4)
    main = struct.pack('<I8sI', len(table) + 11, b'', 1)
    return b'EVB\0' + b'\0' * 60 + main[:-1] + table + b''.join(record[1] for record in records)


def compressed_chunks(*chunks):
    table = b''.join(struct.pack('<III', len(chunk), 0, 0) for chunk in chunks[:-1])
    table += struct.pack('<I', len(chunks[-1]))
    return struct.pack('<II', 8 + len(table), 0) + table + b''.join(chunks)


def synthetic_pe(variant='9_70', *, overlay=b''):
    """An inert three-section PE with original import descriptors and EVB header."""
    data = bytearray(0x800)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x14c, 3, 0, 0, 0, 224, 0x102)
    optional = 0x98
    struct.pack_into('<H', data, optional, 0x10b)
    struct.pack_into('<III', data, optional + 16, 0x1000, 0x1000, 0x1000)
    struct.pack_into('<III', data, optional + 28, 0x400000, 0x1000, 0x200)
    struct.pack_into('<II', data, optional + 56, 0x4000, 0x200)
    struct.pack_into('<H', data, optional + 68, 2)
    struct.pack_into('<I', data, optional + 92, 16)
    sections = 0x178
    for index, (name, rva, raw) in enumerate(((b'.text', 0x1000, 0x200),
                                              (b'.enigma1', 0x2000, 0x400),
                                              (b'.enigma2', 0x3000, 0x600))):
        struct.pack_into('<8sIIIIIIHHI', data, sections + index * 40,
                         name, 0x200, rva, 0x200, raw, 0, 0, 0, 0, 0x60000020)
    # An import table with a live descriptor and a terminating null descriptor.
    struct.pack_into('<IIIII', data, 0x220, 0x1080, 0, 0, 0x1090, 0x10a0)
    data[0x290:0x296] = b'x.dll\0'
    structure = adapter.const.EVB_ENIGMA1_HEADER.get_struct(False, variant)
    offset = 0x400
    for fmt, name in structure:
        value = 0x1020 if name == 'IMPORT_ADDRESS' else 40 if name == 'IMPORT_SIZE' else 0
        if fmt.endswith('s'):
            value = b''
        struct.pack_into('<' + fmt, data, offset, value)
        offset += struct.calcsize('<' + fmt)
    struct.pack_into('<II', data, optional + 96 + 8, 0x2100, 40)
    return bytes(data) + overlay


class TranslationAdapterTests(unittest.TestCase):
    def test_extracts_relative_paths_and_empty_file_without_touching_disk(self):
        image = virtual_image([('data.bin', b'example', None), ('empty', b'', None)])
        self.assertEqual(extract_virtual_files(image), {'data.bin': b'example', 'empty': b''})

    def test_nested_directory_preserved(self):
        node, payload = file_node('a.bin', b'a')
        table = folder_node('%DEFAULT FOLDER%', 1) + folder_node('#mjo', 1) + node + b'\0' * 4
        image = b'EVB\0' + b'\0' * 60 + struct.pack('<I8sI', len(table) + 11, b'', 1)[:-1] + table + payload
        self.assertEqual(extract_virtual_files(image), {'#mjo/a.bin': b'a'})

    def test_rejects_escape_ambiguous_and_reserved_names(self):
        for name in ('..', '.', '../a', 'a\\b', 'C:a', '/tmp', 'file.', 'file ', 'NUL.txt', 'AUX', ''):
            with self.subTest(name=name), self.assertRaises(TranslationFormatError):
                extract_virtual_files(virtual_image([(name, b'a', None)]))

    def test_rejects_case_insensitive_duplicate_paths(self):
        with self.assertRaisesRegex(TranslationFormatError, 'duplicate'):
            extract_virtual_files(virtual_image([('a.bin', b'a', None), ('A.BIN', b'b', None)]))

    def test_rejects_incomplete_tree_payload_and_bad_terminator(self):
        good = virtual_image([('a.bin', b'a', None)])
        for image in (good[:-1], good[:80], virtual_image([('a.bin', b'a', None)], child_count=2),
                      good[:-5] + b'xxxx' + good[-1:]):
            with self.subTest(size=len(image)), self.assertRaises(TranslationFormatError):
                extract_virtual_files(image)

    def test_reads_multiple_aplib_chunks_and_checks_output_size(self):
        # Public self-test vector supplied by the pinned aplib library.
        packed = b'T\x00he quick\xecb\x0erown\xcef\xaex\x80jumps\xed\xe4veur`t?lazy\xead\xfeg\xc0\x00'
        plain = b'The quick brown fox jumps over the lazy dog'
        self.assertEqual(extract_virtual_files(virtual_image([
            ('a', plain * 2, compressed_chunks(packed, packed))])), {'a': plain * 2})
        with self.assertRaises(TranslationFormatError):
            extract_virtual_files(virtual_image([('a', b'x', compressed_chunks(packed))]))

    def test_rejects_bad_compressed_chunk_and_chunk_lengths(self):
        malformed = (compressed_chunks(b'\0'), struct.pack('<III', 12, 0, 100) + b'a',
                     struct.pack('<II', 100, 0), struct.pack('<III', 12, 0, 0))
        for packed in malformed:
            with self.subTest(packed=packed), self.assertRaises(TranslationFormatError):
                extract_virtual_files(virtual_image([('a', b'plain text', packed)]))

    def test_limits_declared_expansion_and_node_count(self):
        good = virtual_image([('a', b'payload', None)])
        with patch.object(adapter, 'MAX_TOTAL_BYTES', 2), self.assertRaises(TranslationFormatError):
            extract_virtual_files(good)
        with patch.object(adapter, 'MAX_NODES', 1), self.assertRaises(TranslationFormatError):
            extract_virtual_files(good)

    def test_restores_both_supported_pe_header_variants(self):
        for variant in ('9_70', '10_70'):
            with self.subTest(variant=variant):
                source = synthetic_pe(variant, overlay=b'overlay')
                restored = restore_virtual_pe(source)
                self.assertEqual(len(restored), 0x400 + 7)
                self.assertEqual(restored[0x200:0x400], source[0x200:0x400])
                self.assertEqual(restored[-7:], b'overlay')
                pe = pefile.PE(data=restored)
                self.assertEqual([s.Name.rstrip(b'\0') for s in pe.sections], [b'.text'])
                self.assertEqual(pe.FILE_HEADER.NumberOfSections, 1)
                self.assertEqual(pe.OPTIONAL_HEADER.SizeOfImage, 0x2000)
                self.assertEqual(pe.OPTIONAL_HEADER.DATA_DIRECTORY[1].VirtualAddress, 0x1020)
                self.assertEqual(pe.OPTIONAL_HEADER.DATA_DIRECTORY[1].Size, 40)
                self.assertEqual(restored[0x178 + 40:0x178 + 120], b'\0' * 80)

    def test_rejects_invalid_pe_and_invalid_restore_directories(self):
        bad_import = bytearray(synthetic_pe())
        struct.pack_into('<I', bad_import, 0x400 + 80, 0xdeadbeef)
        signed = bytearray(synthetic_pe())
        struct.pack_into('<II', signed, 0x98 + 96 + 4 * 8, 0x700, 8)
        overlapping = bytearray(synthetic_pe())
        struct.pack_into('<I', overlapping, 0x178 + 40 + 12, 0x1000)
        wrong_machine = bytearray(synthetic_pe())
        struct.pack_into('<H', wrong_machine, 0x84, 0x1c0)
        for image in (b'not PE', synthetic_pe()[:-1], bytes(bad_import), bytes(signed),
                      bytes(overlapping), bytes(wrong_machine)):
            with self.subTest(size=len(image)), self.assertRaises(TranslationFormatError):
                restore_virtual_pe(image)

    def test_requires_bytes_inputs(self):
        for method in (extract_virtual_files, restore_virtual_pe):
            for value in ('filename.exe', bytearray(b'x'), b''):
                with self.subTest(method=method.__name__, value=type(value).__name__), self.assertRaises(TranslationFormatError):
                    method(value)


if __name__ == '__main__':
    unittest.main()
