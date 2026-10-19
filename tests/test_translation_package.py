"""Synthetic package fingerprints and mocked libarchive ABI; no translation fixtures."""
import ctypes
import hashlib
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
import warnings
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import translation_package as package
import prepare_translation as preparation


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ArchiveFunction:
    """A callable with the signature attributes assigned by a ctypes consumer."""
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class SyntheticLibarchive:
    def __init__(self, members, *, open_status=0, header_status=0, read_error=False):
        self.members = members
        self.index = -1
        self.offset = 0
        self.freed = False
        self.handle = 0x123456789ABC
        self.data_reads = []
        self.archive_read_new = ArchiveFunction(lambda: self.handle)
        self.archive_read_support_filter_all = ArchiveFunction(lambda handle: 0)
        self.archive_read_support_format_all = ArchiveFunction(lambda handle: 0)
        self.archive_read_open_filename = ArchiveFunction(lambda handle, path, size: open_status)
        self.archive_read_free = ArchiveFunction(self.free)
        self.archive_read_next_header = ArchiveFunction(self.next_header)
        self.archive_entry_pathname = ArchiveFunction(lambda entry: self.members[self.index][0].encode())
        self.archive_entry_size = ArchiveFunction(lambda entry: self.members[self.index][2])
        self.archive_read_data = ArchiveFunction(self.read_data)
        self.header_status, self.read_error = header_status, read_error

    def free(self, handle):
        self.freed = True
        return 0

    def next_header(self, handle, pointer):
        if self.header_status:
            return self.header_status
        self.index += 1
        self.offset = 0
        if self.index == len(self.members):
            return 1  # ARCHIVE_EOF
        pointer._obj.value = self.index + 1
        return 0

    def read_data(self, handle, buffer, capacity):
        if self.read_error:
            return -1
        name, content, _ = self.members[self.index]
        self.data_reads.append(name)
        content = content[self.offset:self.offset + capacity]
        ctypes.memmove(buffer, content, len(content))
        self.offset += len(content)
        return len(content)


class PackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "original1.1.rar"
        self.container = b"synthetic-container-not-a-real-translation"
        self.path.write_bytes(self.container)
        self.contents = {"narci_onetwo/narci_onetwo_cn.exe": b"synthetic-chinese-loader-1",
                         "narci_iris/narci_iris_cn.exe": b"synthetic-chinese-loader-2",
                         "readme.txt": b"synthetic-original-attribution"}
        self.notice = {"input_fingerprint": {
            "archive": {"size_bytes": len(self.container), "sha256": digest(self.container)},
            "members": [{"path": name, "size_bytes": len(data), "sha256": digest(data)}
                        for name, data in self.contents.items()]}}
        target = patch.object(package, "source_notice", return_value=self.notice)
        target.start()
        self.addCleanup(target.stop)

    def windows_reader(self, outputs=None, returncode=0):
        outputs = self.contents if outputs is None else outputs
        return patch.object(package.subprocess, "run", side_effect=lambda command, **kwargs:
                            types.SimpleNamespace(returncode=returncode, stdout=outputs.get(command[-1], b""), stderr=b""))

    def test_wrong_size_and_hash_are_rejected_before_decompression(self):
        for data in (b"wrong-length", b"x" * len(self.container)):
            with self.subTest(data=data):
                self.path.write_bytes(data)
                with patch.object(package.subprocess, "run", side_effect=AssertionError("No decompression before recognition")), \
                     patch.object(package, "_unix_members", side_effect=AssertionError("No decompression before recognition")):
                    with self.assertRaises(ValueError):
                        package.read_package(self.path, ["narci_onetwo"])

    def test_windows_reader_requests_only_selected_story_and_original_readme(self):
        fake_os = types.SimpleNamespace(name="nt", environ={"SystemRoot": "C:/Windows"})
        with patch.object(package, "os", fake_os), \
             patch.object(package.subprocess, "CREATE_NO_WINDOW", 0, create=True), self.windows_reader() as run:
            result = package.read_package(self.path, ["narci_onetwo"])
        self.assertEqual(set(result), {"narci_onetwo/narci_onetwo_cn.exe", "readme.txt"})
        self.assertEqual(result["readme.txt"], self.contents["readme.txt"])
        self.assertEqual(self.path.read_bytes(), self.container)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][1:3], ["-xOf", str(self.path)])
            self.assertEqual(call.kwargs["timeout"], 120)
            self.assertNotIn("shell", call.kwargs)

    def test_windows_member_hash_missing_member_and_tar_failure_are_rejected(self):
        wrong_hash = dict(self.contents)
        name = "narci_onetwo/narci_onetwo_cn.exe"
        wrong_hash[name] = b"x" * len(wrong_hash[name])
        missing = dict(self.contents)
        missing.pop("readme.txt")
        fake_os = types.SimpleNamespace(name="nt", environ={"SystemRoot": "C:/Windows"})
        for outputs, code in [(wrong_hash, 0), (missing, 0), (self.contents, 1)]:
            with self.subTest(code=code, members=list(outputs)), patch.object(package, "os", fake_os), \
                 patch.object(package.subprocess, "CREATE_NO_WINDOW", 0, create=True), self.windows_reader(outputs, code):
                with self.assertRaises(ValueError):
                    package.read_package(self.path, ["narci_onetwo"])

    def test_unix_member_bytes_are_checked_even_after_container_fingerprint_matches(self):
        fake_os = types.SimpleNamespace(name="posix")
        with patch.object(package, "os", fake_os), patch.object(package, "_unix_members", return_value=self.contents):
            self.assertEqual(package.read_package(self.path, ["narci_onetwo"])["readme.txt"], self.contents["readme.txt"])
        wrong = dict(self.contents)
        wrong["readme.txt"] = b"x" * len(wrong["readme.txt"])
        with patch.object(package, "os", fake_os), patch.object(package, "_unix_members", return_value=wrong):
            with self.assertRaises(ValueError):
                package.read_package(self.path, ["narci_onetwo"])

    def test_empty_selection_still_validates_attribution_for_bundle_check(self):
        fake_os = types.SimpleNamespace(name="nt", environ={"SystemRoot": "C:/Windows"})
        with patch.object(package, "os", fake_os), \
             patch.object(package.subprocess, "CREATE_NO_WINDOW", 0, create=True), self.windows_reader() as run:
            result = package.read_package(self.path, [])
        self.assertEqual(result, {"readme.txt": self.contents["readme.txt"]})
        self.assertEqual(run.call_count, 1)


