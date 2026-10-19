"""Read the supported EVB virtual layer without writing or executing game files.

Format definitions and PE restoration approach: mos9527/evbunpack, pinned in
requirements.txt (Apache-2.0). This is a bounded, memory-only adaptation; see
THIRD_PARTY.md. aPLib and PE parsing remain provided by their pinned libraries.
The PE operation supports the x86 9_70/10_70 layout used by the PC v1.1 bundle;
it deliberately rejects legacy tables, ambiguous headers and exception tables.
"""
from pathlib import Path
import struct
import sys

_LOCAL_DEPS = Path(__file__).resolve().parents[1] / '.deps' / 'pc-compat'
if _LOCAL_DEPS.is_dir():
    sys.path.insert(0, str(_LOCAL_DEPS))

import aplib
import pefile
from evbunpack import const
from evbunpack.__main__ import get_size_by_struct, unpack

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_NODES = 10000
MAX_DEPTH = 64


class TranslationFormatError(ValueError):
    """The input is malformed or outside the supported EVB subset."""


def _require(condition, message):
    if not condition:
        raise TranslationFormatError(message)


def _input(data):
    _require(isinstance(data, bytes), 'input must be bytes')
    _require(0 < len(data) <= MAX_INPUT_BYTES, 'input size outside supported limits')
    return data


def _slice(data, offset, size):
    _require(0 <= offset <= len(data) and 0 <= size <= len(data) - offset,
             'truncated or out-of-range structure')
    return data[offset:offset + size]


def _safe_name(name, *, root=False):
    if root and name == '%DEFAULT FOLDER%':
        return ''
    _require(bool(name) and name not in ('.', '..'), 'invalid virtual path component')
    _require(not any(c in name for c in '/\\:<>"|?*')
             and not any(ord(c) < 32 for c in name)
             and not name.endswith((' ', '.')), 'unsafe virtual path component')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    _require(name.split('.')[0].upper() not in reserved, 'reserved Windows path component')
    return name


class _LimitedBuffer(bytearray):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def append(self, value):
        _require(len(self) < self.limit, 'aPLib output exceeds declared size')
        super().append(value)

    def __iadd__(self, value):
        _require(len(value) <= self.limit - len(self), 'aPLib output exceeds declared size')
        super().__iadd__(value)
        return self


def _decompress(data, limit):
    try:
        decoder = aplib.APLib(data, strict=True)
        decoder.destination = _LimitedBuffer(limit)
        return decoder.depack()
    except (RuntimeError, TypeError, IndexError, OverflowError) as error:
        raise TranslationFormatError('invalid aPLib chunk') from error


def _file_bytes(data, offset, stored_size, original_size):
    raw = _slice(data, offset, stored_size)
    _require(0 <= original_size <= MAX_FILE_BYTES, 'virtual file exceeds size limit')
    if stored_size == original_size:
        return raw
    header_size = get_size_by_struct(const.EVB_CHUNK_BLOCK)
    header = unpack(const.EVB_CHUNK_BLOCK, _slice(raw, 0, header_size))
    table_end = header['size']
    _require(header_size + 4 <= table_end <= len(raw), 'invalid chunk table size')
    table = raw[header_size:table_end]
    _require(len(table) % 12 in (0, 4), 'invalid chunk table stride')
    chunk_sizes = [struct.unpack_from('<I', table, i)[0] for i in range(0, len(table), 12)]
    _require(chunk_sizes and all(chunk_sizes), 'empty compressed chunk')
    _require(sum(chunk_sizes) == len(raw) - table_end, 'chunk sizes do not cover stored data')
    decoded = bytearray()
    cursor = table_end
    for size in chunk_sizes:
        decoded.extend(_decompress(raw[cursor:cursor + size], original_size - len(decoded)))
        cursor += size
    _require(len(decoded) == original_size, 'decompressed file size mismatch')
    return bytes(decoded)


