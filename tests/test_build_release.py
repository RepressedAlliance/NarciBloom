"""Cross-platform repackaging must preserve native mode bits and original bytes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_release import bundle_existing


class ReleaseBundleTests(unittest.TestCase):
    def test_linux_launcher_mode_and_original_archive_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / 'NarciBloom-test-SteamOS-Fonts.zip'
            original = root / 'original.rar'
            original.write_bytes(b'unchanged artificial archive')
            with zipfile.ZipFile(fonts, 'x') as output:
                launcher = zipfile.ZipInfo('NarciBloom-test-SteamOS-Fonts/NarciBloom')
                launcher.create_system = 3
                launcher.external_attr = 0o100755 << 16
                output.writestr(launcher, b'fake ELF bytes')
                output.writestr('NarciBloom-test-SteamOS-Fonts/_internal/runtime', b'runtime')
            with patch('translation_package.read_package', return_value={'readme.txt': b'credits'}) as reader:
                report = bundle_existing(fonts, original, root / 'output')
            reader.assert_called_once_with(original, [])
            with zipfile.ZipFile(root / 'output' / report['filename']) as bundled:
                launcher = bundled.getinfo('NarciBloom-test-SteamOS-Chinese/NarciBloomChinese')
                self.assertEqual(launcher.external_attr >> 16, 0o100755)
                self.assertEqual(bundled.read(launcher), b'fake ELF bytes')
                self.assertEqual(bundled.read('NarciBloom-test-SteamOS-Chinese/N10 ver1.1补丁.rar'),
                                 original.read_bytes())
                self.assertEqual(bundled.read('NarciBloom-test-SteamOS-Chinese/_internal/runtime'), b'runtime')
                self.assertNotIn('NarciBloom-test-SteamOS-Chinese/NarciBloom', bundled.namelist())

    def test_unrecognized_translation_is_refused_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('translation_package.read_package', side_effect=ValueError('unsupported version')):
                with self.assertRaisesRegex(ValueError, 'unsupported version'):
                    bundle_existing(root / 'test-Fonts.zip', root / 'input.rar', root / 'output')
            self.assertFalse((root / 'output').exists())
