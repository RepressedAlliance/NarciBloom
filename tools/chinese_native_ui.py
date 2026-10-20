"""Localize fixed native UI in the five supported PC Chinese v1.1 engines.

This deliberately does not change ANSI code pages or install runtime hooks.
Dialog/menu captions are UTF-16 resource fields. The voice label's redundant
ANSI overwrite is skipped, leaving the Unicode resource caption intact.
"""
from __future__ import annotations

import hashlib
import re
import struct

import pefile


# Restored engines from the fixed, attributed PC Chinese v1.1 input. Never
# apply these instruction profiles to stock JA/EN engines or arbitrary PEs.
_LEGACY_TABS = ((0x442AE4, 0x4AC74C), (0x442B0F, 0x4AC740),
                (0x442B35, 0x4AC734), (0x442B5B, 0x4AC728))
_PROFILES = {
    '4a1b93637f41fda38f1bccacbaec5b81f841bc2ec87a4ff7ab09aa6d33e346f4':
        ('narci_iris', (0x4410CB, 0x4410F6, 0x4446A2, 0x4446D5), _LEGACY_TABS),
    '07218e11bde45b98e50f0bf465aa8a91aa5f995b98a0c075d806c0148850709d':
        ('narci_zero', (0x4410CB, 0x4410F6, 0x4446A2, 0x4446D5), _LEGACY_TABS),
    '7b6e5dad7dbbd8e7ac2dc4389e7b9a365bb6b9b8c2420a5e642a54a62e139618':
        ('narci_himeko', (0x4410CB, 0x4410F6, 0x4446A2, 0x4446D5), _LEGACY_TABS),
    '38819c6d3fd6a572a05a4b2c1bef18ba2a7411c43075e89675773851dda7c948':
        ('narci_onetwo', (0x46D030, 0x46D05B, 0x47295E, 0x472989),
         ((0x472BC0, 0x4C8AA4), (0x472BF2, 0x4C8AB0),
          (0x472C1C, 0x4C8ABC), (0x472C46, 0x4C8AC8))),
    'cc634eec6b97538d508057b7cc81f4140d0d2a3df6fb70e0d585ebc559c108f9':
        ('narci_sumire', (0x46A83E, 0x46A869, 0x46ADB0, 0x46ADDB),
         ((0x467743, 0x4AD1E4), (0x467771, 0x4AD1F0),
          (0x467798, 0x4AD1FC), (0x4677BF, 0x4AD208))),
}

_DIALOG_LABELS = {
    'OK': '确定', 'ｷｬﾝｾﾙ': '取消', '初期化': '重置',
    'コンフィグレーション': '设置', 'サウンド設定': '音量设置',
    'フォント選択': '字体选择', 'フォント名': '字体名',
    'スピード設定': '速度设置', 'スクリーン詳細設定': '显示设置',
    '文字表示': '文字显示', '画面効果': '画面效果', '高速': '快', '低速': '慢',
    'オートモード': '自动模式', '音声': '语音', '音楽': '音乐', '効果音': '音效',
    '最小': '低', '最大': '高', '男性の音声をＯＦＦ': '关闭男声',
    # Narcissu's supported configuration hides the male channel and uses the
    # surviving female-channel control as the combined voice toggle.
    '女性の音声をＯＦＦ': '关闭语音', '音楽をＯＦＦ': '关闭音乐',
    '効果音をOFF': '关闭音效', '音声は全てOFF': '关闭全部语音',
    '音声個別設定': '单独语音设置', 'ＯＦＦにする音声をチェックしてください': '勾选需要关闭的语音',
    '次テキスト表示時に音声を停止する': '显示下一段文字时停止语音',
    '音声再生中にBGM音量を下げる': '播放语音时降低背景音乐音量',
    '人物の場所に合わせて音声をパンニング': '按人物位置调整语音声像',
    'アンチエイリアス': '抗锯齿', '影付き': '阴影', '縁取り': '描边', '太字': '粗体',
    '全画面モード': '全屏模式', 'フルスクリーンモード': '全屏模式',
    'ウインドウモード': '窗口模式', '常に手前に表示': '窗口置顶',
    '画面サイズ': '画面大小', 'フルスクリーンモード時の画面設定': '全屏模式的显示设置',
    '終了時にウィンドウの位置を保存': '退出时保存窗口位置',
    '全画面時に拡大する（中～低速にパフォーマンスは低下）': '全屏时放大（中低速设备性能可能下降）',
    '全画面時に拡大する（推奨）': '全屏时放大（推荐）',
    '1280x720(実サイズ / 高速 / 推奨)': '1280x720（原始大小／高速／推荐）',
    'DirectDrawを使用': '使用DirectDraw',
    'CTRLキーのスキップ動作は既読のみ': 'Ctrl键仅跳过已读内容',
    '選択肢後もスキップを継続': '选择后继续跳过',
    'クイックセーブ時に確認ダイアログを表示する': '快速保存时显示确认窗口',
    'クイックロード時に確認ダイアログを表示する': '快速读取时显示确认窗口',
    'ゲームの保存と読み込み': '保存与读取',
    'ロードするデータを指定してください': '请选择要读取的存档',
    'フォルダ情報の読み込み中…': '正在读取文件夹信息…',
    'バージョン情報': '版本信息', 'ユーザーサポート': '用户支持',
    'より新しいサポート情報は\n下記のホームページにてご確認ください。': '最新支持信息请查看下方网站。',
}

