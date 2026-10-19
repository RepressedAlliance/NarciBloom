"""Reproduce the prepared PC v1.1 input from the recognized original RAR.

No input code is executed. Output contains third-party translation resources,
including its supplied images/sound effects, and must stay out of source Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from translation_adapter import extract_virtual_files, restore_virtual_pe
from translation_package import PREPARED_ARCHIVE_NAME, _safe_path, read_package, source_notice

ROOT_DIRECTORY = 'NarciBloom-translation-PC-v1.1-prepared'
CACHE_NOTICE = '''NarciBloom prepared translation input / PC v1.1

Translation: 风铃汉化组. Original release:
https://www.rainlain.com/index.php/2024/11/01/2567/
Original credits and redistribution notice are preserved in readme.txt.

This is an unofficial NarciBloom preprocessing of the original PC v1.1 patch.
It contains five statically restored engines and the unchanged virtual files
from that patch, including its code, scripts, UI, images and sound effects.
No additional game media was collected. A separately owned Steam game is required.
The EVB virtual layer was removed; input programs were never executed.
Font, native caption and pagination changes are generated locally at installation.

Redistribution relies on an interpretation of the original general redistribution
notice, not special approval of this preprocessing. No complete third-party rights
chain, software safety or freedom from antivirus detection is asserted.
Preserve attribution; do not charge or impose reply/virtual-currency access gates.
This is not an official update from the translation group or game publisher.
'''


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def prepare_input(source, output):
    """Write a new ZIP; never overwrite an existing output.

    Ordering, timestamps and metadata are fixed. Byte-for-byte reproduction
    additionally requires the same Python/zlib toolchain. Release recognition
    fingerprints match the published material, not every possible rebuild.
    """
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    notice = source_notice()
    original = notice['input_fingerprint']
    members = [item for item in original['members'] if item['path'].endswith('.exe')]
    inputs = read_package(source, [item['path'].split('/')[0] for item in members])
    if any(not isinstance(data, bytes) for data in inputs.values()):
        raise ValueError('Preparation requires the recognized original RAR input')
    # Container hashes cannot be embedded in the container they fingerprint.
    # The public recognition record lives in docs/translation-source.json.
    embedded_notice = {key: value for key, value in notice.items() if key != 'prepared_input'}
    files = {'readme.txt': inputs.pop('readme.txt'),
             'source-notice.json': _json_bytes(embedded_notice),
             'CACHE-NOTICE.txt': CACHE_NOTICE.encode('utf-8')}
    modules = {}
    for member in members:
        module = member['path'].split('/')[0]
        packed = inputs.pop(member['path'])
        virtual = extract_virtual_files(packed)
        engine = restore_virtual_pe(packed)
        engine_path = f'modules/{module}/engine.exe'
        files[engine_path] = engine
        records = []
        for name, data in sorted(virtual.items()):
            _safe_path(name)
            path = f'modules/{module}/virtual/{name}'
            files[path] = data
            records.append(dict(_record(path, data), source_virtual_path=name))
        modules[module] = {'source_member': member['path'],
                           'source_member_sha256': member['sha256'],
                           'engine': _record(engine_path, engine),
                           'virtual_files': records,
                           'virtual_bytes': sum(map(len, virtual.values()))}
    manifest = {
        'schema': 1, 'kind': 'narcibloom-prepared-original-translation-input',
        'status': 'Unofficial transparent prepared input; font changes generated locally.',
        'source_archive': original['archive'], 'source_members': original['members'],
        'source_notice_path': 'source-notice.json',
        'processing': {
            'operation': 'extract_virtual_files + restore_virtual_pe only',
            'no_font_or_caption_patch': True, 'original_programs_executed': False,
            'adapter_sha256': hashlib.sha256(Path(__file__).with_name('translation_adapter.py')
                                             .read_text(encoding='utf-8').replace('\r\n', '\n')
                                             .encode('utf-8')).hexdigest(),
            'adapter_hash_normalization': 'UTF-8 with LF line endings',
            'dependencies': {'evbunpack': '0.2.6', 'aplib': '0.6', 'pefile': '2024.8.26'},
        },
        'scope': 'Original translation-supplied code, scripts, UI, images and sound effects; '
                 'no additional game media collected. Restoration and scan results do not '
                 'establish software safety or special redistribution approval.',
        'modules': modules,
        'files': [_record(name, data) for name, data in sorted(files.items())],
    }
    manifest_bytes = _json_bytes(manifest)
    files['manifest.json'] = manifest_bytes
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as destination:
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(ROOT_DIRECTORY + '/' + _safe_path(name), (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with output.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {
        'archive': {'filename': PREPARED_ARCHIVE_NAME, 'size_bytes': output.stat().st_size, 'sha256': checksum},
        'root_directory': ROOT_DIRECTORY,
        'manifest': {'size_bytes': len(manifest_bytes), 'sha256': hashlib.sha256(manifest_bytes).hexdigest()},
        'modules': len(modules), 'virtual_files': sum(len(item['virtual_files']) for item in modules.values()),
    }


def _record(path, data):
    return {'path': path, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Recognized original PC v1.1 RAR')
    parser.add_argument('--output', required=True, help='New output ZIP path')
    arguments = parser.parse_args()
    print(json.dumps(prepare_input(arguments.source, arguments.output), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