def extract_virtual_files(packed_exe_bytes: bytes) -> dict[str, bytes]:
    """Return validated POSIX-relative virtual file names and contents.

    Reads the modern EVB tree and raw/chunked aPLib content in memory. The
    default virtual folder is removed. Windows-ambiguous and duplicate paths,
    incomplete trees, out-of-range payloads and excessive expansion fail closed.
    No executable code is loaded. A matching source hash is the caller's concern.
    """
    data = _input(packed_exe_bytes)
    magic = data.find(const.EVB_MAGIC)
    _require(magic >= 0, 'EVB filesystem signature not found')
    header_size = get_size_by_struct(const.EVB_PACK_HEADER)
    _slice(data, magic, header_size)
    main_pos = magic + header_size
    main_size = get_size_by_struct(const.EVB_NODE_MAIN)
    main = unpack(const.EVB_NODE_MAIN, _slice(data, main_pos, main_size))
    table_end = main_pos + main_size + main['size'] - 12
    cursor = main_pos + main_size - 1  # modern table overlaps the main's final byte
    _require(cursor < table_end <= len(data), 'invalid virtual table bounds')
    _require(0 < main['objects_count'] <= MAX_NODES, 'invalid root object count')
    payload_cursor = table_end
    result = {}
    seen = set()
    total = 0
    visited = 0

    def read(size):
        nonlocal cursor
        _require(0 <= size <= table_end - cursor, 'truncated virtual node')
        value = data[cursor:cursor + size]
        cursor += size
        return value

    def visit(parent, depth):
        nonlocal visited, total, payload_cursor
        visited += 1
        _require(visited <= MAX_NODES and depth <= MAX_DEPTH, 'virtual tree limit exceeded')
        node = unpack(const.EVB_HEADER_NODE, read(get_size_by_struct(const.EVB_HEADER_NODE)))
        _require(node['size'] == 0, 'unsupported legacy virtual node')
        name = bytearray()
        while True:
            char = read(2)
            if char == b'\0\0':
                break
            name.extend(char)
            _require(len(name) <= 510, 'virtual path component too long')
        try:
            name = name.decode('utf-16-le')
        except UnicodeDecodeError as error:
            raise TranslationFormatError('invalid UTF-16 virtual name') from error
        kind = read(1)[0]
        name = _safe_name(name, root=depth == 0 and kind == const.NODE_TYPE_FOLDER)
        path = '/'.join(part for part in (parent, name) if part)
        key = path.casefold()
        _require(key not in seen, 'duplicate virtual path')
        seen.add(key)
        if kind == const.NODE_TYPE_FOLDER:
            read(25)
            _require(node['objects_count'] <= MAX_NODES - visited, 'invalid folder object count')
            for _ in range(node['objects_count']):
                visit(path, depth + 1)
        elif kind == const.NODE_TYPE_FILE:
            _require(node['objects_count'] == 0 and bool(path), 'invalid file node')
            info = unpack(const.EVB_NODE_OPTIONAL_FILE,
                          read(get_size_by_struct(const.EVB_NODE_OPTIONAL_FILE)))
            total += info['original_size']
            _require(total <= MAX_TOTAL_BYTES, 'virtual filesystem exceeds size limit')
            result[path] = _file_bytes(data, payload_cursor, info['stored_size'], info['original_size'])
            payload_cursor += info['stored_size']
        else:
            raise TranslationFormatError('unsupported virtual node type')

    for _ in range(main['objects_count']):
        visit('', 0)
    _require(data[cursor:table_end] == b'\0' * 4, 'invalid virtual table terminator')
    return result


def _parse_pe(data):
    try:
        pe = pefile.PE(data=data, fast_load=True)
    except (pefile.PEFormatError, struct.error, IndexError) as error:
        raise TranslationFormatError('invalid PE image') from error
    _require(pe.PE_TYPE == pefile.OPTIONAL_HEADER_MAGIC_PE, 'only x86 PE images are supported')
    _require(pe.FILE_HEADER.Machine == 0x14c, 'only i386 PE images are supported')
    sections = pe.sections
    _require(len(sections) >= 3, 'missing original or EVB sections')
    _require(len(sections) == pe.FILE_HEADER.NumberOfSections, 'incomplete PE section table')
    _require([s.Name.rstrip(b'\0') for s in sections[-2:]] == [b'.enigma1', b'.enigma2'],
             'EVB sections must be the final two sections')
    last_end = sections[0].get_file_offset() + len(sections) * 40
    last_virtual_end = 0
    for section in sections:
        _require(section.PointerToRawData >= last_end, 'overlapping PE sections')
        _require(section.VirtualAddress >= last_virtual_end, 'overlapping PE virtual sections')
        _slice(data, section.PointerToRawData, section.SizeOfRawData)
        last_end = section.PointerToRawData + section.SizeOfRawData
        # EVB's raw VFS can be much larger than its mapped .enigma1 VirtualSize.
        last_virtual_end = section.VirtualAddress + section.Misc_VirtualSize
    _require(sections[-2].PointerToRawData + sections[-2].SizeOfRawData
             == sections[-1].PointerToRawData, 'noncontiguous EVB sections')
    _require(pe.FILE_HEADER.PointerToSymbolTable == 0, 'COFF symbol overlays are unsupported')
    dirs = pe.OPTIONAL_HEADER.DATA_DIRECTORY
    _require(len(dirs) >= 16, 'incomplete PE data directories')
    _require(dirs[4].VirtualAddress == 0 and dirs[4].Size == 0, 'signed PE images are unsupported')
    _require(dirs[3].VirtualAddress == 0 and dirs[3].Size == 0, 'PE exception tables are unsupported')
    return pe


