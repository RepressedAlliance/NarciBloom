"""Fetch the pinned MIT-licensed Majiro tool dependency, without game files."""
import io
import urllib.request
import zipfile
from pathlib import Path

COMMIT = 'f7ec450d5b78f0ed6df603b8c0b0ed79748d9cee'
PROJECT = Path(__file__).resolve().parents[1]
DEST = PROJECT / '.deps/majiro-py'


def main():
    marker = DEST / 'UPSTREAM_COMMIT'
    if marker.exists():
        if marker.read_text().strip() != COMMIT:
            raise SystemExit('Dependency revision differs; review .deps/majiro-py before replacing it')
        print('Pinned majiro-py dependency is already available')
        return
    if DEST.exists():
        raise SystemExit('Partial dependency directory exists; review it before retrying')
    url = f'https://codeload.github.com/trigger-segfault/majiro-py/zip/{COMMIT}'
    request = urllib.request.Request(url, headers={'User-Agent': 'NarciBloom-bootstrap'})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    prefix = f'majiro-py-{COMMIT}/'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        selected = [(item, item.filename[len(prefix):]) for item in archive.infolist()
                    if item.filename.startswith(prefix) and not item.is_dir()]
        for item, relative in selected:
            if not (relative.startswith('src/') or relative == 'LICENSE'):
                continue
            target = DEST / relative
            if not target.resolve().is_relative_to(DEST.resolve()):
                raise SystemExit('Unexpected archive path')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
    if not (DEST / 'LICENSE').is_file() or not (DEST / 'src/mjotool/crypt.py').is_file():
        raise SystemExit('Dependency archive is missing expected files')
    marker.write_text(COMMIT + '\n')
    print('Pinned majiro-py dependency downloaded to .deps/majiro-py')


if __name__ == '__main__':
    main()
