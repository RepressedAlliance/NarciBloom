"""Build Chinese font overrides from player-owned bytes; never write game files."""
from dataclasses import dataclass
import hashlib
import re

from build_font_settings import Script, build_overrides
from patch_narcissu_font import archive, entries
from translation_adapter import extract_virtual_files, restore_virtual_pe
import pefile


@dataclass(frozen=True)
class ChineseBuild:
    payload: dict[str, bytes]
    executable: bytes
    report: dict


_CAPTION_HOOKS = {
    'narci_iris': [('Narcissu_cn.dll', '9aa1a7d223d7a34143b33af9c8ab9f21bbdf5a20b00e82afa5d8c4ac12a151ba', 0x5113, 'c7451060630310')],
    'narci_zero': [('Narcissu_cn.dll', 'd1b1d313bd9b00236e338dbae95653941e7103dd747f2b77651e3b12cbacd256', 0x52f3, 'c74510c0990310')],
    'narci_sumire': [('Narcissu_cn.dll', '2505a3280450fd40f5a76b66dc2eb48c5e79732b010604522cbe479e7e128148', 0x52f3, 'c74510c0990310')],
    'narci_himeko': [('Narcissu_cn.dll', '4d4f57979f15ac9be55723d51ba4e0413ec8274adcea6eb177af953911a74919', 0x52f3, 'c74510c0990310')],
    'narci_onetwo': [('Narcissu_cn.dll', '4e09ea0718dabe062756ad576828bf84f6779fe22be9b929a794a8495ecf9766', 0x3473, 'c7451048420310'),
                      ('FontPatch.dll', 'f73496c836c0c5b3e4e44158b70fdf15ebb219f564d1489aa43cb93128285167', 0x1443, 'c745104c3d0110')],
}


def _translation_lines(blob):
    # Encoding is a per-table property: even Iris/Zero mix GBK UI and UTF-16 story tables.
    if blob.startswith(b'\xff\xfe'):
        encoding = 'utf-16'
    elif blob.startswith(b'\xfe\xff'):
        encoding = 'utf-16-be'
        blob = blob[2:]
    else:
        encoding = 'gbk'
    return blob.decode(encoding).splitlines(), encoding


def _encode_table(lines, encoding):
    text = '\r\n'.join(lines) + '\r\n'
    if encoding == 'utf-16-be':
        return b'\xfe\xff' + text.encode(encoding)
    return text.encode(encoding)


def _nonascii_literals(script):
    return [i for i in script.ins if i.name == 'ldstr' and any(c >= 128 for c in i.fields['s'])]


def _loader_literals(script):
    # All five pinned v1.1 Narcissu_cn DLLs use `cmp byte ptr [eax], 0x81;
    # jb ...` when collecting ldstr translations. ASCII-prefixed error strings
    # containing Japanese later in the literal do not consume a table record.
    return [i for i in script.ins if i.name == 'ldstr' and i.fields['s']
            and i.fields['s'][0] >= 0x81]