class PreparedPackageTests(unittest.TestCase):
    """Tiny synthetic ZIPs, with recognition metadata explicitly pinned per test."""
    root = 'prepared-input/'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'renamed.input'
        self.source_members = [
            {'path': 'narci_iris/original.exe', 'size_bytes': 8, 'sha256': digest(b'original')},
            {'path': 'readme.txt', 'size_bytes': 7, 'sha256': digest(b'credits')},
        ]
        self.files = {'readme.txt': b'credits', 'source-notice.json': b'{}',
                      'CACHE-NOTICE.txt': b'processed input notice',
                      'modules/narci_iris/engine.exe': b'synthetic-restored-engine',
                      'modules/narci_iris/virtual/#mjo/config.mjo': b'synthetic-script'}
        records = {name: {'path': name, 'size_bytes': len(data), 'sha256': digest(data)}
                   for name, data in self.files.items()}
        virtual = dict(records['modules/narci_iris/virtual/#mjo/config.mjo'],
                       source_virtual_path='#mjo/config.mjo')
        original_archive = {'filename': 'original.rar', 'size_bytes': 5, 'sha256': digest(b'raw!!')}
        self.manifest = {'schema': 1, 'source_archive': original_archive,
                         'source_members': self.source_members, 'files': list(records.values()),
                         'modules': {'narci_iris': {
                             'source_member': 'narci_iris/original.exe',
                             'source_member_sha256': self.source_members[0]['sha256'],
                             'engine': records['modules/narci_iris/engine.exe'],
                             'virtual_files': [virtual]}}}
        self.notice = {'input_fingerprint': {'archive': original_archive,
                                             'members': self.source_members}}
        self.patch = patch.object(package, 'source_notice', return_value=self.notice)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def make_zip(self, *, files=None, manifest=None, extra=(), manifest_bytes=None):
        files = self.files if files is None else files
        manifest = self.manifest if manifest is None else manifest
        manifest_bytes = (json.dumps(manifest).encode() if manifest_bytes is None else manifest_bytes)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in files.items():
                    archive.writestr(self.root + name, data)
                archive.writestr(self.root + 'manifest.json', manifest_bytes)
                for name, data in extra:
                    archive.writestr(name, data)
        self.notice['prepared_input'] = {
            'root_directory': self.root[:-1],
            'archive': {'size_bytes': self.path.stat().st_size, 'sha256': digest(self.path.read_bytes())},
            'manifest': {'size_bytes': len(manifest_bytes), 'sha256': digest(manifest_bytes)},
        }

    def test_selected_module_returns_prepared_sources_and_original_readme(self):
        self.make_zip()
        with patch.object(package.subprocess, 'run', side_effect=AssertionError('No tar for ZIP')):
            result = package.read_package(self.path, ['narci_iris'])
        self.assertEqual(result['readme.txt'], b'credits')
        source = result['narci_iris/original.exe']
        self.assertIsInstance(source, package.PreparedTranslation)
        self.assertEqual(source.module, 'narci_iris')
        self.assertEqual(source.restored_engine, b'synthetic-restored-engine')
        self.assertEqual(source.virtual_files, {'#mjo/config.mjo': b'synthetic-script'})
        self.assertEqual(package.read_package(self.path, []), {'readme.txt': b'credits'})

    def test_container_size_and_hash_are_checked_before_opening_zip(self):
        self.make_zip()
        original = self.path.read_bytes()
        for bad in (original + b'x', b'x' * len(original)):
            with self.subTest(size=len(bad)):
                self.path.write_bytes(bad)
                with patch.object(package.zipfile, 'ZipFile', side_effect=AssertionError('No ZIP parsing')):
                    with self.assertRaises(ValueError):
                        package.read_package(self.path, ['narci_iris'])

    def test_every_member_is_checked_even_when_no_module_is_selected(self):
        changed = dict(self.files)
        name = 'modules/narci_iris/virtual/#mjo/config.mjo'
        for bad in (b'x' * len(changed[name]), changed[name] + b'x'):
            changed[name] = bad
            self.make_zip(files=changed)
            with self.subTest(size=len(bad)), self.assertRaisesRegex(ValueError, 'size|hash'):
                package.read_package(self.path, [])

    def test_manifest_fingerprint_and_original_readme_are_checked(self):
        self.make_zip()
        self.notice['prepared_input']['manifest']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'hash'):
            package.read_package(self.path, [])
        manifest = copy.deepcopy(self.manifest)
        files = dict(self.files, **{'readme.txt': b'changed'})
        next(item for item in manifest['files'] if item['path'] == 'readme.txt')['sha256'] = digest(b'changed')
        self.make_zip(files=files, manifest=manifest)
        with self.assertRaisesRegex(ValueError, 'original readme'):
            package.read_package(self.path, [])

    def test_unsafe_duplicate_and_special_zip_members_are_rejected(self):
        symlink = zipfile.ZipInfo(self.root + 'symlink')
        symlink.create_system = 3
        symlink.external_attr = 0o120777 << 16
        compressed = zipfile.ZipInfo(self.root + 'other-compression')
        compressed.compress_type = zipfile.ZIP_BZIP2
        names = ['../outside', '/absolute', self.root + 'a/../b', self.root + 'C:drive',
                 self.root + 'folder\\file', self.root + 'NUL.txt', self.root + 'trailing. ',
                 self.root + 'directory/', self.root + 'readme.txt', self.root + 'README.TXT',
                 symlink, compressed]
        for name in names:
            self.make_zip(extra=[(name, b'x')])
            with self.subTest(name=str(name)), self.assertRaises(ValueError):
                package.read_package(self.path, [])

    def test_missing_extra_duplicate_json_keys_and_manifest_files_are_rejected(self):
        files = dict(self.files)
        del files['CACHE-NOTICE.txt']
        self.make_zip(files=files)
        with self.assertRaises(ValueError):
            package.read_package(self.path, [])
        self.make_zip(extra=[(self.root + 'unexpected', b'x')])
        with self.assertRaises(ValueError):
            package.read_package(self.path, [])
        self.make_zip(manifest_bytes=b'{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            package.read_package(self.path, [])
        manifest = copy.deepcopy(self.manifest)
        manifest['files'].append(dict(manifest['files'][0], path='README.TXT'))
        self.make_zip(manifest=manifest)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            package.read_package(self.path, [])

    def test_source_identity_and_cross_module_paths_are_rejected(self):
        for change in ('archive', 'module', 'engine', 'virtual', 'record'):
            manifest = copy.deepcopy(self.manifest)
            record = manifest['modules']['narci_iris']
            if change == 'archive': manifest['source_archive']['sha256'] = '0' * 64
            elif change == 'module': record['source_member'] = 'other/original.exe'
            elif change == 'engine': record['engine']['path'] = 'modules/other/engine.exe'
            elif change == 'virtual': record['virtual_files'][0]['source_virtual_path'] = '../escape'
            else: record['virtual_files'][0]['sha256'] = '0' * 64
            self.make_zip(manifest=manifest)
            with self.subTest(change=change), self.assertRaises(ValueError):
                package.read_package(self.path, ['narci_iris'])
        self.make_zip()
        with self.assertRaisesRegex(ValueError, 'selection'):
            package.read_package(self.path, ['other'])

    def test_preparation_is_deterministic_preserves_payload_and_avoids_self_reference(self):
        self.notice['prepared_input'] = {'obsolete_fingerprint': 'not embedded'}
        first = Path(self.temporary.name) / 'prepared-one.zip'
        second = Path(self.temporary.name) / 'prepared-two.zip'
        inputs = {'narci_iris/original.exe': b'original', 'readme.txt': b'credits'}
        with patch.object(preparation, 'source_notice', return_value=self.notice), \
             patch.object(preparation, 'read_package', side_effect=lambda *args: dict(inputs)), \
             patch.object(preparation, 'extract_virtual_files', return_value={'#mjo/config.mjo': b'script'}), \
             patch.object(preparation, 'restore_virtual_pe', return_value=b'restored'):
            metadata = preparation.prepare_input('recognized.rar', first)
            same = preparation.prepare_input('recognized.rar', second)
            with self.assertRaises(FileExistsError):
                preparation.prepare_input('recognized.rar', first)
        self.assertEqual(metadata, same)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.notice['prepared_input'] = metadata
        result = package.read_package(first, ['narci_iris'])
        self.assertEqual(result['readme.txt'], b'credits')
        self.assertEqual(result['narci_iris/original.exe'].virtual_files, {'#mjo/config.mjo': b'script'})
        self.assertEqual(result['narci_iris/original.exe'].restored_engine, b'restored')
        with zipfile.ZipFile(first) as archive:
            prefix = preparation.ROOT_DIRECTORY + '/'
            notice = json.loads(archive.read(prefix + 'source-notice.json'))
            self.assertNotIn('prepared_input', notice)
            self.assertNotIn('prototype', archive.read(prefix + 'manifest.json').decode())
            self.assertTrue(all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist()))


