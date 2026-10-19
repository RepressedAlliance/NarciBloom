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
import tkinter
import urllib.request
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def runtime_notices(destination):
    """Keep the notices for the Python runtime and its bundled native libraries."""
    python_version = '.'.join(map(str, sys.version_info[:3]))
    tcl_version = tkinter.Tcl().eval('info patchlevel')
    openssl_version = ssl.OPENSSL_VERSION.split()[1]
    sources = {
        'CPython-LICENSE.txt': f'https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE',
        'OpenSSL-LICENSE.txt': f'https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/LICENSE.txt',
        'zlib-LICENSE.txt': f'https://raw.githubusercontent.com/madler/zlib/v{zlib.ZLIB_RUNTIME_VERSION}/LICENSE',
        'Tcl-LICENSE.txt': f"https://raw.githubusercontent.com/tcltk/tcl/core-{tcl_version.replace('.', '-')}/license.terms",
    }
    for filename, url in sources.items():
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(256 * 1024)
        if len(data) < 100 or b'<html' in data.lower():
            raise ValueError(f'Invalid runtime license response: {filename}')
        (destination / filename).write_bytes(data)
    (destination / 'runtime-sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')


def build(destination, translation_archive=None):
    sys.path.insert(0, str(ROOT / 'tools'))
    from installer_app_backend import VERSION
    from translation_package import read_package
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise SystemExit('Choose a new empty build destination; existing output is retained')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'NarciBloom', '--paths', str(ROOT / 'tools'),
               '--paths', str(ROOT / '.deps/majiro-py/src'),
               '--hidden-import', 'installer_app_backend', '--hidden-import', 'chinese_builder',
               '--collect-all', 'mjotool', '--collect-all', 'evbunpack',
               '--distpath', str(destination / 'frozen'), '--workpath', str(destination / 'pyinstaller'),
               '--specpath', str(destination),
               '--add-data', str(ROOT / 'docs') + ':docs']
    if sys.platform == 'win32':
        command.append('--windowed')
    command.append(str(ROOT / 'tools/app.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    folder = destination / 'frozen/NarciBloom'
    notices = folder / 'licenses'
    notices.mkdir()
    shutil.copy2(ROOT / 'LICENSE', notices / 'NarciBloom-LICENSE.txt')
    shutil.copy2(ROOT / 'THIRD_PARTY.md', notices / 'THIRD_PARTY.md')
    shutil.copy2(ROOT / '.deps/majiro-py/LICENSE', notices / 'majiro-py-LICENSE.txt')
    runtime_notices(notices)
    for package in ['evbunpack', 'aplib', 'pefile', 'PyInstaller', 'altgraph', 'pyinstaller-hooks-contrib']:
        distribution = importlib.metadata.distribution(package)
        for item in distribution.files or []:
            if any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(item))
                if source.is_file():
                    shutil.copy2(source, notices / (package + '-' + item.name))
    for name in ['INSTALLATION.md', 'TRANSLATION.md', 'COMPATIBILITY.md']:
        shutil.copy2(ROOT / 'docs' / name, folder / name)
    extension = '.exe' if sys.platform == 'win32' else ''
    platform = 'Windows-x64' if sys.platform == 'win32' else 'SteamOS-Linux-x64'
    if not extension:
        # Dolphin can execute the native file directly after extraction.
        (folder / 'NarciBloom').chmod(0o755)
    products = []
    for chinese in ([False, True] if translation_archive else [False]):
        if chinese:
            read_package(translation_archive, [])  # Validate original archive and preserve its bytes.
            shutil.copy2(translation_archive, folder / 'N10 ver1.1补丁.rar')
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
    parser.add_argument('--translation-archive', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output, arguments.translation_archive), indent=2))
