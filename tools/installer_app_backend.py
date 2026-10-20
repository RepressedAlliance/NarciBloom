"""Player-facing operations shared by the Windows and SteamOS front ends."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from build_font_settings import build_overrides
from install_manager import InstallError, InstallManager
from patch_narcissu_font import archive, entries
from steam_discovery import discover_installations, inspect_game
from translation_package import read_package, resource_path, source_notice

VERSION = '0.2.0-preview.4'
ARCHIVES = ['scenario.arc', 'fastdata.arc', 'update.arc'] + [f'update{i}.arc' for i in range(1, 12)]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _profiles():
    return json.loads(resource_path('docs/source-profiles.json').read_text(encoding='utf-8'))['profiles']


def _translation_hashes():
    return {item['path'].split('/')[0]: item['sha256']
            for item in source_notice()['input_fingerprint']['members'] if item['path'].endswith('.exe')}


def _executable_relative(manager, story, record):
    actual = story.executable.relative_to(manager.game_dir).as_posix()
    return next((name for name in (record or {}).get('files', {})
                 if name.casefold() == actual.casefold()), actual)


def _baseline(manager, module, executable_relative):
    """Read only code/config source archives; large media archives are irrelevant."""
    files = {}
    for name in ARCHIVES:
        blob = manager.original_file(f'{module}/{name}')
        if blob is not None:
            files.update({name: value[2] for name, value in entries(blob).items()})
    executable = manager.original_file(executable_relative)
    if executable is None:
        raise InstallError(f'Missing story executable: {module}')
    for match in re.finditer(rb'MajiroArcV[13]\.000\x00', executable):
        try:
            embedded = entries(executable, match.start())
        except (AssertionError, ValueError, IndexError, struct.error):
            continue
        files.update({name: value[2] for name, value in embedded.items()})
    return executable, files


def _recognize(module, executable, files):
    checksum = _sha(executable)
    for profile in _profiles():
        if profile['module'] != module or profile['exe_sha256'] != checksum:
            continue
        if all(name in files and _sha(files[name]) == digest for name, digest in profile['files'].items()):
            return profile['language']
    if _translation_hashes().get(module) == checksum:
        # The packed layer is matched separately; the stock resource baseline
        # still has to match one of the supported language profiles.
        for profile in _profiles():
            if profile['module'] == module and all(
                    name in files and _sha(files[name]) == digest for name, digest in profile['files'].items()):
                return 'zh-CN'
    raise InstallError(f'Unsupported or modified source version: {module}. Restore Steam files or use a supported PC v1.1 translation.')


def _check_external_overrides(manager, module):
    folder = manager.game_dir / module
    record = manager.read_record() or {'files': {}}
    managed = {name.casefold() for name in record['files']}
    # Unknown loose scripts take precedence over an ARC and can silently defeat
    # the patch. Do not overwrite an earlier mod without recognizing its input.
    candidates = [folder / 'update12.arc']
    environments = [path for path in folder.iterdir() if path.name.casefold() == 'majiro.env']
    if len(environments) > 1:
        raise InstallError('Conflicting environment filenames: ' + ', '.join(path.name for path in environments))
    candidates.extend(environments)
    for name in ('#mjo', '#cfg', '#txt'):
        directory = folder / name
        if directory.is_dir():
            candidates.extend(path for path in directory.rglob('*') if path.is_file())
    unknown = [str(path.relative_to(manager.game_dir)) for path in candidates
               if path.exists() and path.relative_to(manager.game_dir).as_posix().casefold() not in managed]
    if unknown:
        raise InstallError('Existing unrecognized overrides must be removed or restored first: ' + ', '.join(unknown[:4]))


def available_games():
    return [{'path': str(game.path), 'title': 'Narcissu 10th Anniversary Anthology Project'}
            for game in discover_installations()]


def scan_game(path):
    game = inspect_game(path)
    manager = InstallManager(game.path)
    record = manager.read_record()
    prior = (record or {}).get('metadata', {}).get('stories', {})
    transaction = manager.state / 'transaction.json'
    pending = False
    if transaction.is_file():
        pending = json.loads(transaction.read_text(encoding='utf-8')).get('status') == 'pending'
    modules = []
    for module in game.modules:
        error = None
        try:
            if pending:
                modules.append({'id': module.id, 'title': module.title,
                                'language': prior.get(module.id, {}).get('language', 'unknown'),
                                'supported': True, 'reason': 'An interrupted operation will be recovered before installation.'})
                continue
            _check_external_overrides(manager, module.id)
            executable, files = _baseline(manager, module.id, _executable_relative(manager, module, record))
            language = _recognize(module.id, executable, files)
            language = prior.get(module.id, {}).get('language', language)
        except (ValueError, AssertionError, OSError, InstallError, struct.error, IndexError) as exc:
            language, error = 'unknown', str(exc)
        modules.append({'id': module.id, 'title': module.title, 'language': language,
                        'supported': error is None, 'reason': error})
    return {'path': str(game.path), 'modules': modules,
            'installed_version': (record or {}).get('version'), 'recovery_required': pending}


def default_font(language):
    """Choose a locally present CJK family; no system installation or locale change."""
    preferred = (['Microsoft YaHei', 'SimSun', 'Noto Sans CJK SC'] if language == 'zh-CN'
                 else ['UD Digi Kyokasho N', 'Yu Gothic', 'MS Gothic', 'Noto Sans CJK JP'])
    available = ''
    if os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                    index = 0
                    while True:
                        try:
                            available += ' ' + winreg.EnumValue(key, index)[0]
                            index += 1
                        except OSError:
                            break
            except OSError:
                pass
    else:
        try:
            available = subprocess.check_output(['fc-list', ':lang=' + ('zh-cn' if language == 'zh-CN' else 'ja'),
                                                 'family'], text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        preferred = list(reversed(preferred))
    for family in preferred:
        if family.casefold() in available.casefold():
            return family
    # Windows/Wine can provide these aliases without a host fontconfig entry.
    return 'Microsoft YaHei' if language == 'zh-CN' else 'MS Gothic'


def _prepare_native_engine(executable):
    from chinese_builder import native_dialogs
    from native_fontout import stock_fontout
    executable, charset_report = stock_fontout(executable)
    executable, report = native_dialogs(executable)
    report['script_ui_charset'] = charset_report
    return executable, report


def run_install(game_dir, modules, chinese=False, progress=lambda message: None,
                font_family=None, translation_archive=None):
    manager = InstallManager(game_dir)
    manager.recover()
    game = inspect_game(manager.game_dir)
    chosen = list(dict.fromkeys(modules))
    if not chosen or set(chosen) - set(game.module_ids):
        raise InstallError('Select at least one locally installed story')
    record = manager.read_record() or {'files': {}, 'metadata': {}}
    executables = {story.id: _executable_relative(manager, story, record) for story in game.modules}
    prior = record['metadata'].get('stories', {})
    # The selection is the complete desired set: deselected previously managed
    # stories are restored by InstallManager as part of the same transaction.
    needs_archive = chinese or any(prior.get(module, {}).get('language') == 'zh-CN'
                                  and _sha(manager.original_file(executables[module]) or b'')
                                      != _translation_hashes().get(module) for module in chosen)
    package = None
    if needs_archive:
        translation_archive = translation_archive or record['metadata'].get('translation_archive')
        if not translation_archive:
            raise InstallError('Select the prepared PC v1.1 translation ZIP or original RAR package')
        progress('Checking the PC v1.1 translation input…')
        package = read_package(translation_archive, chosen)
    payload, stories = {}, {}
    for module in chosen:
        progress(f'Building {module}…')
        _check_external_overrides(manager, module)
        executable_relative = executables[module]
        executable, files = _baseline(manager, module, executable_relative)
        language = _recognize(module, executable, files)
        use_chinese = chinese or language == 'zh-CN' or prior.get(module, {}).get('language') == 'zh-CN'
        language = 'zh-CN' if use_chinese else language
        family = font_family or default_font(language)
        if use_chinese:
            from chinese_builder import build_chinese_payload
            if package is None:
                # Standalone patch can use a recognized packed translation
                # already installed by the player, without an external archive.
                packed = executable
            else:
                members = [name for name in package if name.split('/')[0].casefold() == module
                           and name.casefold().endswith('.exe')]
                if len(members) != 1:
                    raise InstallError(f'Expected one translation executable for {module}')
                member = members[0]
                packed = package[member]
            built = build_chinese_payload(module, packed, files, font_family=family)
            generated = dict(built.payload)
            generated[Path(executable_relative).name] = built.executable
            report = built.report
            if package:
                generated['NarciBloom-translation-readme.txt'] = package['readme.txt']
        else:
            override, report, _, _ = build_overrides(module, files, language, family)
            generated = {'update12.arc': archive(override)}
            engine, native_report = _prepare_native_engine(executable)
            generated[Path(executable_relative).name] = engine
            report.update(native_report)
        for name, data in generated.items():
            payload[f'{module}/{name}'] = data
        stories[module] = {'language': language, 'font_family': family,
                           'source_exe_sha256': _sha(executable), 'build': report}
    metadata = {'stories': stories}
    if translation_archive and needs_archive:
        metadata['translation_archive'] = str(Path(translation_archive).resolve())
    # Staging contains only generated install files, never full media or saves.
    with tempfile.TemporaryDirectory(prefix='narcibloom-') as temporary:
        staging = Path(temporary)
        for relative, data in payload.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        progress('Installing generated files…')
        result = manager.install(staging, {name: _sha(data) for name, data in payload.items()},
                                 version=VERSION, metadata=metadata)
    progress('Installation complete.')
    return {'version': VERSION, 'modules': list(stories), 'files': len(result['files'])}


def run_uninstall(game_dir, progress=lambda message: None):
    progress('Restoring files saved before installation…')
    result = InstallManager(game_dir).uninstall()
    progress('Original files restored. Personal saves retained.')
    return result