def prepare_menu_translation(original_blob, patched_blob, table_blob=None, *, replacements=None,
                             source_aliases=None):
    """Retain CP932 loader markers and append one translation per new ldstr.

    Only UI scripts without dialogue `text` opcodes are supported here. Story
    tables use a different stream of records and are never passed to this helper.
    `replacements` maps an original CP932 literal (decoded string) to new UI text.
    `source_aliases` maps appended ldstr code offsets to their original offsets.
    Cloned literals retain CP932 bytes and reuse the original table record; only
    genuine new UI strings are decoded as GBK and replaced with CP932 markers.
    """
    original, prepared = Script(original_blob), Script(patched_blob)
    if any(i.name == 'text' for i in original.ins):
        raise ValueError('dialogue translation tables must not be rewritten as UI tables')
    originals = _loader_literals(original)
    replacements = replacements or {}
    if table_blob is None:
        translated = [i.fields['s'].rstrip(b'\0').decode('cp932') for i in originals]
        encoding = 'utf-16'
    else:
        translated, encoding = _translation_lines(table_blob)
        if len(translated) != len(originals):
            raise ValueError('UI translation table does not match original non-ASCII ldstr count')
    # The font menu patch changes one existing caption. Keep its original marker
    # bytes/length in code; update the corresponding translation instead.
    for index, item in enumerate(originals):
        prepared.code[item.offset:item.offset + len(item.raw)] = item.raw
        source = item.fields['s'].rstrip(b'\0').decode('cp932')
        if source in replacements:
            translated[index] = replacements[source]
    records_by_offset = {item.offset: index for index, item in enumerate(originals)}
    original_literals = {item.offset: item for item in original.ins if item.name == 'ldstr'}
    originals_by_marker = {}
    for item in original_literals.values():
        originals_by_marker.setdefault(item.fields['s'], []).append(item)
    aliases = {int(target): int(source) for target, source in (source_aliases or {}).items()}
    used_aliases = set()
    added = []
    reused = 0
    for item in prepared.ins:
        if item.offset < len(original.code) or item.name != 'ldstr':
            continue
        raw = item.fields['s']
        if item.offset in aliases:
            source_offset = aliases[item.offset]
            source = original_literals.get(source_offset)
            if source is None or source.fields['s'] != raw:
                raise ValueError('cloned translation alias does not match its original ldstr')
            used_aliases.add(item.offset)
            index = records_by_offset.get(source_offset)
            if index is not None:
                added.append(translated[index])
                reused += 1
            # ASCII-prefixed Japanese remains excluded by the native loader.
            continue
        if raw in originals_by_marker:
            indices = [records_by_offset[source.offset] for source in originals_by_marker[raw]
                       if source.offset in records_by_offset]
            meanings = {translated[index] for index in indices}
            if len(meanings) > 1:
                raise ValueError('ambiguous cloned translation marker requires a source alias')
            if meanings:
                added.append(translated[indices[0]])
                reused += 1
            continue
        if not any(c >= 128 for c in raw):
            continue
        added.append(item.fields['s'].rstrip(b'\0').decode('gbk'))
        size = len(item.fields['s'])
        marker = 'あ'.encode('cp932')
        if size <= len(marker):
            raise ValueError('new translation marker does not fit instruction')
        marker = marker.ljust(size - 1, b' ') + b'\0'
        prepared.code[item.offset + 4:item.offset + len(item.raw)] = marker
    if used_aliases != set(aliases):
        raise ValueError('translation source alias does not identify an appended ldstr')
    translated.extend(added)
    result = prepared.finish()
    if len(_loader_literals(Script(result))) != len(translated):
        raise ValueError('generated UI translation table is not aligned')
    return result, _encode_table(translated, encoding), {
        'encoding': encoding, 'existing_records': len(originals), 'added_records': len(added),
        'reused_records': reused, 'new_ui_records': len(added) - reused,
    }


def effective_chinese_sources(stock_files, virtual_files):
    """Apply original resource < virtual update ARC < loose #mjo precedence."""
    effective = dict(stock_files)
    for name in ['update.arc'] + [f'update{i}.arc' for i in range(1, 13)]:
        if name in virtual_files:
            effective.update({n: item[2] for n, item in entries(virtual_files[name]).items()})
    for path, data in virtual_files.items():
        if path.startswith('#mjo/') and path.endswith('.mjo'):
            name = path[len('#mjo/'):]
            if '/' in name:
                raise ValueError('nested virtual script path is unsupported')
            effective[name] = data
    return effective


def _caption_assignment(dll, expected_hash, rva, expected_hex):
    if hashlib.sha256(dll).hexdigest() != expected_hash:
        raise ValueError('unsupported translation DLL fingerprint')
    image = pefile.PE(data=dll, fast_load=True)
    offset = image.get_offset_from_rva(rva)
    expected = bytes.fromhex(expected_hex)
    if (len(expected) != 7 or expected[:3] != b'\xc7\x45\x10'
            or dll[offset:offset + 7] != expected
            or dll[offset + 7:offset + 10] != b'\x5d\xff\x25'):
        raise ValueError('translation DLL caption hook does not match')
    result = bytearray(dll)
    # Skip the 7-byte stack-argument assignment, preserving its immediate operand
    # and relocation record. The epilogue/forwarding jump still executes.
    result[offset:offset + 2] = b'\xeb\x05'
    return bytes(result)