class LibarchiveInterfaceTests(unittest.TestCase):
    def wanted(self, data=b"synthetic-data"):
        return {"readme.txt": {"size_bytes": len(data), "sha256": digest(data)}}

    def read(self, library, wanted=None):
        with patch.object(package.ctypes.util, "find_library", return_value="synthetic-libarchive"), \
             patch.object(package.ctypes, "CDLL", return_value=library):
            return package._unix_members(Path("synthetic.rar"), wanted or self.wanted())

    def test_pointer_and_size_signatures_avoid_64_bit_truncation_and_free_handle(self):
        data = b"synthetic-data"
        library = SyntheticLibarchive([("ignored.exe", b"ignored", 7), ("readme.txt", data, len(data))])
        self.assertEqual(self.read(library), {"readme.txt": data})
        self.assertIs(library.archive_read_new.restype, ctypes.c_void_p)
        self.assertEqual(library.archive_read_next_header.argtypes,
                         [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)])
        self.assertIs(library.archive_entry_size.restype, ctypes.c_int64)
        self.assertIs(library.archive_read_data.restype, ctypes.c_ssize_t)
        self.assertTrue(library.freed)
        self.assertNotIn("ignored.exe", library.data_reads)

    def test_member_size_duplicate_and_overrun_are_rejected_and_handle_freed(self):
        data = b"synthetic-data"
        for members in [[("readme.txt", data, len(data) + 1)],
                        [("readme.txt", data, len(data)), ("readme.txt", data, len(data))],
                        [("readme.txt", data + b"extra", len(data))]]:
            library = SyntheticLibarchive(members)
            with self.subTest(members=members), self.assertRaises(ValueError):
                self.read(library)
            self.assertTrue(library.freed)

    def test_open_header_and_read_failures_free_native_handle(self):
        data = b"synthetic-data"
        for options in [{"open_status": -30}, {"header_status": -30}, {"read_error": True}]:
            library = SyntheticLibarchive([("readme.txt", data, len(data))], **options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.read(library)
            self.assertTrue(library.freed)

    def test_missing_library_and_null_handle_fail_with_clear_runtime_error(self):
        with patch.object(package.ctypes.util, "find_library", return_value=None), \
             patch.object(package.ctypes, "CDLL", side_effect=AssertionError("No library to load")):
            with self.assertRaisesRegex(RuntimeError, "libarchive"):
                package._unix_members(Path("synthetic.rar"), self.wanted())
        library = SyntheticLibarchive([])
        library.handle = 0
        with self.assertRaisesRegex(RuntimeError, "allocate"):
            self.read(library)
        self.assertFalse(library.freed)


if __name__ == "__main__":
    unittest.main()
