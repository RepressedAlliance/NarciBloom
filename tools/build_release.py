"""Build portable player distributions; never include installed game files."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import sysconfig
import tkinter
import urllib.error
import urllib.request
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def runtime_notices(destination):
    """Keep the notices for the Python runtime and its bundled native libraries."""
    python_version = '.'.join(map(str, sys.version_info[:3]))
    tcl_version = tkinter.Tcl().eval('info patchlevel')
    openssl_version = ssl.OPENSSL_VERSION.split()[1]
    zlib_version = zlib.ZLIB_RUNTIME_VERSION
    openssl_url = f'https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/LICENSE.txt'
    candidates = {
        'CPython-LICENSE.txt': (python_version, [f'https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE']),
        'OpenSSL-LICENSE.txt': (openssl_version, [openssl_url]),
        'zlib-LICENSE.txt': (zlib_version, [
            f'https://raw.githubusercontent.com/madler/zlib/v{zlib_version}/LICENSE',
            f'https://raw.githubusercontent.com/madler/zlib/v{zlib_version}/README']),
        'Tcl-LICENSE.txt': (tcl_version, [f"https://raw.githubusercontent.com/tcltk/tcl/core-{tcl_version.replace('.', '-')}/license.terms"]),
    }
    sources = {}
    for filename, (version, urls) in candidates.items():
        failure = None
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read(256 * 1024)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    failure = exc
                    continue
                raise RuntimeError(f'Cannot fetch {filename} for version {version}: {url} (HTTP {exc.code})') from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f'Cannot fetch {filename} for version {version}: {url}') from exc
            if len(data) < 100 or b'<html' in data.lower():
                raise ValueError(f'Invalid runtime license response: {filename}, version {version}, {url}')
            if url.endswith('/README') and (f'zlib {version}'.encode() not in data
                    or b'Copyright notice:' not in data or b'This notice may not be removed or altered' not in data):
                raise ValueError(f'The zlib {version} README does not contain its version and complete license notice')
            (destination / filename).write_bytes(data)
            sources[filename] = url
            print(f'Runtime notice: {filename}, version {version}, {url}', flush=True)
            break
        else:
            raise RuntimeError(f'No version-matched runtime notice found for {filename}, version {version}: {urls}') from failure
    (destination / 'runtime-sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')


def _prepared_input(path):
    """Validate the prepared container, including when a caller renamed it."""
    from translation_package import PREPARED_ARCHIVE_NAME, PreparedTranslation, read_package
    path = Path(path)
    contents = read_package(path, ['narci_onetwo'])
    engines = [value for name, value in contents.items() if name.casefold().endswith('.exe')]
    if (len(engines) != 1 or not isinstance(engines[0], PreparedTranslation)
            or engines[0].module != 'narci_onetwo'):
        raise ValueError('Chinese releases require the validated prepared PC v1.1 ZIP; '
                         'the original RAR remains supported as manual installer input')
    return path, PREPARED_ARCHIVE_NAME


def bundle_existing(font_package, translation_archive, destination):
    """Add an unchanged validated prepared input ZIP to a built platform package.

    This also allows a Linux build from CI to be bundled on Windows without
    rebuilding its native launcher or losing the ZIP executable permission bits.
    """
    sys.path.insert(0, str(ROOT / 'tools'))
    translation_archive, translation_name = _prepared_input(translation_archive)
    if not font_package.name.endswith('-Fonts.zip'):
        raise ValueError('Select an original Fonts ZIP package')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / font_package.name.replace('-Fonts.zip', '-Chinese.zip')
    with zipfile.ZipFile(font_package) as source, zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as output:
        roots = {item.filename.split('/')[0] for item in source.infolist()}
        if len(roots) != 1:
            raise ValueError('Expected exactly one portable package folder')
        old_root = roots.pop()
        new_root = old_root.removesuffix('-Fonts') + '-Chinese'
        launcher = False
        for item in source.infolist():
            parts = Path(item.filename).parts
            if '..' in parts or item.filename.startswith('/'):
                raise ValueError('Unexpected archive path')
            data = source.read(item)
            relative = item.filename[len(old_root) + 1:]
            if relative in ('NarciBloom', 'NarciBloom.exe'):
                relative = relative.replace('NarciBloom', 'NarciBloomChinese', 1)
                launcher = True
            item.filename = new_root + '/' + relative
            output.writestr(item, data)
        if not launcher:
            raise ValueError('Native launcher is missing')
        output.write(translation_archive, new_root + '/' + translation_name)
    with target.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'filename': target.name, 'sha256': checksum, 'size_bytes': target.stat().st_size}


def build(destination, translation_archive=None):
    sys.path.insert(0, str(ROOT / 'tools'))
    from installer_app_backend import VERSION
    if translation_archive:
        translation_archive, translation_name = _prepared_input(translation_archive)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise SystemExit('Choose a new empty build destination; existing output is retained')
    # Keep common SteamOS libraries on the OS instead of redistributing an
    # accidental copy of its X11/GLib/font/RAR stack and its source obligations.
    # Python extensions and Python itself are retained by PyInstaller's API.
    spec = destination / 'NarciBloom.spec'
    spec.write_text(f'''import sys
from PyInstaller.utils.hooks import collect_data_files
sys.path.insert(0, {str(ROOT / '.deps/majiro-py/src')!r})
a = Analysis([{str(ROOT / 'tools/app.py')!r}],
    pathex=[{str(ROOT / 'tools')!r}, {str(ROOT / '.deps/majiro-py/src')!r}],
    binaries=[], datas=[({str(ROOT / 'docs')!r}, 'docs')] + collect_data_files('evbunpack'),
    hiddenimports=['installer_app_backend', 'chinese_builder'],
    hookspath=[], hooksconfig={{}}, runtime_hooks=[], excludes=[], noarchive=False)
if sys.platform != 'win32':
    a.exclude_system_libraries(['libtcl*.so*', 'libtk*.so*', 'libffi.so*',
                               'libcrypto.so*', 'libssl.so*', 'libz.so*'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NarciBloom',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console={sys.platform != 'win32'!r})
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='NarciBloom')
''', encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--distpath', str(destination / 'frozen'), '--workpath', str(destination / 'pyinstaller'),
               str(spec)]
    subprocess.run(command, cwd=ROOT, check=True)
    folder = destination / 'frozen/NarciBloom'
    notices = folder / 'licenses'
    notices.mkdir()
    shutil.copy2(ROOT / 'LICENSE', notices / 'NarciBloom-LICENSE.txt')
    shutil.copy2(ROOT / 'LICENSE-APACHE-2.0.txt', notices / 'LICENSE-APACHE-2.0.txt')
    shutil.copy2(ROOT / 'THIRD_PARTY.md', notices / 'THIRD_PARTY.md')
    shutil.copy2(ROOT / '.deps/majiro-py/LICENSE', notices / 'majiro-py-LICENSE.txt')
    runtime_notices(notices)
    if sys.platform != 'win32':
        from runtime_licenses import collect_native_notices
        native = collect_native_notices(folder, notices, provider_notices=[{
            'provider': 'CPython', 'source_root': sys.base_prefix,
            'stdlib_extension_root': sysconfig.get_config_var('DESTSHARED'),
            'notice': notices / 'CPython-LICENSE.txt'}])
        (notices / 'native-runtime-report.json').write_text(json.dumps(native, indent=2), encoding='utf-8')
        if native['unresolved_files'] or native['missing_notices'] or native['source_review_required']:
            raise ValueError('Native runtime notices need review; inspect licenses/native-runtime-report.json')
    for package in ['evbunpack', 'aplib', 'pefile', 'PyInstaller', 'altgraph', 'pyinstaller-hooks-contrib']:
        distribution = importlib.metadata.distribution(package)
        for item in distribution.files or []:
            if any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(item))
                if source.is_file():
                    shutil.copy2(source, notices / (package + '-' + item.name))
    for name in ['INSTALLATION.md', 'TRANSLATION.md', 'COMPATIBILITY.md']:
        shutil.copy2(ROOT / 'docs' / name, folder / name)
    try:
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        changes = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        revision = changes = None
    (folder / 'build-info.json').write_text(json.dumps({
        'version': VERSION, 'source_revision': revision.stdout.strip() if revision and revision.returncode == 0 else None,
        'source_has_uncommitted_changes': bool(changes.stdout.strip()) if changes and changes.returncode == 0 else None,
        'platform': sys.platform, 'python': '.'.join(map(str, sys.version_info[:3])),
        'pyinstaller': importlib.metadata.version('PyInstaller')}, indent=2), encoding='utf-8')
    extension = '.exe' if sys.platform == 'win32' else ''
    platform = 'Windows-x64' if sys.platform == 'win32' else 'SteamOS-Linux-x64'
    if not extension:
        # Dolphin can execute the native file directly after extraction.
        (folder / 'NarciBloom').chmod(0o755)
    products = []
    for chinese in ([False, True] if translation_archive else [False]):
        if chinese:
            shutil.copy2(translation_archive, folder / translation_name)
        name = f'NarciBloom-{VERSION}-{platform}-' + ('Chinese' if chinese else 'Fonts')
        target = destination / (name + '.zip')
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    relative = path.relative_to(folder)
                    if chinese and relative.as_posix() == 'NarciBloom' + extension:
                        relative = Path('NarciBloomChinese' + extension)
                    output.write(path, str(Path(name) / relative))
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        products.append({'filename': target.name, 'sha256': digest, 'size_bytes': target.stat().st_size})
    (destination / 'SHA256SUMS.txt').write_text(
        ''.join(f"{item['sha256']}  {item['filename']}\n" for item in products), encoding='utf-8')
    (destination / 'artifacts.json').write_text(json.dumps(products, indent=2), encoding='utf-8')
    return products


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--translation-input', '--translation-archive', dest='translation_archive', type=Path,
                        help='Validated prepared PC v1.1 input ZIP for the Chinese product')
    parser.add_argument('--bundle-existing', type=Path, help='Create the Chinese variant from a built Fonts ZIP')
    arguments = parser.parse_args()
    if arguments.bundle_existing:
        if not arguments.translation_archive:
            parser.error('--bundle-existing requires --translation-input')
        print(json.dumps(bundle_existing(arguments.bundle_existing, arguments.translation_archive, arguments.output), indent=2))
    else:
        print(json.dumps(build(arguments.output, arguments.translation_archive), indent=2))
