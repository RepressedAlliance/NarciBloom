"""Backend integration with synthetic archives and an artificial payload builder."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import install_manager
import installer_app_backend as backend
from install_manager import ConflictError, InstallError, InstallManager
from patch_narcissu_font import archive, entries
from translation_package import PreparedTranslation


def digest(data):
    return hashlib.sha256(data).hexdigest()


def put(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.game = Path(self.temporary.name).resolve() / "game"
        self.game.mkdir()
        self.profiles = []
        self.originals = {}
        self.builds = []
        self.build_version = "one"
        for target in [patch.object(backend, "_profiles", side_effect=lambda: self.profiles),
                       patch.object(backend, "_translation_hashes", return_value={}),
                       patch.object(backend, "default_font", return_value="Synthetic local font"),
                       patch.object(backend, "build_overrides", side_effect=self.build),
                       patch.object(backend, "_prepare_native_engine", side_effect=lambda data: (data, {})),
                       patch.object(backend, "InstallManager", side_effect=lambda path: InstallManager(
                           path, process_checker=lambda _: []))]:
            target.start()
            self.addCleanup(target.stop)

    def add_story(self, module="narci_onetwo", language="ja", executable_name=None):
        executable = f"synthetic-executable:{module}:{language}".encode()
        files = {"config.mjo": f"synthetic-config:{module}:{language}".encode(),
                 "sysdata.cfg": b"synthetic-font-configuration"}
        arc = archive(files)
        put(self.game, f"{module}/{executable_name or module + '.exe'}", executable)
        put(self.game, f"{module}/scenario.arc", arc)
        self.originals[module] = (executable, arc)
        self.profiles.append({"module": module, "language": language, "exe_sha256": digest(executable),
                              "files": {name: digest(data) for name, data in files.items()}})

    def build(self, module, files, language, family):
        self.builds.append((module, dict(files), language, family))
        return {"config.mjo": f"synthetic-patch:{language}:{self.build_version}".encode()}, {"synthetic": True}, {}, {}

    def manager(self):
        return InstallManager(self.game, process_checker=lambda _: [])

    def test_partial_story_font_install_update_uninstall_uses_original_input(self):
        self.add_story()
        save = put(self.game, "narci_onetwo/save_chs/slot1.dat", b"personal-progress")
        before = backend.scan_game(self.game)
        self.assertEqual([module["id"] for module in before["modules"]], ["narci_onetwo"])
        self.assertTrue(before["modules"][0]["supported"])
        self.assertIsNone(before["installed_version"])
        messages = []
        first = backend.run_install(self.game, ["narci_onetwo"], progress=messages.append)
        self.assertEqual(first["modules"], ["narci_onetwo"])
        self.assertTrue(messages)
        first_bytes = (self.game / "narci_onetwo/update12.arc").read_bytes()
        self.build_version = "two"
        backend.run_install(self.game, ["narci_onetwo"])
        self.assertNotEqual((self.game / "narci_onetwo/update12.arc").read_bytes(), first_bytes)
        self.assertEqual(self.builds[0][1], self.builds[1][1])
        current = backend.scan_game(self.game)
        self.assertEqual(current["installed_version"], backend.VERSION)
        self.assertEqual(current["modules"][0]["language"], "ja")
        backend.run_uninstall(self.game)
        self.assertFalse((self.game / "narci_onetwo/update12.arc").exists())
        self.assertEqual((self.game / "narci_onetwo/narci_onetwo.exe").read_bytes(), self.originals["narci_onetwo"][0])
        self.assertEqual((self.game / "narci_onetwo/scenario.arc").read_bytes(), self.originals["narci_onetwo"][1])
        self.assertEqual(save.read_bytes(), b"personal-progress")

    def test_font_mode_preserves_each_source_language_and_does_not_load_translation(self):
        self.add_story("narci_onetwo", "ja")
        self.add_story("narci_iris", "en")
        with patch.object(backend, "read_package", side_effect=AssertionError("Font mode must not load a Chinese archive")):
            backend.run_install(self.game, ["narci_onetwo", "narci_iris"], chinese=False,
                                translation_archive="unused.rar")
        self.assertEqual([(item[0], item[2]) for item in self.builds], [("narci_onetwo", "ja"), ("narci_iris", "en")])
        record = self.manager().read_record()
        self.assertEqual(record["metadata"]["stories"]["narci_iris"]["language"], "en")
        self.assertEqual((self.game / "narci_iris/narci_iris.exe").read_bytes(), self.originals["narci_iris"][0])

    def test_deselecting_previous_story_restores_it_without_installing_missing_dlc(self):
        self.add_story()
        self.add_story("narci_iris")
        backend.run_install(self.game, ["narci_onetwo", "narci_iris"])
        backend.run_install(self.game, ["narci_iris"])
        self.assertFalse((self.game / "narci_onetwo/update12.arc").exists())
        self.assertTrue((self.game / "narci_iris/update12.arc").is_file())
        with self.assertRaises(InstallError):
            backend.run_install(self.game, ["narci_zero"])
        self.assertFalse((self.game / "narci_zero").exists())

    def test_unknown_executable_or_relevant_source_is_visible_and_refused(self):
        self.add_story()
        for relative, replacement in [("narci_onetwo/narci_onetwo.exe", b"unknown-version"),
                                      ("narci_onetwo/scenario.arc", archive({"config.mjo": b"modified"}))]:
            with self.subTest(relative=relative):
                original = (self.game / relative).read_bytes()
                put(self.game, relative, replacement)
                scan = backend.scan_game(self.game)
                self.assertFalse(scan["modules"][0]["supported"])
                self.assertIn("Unsupported", scan["modules"][0]["reason"])
                with self.assertRaises(InstallError):
                    backend.run_install(self.game, ["narci_onetwo"])
                self.assertFalse((self.game / "narci_onetwo/update12.arc").exists())
                put(self.game, relative, original)
        self.assertEqual(self.builds, [])

    def test_truncated_archive_is_reported_as_unsupported_in_scan(self):
        self.add_story()
        put(self.game, "narci_onetwo/scenario.arc", b"MajiroArcV3.000\0xxxx")
        scan = backend.scan_game(self.game)
        self.assertEqual(len(scan["modules"]), 1)
        self.assertFalse(scan["modules"][0]["supported"])
        self.assertTrue(scan["modules"][0]["reason"])

    def test_unrecognized_external_override_and_later_steam_changes_are_preserved(self):
        self.add_story()
        override = put(self.game, "narci_onetwo/update12.arc", b"third-party-mod")
        self.assertFalse(backend.scan_game(self.game)["modules"][0]["supported"])
        with self.assertRaises(InstallError):
            backend.run_install(self.game, ["narci_onetwo"])
        self.assertEqual(override.read_bytes(), b"third-party-mod")
        override.unlink()
        backend.run_install(self.game, ["narci_onetwo"])
        put(self.game, "narci_onetwo/update12.arc", b"later-steam-or-user-change")
        with self.assertRaises(ConflictError):
            backend.run_uninstall(self.game)
        self.assertEqual(override.read_bytes(), b"later-steam-or-user-change")

    def test_loose_environment_cannot_shadow_the_managed_title_without_review(self):
        self.add_story()
        environment = put(self.game, "narci_onetwo/MAJIRO.ENV", b"TITLEBAR\tcustom-title\r\n")
        self.assertFalse(backend.scan_game(self.game)["modules"][0]["supported"])
        with self.assertRaisesRegex(InstallError, "unrecognized overrides"):
            backend.run_install(self.game, ["narci_onetwo"])
        self.assertEqual(environment.read_bytes(), b"TITLEBAR\tcustom-title\r\n")

    def test_case_sensitive_duplicate_environments_are_rejected(self):
        self.add_story()
        lower = put(self.game, "narci_onetwo/majiro.env", b"TITLEBAR\tone\r\n")
        upper = self.game / "narci_onetwo/MAJIRO.ENV"
        if upper.exists():
            self.skipTest("Requires a case-sensitive filesystem")
        upper.write_bytes(b"TITLEBAR\ttwo\r\n")
        with self.assertRaisesRegex(InstallError, "Conflicting environment filenames"):
            backend.run_install(self.game, ["narci_onetwo"])
        self.assertEqual(lower.read_bytes(), b"TITLEBAR\tone\r\n")
        self.assertEqual(upper.read_bytes(), b"TITLEBAR\ttwo\r\n")

    def test_chinese_mode_uses_requested_original_package_and_recovers_stock_on_uninstall(self):
        self.add_story()
        fake = types.SimpleNamespace(build_chinese_payload=lambda module, packed, files, font_family:
             types.SimpleNamespace(payload={"#mjo/config.mjo": b"synthetic-chinese-script", "update12.arc": b"synthetic-chinese-arc"},
                                   executable=b"synthetic-chinese-executable", report={"synthetic": True}))
        package = {"narci_onetwo/narci_onetwo_cn.exe": b"synthetic-packed-chinese", "readme.txt": b"original-attribution"}
        with patch.dict(sys.modules, {"chinese_builder": fake}), patch.object(backend, "read_package", return_value=package) as read:
            backend.run_install(self.game, ["narci_onetwo"], chinese=True, translation_archive="original1.1.rar")
            read.assert_called_once_with("original1.1.rar", ["narci_onetwo"])
            record = self.manager().read_record()
            self.assertEqual(record["metadata"]["stories"]["narci_onetwo"]["language"], "zh-CN")
            self.assertEqual(backend.scan_game(self.game)["modules"][0]["language"], "zh-CN")
            self.assertEqual((self.game / "narci_onetwo/NarciBloom-translation-readme.txt").read_bytes(), b"original-attribution")
            # A later font-only update retains the recorded Chinese choice.
            backend.run_install(self.game, ["narci_onetwo"], chinese=False)
        backend.run_uninstall(self.game)
        self.assertEqual((self.game / "narci_onetwo/narci_onetwo.exe").read_bytes(), self.originals["narci_onetwo"][0])
        self.assertFalse((self.game / "narci_onetwo/#mjo/config.mjo").exists())

    def test_interrupted_install_is_visible_and_next_install_recovers_before_building(self):
        self.add_story()
        atomic_json = install_manager._atomic_json

        def terminate_before_record(target, value):
            if target.name == "record.json":
                raise KeyboardInterrupt("simulated process termination")
            return atomic_json(target, value)

        with patch.object(install_manager, "_atomic_json", side_effect=terminate_before_record):
            with self.assertRaises(KeyboardInterrupt):
                backend.run_install(self.game, ["narci_onetwo"])
        scan = backend.scan_game(self.game)
        self.assertTrue(scan["recovery_required"])
        self.assertTrue(scan["modules"][0]["supported"])
        backend.run_install(self.game, ["narci_onetwo"])
        self.assertEqual(self.manager().read_record()["version"], backend.VERSION)
        self.assertTrue(backend.scan_game(self.game)["modules"][0]["supported"])

    def test_capitalized_steam_executable_keeps_one_name_through_both_products(self):
        module = "narci_himeko"
        relative = f"{module}/Narci_himeko.exe"
        self.add_story(module, executable_name="Narci_himeko.exe")
        save = put(self.game, f"{module}/save_chs/slot.dat", b"progress")
        self.assertTrue(backend.scan_game(self.game)["modules"][0]["supported"])
        with patch.object(backend, "_prepare_native_engine", return_value=(b"font-engine", {})):
            backend.run_install(self.game, [module])
            backend.run_install(self.game, [module])
        self.assertIn(relative, self.manager().read_record()["files"])
        self.assertEqual(self.manager().original_file(f"{module}/{module}.exe"), self.originals[module][0])
        fake = types.SimpleNamespace(build_chinese_payload=lambda *args, **kwargs:
             types.SimpleNamespace(payload={"#mjo/config.mjo": b"chinese"},
                                   executable=b"chinese-engine", report={}))
        package = {f"{module}/Narci_himeko.exe": b"packed", "readme.txt": b"attribution"}
        with patch.dict(sys.modules, {"chinese_builder": fake}), patch.object(backend, "read_package", return_value=package):
            backend.run_install(self.game, [module], chinese=True, translation_archive="original.rar")
            backend.run_install(self.game, [module], chinese=False)
        self.assertEqual((self.game / relative).read_bytes(), b"chinese-engine")
        self.assertEqual([p.name for p in (self.game / module).iterdir()
                          if p.suffix.casefold() == '.exe'], ["Narci_himeko.exe"])
        backend.run_uninstall(self.game)
        self.assertEqual((self.game / relative).read_bytes(), self.originals[module][0])
        self.assertEqual(save.read_bytes(), b"progress")

    @unittest.skipUnless(os.name == 'nt', 'Legacy case-insensitive Windows record')
    def test_legacy_lowercase_windows_record_keeps_actual_capitalized_filename(self):
        module = "narci_himeko"
        actual, legacy = f"{module}/Narci_himeko.exe", f"{module}/{module}.exe"
        self.add_story(module, executable_name="Narci_himeko.exe")
        backend.run_install(self.game, [module])
        record = self.manager().read_record()
        record['files'][legacy] = record['files'].pop(actual)
        (self.manager().state / 'record.json').write_text(json.dumps(record))
        with patch.object(backend, '_prepare_native_engine', return_value=(b'new-engine', {})):
            backend.run_install(self.game, [module])
        self.assertIn(legacy, self.manager().read_record()['files'])
        self.assertNotIn(actual, self.manager().read_record()['files'])
        self.assertIn('Narci_himeko.exe', [p.name for p in (self.game / module).iterdir()])
        backend.run_uninstall(self.game)
        self.assertEqual((self.game / actual).read_bytes(), self.originals[module][0])

    def test_case_distinct_duplicate_executables_are_rejected_before_building(self):
        self.add_story('narci_himeko', executable_name='Narci_himeko.exe')
        put(self.game, 'narci_himeko/narci_himeko.exe', b'different')
        if len(list((self.game / 'narci_himeko').glob('*.exe'))) != 2:
            self.skipTest('Filesystem does not permit case-distinct names')
        with self.assertRaisesRegex(ValueError, 'Ambiguous story executable'):
            backend.scan_game(self.game)
        with self.assertRaisesRegex(ValueError, 'Ambiguous story executable'):
            backend.run_install(self.game, ['narci_himeko'])
        self.assertEqual(self.builds, [])

    def test_prepared_input_is_passed_intact_and_reused_for_font_update(self):
        module = 'narci_himeko'
        self.add_story(module, executable_name='Narci_himeko.exe')
        prepared = PreparedTranslation(module, b'unchanged-restored-engine', {'#txt/config.txt': b'original-table'})
        received = []

        def build(game, value, files, font_family):
            received.append(value)
            return types.SimpleNamespace(payload={'#txt/config.txt': value.virtual_files['#txt/config.txt']},
                                         executable=b'built-prepared-engine', report={})

        package = {module + '/Narci_himeko.exe': prepared, 'readme.txt': b'original-credits'}
        with patch.dict(sys.modules, {'chinese_builder': types.SimpleNamespace(build_chinese_payload=build)}), \
             patch.object(backend, 'read_package', return_value=package) as read:
            backend.run_install(self.game, [module], chinese=True, translation_archive='prepared.zip')
            backend.run_install(self.game, [module], chinese=False)
            self.assertEqual(read.call_count, 2)
            self.assertEqual(read.call_args.args, (str(Path('prepared.zip').resolve()), [module]))
        self.assertEqual(received, [prepared, prepared])
        record = self.manager().read_record()
        self.assertEqual(record['metadata']['stories'][module]['language'], 'zh-CN')
        self.assertIn(module + '/Narci_himeko.exe', record['files'])
        self.assertEqual((self.game / module / 'NarciBloom-translation-readme.txt').read_bytes(), b'original-credits')
        backend.run_uninstall(self.game)
        self.assertEqual((self.game / module / 'Narci_himeko.exe').read_bytes(), self.originals[module][0])
        self.assertFalse((self.game / module / '#txt/config.txt').exists())


if __name__ == "__main__":
    unittest.main()