def native_dialogs(executable):
    """Return (PE bytes, report) with fixed native UI fields changed to ASCII.

    Applies to the stock Japanese/English engines as well as restored Chinese
    engines. Replacements stay within existing resource/string fields and never
    parse or change embedded archives, script text, imports or instruction code.
    This does not identify or replace a title supplied dynamically by a script.
    """
    image = pefile.PE(data=executable, fast_load=True)
    resources = [s for s in image.sections if s.Name.rstrip(b'\0') == b'.rsrc']
    if len(resources) != 1:
        raise ValueError('expected one PE resource section')
    section = resources[0]
    start, end = section.PointerToRawData, section.PointerToRawData + section.SizeOfRawData
    result = bytearray(executable)
    changed = 0
    labels = {'フォント選択': 'Font', 'フォント名': 'Font', 'ｷｬﾝｾﾙ': 'Back',
              'スピード設定': 'Speed', 'サウンド設定': 'Sound', 'スクリーン詳細設定': 'Display',
              'コンフィグレーション': 'Settings', '初期化': 'Def', '画面効果': 'FX',
              '文字表示': 'Text', '高速': 'Hi', '低速': 'Lo', 'オートモード': 'Auto',
              '最小': 'Lo', '最大': 'Hi', '音声': 'VO', '音楽': 'BG', '効果音': 'SE',
              '全画面モード': 'Full', '常に手前に表示': 'On top',
              'バージョン情報': 'About', 'ユーザーサポート': 'Support',
              'ファイル/設定(&F)': '&File', 'ファイル(&F)': '&File',
              'セーブ(&S)': '&Save', '名前を付けてセーブ(&A)': 'Save &as',
              'ロード(&O)': '&Open', 'ロード(&L)': '&Load',
              '名前で指定してロード(&L)': '&Load file', 'ジョイスティック使用(&J)': '&Joystick',
              'スピード設定(&P)...': 'S&peed...', 'サウンド設定(&V)...': '&Volume...',
              'フォント設定(&F)...': '&Font...', 'フォント(&O)': 'F&ont',
              'タイトルへ戻る(&B)': '&Back', 'フルスクリーン(&F)': '&Full',
              'ウインドウ(&W)': '&Window', 'ワイドモード(&M)': '&Mode',
              'ムービー設定(&S)': '&Setup', 'ムービー禁止(&D)': '&Disable',
              'ムービーを禁止(&M)': '&Movie off',
              'スクリーン詳細設定(&O)...': '&Options...',
              'オートプレイ(F6)': 'Auto (F6)', '既読スキップ(F7)': 'Read (F7)',
              'スキップ(F8)': 'Skip(F8)', 'ヘルプ(&H)': '&Help',
              'バージョン情報(&A)...': '&About...', 'エラーログを開く(&E)': '&Error log',
              'コンフィグ(&F)...': 'Con&fig...', 'コンフィグ(F3)': 'Cfg(F3)',
              'オートプレイ': 'Auto', 'オートモード(F6)': 'Auto (F6)',
              'スキップ(F7)': 'Skip(F7)', 'スクリーン(F4)': 'View(F4)',
              'スクリーン(&S)': '&Screen', 'バックログ(F8)': 'Log(F8)',
              '読んだ所はスキップ(&R)': '&Read skip', 'スキップ(&N)': '&Next',
              'ユーザーサポート(&U)...': 'S&upport...', '次の選択に飛ぶ(&N)': 'Next(&N)'}
    for old, new in labels.items():
        needle = old.encode('utf-16le') + b'\0\0'
        replacement = new.ljust(len(old)).encode('utf-16le') + b'\0\0'
        if len(replacement) != len(needle):
            raise ValueError(f'native caption replacement exceeds resource field: {old!r}')
        for match in re.finditer(re.escape(needle), executable[start:end]):
            offset = start + match.start()
            if offset % 2:
                raise ValueError('unaligned native dialog caption')
            result[offset:offset + len(needle)] = replacement
            changed += 1
    samples = 0
    for old, new in [('文字サンプルです。１２３４', 'Font preview 1234 ABCD'), ('\u3000' * 30, ' ' * 60)]:
        needle = old.encode('cp932') + b'\0'
        replacement = new.encode('ascii')
        locations = []
        for data_section in image.sections:
            if data_section.Name.rstrip(b'\0') in (b'.rdata', b'.data'):
                lo = data_section.PointerToRawData
                hi = lo + data_section.SizeOfRawData
                locations.extend(lo + m.start() for m in re.finditer(re.escape(needle), executable[lo:hi]))
        if len(locations) > 1 or len(replacement) >= len(needle):
            raise ValueError('ambiguous or oversized font preview field')
        if locations:
            offset = locations[0]
            result[offset:offset + len(needle)] = replacement.ljust(len(needle) - 1, b' ') + b'\0'
            samples += 1
    # Hardcoded MessageBoxA strings live in original data sections. Never search
    # an overlay/embedded archive, where the same bytes could be story content.
    prompts = {'終了してよろしいですか？': 'Exit the game?',
               '終了します。よろしいですか？': 'Exit the game?',
               'ゲームを終了します。よろしいですか？': 'Exit the game?',
               'タイトルに戻ります。よろしいですか？': 'Return to title?',
               'エラーです': 'Error', '終了確認': 'Confirm', '確認': 'Info'}
    prompt_changes = 0
    for section in image.sections:
        if section.Name.rstrip(b'\0') not in (b'.rdata', b'.data'):
            continue
        lo, hi = section.PointerToRawData, section.PointerToRawData + section.SizeOfRawData
        for old, new in prompts.items():
            needle = old.encode('cp932') + b'\0'
            replacement = new.encode('ascii')
            if len(replacement) >= len(needle):
                raise ValueError('native prompt replacement exceeds its field')
            for match in re.finditer(re.escape(needle), executable[lo:hi]):
                offset = lo + match.start()
                # A complete NUL-terminated string, never a Japanese suffix.
                if offset > lo and executable[offset - 1] != 0:
                    continue
                result[offset:offset + len(needle)] = replacement.ljust(len(needle) - 1, b' ') + b'\0'
                prompt_changes += 1
    return bytes(result), {'native_caption_fields': changed, 'native_preview_fields': samples,
                           'native_prompt_fields': prompt_changes}


