"""Select the original script UI character set for recognized stock engines.

Only the three older Japanese engines require a byte change. This function
accepts original stock PE bytes, before native_dialogs changes fixed captions.
Chinese translation engines must continue through their separate builder.
"""
import hashlib

import pefile


# Original source SHA -> module, language, instruction VA, complete instruction.
# C6 writes LOGFONTA.lfCharSet directly; C7 writes the containing DWORD.
PROFILES = {
    'f687e510f14dcbb2fe467f31b740f10e8baa6ca981ca626d61d0b6b7ee7cc825': ('narci_iris', 'ja', 0x41a55f, 'c605971f4c0001'),
    '45c8a1b5ea39a552629e637e4435b9fa9639978f40f3c164a24867c739d70075': ('narci_himeko', 'ja', 0x41a55f, 'c605971f4c0001'),
    'f85b6f836bf21360c50e997664df5635992a06c3eb8c3fa21ffd51811adfb137': ('narci_zero', 'ja', 0x41a55f, 'c605971f4c0001'),
    'c573a0901b007c1db2cc96f6277aafe15401352b7c52f4a2bb16b6bc69ce8693': ('narci_onetwo', 'ja', 0x444f5a, 'c705c4e3530000000080'),
    '33ca175716962f6387523fac3d4c8edc4864b038c7ac3953e7e62b19091fff40': ('narci_sumire', 'ja', 0x447153, 'c7059827530000000080'),
    'f88df926e03f806cd354ecc21ae4fda6fe272cbe8b57f31ef95550f9046ff6e4': ('narci_iris', 'en', 0x4471e3, 'c7057817530000000000'),
    'dbbbd6ce447846311a2ff934f8c15d51b9f3ca384b55d1e639d339633e6ec8e2': ('narci_himeko', 'en', 0x4471e3, 'c7057817530000000000'),
    'f0255f28dd6ce77b71565363e75e5b59ea192da0136b50cfa6d62cfd8b0f40d3': ('narci_onetwo', 'en', 0x4471e3, 'c7057817530000000000'),
    'a39ab5c816cf447bd6e0e54110abe617225b93da9bc05e5e7d49a935b2aeda56': ('narci_sumire', 'en', 0x4471e3, 'c7057817530000000000'),
    'd2bd02daed3053b970f8d2006173ff9c40a24dbd5c6555925eddb0b214517df1': ('narci_zero', 'en', 0x4471e3, 'c7057817530000000000'),
}


def stock_fontout(executable):
    """Return (PE bytes, report); reject unknown or modified original inputs.

    Keep CP932 slot descriptions and script strings unchanged. The older UI
    renderer used DEFAULT_CHARSET, while its story renderer used SHIFTJIS.
    Set that UI LOGFONTA field to SHIFTJIS for Japanese stock input. Newer JA
    and EN engines already select their intended explicit charset and are
    validated without changes. This never handles Chinese translation DLLs.
    """
    source_hash = hashlib.sha256(executable).hexdigest()
    if source_hash not in PROFILES:
        raise ValueError('Unsupported original stock engine for script UI charset')
    module, language, address, expected_hex = PROFILES[source_hash]
    expected = bytes.fromhex(expected_hex)
    image = pefile.PE(data=executable, fast_load=True)
    if image.OPTIONAL_HEADER.ImageBase != 0x400000:
        raise ValueError('Unexpected stock engine image base')
    rva = address - image.OPTIONAL_HEADER.ImageBase
    section = image.get_section_by_rva(rva)
    if (section is None or section.Name.rstrip(b'\0') != b'.text'
            or not section.Characteristics & 0x20000000):
        raise ValueError('Script UI charset instruction is outside executable text')
    offset = image.get_offset_from_rva(rva)
    if executable[offset:offset + len(expected)] != expected:
        raise ValueError('Stock script UI charset instruction differs')
    old = expected[-1]
    changed = language == 'ja' and old == 1
    new = 128 if changed else old
    result = bytearray(executable)
    result[offset + len(expected) - 1] = new
    return bytes(result), {
        'module': module, 'language': language, 'source_sha256': source_hash,
        'field': 'script_ui_LOGFONTA.lfCharSet', 'instruction_va': hex(address),
        'file_offset': offset + len(expected) - 1,
        'original_charset': old, 'charset': new, 'changed': changed,
    }
