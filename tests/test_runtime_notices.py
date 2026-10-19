"""Runtime notices use exact-version official sources, including older zlib tags."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_release as release


class RuntimeNoticeDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name)
        self.license = b"Synthetic exact-version copyright and permission notice.\n" * 5
        self.readme = (b"ZLIB DATA COMPRESSION LIBRARY\nzlib 1.2.11 is a compression library.\nCopyright notice:\n"
                       b"Synthetic author.\nPermission is granted subject to restrictions.\n"
                       b"This notice may not be removed or altered from any source distribution.\n")
        for target in [patch.object(release.tkinter, "Tcl", return_value=types.SimpleNamespace(eval=lambda _: "8.6.12")),
                       patch.object(release.ssl, "OPENSSL_VERSION", "OpenSSL 3.0.2 test"),
                       contextlib.redirect_stdout(io.StringIO())]:
            target.__enter__()
            self.addCleanup(target.__exit__, None, None, None)

    def test_missing_license_file_uses_readme_from_same_zlib_tag_and_records_actual_url(self):
        requested = []

        def fetch(url, **kwargs):
            requested.append(url)
            if url.endswith("v1.2.11/LICENSE"):
                raise urllib.error.HTTPError(url, 404, "Missing", {}, None)
            return io.BytesIO(self.readme if url.endswith("/README") else self.license)

        with patch.object(release.zlib, "ZLIB_RUNTIME_VERSION", "1.2.11"), \
             patch.object(release.urllib.request, "urlopen", side_effect=fetch):
            release.runtime_notices(self.destination)
        sources = json.loads((self.destination / "runtime-sources.json").read_text())
        self.assertEqual(sources["zlib-LICENSE.txt"], "https://raw.githubusercontent.com/madler/zlib/v1.2.11/README")
        self.assertEqual((self.destination / "zlib-LICENSE.txt").read_bytes(), self.readme)
        self.assertEqual([url for url in requested if "madler/zlib" in url], [
            "https://raw.githubusercontent.com/madler/zlib/v1.2.11/LICENSE",
            "https://raw.githubusercontent.com/madler/zlib/v1.2.11/README"])
        self.assertTrue(sources["Tcl-LICENSE.txt"].endswith("core-8-6-12/license.terms"))

    def test_current_zlib_keeps_dedicated_license_without_trying_readme(self):
        with patch.object(release.zlib, "ZLIB_RUNTIME_VERSION", "1.3.1"), \
             patch.object(release.urllib.request, "urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(self.license)) as fetch:
            release.runtime_notices(self.destination)
        self.assertFalse(any(call.args[0].endswith("/README") for call in fetch.call_args_list))
        sources = json.loads((self.destination / "runtime-sources.json").read_text())
        self.assertTrue(sources["zlib-LICENSE.txt"].endswith("v1.3.1/LICENSE"))

    def test_missing_version_wrong_readme_and_server_errors_do_not_fall_back_to_latest(self):
        for scenario in ("missing", "wrong-version", "server-error"):
            requested = []

            def fetch(url, **kwargs):
                requested.append(url)
                if "madler/zlib" not in url:
                    return io.BytesIO(self.license)
                if scenario == "server-error":
                    raise urllib.error.HTTPError(url, 503, "Unavailable", {}, None)
                if scenario == "missing" or url.endswith("/LICENSE"):
                    raise urllib.error.HTTPError(url, 404, "Missing", {}, None)
                return io.BytesIO(self.readme.replace(b"zlib 1.2.11", b"zlib 1.2.12"))

            with self.subTest(scenario=scenario), patch.object(release.zlib, "ZLIB_RUNTIME_VERSION", "1.2.11"), \
                 patch.object(release.urllib.request, "urlopen", side_effect=fetch):
                with self.assertRaisesRegex((RuntimeError, ValueError), "(?:zlib|version 1.2.11)"):
                    release.runtime_notices(self.destination)
            self.assertTrue(all("v1.2.11/" in url for url in requested if "madler/zlib" in url))
            if scenario == "server-error":
                self.assertFalse(any(url.endswith("/README") for url in requested))


if __name__ == "__main__":
    unittest.main()
