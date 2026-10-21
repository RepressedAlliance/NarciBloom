"""Synthetic package ownership/notices for native runtime collection."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import runtime_licenses as runtime


def put(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class RuntimeFilterTests(unittest.TestCase):
    def test_minimal_runtime_keeps_python_tk_ffi_crypto_and_uses_host_x11_archive_glib(self):
        keep = [(name, "/usr/lib/" + name, "BINARY") for name in
                ["libpython3.13.so.1.0", "libtcl8.6.so", "libtk8.6.so", "libffi.so.8", "libcrypto.so.3", "libssl.so.3"]]
        keep += [("python3.13/lib-dynload/_tkinter.so", "/usr/lib/python3.13/lib-dynload/_tkinter.so", "EXTENSION"),
                 ("extension.so", "/opt/venv/lib/extension.so", "EXTENSION")]
        excluded = [(name, "/usr/lib/" + name, "BINARY") for name in
                    ["libX11.so.6", "libXft.so.2", "libfontconfig.so.1", "libglib-2.0.so.0", "libarchive.so.13",
                     "liblzma.so.5", "libstdc++.so.6", "libgcc_s.so.1", "libz.so.1"]]
        self.assertEqual(runtime.filter_linux_binaries(keep + excluded), keep)
        self.assertEqual(runtime.filter_linux_binaries([("private.so", "/usr/library/private.so", "BINARY")]),
                         [("private.so", "/usr/library/private.so", "BINARY")])


class RuntimeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.frozen = self.root / "dist/frozen/NarciBloom"
        self.internal = self.frozen / "_internal"
        self.internal.mkdir(parents=True)
        self.destination = self.root / "notices"
        self.share = self.root / "system/usr/share"
        self.share.mkdir(parents=True)
        self.common = self.share / "licenses/common"
        self.ubuntu_common = self.share / "common-licenses"
        self.metadata = {}
        self.owners = {}
        self.origins = []
        self.database = types.SimpleNamespace(manager="pacman", owner=lambda source: self.owners.get(str(source)),
                            details=lambda package: copy.deepcopy(self.metadata[package]))
        for target in (patch.object(runtime, "_database", return_value=self.database),
                       patch.object(runtime, "SHARE_ROOT", self.share),
                       patch.object(runtime, "COMMON_ROOTS", (self.common, self.ubuntu_common))):
            target.start()
            self.addCleanup(target.stop)

    def add_library(self, name, package, declared="MIT", notice=None):
        source = put(self.root, "system/usr/lib/" + name, b"\x7fELFsynthetic-native-library")
        put(self.internal, name, b"\x7fELFsynthetic-native-library")
        self.origins.append((name, str(source), "BINARY"))
        self.owners[str(source)] = package
        sources = []
        if notice is not None:
            sources.append(str(put(self.share, "licenses/" + package + "/COPYING", notice)))
        self.metadata[package] = {"name": package, "version": "1.2-3", "declared_licenses": declared,
                                  "source_package": None, "source_version": None, "package_files": sources}

    def collect(self, **kwargs):
        put(self.root, "dist/pyinstaller/NarciBloom/Analysis-00.toc", repr(([], self.origins)).encode())
        return runtime.collect_native_notices(self.frozen, self.destination, **kwargs)

    def provider(self):
        root = self.root / "opt/hostedtoolcache/Python/3.13/x64"
        extensions = root / "lib/python3.13/lib-dynload"
        extensions.mkdir(parents=True)
        notice = put(self.root, "provider-notices/CPython-LICENSE.txt", b"Synthetic CPython provider notice")
        return {"provider": "CPython", "source_root": root, "stdlib_extension_root": extensions, "notice": notice}

    def provider_library(self, relative, source):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"\x7fELFsynthetic-provider-library")
        put(self.internal, relative, source.read_bytes())
        self.origins.append((relative, str(source), "EXTENSION" if "lib-dynload" in relative else "BINARY"))

    def test_owned_library_copies_exact_attribution_and_inventory_is_not_compliance_claim(self):
        notice = b"Copyright Synthetic Author\nPermission is hereby granted.\n"
        self.add_library("libX11.so.6", "libx11", notice=notice)
        put(self.internal, "not-a-library.so", b"plain-data")
        report = self.collect()
        self.assertEqual(len(report["files"]), 1)
        self.assertEqual(report["packages"][0]["version"], "1.2-3")
        copied = report["packages"][0]["notices"][0]["file"]
        self.assertEqual((self.destination / copied).read_bytes(), notice)
        self.assertTrue(report["notice_collection_complete"])
        self.assertEqual(report["compliance_status"], "not_assessed")
        serialized = (self.destination / "native-runtime-report.json").read_text()
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(json.loads(serialized), report)
        # Repeating collection does not rewrite different user-provided notices.
        self.assertEqual(self.collect(), report)

    def test_ubuntu_copyright_references_common_lgpl_but_source_obligations_remain_unverified(self):
        self.database.manager = "dpkg"
        self.add_library("libglib-2.0.so.0", "libglib2.0-0:amd64", declared="")
        copyright_file = put(self.share, "doc/libglib2.0-0/copyright",
                             b"Copyright: Synthetic Author\nLicense: LGPL-2.1+\n"
                             b" See /usr/share/common-licenses/LGPL-2.1 for the full license.\n")
        self.metadata["libglib2.0-0:amd64"]["package_files"] = [str(copyright_file)]
        common = put(self.ubuntu_common, "LGPL-2.1", b"Synthetic LGPL-2.1 license text")
        report = self.collect()
        self.assertTrue(report["notice_collection_complete"])
        self.assertEqual(report["source_review_required"][0]["package"], "libglib2.0-0:amd64")
        self.assertIn("corresponding source", report["source_review_required"][0]["reason"])
        self.assertEqual((self.destination / "native/common/LGPL-2.1").read_bytes(), common.read_bytes())
        self.assertEqual(len(report["packages"][0]["notices"]), 2)

    def test_missing_shared_license_and_package_notices_are_reported_without_inventing_them(self):
        self.add_library("libacl.so.1", "acl", declared="LGPL")
        report = self.collect()
        self.assertFalse(report["notice_collection_complete"])
        self.assertEqual(report["missing_notices"][0]["package"], "acl")
        self.assertIn("version unspecified", report["packages"][0]["missing_shared_licenses"][0])
        self.assertTrue(report["source_review_required"])
        self.assertEqual(report["packages"][0]["notices"], [])

    def test_arch_versioned_common_license_is_collected_with_package_exception_notice(self):
        self.add_library("libgcc_s.so.1", "gcc-libs", declared="GPL-3.0-with-GCC-exception",
                         notice=b"Synthetic GCC Runtime Library Exception")
        put(self.common, "GPL3/license.txt", b"Synthetic GPL3 license")
        report = self.collect()
        self.assertTrue(report["notice_collection_complete"])
        self.assertTrue((self.destination / "native/common/GPL3/license.txt").exists())
        self.assertTrue(report["source_review_required"])

    def test_without_analysis_basename_alone_cannot_assign_a_different_installed_library(self):
        self.add_library("libunknown.so.1", "unknown", notice=b"Synthetic notice")
        source = Path(self.origins[0][1])
        source.write_bytes(b"\x7fELFdifferent-native-library-version")
        with patch.object(runtime, "_library_candidates", return_value=iter([source])):
            report = runtime.collect_native_notices(self.internal, self.destination)
        self.assertEqual(len(report["unresolved_files"]), 1)
        self.assertFalse(report["notice_collection_complete"])
        self.assertEqual(report["packages"], [])

    def test_existing_different_notice_is_preserved_and_not_silently_overwritten(self):
        self.add_library("libX11.so.6", "libx11", notice=b"Synthetic notice")
        copied = put(self.destination, "native/packages/libx11/licenses/libx11/COPYING", b"existing-user-notice")
        with self.assertRaisesRegex(ValueError, "different existing notice"):
            self.collect()
        self.assertEqual(copied.read_bytes(), b"existing-user-notice")

    def test_setup_python_provider_covers_only_traced_runtime_and_named_stdlib_extensions(self):
        provider = self.provider()
        runtime_name = "libpython3.13.so.1.0"
        extension = "_tkinter.cpython-313-x86_64-linux-gnu.so"
        self.provider_library(runtime_name, provider["source_root"] / "lib" / runtime_name)
        self.provider_library("python3.13/lib-dynload/" + extension, provider["stdlib_extension_root"] / extension)
        with patch.object(runtime.sys, "stdlib_module_names", frozenset({"_tkinter"})):
            report = self.collect(provider_notices=[provider])
        self.assertTrue(report["notice_collection_complete"])
        self.assertEqual(report["unresolved_files"], [])
        self.assertEqual(len(report["separately_supplied"]), 1)
        supplied = report["separately_supplied"][0]
        self.assertEqual(len(supplied["files"]), 2)
        self.assertEqual((self.destination / supplied["notice"]["file"]).read_bytes(), provider["notice"].read_bytes())
        self.assertTrue(all(item["notice_status"] == "separately_supplied" for item in report["files"]))

    def test_owned_python_without_distro_notice_uses_explicit_provider_notice(self):
        provider = self.provider()
        name = "libpython3.13.so.1.0"
        source = provider["source_root"] / "lib" / name
        self.provider_library(name, source)
        self.owners[str(source)] = "python"
        self.metadata["python"] = {"name": "python", "version": "3.13.5-1", "declared_licenses": "PSF-2.0",
                                    "source_package": None, "source_version": None, "package_files": []}
        report = self.collect(provider_notices=[provider])
        self.assertTrue(report["notice_collection_complete"])
        self.assertEqual(report["packages"][0]["notice_status"], "separately_supplied")
        self.assertEqual(report["missing_notices"], [])

    def test_provider_does_not_exempt_other_libraries_outside_sources_or_forged_basenames(self):
        provider = self.provider()
        self.provider_library("libarchive.so.13", provider["source_root"] / "lib/libarchive.so.13")
        self.provider_library("libpython3.13.so.1.0", self.root / "outside/libpython3.13.so.1.0")
        self.provider_library("libpython3.12.so.1.0", provider["source_root"] / "lib/libunrelated.so.1")
        extension = "thirdparty.cpython-313-x86_64-linux-gnu.so"
        self.provider_library("python3.13/lib-dynload/" + extension, provider["stdlib_extension_root"] / extension)
        with patch.object(runtime.sys, "stdlib_module_names", frozenset({"_tkinter"})):
            report = self.collect(provider_notices=[provider])
        self.assertFalse(report["notice_collection_complete"])
        self.assertEqual(len(report["unresolved_files"]), 4)
        self.assertEqual(report["separately_supplied"], [])

    def reviewed_runtime_fixture(self, index):
        # Synthetic notices exercise the selector without downloading or
        # duplicating complete distro copyright files in the source tree.
        review = copy.deepcopy(runtime.RUNTIME_LICENSE_REVIEWS[index])
        name, package = review["shipped_basenames"][0], review["package"]
        self.add_library(name, package, declared="")
        if index == 0:
            notice = (b"License: MIT\nSynthetic runtime permission.\n\n"
                      b"Documentation/doc/*: GPL.\nSee /usr/share/common-licenses/GPL\n")
            put(self.ubuntu_common, "GPL", b"Synthetic complete GPL notice")
        else:
            notice = (b"Files: *\nLicense: Apache-2.0\n\n"
                      b"Files: external/perl/Text-Template-1.56/*\nLicense: Artistic or GPL-1+\n"
                      b"See /usr/share/common-licenses/GPL-1\n")
            put(self.ubuntu_common, "GPL-1", b"Synthetic complete GPL-1 notice")
        path = put(self.share, review["primary_notices"][0]["path"], notice)
        review["primary_notices"][0]["sha256"] = hashlib.sha256(notice).hexdigest()
        self.metadata[package].update(version=review["version"], source_package=review["source_package"],
                                      source_version=review["source_version"], package_files=[str(path)])
        return review, notice

    def test_exact_reviewed_runtime_scope_retains_full_notices_and_unassessed_status(self):
        self.database.manager = "dpkg"
        fixtures = [self.reviewed_runtime_fixture(index) for index in (0, 1)]
        with patch.object(runtime, "RUNTIME_LICENSE_REVIEWS", tuple(item[0] for item in fixtures)):
            report = self.collect()
        self.assertEqual(report["source_review_required"], [])
        self.assertEqual(report["missing_notices"], [])
        self.assertEqual(report["unresolved_files"], [])
        self.assertEqual(report["compliance_status"], "not_assessed")
        self.assertEqual({item["runtime_license"] for item in report["reviewed_runtime_licenses"]},
                         {"MIT", "Apache-2.0"})
        self.assertEqual(len(report["reviewed_runtime_licenses"]), 2)
        for review, notice in fixtures:
            selected = next(item for item in report["reviewed_runtime_licenses"] if item["package"] == review["package"])
            self.assertEqual(selected["primary_notices"], list(review["primary_notices"]))
            self.assertEqual(selected["primary_sources"], list(review["primary_sources"]))
            self.assertTrue(selected["excluded_scopes"])
            package = next(item for item in report["packages"] if item["name"] == review["package"])
            original = next(item for item in package["notices"] if item["file"].endswith("/copyright"))
            self.assertEqual((self.destination / original["file"]).read_bytes(), notice)
            self.assertTrue(any(item["file"].startswith("native/common/GPL") for item in package["notices"]))

    def test_review_cannot_cover_changed_identity_hash_or_shipped_basenames(self):
        self.database.manager = "dpkg"
        review, _notice = self.reviewed_runtime_fixture(1)
        package = review["package"]
        baseline = copy.deepcopy(self.metadata[package])
        for field in ("version", "source_package", "source_version", "package_name",
                      "notice_sha256", "notice_path", "package_manager", "basename"):
            with self.subTest(field=field):
                self.metadata[package] = copy.deepcopy(baseline)
                self.database.manager = "dpkg"
                changed_review = copy.deepcopy(review)
                if field == "notice_sha256":
                    changed_review["primary_notices"][0]["sha256"] = "0" * 64
                elif field == "package_manager":
                    self.database.manager = "pacman"
                elif field == "basename":
                    changed_review["shipped_basenames"] = ("libssl.so.3",)
                elif field == "notice_path":
                    changed_review["primary_notices"][0]["path"] = "doc/another/copyright"
                elif field == "package_name":
                    self.metadata[package]["name"] += "-changed"
                else:
                    self.metadata[package][field] += "-changed"
                with patch.object(runtime, "RUNTIME_LICENSE_REVIEWS", (changed_review,)):
                    report = self.collect()
                self.assertEqual(report["reviewed_runtime_licenses"], [])
                self.assertEqual(report["source_review_required"][0]["package"], package)

    def test_changed_installed_notice_bytes_require_new_scope_review(self):
        self.database.manager = "dpkg"
        review, notice = self.reviewed_runtime_fixture(1)
        path = self.share / review["primary_notices"][0]["path"]
        path.write_bytes(notice + b"\nChanged installed package notice.\n")
        with patch.object(runtime, "RUNTIME_LICENSE_REVIEWS", (review,)):
            report = self.collect()
        self.assertEqual(report["reviewed_runtime_licenses"], [])
        self.assertEqual(report["source_review_required"][0]["package"], review["package"])

    def test_additional_library_from_reviewed_package_still_needs_review(self):
        self.database.manager = "dpkg"
        review, _notice = self.reviewed_runtime_fixture(1)
        package = review["package"]
        source = put(self.root, "system/usr/lib/libssl.so.3", b"\x7fELFadditional-runtime")
        put(self.internal, "libssl.so.3", source.read_bytes())
        self.origins.append(("libssl.so.3", str(source), "BINARY"))
        self.owners[str(source)] = package
        with patch.object(runtime, "RUNTIME_LICENSE_REVIEWS", (review,)):
            report = self.collect()
        self.assertEqual(report["reviewed_runtime_licenses"], [])
        self.assertEqual(report["source_review_required"][0]["package"], package)

    def test_review_does_not_remove_unknown_gnu_library_gate_or_missing_shared_notice(self):
        self.database.manager = "dpkg"
        review, _notice = self.reviewed_runtime_fixture(0)
        self.add_library("libunknown.so.1", "unknown-runtime", declared="LGPL-2.1+",
                         notice=b"License: LGPL-2.1+\nSynthetic unknown runtime\n")
        with patch.object(runtime, "RUNTIME_LICENSE_REVIEWS", (review,)):
            report = self.collect()
        self.assertEqual(len(report["reviewed_runtime_licenses"]), 1)
        self.assertEqual(report["source_review_required"][0]["package"], "unknown-runtime")
        self.assertEqual(report["missing_notices"][0]["package"], "unknown-runtime")
        self.assertFalse(report["notice_collection_complete"])


class PackageDatabaseTests(unittest.TestCase):
    def test_pacman_owner_version_and_license_fields(self):
        def run(args):
            if args[1] == "-Qoq":
                return 0, "libx11\n"
            if args[1] == "-Qi":
                return 0, "Name            : libx11\nVersion         : 1.8.12-1\nLicenses        : MIT AND X11\n"
            return 0, "/usr/lib/libX11.so.6\n/usr/share/licenses/libx11/COPYING\n"
        database = runtime._PackageDatabase("pacman")
        with patch.object(runtime, "_run", side_effect=run):
            self.assertEqual(database.owner(Path("/usr/lib/libX11.so.6")), "libx11")
            details = database.details("libx11")
        self.assertEqual(details["version"], "1.8.12-1")
        self.assertEqual(details["declared_licenses"], "MIT AND X11")

    def test_dpkg_multiarch_owner_and_source_package_version(self):
        def run(args):
            if args[1] == "-S":
                return 0, "/usr/lib/libX11.so.6 is not an ownership record\nlibx11-6:amd64: /usr/lib/libX11.so.6\n"
            if args[1] == "-W":
                return 0, "2:1.7.5-1ubuntu0.3\tlibx11\t2:1.7.5-1ubuntu0.3\n"
            return 0, "/usr/share/doc/libx11-6/copyright\n"
        database = runtime._PackageDatabase("dpkg")
        with patch.object(runtime, "_run", side_effect=run):
            self.assertEqual(database.owner("/usr/lib/libX11.so.6"), "libx11-6:amd64")
            details = database.details("libx11-6:amd64")
        self.assertEqual(details["source_package"], "libx11")
        self.assertEqual(details["source_version"], "2:1.7.5-1ubuntu0.3")


if __name__ == "__main__":
    unittest.main()
