"""Read pinned original/prepared translation inputs without executing them."""
from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

PREPARED_ARCHIVE_NAME = 'NarciBloom-translation-PC-v1.1-prepared.zip'


@dataclass(frozen=True)
class PreparedTranslation:
    """Recognized restored engine and unchanged virtual files for one module."""
    module: str
    restored_engine: bytes
    virtual_files: dict[str, bytes]


def _safe_path(name):
    if (not isinstance(name, str) or not name or any(c in name for c in '\\:*?"<>|')
            or name.startswith('/') or any(ord(c) < 32 for c in name)):
        raise ValueError('Unsafe prepared translation path')
    for part in name.split('/'):
        if (not part or part in ('.', '..') or part.endswith((' ', '.'))
                or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)):
            raise ValueError('Unsafe prepared translation path')
    return name


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate prepared manifest key')
        result[key] = value
    return result


def _checked_bytes(data, expected, label):
    if (len(data) != expected['size_bytes']
            or hashlib.sha256(data).hexdigest() != expected['sha256']):
        raise ValueError(f'Prepared translation size or hash mismatch: {label}')
    return data


def _read_prepared(stream, specification, notice, modules):
    """Validate the entire recognized ZIP; keep requested modules in memory."""
    root = _safe_path(specification['root_directory']) + '/'
    manifest_name = root + 'manifest.json'
    with zipfile.ZipFile(stream) as container:
        infos = container.infolist()
        if len(infos) > 1024 or sum(i.file_size for i in infos) > 256 * 1024 * 1024:
            raise ValueError('Prepared translation archive exceeds bounds')
        index, folded = {}, set()
        for info in infos:
            _safe_path(info.orig_filename)
            _safe_path(info.filename)
            mode = info.external_attr >> 16
            if (info.orig_filename != info.filename or info.filename.casefold() in folded or info.is_dir()
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or info.flag_bits & 1 or info.file_size > 128 * 1024 * 1024
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError('Unsupported or duplicate prepared ZIP member')
            index[info.filename] = info
            folded.add(info.filename.casefold())
        if manifest_name not in index:
            raise ValueError('Missing prepared translation manifest')

        def read(name, expected):
            info = index.get(name)
            if info is None or info.file_size != expected['size_bytes']:
                raise ValueError(f'Missing or wrong-sized prepared member: {name}')
            return _checked_bytes(container.read(info), expected, name)

        manifest = json.loads(read(manifest_name, specification['manifest']),
                              object_pairs_hook=_json_object)
        original = notice['input_fingerprint']
        source_members = {item['path']: item for item in original['members']}
        if (manifest['schema'] != 1 or manifest['source_archive'] != original['archive']
                or manifest['source_members'] != original['members']):
            raise ValueError('Prepared translation source identity differs')
        expected_files = {}
        for item in manifest['files']:
            name = _safe_path(item['path'])
            if name.casefold() in {p.casefold() for p in expected_files}:
                raise ValueError('Duplicate prepared manifest file')
            expected_files[name] = item
        if set(index) != {root + name for name in expected_files} | {manifest_name}:
            raise ValueError('Missing or unexpected prepared ZIP member')
        known_modules = {p.split('/')[0] for p in source_members if p.endswith('.exe')}
        if set(manifest['modules']) != known_modules:
            raise ValueError('Prepared module set differs from original translation')
        keep = {'readme.txt'}
        definitions = {}
        module_paths = set()
        for module, record in manifest['modules'].items():
            member = record['source_member']
            if (member not in source_members or member.split('/')[0] != module
                    or record['source_member_sha256'] != source_members[member]['sha256']):
                raise ValueError('Prepared module source member differs')
            engine = record['engine']
            if engine['path'] != f'modules/{module}/engine.exe':
                raise ValueError('Unexpected prepared engine path')
            records = [engine] + record['virtual_files']
            virtual = {}
            for item in record['virtual_files']:
                relative = _safe_path(item['source_virtual_path'])
                if (item['path'] != f'modules/{module}/virtual/{relative}'
                        or relative.casefold() in {p.casefold() for p in virtual}):
                    raise ValueError('Unexpected or duplicate prepared virtual path')
                virtual[relative] = item['path']
            for item in records:
                name = _safe_path(item['path'])
                if (name in module_paths or name not in expected_files
                        or any(item[key] != expected_files[name][key]
                               for key in ('size_bytes', 'sha256'))):
                    raise ValueError('Prepared module and file manifests differ')
                module_paths.add(name)
            if module in modules:
                keep.update(item['path'] for item in records)
                definitions[member] = (module, engine['path'], virtual)
        if {name for name in expected_files if name.startswith('modules/')} != module_paths:
            raise ValueError('Unreferenced prepared module files')
        data = {}
        for name, expected in expected_files.items():
            content = read(root + name, expected)
            if name in keep:
                data[name] = content
        _checked_bytes(data['readme.txt'], source_members['readme.txt'], 'original readme')
        result = {'readme.txt': data['readme.txt']}
        for member, (module, engine_path, virtual) in definitions.items():
            result[member] = PreparedTranslation(module, data[engine_path],
                                                {name: data[path] for name, path in virtual.items()})
        return result


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
    """Return original member keys with bytes/PreparedTranslation and readme.

    Fingerprints recognize the observed release, not publisher authenticity or
    malware safety. No protection settings are changed by this reader.
    """
    path = Path(path)
    source = source_notice()
    notice = source['input_fingerprint']
    expected = notice['archive']
    prepared = source.get('prepared_input')
    allowed = {item['path'].split('/')[0] for item in notice['members']
               if item['path'].endswith('.exe')}
    modules = set(modules)
    if modules - allowed:
        raise ValueError('Unsupported translation module selection')
    size = path.stat().st_size
    candidates = [('original', expected)]
    if prepared:
        candidates.append(('prepared', prepared['archive']))
    candidates = [(kind, item) for kind, item in candidates if size == item['size_bytes']]
    if not candidates:
        raise ValueError('This is not the supported PC v1.1 translation archive')
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        recognized = next((kind for kind, item in candidates if checksum == item['sha256']), None)
        if recognized is None:
            raise ValueError('Translation archive differs from the supported PC v1.1 input')
        if recognized == 'prepared':
            stream.seek(0)
            try:
                return _read_prepared(stream, prepared, source, modules)
            except (KeyError, TypeError, UnicodeError, zipfile.BadZipFile, NotImplementedError) as error:
                raise ValueError('Invalid prepared translation structure') from error
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
