"""Cross-platform repackaging must preserve native mode bits and original bytes."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_release
from build_release import bundle_existing
from translation_package import PreparedTranslation, PREPARED_ARCHIVE_NAME


class ReleaseBundleTests(unittest.TestCase):
    def test_linux_launcher_mode_and_prepared_input_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / 'NarciBloom-test-SteamOS-Fonts.zip'
            original = root / 'renamed-prepared.zip'
            original.write_bytes(b'unchanged artificial archive')
            with zipfile.ZipFile(fonts, 'x') as output:
                launcher = zipfile.ZipInfo('NarciBloom-test-SteamOS-Fonts/NarciBloom')
                launcher.create_system = 3
                launcher.external_attr = 0o100755 << 16
                output.writestr(launcher, b'fake ELF bytes')
                output.writestr('NarciBloom-test-SteamOS-Fonts/_internal/runtime', b'runtime')
            prepared = {'narci_onetwo/narci_onetwo_cn.exe': PreparedTranslation('narci_onetwo', b'engine', {}),
                        'readme.txt': b'credits'}
            with patch('translation_package.read_package', return_value=prepared) as reader:
                report = bundle_existing(fonts, original, root / 'output')
            reader.assert_called_once_with(original, ['narci_onetwo'])
            with zipfile.ZipFile(root / 'output' / report['filename']) as bundled:
                launcher = bundled.getinfo('NarciBloom-test-SteamOS-Chinese/NarciBloomChinese')
                self.assertEqual(launcher.external_attr >> 16, 0o100755)
                self.assertEqual(bundled.read(launcher), b'fake ELF bytes')
                self.assertEqual(bundled.read('NarciBloom-test-SteamOS-Chinese/' + PREPARED_ARCHIVE_NAME),
                                 original.read_bytes())
                self.assertFalse(any(name.casefold().endswith('.rar') for name in bundled.namelist()))
                self.assertEqual(bundled.read('NarciBloom-test-SteamOS-Chinese/_internal/runtime'), b'runtime')
                self.assertNotIn('NarciBloom-test-SteamOS-Chinese/NarciBloom', bundled.namelist())

    def test_unrecognized_translation_is_refused_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('translation_package.read_package', side_effect=ValueError('unsupported version')):
                with self.assertRaisesRegex(ValueError, 'unsupported version'):
                    bundle_existing(root / 'test-Fonts.zip', root / 'input.zip', root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_original_rar_cannot_be_mislabelled_as_prepared_release_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('original.rar', 'renamed-original.zip'):
                with patch('translation_package.read_package', return_value={
                        'narci_onetwo/narci_onetwo_cn.exe': b'raw-packed-original', 'readme.txt': b'credits'}):
                    with self.assertRaisesRegex(ValueError, 'require the validated prepared'):
                        bundle_existing(root / 'test-Fonts.zip', root / name, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_new_build_fonts_and_chinese_products_keep_material_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('LICENSE', 'LICENSE-APACHE-2.0.txt', 'THIRD_PARTY.md', '.deps/majiro-py/LICENSE',
                         'docs/INSTALLATION.md', 'docs/TRANSLATION.md', 'docs/COMPATIBILITY.md'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic notice')
            prepared = root / 'input.zip'
            prepared.write_bytes(b'prepared-container-kept-identical')
            output = root / 'output'

            def run(command, **kwargs):
                if command[0] == 'git':
                    return types.SimpleNamespace(returncode=0, stdout='a' * 40 if command[1] == 'rev-parse' else '')
                frozen = output / 'frozen/NarciBloom'
                frozen.mkdir(parents=True)
                (frozen / 'NarciBloom.exe').write_bytes(b'artificial launcher')
                return types.SimpleNamespace(returncode=0)

            material = {'narci_onetwo/narci_onetwo_cn.exe': PreparedTranslation('narci_onetwo', b'engine', {}),
                        'readme.txt': b'credits'}
            with patch.object(build_release, 'ROOT', root), patch.object(build_release.sys, 'platform', 'win32'), \
                 patch.object(build_release, 'runtime_notices'), patch.object(build_release.subprocess, 'run', side_effect=run), \
                 patch.object(build_release.importlib.metadata, 'distribution', return_value=types.SimpleNamespace(files=[])), \
                 patch.object(build_release.importlib.metadata, 'version', return_value='synthetic'), \
                 patch('translation_package.read_package', return_value=material):
                products = build_release.build(output, prepared)
            self.assertEqual(len(products), 2)
            for product in products:
                with zipfile.ZipFile(output / product['filename']) as archive:
                    inputs = [name for name in archive.namelist() if name.endswith(PREPARED_ARCHIVE_NAME)]
                    self.assertEqual(len(inputs), int('-Chinese.zip' in product['filename']))
                    if inputs:
                        self.assertEqual(archive.read(inputs[0]), prepared.read_bytes())
                    self.assertFalse(any(name.casefold().endswith('.rar') for name in archive.namelist()))
