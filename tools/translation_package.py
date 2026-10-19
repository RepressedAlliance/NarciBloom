"""Read the unchanged, recognized translation archive without executing it."""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def resource_path(relative):
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return root / relative


def source_notice():
    return json.loads(resource_path('docs/translation-source.json').read_text(encoding='utf-8'))


def _unix_members(path, wanted):
    """Use SteamOS's libarchive; no shell, extraction directory or external tool."""
    name = ctypes.util.find_library('archive')
    if not name:
        raise RuntimeError('libarchive is required to read the original RAR package')
    lib = ctypes.CDLL(name)
    lib.archive_read_new.restype = ctypes.c_void_p
    for field in ('archive_read_support_filter_all', 'archive_read_support_format_all',
                  'archive_read_free'):
        getattr(lib, field).argtypes = [ctypes.c_void_p]
    lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
    lib.archive_entry_pathname.restype = ctypes.c_char_p
    lib.archive_entry_size.argtypes = [ctypes.c_void_p]
    lib.archive_entry_size.restype = ctypes.c_int64
    lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    lib.archive_read_data.restype = ctypes.c_ssize_t
    handle = lib.archive_read_new()
    if not handle:
        raise RuntimeError('Cannot allocate archive reader')
    result = {}
    try:
        lib.archive_read_support_filter_all(handle)
        lib.archive_read_support_format_all(handle)
        if lib.archive_read_open_filename(handle, os.fsencode(path), 65536) != 0:
            raise ValueError('Cannot open translation archive')
        entry = ctypes.c_void_p()
        while True:
            status = lib.archive_read_next_header(handle, ctypes.byref(entry))
            if status == 1:
                break
            if status != 0:
                raise ValueError('Cannot read translation archive header')
            member = lib.archive_entry_pathname(entry).decode('utf-8').replace('\\', '/')
            if member not in wanted:
                continue
            size = lib.archive_entry_size(entry)
            if member in result or size != wanted[member]['size_bytes']:
                raise ValueError('Unexpected translation member size or duplicate')
            data = bytearray()
            buffer = ctypes.create_string_buffer(1024 * 1024)
            while True:
                count = lib.archive_read_data(handle, buffer, len(buffer))
                if count < 0:
                    raise ValueError('Cannot decompress translation member')
                if count == 0:
                    break
                data.extend(buffer.raw[:count])
                if len(data) > size:
                    raise ValueError('Translation member exceeds declared size')
            result[member] = bytes(data)
    finally:
        lib.archive_read_free(handle)
    return result


def read_package(path, modules):
    """Return requested EXEs plus the original readme after version checks.

    Fingerprints recognize the observed release, not publisher authenticity or
    malware safety. No protection settings are changed by this reader.
    """
    path = Path(path)
    notice = source_notice()['input_fingerprint']
    expected = notice['archive']
    if path.stat().st_size != expected['size_bytes']:
        raise ValueError('This is not the supported PC v1.1 translation archive')
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    if checksum != expected['sha256']:
        raise ValueError('Translation archive differs from the supported PC v1.1 input')
    wanted = {item['path']: item for item in notice['members']
              if item['path'] == 'readme.txt' or item['path'].split('/')[0] in modules}
    if os.name == 'nt':
        tar = Path(os.environ['SystemRoot']) / 'System32/tar.exe'
        result = {}
        for member in wanted:
            completed = subprocess.run([str(tar), '-xOf', str(path), member],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
            if completed.returncode:
                raise ValueError('Cannot read the original RAR archive using Windows tar')
            result[member] = completed.stdout
    else:
        result = _unix_members(path, wanted)
    for member, item in wanted.items():
        data = result.get(member, b'')
        if len(data) != item['size_bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError(f'Translation member does not match the supported version: {member}')
    return result
