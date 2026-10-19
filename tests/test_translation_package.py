"""Synthetic package fingerprints and mocked libarchive ABI; no translation fixtures."""
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import translation_package as package


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