def _original_range(pe, rva, size):
    for section in pe.sections[:-2]:
        delta = rva - section.VirtualAddress
        if 0 <= delta and size > 0 and delta + size <= section.SizeOfRawData:
            return section.PointerToRawData + delta
    return None


def restore_virtual_pe(packed_exe_bytes: bytes) -> bytes:
    """Remove supported EVB sections and restore original PE directories in memory.

    The original engine, including its .detour translation hooks, is retained.
    The result is data only; callers decide where to install it. Static structural
    validation cannot establish that a restored program will run successfully.
    """
    data = _input(packed_exe_bytes)
    pe = _parse_pe(data)
    enigma1, enigma2 = pe.sections[-2:]
    candidates = []
    for variant in ('9_70', '10_70'):
        structure = const.EVB_ENIGMA1_HEADER.get_struct(False, variant)
        header = unpack(structure, _slice(data, enigma1.PointerToRawData, get_size_by_struct(structure)))
        address, size = header['IMPORT_ADDRESS'], header['IMPORT_SIZE']
        offset = _original_range(pe, address, size)
        if offset is None or not 20 <= size <= 1024 * 1024 or size % 20:
            continue
        if data[offset + size - 20:offset + size] != b'\0' * 20:
            continue
        reloc, reloc_size = header['RELOC_ADDRESS'], header['RELOC_SIZE']
        if (reloc == 0) != (reloc_size == 0):
            continue
        if reloc_size and _original_range(pe, reloc, reloc_size) is None:
            continue
        if header['TLS_ADDRESS'] or header['TLS_SIZE']:
            if header['TLS_SIZE'] != 24 or _original_range(pe, header['TLS_ADDRESS'], 24) is None:
                continue
        candidates.append(header)
    _require(len(candidates) == 1, 'unsupported or ambiguous EVB PE header variant')
    header = candidates[0]
    dirs = pe.OPTIONAL_HEADER.DATA_DIRECTORY
    for index, prefix in ((1, 'IMPORT'), (5, 'RELOC')):
        dirs[index].VirtualAddress = header[prefix + '_ADDRESS']
        dirs[index].Size = header[prefix + '_SIZE']
    tls_rva = header['TLS_ADDRESS']
    if not tls_rva and any(header['TLS']):
        matches = []
        for section in pe.sections[:-2]:
            chunk = data[section.PointerToRawData:section.PointerToRawData + section.SizeOfRawData]
            offset = chunk.find(header['TLS'][:12])
            if offset >= 0 and offset + 24 <= len(chunk):
                matches.append(section.VirtualAddress + offset)
        _require(len(matches) <= 1, 'ambiguous original TLS directory')
        tls_rva = matches[0] if matches else 0
    dirs[9].VirtualAddress = tls_rva
    dirs[9].Size = 24 if tls_rva else 0
    for index, directory in enumerate(dirs):
        if directory.Size and index != 4:
            _require(_original_range(pe, directory.VirtualAddress, directory.Size) is not None,
                     'PE directory points outside original sections')
    _require(_original_range(pe, pe.OPTIONAL_HEADER.AddressOfEntryPoint, 1) is not None,
             'entry point points outside original sections')
    original_sections = pe.sections[:-2]
    end = enigma2.PointerToRawData + enigma2.SizeOfRawData
    rebuilt = bytearray(data[:enigma1.PointerToRawData] + data[end:])
    for section in (enigma1, enigma2):
        offset = section.get_file_offset()
        rebuilt[offset:offset + 40] = b'\0' * 40
    pe.__data__ = rebuilt
    pe.sections = original_sections
    pe.FILE_HEADER.NumberOfSections = len(original_sections)
    pe.OPTIONAL_HEADER.SizeOfHeaders = original_sections[0].PointerToRawData
    alignment = pe.OPTIONAL_HEADER.SectionAlignment
    _require(alignment > 0 and alignment & (alignment - 1) == 0, 'invalid section alignment')
    last = original_sections[-1]
    image_end = last.VirtualAddress + max(last.Misc_VirtualSize, last.SizeOfRawData)
    pe.OPTIONAL_HEADER.SizeOfImage = (image_end + alignment - 1) // alignment * alignment
    pe.OPTIONAL_HEADER.CheckSum = 0
    # pefile retains structures removed from .sections in its internal write list.
    pe.__structures__ = [s for s in pe.__structures__ if s is not enigma1 and s is not enigma2]
    result = bytes(pe.write())
    _require(len(result) == len(rebuilt), 'unexpected PE serialization size')
    return result