_MENU_LABELS = {
    'ファイル/設定': '文件/设置', 'ファイル': '文件', 'セーブ': '保存',
    '名前を付けてセーブ': '另存为', 'ロード': '读取', '名前で指定してロード': '按名称读取',
    'Qセーブ': '快存', 'Qロード': '快读', 'ジョイスティック使用': '使用手柄',
    'スピード設定': '速度设置', 'サウンド設定': '音量设置', 'フォント設定': '字体设置',
    'フォント': '字体', 'タイトルへ戻る': '返回标题', 'フルスクリーン': '全屏',
    'ウインドウ': '窗口', 'ワイドモード': '宽屏模式', 'ムービー設定': '视频设置',
    'ムービー禁止': '禁用视频', 'ムービーを禁止': '禁用视频',
    'スクリーン詳細設定': '显示设置', 'オートプレイ': '自动播放',
    'オートモード': '自动模式', '既読スキップ': '跳过已读', 'スキップ': '跳过',
    '強制スキップ': '强制跳过', 'ヘルプ': '帮助', 'バージョン情報': '版本信息',
    'エラーログを開く': '打开错误日志', 'コンフィグ': '设置', '設定': '设置',
    'スクリーン': '显示', 'バックログ': '回看', '読んだ所はスキップ': '跳过已读',
    'ユーザーサポート': '用户支持', '次の選択に飛ぶ': '跳到下一选择',
    '前の選択に戻る': '返回上一选择', '画面の保存': '保存画面', '画面設定': '显示设置',
    '終了': '退出', '自動進行': '自动播放', '音声個別設定': '单独语音设置',
    '常に手前に表示': '窗口置顶', '拡張設定': '扩展设置',
    'DirectShowで再生': 'DirectShow播放', 'MCIで再生': 'MCI播放',
}


class _Reader:
    def __init__(self, blob):
        self.blob, self.pos = blob, 0

    def take(self, count):
        end = self.pos + count
        if count < 0 or end > len(self.blob):
            raise ValueError('truncated native UI resource')
        value = self.blob[self.pos:end]
        self.pos = end
        return value

    def number(self, fmt):
        value = struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))
        return value[0] if len(value) == 1 else value

    def text(self):
        start = self.pos
        first = self.number('H')
        if first == 0xFFFF:
            self.number('H')
            return None
        if first:
            while self.number('H'):
                pass
        return (start, self.pos - start,
                self.blob[start:self.pos - 2].decode('utf-16le'))

    def align(self):
        self.take((-self.pos) % 4)


def _dialog_fields(blob):
    """Read standard/DIALOGEX fields without changing template alignment."""
    r = _Reader(blob)
    extended = blob[:4] == b'\x01\0\xff\xff'
    if extended:
        r.take(8)  # version, signature, help ID
        _ext, style = r.number('II')
    else:
        style, _ext = r.number('II')
    count = r.number('H')
    r.take(8)
    r.text()  # menu
    r.text()  # class
    fields = [(None, r.text())]
    if style & 0x40:
        r.take(6 if extended else 2)
        r.text()  # preserve the native dialog's font face
    for _ in range(count):
        r.align()
        r.take(20 if extended else 16)
        ident = r.number('I' if extended else 'H')
        r.text()  # control class
        fields.append((ident, r.text()))
        extra = r.number('H')
        if extra:
            r.take(extra - 2)
    return fields