def build_chinese_payload(game, packed_exe_bytes, stock_files, font_family=None) -> ChineseBuild:
    """Build module-relative payload and a separate restored engine in memory.

    `stock_files` is the already-expanded effective original resource mapping,
    as accepted by build_overrides. The backend supplies the original EXE name
    when installing `executable`. All other results use module-relative paths.
    """
    if game not in _CAPTION_HOOKS:
        raise ValueError('unsupported Chinese module')
    virtual = extract_virtual_files(packed_exe_bytes)
    effective = effective_chinese_sources(stock_files, virtual)
    overrides, report, _functions, _hashes = build_overrides(game, effective, 'zh-CN', font_family)
    payload = dict(virtual)
    table_reports = {}
    for name, patched in list(overrides.items()):
        if not name.endswith('.mjo'):
            continue
        original = effective[name]
        added_ui = any(i.offset >= len(Script(original).code)
                       for i in _nonascii_literals(Script(patched)))
        if added_ui or (game == 'narci_onetwo' and name == 'pausemenu.mjo'):
            table_name = '#txt/' + name[:-4] + '.txt'
            replacements = {'フォント設定': '字体 / 字号'} if name == 'pausemenu.mjo' else None
            aliases = (report.get('pagination', {}).get('translation_source_aliases')
                       if name == 'console.mjo' else None)
            patched, table, table_report = prepare_menu_translation(
                original, patched, payload.get(table_name), replacements=replacements,
                source_aliases=aliases)
            overrides[name] = patched
            payload[table_name] = table
            table_reports[name] = table_report
        # Keep the translation DLL's highest-priority loose script in sync with
        # the same bytes in update12.arc, including originally absent CONFIG.
        payload['#mjo/' + name] = patched
    payload['update12.arc'] = archive(overrides)
    hooks = []
    for name, digest, rva, expected in _CAPTION_HOOKS[game]:
        if name not in payload:
            raise ValueError('required Chinese translation DLL is missing')
        payload[name] = _caption_assignment(payload[name], digest, rva, expected)
        hooks.append({'dll': name, 'rva': rva, 'change': 'preserve original window and child-control captions'})
    executable, dialogs = native_dialogs(restore_virtual_pe(packed_exe_bytes))
    report = dict(report, source='PC Chinese v1.1 virtual files', ui_translation_tables=table_reports,
                  caption_hooks=hooks, **dialogs, payload_files=sorted(payload))
    return ChineseBuild(payload, executable, report)
