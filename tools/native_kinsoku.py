"""Adapt the reviewed native line-break tables to the Chinese renderer's GBK.

Call only for the supported Chinese translation. Japanese and English retain
their original environment. This changes two configuration values, not text,
glyph metrics, the native pullback mode, or any script/wait/save behavior.
"""
import hashlib
import re


# These are the configured native tables in the supported player-owned inputs.
# Match the complete values so a player's custom table is never discarded.
_ORIGINAL = {
    'GYOUTOUKINSOKU': bytes.fromhex(
        '815b814181428143814481768178816a81488149829f82a182a382a582a7'
        '82c182e182e382e582ec83408342834483468348838383858387838e8395'
        '8396814a814b815481558152815387818145816381468147815d817a816c'
        '816e817081728174'),
    'GYOUMATUKINSOKU': bytes.fromhex(
        '817581778169817981658167816b816d816f81718173'),
}

# Basic closing/opening punctuation only. Native preservation of ellipsis/dash
# pairs and arbitrary-length punctuation clusters has not been established.
_PREVIEW4_NO_START = '、。，．？！：；）〕］｝〉》」』】〗”’'
# A trailing fullwidth wave is part of the preceding spoken syllable. Leaving
# it eligible at line start permits a short tail such as ～」. Let the native
# TYPE0 pullback carry the preceding character with it, using actual widths.
NO_START = _PREVIEW4_NO_START + '～'
NO_END = '（〔［｛〈《「『【〖“‘'
_CHINESE = {
    # Older supported engines use byte strstr instead of MBCS-aware search.
    # FF is neither a valid GBK character nor a lead/trail byte, so it prevents
    # matches straddling adjacent punctuation cells. Native config readers copy
    # this byte unchanged; it never becomes displayed text or a font setting.
    'GYOUTOUKINSOKU': b'\xff'.join(c.encode('gbk') for c in NO_START),
    'GYOUMATUKINSOKU': b'\xff'.join(c.encode('gbk') for c in NO_END),
}
_PREVIEW4 = dict(_CHINESE, GYOUTOUKINSOKU=b'\xff'.join(
    c.encode('gbk') for c in _PREVIEW4_NO_START))


def chinese_kinsoku_env(blob: bytes) -> tuple[bytes, dict]:
    """Return a Chinese-only environment edit and metadata; never write files.

    Accept the exact original, preview.4, or current already-patched pair.
    Reject unknown, mixed, missing or duplicate settings. Preserve every byte
    outside the two values, including comments, key spacing and line endings.
    The caller must select this helper only for the supported Chinese loader;
    the environment itself does not identify the language of the renderer.
    """
    matches = {}
    for key in ('KINSOKU_TYPE', *_ORIGINAL):
        pattern = rb'(?m)^[ \t]*' + key.encode('ascii') + rb'[ \t]+([^\r\n]*)(?:\r?$)'
        found = list(re.finditer(pattern, blob))
        if len(found) != 1:
            raise ValueError(f'expected exactly one active {key} setting')
        matches[key] = found[0]
    if matches['KINSOKU_TYPE'].group(1) != b'0':
        raise ValueError('only the reviewed native KINSOKU_TYPE 0 is supported')
    previous = {key: matches[key].group(1) for key in _ORIGINAL}
    if previous not in (_ORIGINAL, _PREVIEW4, _CHINESE):
        raise ValueError('unrecognized native kinsoku tables; custom values were not changed')
    result = blob
    changed = []
    # Replace from the end so earlier spans retain their original positions.
    for key in sorted(_CHINESE, key=lambda key: matches[key].start(1), reverse=True):
        value = _CHINESE[key]
        if len(value) >= 0x100 or any(byte in value for byte in (0, 10, 13)):
            raise ValueError('Chinese punctuation table exceeds native capacity')
        match = matches[key]
        if match.group(1) != value:
            result = result[:match.start(1)] + value + result[match.end(1):]
            changed.append(blob.count(b'\n', 0, match.start()) + 1)
    return result, {
        'encoding': 'gbk',
        'kinsoku_type': 0,
        'table_separator_hex': 'ff',
        'changed_line_one_based': sorted(changed),
        'already_patched': not changed,
        'table_bytes': {key: len(value) for key, value in _CHINESE.items()},
        'before_sha256': hashlib.sha256(blob).hexdigest(),
        'after_sha256': hashlib.sha256(result).hexdigest(),
    }