def _menu_fields(blob):
    r = _Reader(blob)
    version, extra = r.number('HH')
    if version != 0:
        raise ValueError('unsupported native menu resource version')
    r.take(extra)
    fields = []

    def walk(depth):
        if depth > 32:
            raise ValueError('native menu nesting exceeds limit')
        while True:
            flags = r.number('H')
            ident = None if flags & 0x10 else r.number('H')
            fields.append((ident, r.text()))
            if flags & 0x10:
                walk(depth + 1)
            if flags & 0x80:
                break

    walk(0)
    return fields


def _menu_translation(text):
    label, tab, shortcut = text.partition('\t')
    match = re.fullmatch(r'(.*?)(\([&]?[A-Za-z0-9]+\))?(\.\.\.)?', label)
    if match is None:
        return None
    body, accelerator, dots = match.groups()
    if body not in _MENU_LABELS:
        return None
    return _MENU_LABELS[body] + (accelerator or '') + (dots or '') + tab + shortcut


def _put_text(result, offset, capacity, text):
    encoded = text.encode('utf-16le')
    if (capacity < 2 or capacity % 2 or offset < 0 or offset + capacity > len(result)
            or len(encoded) > capacity - 2):
        raise ValueError('Chinese native caption exceeds its resource field')
    # Spaces retain the original terminator position and every later field.
    result[offset:offset + capacity] = (encoded + b' \0' * ((capacity - 2 - len(encoded)) // 2)
                                        + b'\0\0')


def _skip_voice_overwrite(raw, result, offset, expected_pointer, iat):
    """Cancel one argument then skip the unchanged HWND push and ANSI call.

    The original pointer and call operands remain in place, so HIGHLOW
    relocations still operate on data operands, never replacement opcodes.
    """
    if raw[offset:offset + 10] != b'\x68' + struct.pack('<I', expected_pointer) + b'\x68\xed\x03\0\0':
        raise ValueError('unexpected Chinese voice label arguments')
    tail = raw[offset + 10:offset + 17]
    if tail[:3] in (b'\x57\xff\xd6', b'\x56\xff\xd7'):
        skip = 3
    elif tail[:1] in (b'\x56', b'\x57') and tail[1:] == b'\xff\x15' + struct.pack('<I', iat):
        skip = 7
    else:
        raise ValueError('unexpected Chinese voice label call')
    result[offset + 5:offset + 10] = b'\x83\xc4\x04\xeb' + bytes([skip])
    return skip


def localize_chinese_native_ui(executable, *, baseline=None):
    """Return (bytes, report) for a recognized restored Chinese v1.1 engine.

    ``baseline`` may contain the existing fixed ASCII prompt/font-preview
    changes from ``native_dialogs``. Original bytes determine field boundaries
    and instruction profiles; unknown engines fail rather than guessing.
    Copyright notices, actor names, scripts, saves and OS dialogs are excluded.
    """
    digest = hashlib.sha256(executable).hexdigest()
    if digest not in _PROFILES:
        raise ValueError('unsupported restored Chinese native UI engine')
    module, voice_calls, tabs = _PROFILES[digest]
    if baseline is not None and len(baseline) != len(executable):
        raise ValueError('native UI baseline changed PE size')
    result = bytearray(executable if baseline is None else baseline)
    image = pefile.PE(data=executable)
    base = image.OPTIONAL_HEADER.ImageBase
    relocations = {entry.rva for block in getattr(image, 'DIRECTORY_ENTRY_BASERELOC', [])
                   for entry in block.entries if entry.type == 3}

    def unrelocated(offset, size):
        rva = image.get_rva_from_offset(offset)
        if any(rva < start + 4 and start < rva + size for start in relocations):
            raise ValueError('native UI instruction overlaps a base relocation')

    imports = {e.name: e.address for lib in image.DIRECTORY_ENTRY_IMPORT for e in lib.imports if e.name}
    captions = menus = 0
    volume_controls = set()
    remaining = set()
    for typ in image.DIRECTORY_ENTRY_RESOURCE.entries:
        if typ.id not in (4, 5):
            continue
        for resource in typ.directory.entries:
            name = str(resource.name) if resource.name is not None else str(resource.id)
            for language in resource.directory.entries:
                data = language.data.struct
                offset = image.get_offset_from_rva(data.OffsetToData)
                blob = image.get_data(data.OffsetToData, data.Size)
                fields = _dialog_fields(blob) if typ.id == 5 else _menu_fields(blob)
                # Generic engine editor/H-scene panels are not Narcissu UI.
                excluded = name.startswith('ABOUTDIALOG') or name == 'EXTRASETUP'
                for ident, field in fields:
                    if field is None:
                        continue
                    pos, size, text = field
                    if typ.id == 5 and name in ('VOLUMECONFIG', 'SUB_VOLUMECONFIG') and ident == 1005:
                        if text != '女性の音声をＯＦＦ':
                            raise ValueError('unexpected Chinese voice checkbox template')
                        volume_controls.add((name, language.id))
                    new = None if excluded else (_DIALOG_LABELS.get(text) if typ.id == 5 else _menu_translation(text))
                    if new is None:
                        if text and any(ord(c) >= 128 for c in text):
                            remaining.add((typ.id, name))
                        continue
                    _put_text(result, offset + pos, size, new)
                    captions += typ.id == 5
                    menus += typ.id == 4
    if volume_controls != {('VOLUMECONFIG', 1041), ('SUB_VOLUMECONFIG', 1041)}:
        raise ValueError('expected both Chinese voice checkbox templates')
    needle = '音声をＯＦＦ'.encode('cp932') + b'\0'
    locations = []
    for section in image.sections:
        if section.Name.rstrip(b'\0') not in (b'.rdata', b'.data'):
            continue
        lo, hi = section.PointerToRawData, section.PointerToRawData + section.SizeOfRawData
        locations.extend(lo + m.start() for m in re.finditer(re.escape(needle), executable[lo:hi]))
    if len(locations) != 1:
        raise ValueError('ambiguous Chinese voice label field')
    pointer = base + image.get_rva_from_offset(locations[0])
    call_report = []
    for va in voice_calls:
        offset = image.get_offset_from_rva(va - base)
        unrelocated(offset + 5, 5)
        skip = _skip_voice_overwrite(executable, result, offset, pointer, imports[b'SetDlgItemTextA'])
        call_report.append({'argument_rva': va - base + 5, 'skipped_bytes': skip})
    # TCM_INSERTITEMW defines the string encoding; SendMessageA merely passes
    # that explicit common-control message. No IAT/API replacement is needed.
    for (message, pointer), (old, new) in zip(tabs, (
            ('システム', '系统'), ('サウンド', '音量'), ('スクリーン', '显示'), ('フォント', '字体'))):
        offset = image.get_offset_from_rva(message - base)
        unrelocated(offset, 5)
        if executable[offset:offset + 5] != b'\x68\x07\x13\0\0':
            raise ValueError('unexpected native tab insert message')
        string_offset = image.get_offset_from_rva(pointer - base)
        original = old.encode('cp932') + b'\0'
        if executable[string_offset:string_offset + len(original)] != original:
            raise ValueError('unexpected native tab caption')
        encoded = new.encode('utf-16le') + b'\0\0'
        if len(encoded) > len(original):
            raise ValueError('Chinese tab caption exceeds its field')
        result[offset:offset + 5] = b'\x68\x3e\x13\0\0'
        result[string_offset:string_offset + len(original)] = encoded.ljust(len(original), b'\0')
    return bytes(result), {
        'chinese_native_ui': {'module': module, 'dialog_fields': captions, 'menu_fields': menus,
                              'voice_overwrite_guards': call_report, 'unicode_tabs': len(tabs),
                              'remaining_resource_groups': [f'{kind}:{name}' for kind, name in sorted(remaining)],
                              'scope': 'fixed Unicode captions; ANSI error/OS/dynamic actor fields excluded'},
    }
