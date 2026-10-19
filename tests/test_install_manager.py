"""Installer lifecycle tests use synthetic local files, never game resources."""
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
import install_manager as im
from install_manager import (ConflictError, GameRunningError, InstallError,
                             InstallManager, PathSafetyError)
from steam_discovery import discover_installations, inspect_game, parse_vdf


def put(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def add_story(root, module="narci_onetwo"):
    put(root, f"{module}/{module}.exe", b"synthetic-executable")
    put(root, f"{module}/scenario.arc", b"synthetic-archive")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.game = self.root / "game"
        self.game.mkdir()
        self.payload = self.root / "payload"
        self.payload.mkdir()
        add_story(self.game)
        self.path = "narci_onetwo/update12.arc"
        self.manager = InstallManager(self.game, process_checker=lambda _: [])

    def install(self, content=b"font-patch", version="v1"):
        put(self.payload, self.path, content)
        return self.manager.install(self.payload, [self.path], version=version,
                                    metadata={"language": "ja"})

    def test_reinstall_upgrade_and_uninstall_retain_true_original_and_saves(self):
        put(self.game, self.path, b"original-existing-update")
        save_paths = ["narci_onetwo/savedata/slot01.dat", "narci_onetwo/save_chs/slot02.sav",
                      "narci_onetwo/save/global.sav", "narci_onetwo/system.dat"]
        for name in save_paths:
            put(self.game, name, b"personal-progress")
        first = self.install()
        second = self.install()
        self.assertEqual(first["files"], second["files"])
        upgraded = self.install(b"new-patch", version="v2")
        self.assertEqual(upgraded["version"], "v2")
        self.assertEqual((self.game / self.path).read_bytes(), b"new-patch")
        entry = upgraded["files"][self.path]
        self.assertEqual((self.manager.state / entry["backup"]).read_bytes(), b"original-existing-update")
        report = self.manager.uninstall()
        self.assertEqual(report["restored"], [self.path])
        self.assertEqual((self.game / self.path).read_bytes(), b"original-existing-update")
        self.assertTrue(self.manager.uninstall()["already_uninstalled"])
        self.assertEqual(self.manager.read_record()["files"], {})
        for name in save_paths:
            self.assertEqual((self.game / name).read_bytes(), b"personal-progress")

    def test_original_file_reads_unmanaged_and_backed_up_input_without_writing(self):
        exe = "narci_onetwo/narci_onetwo.exe"
        self.assertEqual(self.manager.original_file(exe), b"synthetic-executable")
        self.assertIsNone(self.manager.original_file(self.path))
        self.assertFalse(self.manager.state.exists())
        put(self.payload, exe, b"replaced-executable")
        put(self.payload, self.path, b"added-patch")
        self.manager.install(self.payload, [exe, self.path], version="v1")
        self.assertEqual(self.manager.original_file(exe), b"synthetic-executable")
        self.assertEqual(self.manager.original_file("narci_onetwo/NARCI_ONETWO.EXE"), b"synthetic-executable")
        self.assertIsNone(self.manager.original_file(self.path))
        self.assertEqual((self.game / exe).read_bytes(), b"replaced-executable")
        for invalid in ["../outside", "narci_onetwo/save_chs/slot.dat"]:
            with self.assertRaises(PathSafetyError):
                self.manager.original_file(invalid)

    def test_target_executable_case_is_preserved_and_alias_creation_is_refused_on_linux(self):
        put(self.game, 'narci_himeko/Narci_himeko.exe', b'original')
        put(self.game, 'narci_himeko/scenario.arc', b'archive')
        actual = 'narci_himeko/Narci_himeko.exe'
        alias = 'narci_himeko/narci_himeko.exe'
        put(self.payload, alias, b'patch')
        if os.name != 'nt':
            with self.assertRaises(PathSafetyError):
                self.manager.install(self.payload, [alias], version='v1')
            self.assertEqual((self.game / actual).read_bytes(), b'original')
            (self.payload / alias).unlink()
        else:
            self.manager.install(self.payload, [alias], version='legacy')
            self.assertIn('Narci_himeko.exe', [p.name for p in (self.game / 'narci_himeko').iterdir()])
            self.manager.uninstall()
        put(self.payload, actual, b'patch')
        self.manager.install(self.payload, [actual], version='v2')
        self.assertEqual(inspect_game(self.game).modules[1].executable.name, 'Narci_himeko.exe')
        self.manager.uninstall()
        self.assertEqual((self.game / actual).read_bytes(), b'original')

    def test_renamed_managed_executable_on_case_sensitive_filesystem_is_a_conflict(self):
        if os.name == 'nt':
            self.skipTest('Case-sensitive rename conflict is Linux-specific')
        actual = 'narci_himeko/Narci_himeko.exe'
        renamed = 'narci_himeko/narci_himeko.exe'
        put(self.game, actual, b'original')
        put(self.game, 'narci_himeko/scenario.arc', b'archive')
        put(self.payload, actual, b'patch')
        self.manager.install(self.payload, [actual], version='v1')
        (self.game / actual).rename(self.game / renamed)
        with self.assertRaises(InstallError):
            self.manager.uninstall()
        self.assertEqual((self.game / renamed).read_bytes(), b'patch')

    def test_metadata_update_and_identical_payload_do_not_rewrite_game_files(self):
        record = self.install()
        with patch.object(im, "_atomic_copy", side_effect=AssertionError("Game files must not be rewritten")):
            changed = self.manager.update_metadata({"language": "en", "builder": "current"})
            self.assertEqual(changed["files"], record["files"])
            self.assertEqual(changed["version"], "v1")
            updated = self.manager.install(self.payload, [self.path], version="v2")
        self.assertEqual(updated["metadata"], {"language": "en", "builder": "current"})
        self.assertEqual(updated["version"], "v2")
        self.assertEqual((self.game / self.path).read_bytes(), b"font-patch")

    def test_upgrade_restores_dropped_files_and_removes_only_own_addition(self):
        put(self.game, self.path, b"original")
        extra = "narci_onetwo/#mjo/config.mjo"
        put(self.payload, self.path, b"patch1")
        put(self.payload, extra, b"new-file")
        self.manager.install(self.payload, [self.path, extra], version="v1")
        self.manager.install(self.payload, [extra], version="v2")
        self.assertEqual((self.game / self.path).read_bytes(), b"original")
        put(self.game, "narci_onetwo/#mjo/independent.mjo", b"user-other-file")
        report = self.manager.uninstall()
        self.assertEqual(report["removed"], [extra])
        self.assertFalse((self.game / extra).exists())
        self.assertEqual((self.game / "narci_onetwo/#mjo/independent.mjo").read_bytes(), b"user-other-file")

    def test_user_or_steam_changes_block_reinstall_upgrade_and_uninstall(self):
        record = self.install()
        put(self.game, self.path, b"steam-update-or-user-mod")
        for action in (lambda: self.install(), lambda: self.install(b"next", "v2"), self.manager.uninstall):
            with self.subTest(action=action), self.assertRaises(ConflictError) as raised:
                action()
            self.assertEqual(raised.exception.paths, (self.path,))
            self.assertEqual((self.game / self.path).read_bytes(), b"steam-update-or-user-mod")
        self.assertEqual(self.manager.read_record(), record)

    def test_missing_managed_file_is_a_conflict(self):
        self.install()
        (self.game / self.path).unlink()
        with self.assertRaises(ConflictError):
            self.manager.uninstall()
        self.assertFalse((self.game / self.path).exists())

    def test_only_existing_stories_can_be_installed_and_incomplete_dlc_omitted(self):
        put(self.game, "narci_iris/narci_iris.exe", b"partial-download")
        put(self.payload, self.path, b"valid-patch")
        other = "narci_iris/update12.arc"
        put(self.payload, other, b"not-owned-dlc-patch")
        self.assertEqual(inspect_game(self.game).module_ids, ("narci_onetwo",))
        with self.assertRaises(ConflictError):
            self.manager.install(self.payload, [self.path, other], version="v1")
        self.assertFalse((self.game / self.path).exists())
        self.assertFalse((self.game / other).exists())
        self.install()
        self.assertEqual(self.manager.read_record()["modules"], ["narci_onetwo"])

    def test_reject_escape_nonportable_paths_and_save_data(self):
        for relative in ["../outside", "/absolute", "C:/absolute", "C:relative", "narci_onetwo/../oops",
                         "narci_onetwo//update.arc", "narci_onetwo/./update.arc", "narci_onetwo\\x",
                         "narci_onetwo/file:stream", "narci_onetwo/NUL", "narci_onetwo/CON.txt",
                         "narci_onetwo/file. ", "other_game/patch.arc", ".narcibloom/record.json",
                         "narci_onetwo/savedata/x", "narci_onetwo/save_chs/x", "narci_onetwo/SAVES/x",
                         "narci_onetwo/slot.SAV", "narci_onetwo/system.dat", "narci_onetwo/settings.ini"]:
            with self.subTest(relative=relative), self.assertRaises(PathSafetyError):
                self.manager.install(self.payload, [relative], version="v1")
        self.assertFalse(self.manager.state.exists())

    def test_duplicate_and_overlapping_payload_paths_rejected(self):
        for files in ([self.path, self.path], [self.path, self.path.upper().replace("NARCI_ONETWO", "narci_onetwo")],
                      ["narci_onetwo/#mjo", "narci_onetwo/#mjo/config.mjo"]):
            with self.subTest(files=files), self.assertRaises(PathSafetyError):
                self.manager.install(self.payload, files, version="v1")

    def test_case_only_upgrade_path_change_rejected(self):
        self.install()
        spelling = "narci_onetwo/UPDATE12.arc"
        put(self.payload, spelling, b"patch")
        with self.assertRaises(PathSafetyError):
            self.manager.install(self.payload, [spelling], version="v2")

    def test_missing_or_wrong_checksum_payload_leaves_game_unchanged(self):
        put(self.game, self.path, b"original")
        with self.assertRaises(InstallError):
            self.manager.install(self.payload, [self.path], version="v1")
        put(self.payload, self.path, b"bad-file")
        with self.assertRaises(InstallError):
            self.manager.install(self.payload, {self.path: "0" * 64}, version="v1")
        self.assertEqual((self.game / self.path).read_bytes(), b"original")
        self.assertIsNone(self.manager.read_record())
        checksum = hashlib.sha256(b"bad-file").hexdigest()
        self.manager.install(self.payload, {self.path: checksum}, version="v1")

    def test_game_running_blocks_every_mutation_and_fails_closed_on_process_error(self):
        self.install()
        busy = InstallManager(self.game, process_checker=lambda _: ["narci_onetwo.exe PID 1"])
        for action in (lambda: busy.install(self.payload, [self.path], version="v2"), busy.uninstall, busy.recover):
            with self.assertRaises(GameRunningError):
                action()
        with patch.object(self.manager, "_process_checker", side_effect=OSError("enumeration failed")):
            with self.assertRaises(OSError):
                self.manager.uninstall()
        self.assertEqual((self.game / self.path).read_bytes(), b"font-patch")

    def test_windows_process_check_includes_installed_translation_executable_names(self):
        put(self.game, "narci_onetwo/narci_onetwo_cn.exe", b"translation")
        put(self.game, "narci_zero/narci_zero_cn_.EXE", b"translation")
        result = types.SimpleNamespace(stdout='"narci_onetwo_cn.exe","101"\n"NARCI_ZERO_CN_.EXE","102"\n"Steam.exe","103"\n')
        fake_os = types.SimpleNamespace(name="nt")
        with patch.object(im, "os", fake_os), patch.object(im.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
                patch.object(im.subprocess, "run", return_value=result):
            processes = im.running_game_processes(self.game)
        self.assertEqual(processes, ["narci_onetwo_cn.exe (PID 101)", "NARCI_ZERO_CN_.EXE (PID 102)"])

    def test_linux_process_check_includes_wine_translation_paths_and_preserves_same_name_policy(self):
        put(self.game, "narci_onetwo/narci_onetwo_cn.exe", b"translation")
        put(self.game, "narci_zero/narci_zero_cn_.exe", b"translation")

        class Process:
            def __init__(self, pid, command):
                self.name, self.command = str(pid), command

            def __truediv__(self, component):
                self_component = self
                return types.SimpleNamespace(read_bytes=lambda: self_component.command)

        proc = types.SimpleNamespace(is_dir=lambda: True, iterdir=lambda: iter([
            Process(201, b"wine\0Z:\\other-copy\\narci_onetwo_cn.exe\0"),
            Process(202, b"/somewhere/narci_zero_cn_.exe\0"),
            Process(203, b"/usr/bin/steam\0"),
        ]))
        with patch.object(im, "os", types.SimpleNamespace(name="posix")), patch.object(im, "Path", return_value=proc):
            processes = im.running_game_processes(self.game)
        self.assertEqual(processes, ["narci_onetwo_cn.exe (PID 201)", "narci_zero_cn_.exe (PID 202)"])

    def test_game_started_during_staging_blocks_commit(self):
        checks = iter([[], ["narci_onetwo.exe"]])
        self.manager._process_checker = lambda _: next(checks)
        put(self.payload, self.path, b"patch")
        with self.assertRaises(GameRunningError):
            self.manager.install(self.payload, [self.path], version="v1")
        self.assertFalse((self.game / self.path).exists())

    def test_failure_after_first_write_rolls_back_original_and_new_files(self):
        put(self.game, self.path, b"original")
        extra = "narci_onetwo/#txt/config.txt"
        put(self.payload, self.path, b"patch")
        put(self.payload, extra, b"new")
        original_copy = im._atomic_copy
        failed = False

        def fail_once(source, target):
            nonlocal failed
            if target == self.game / extra and not failed:
                failed = True
                raise OSError("simulated disk write failure")
            return original_copy(source, target)

        with patch.object(im, "_atomic_copy", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.manager.install(self.payload, [self.path, extra], version="v1")
        self.assertEqual((self.game / self.path).read_bytes(), b"original")
        self.assertFalse((self.game / extra).exists())
        self.assertEqual(self.manager.read_record()["files"], {})
        self.assertFalse(self.manager.recover()["recovered"])

    def test_failed_upgrade_restores_previous_install_record_and_bytes(self):
        original_record = self.install()
        extra = "narci_onetwo/#txt/config.txt"
        put(self.payload, self.path, b"v2")
        put(self.payload, extra, b"new")
        copy = im._atomic_copy
        with patch.object(im, "_atomic_copy", side_effect=lambda source, target:
                          (_ for _ in ()).throw(OSError("disk full")) if target == self.game / extra
                          else copy(source, target)):
            with self.assertRaises(OSError):
                self.manager.install(self.payload, [self.path, extra], version="v2")
        self.assertEqual((self.game / self.path).read_bytes(), b"font-patch")
        self.assertEqual(self.manager.read_record(), original_record)

    def test_failed_uninstall_restores_installed_state_and_allows_retry(self):
        extra = "narci_onetwo/#mjo/config.mjo"
        put(self.game, self.path, b"original-arc")
        put(self.game, extra, b"original-script")
        put(self.payload, self.path, b"patch-arc")
        put(self.payload, extra, b"patch-script")
        record = self.manager.install(self.payload, [self.path, extra], version="v1")
        copy, failed = im._atomic_copy, False

        def fail_once(source, target):
            nonlocal failed
            if target == self.game / extra and not failed:
                failed = True
                raise OSError("simulated restoration failure")
            return copy(source, target)

        with patch.object(im, "_atomic_copy", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.manager.uninstall()
        self.assertEqual((self.game / self.path).read_bytes(), b"patch-arc")
        self.assertEqual((self.game / extra).read_bytes(), b"patch-script")
        self.assertEqual(self.manager.read_record(), record)
        self.manager.uninstall()
        self.assertEqual((self.game / self.path).read_bytes(), b"original-arc")
        self.assertEqual((self.game / extra).read_bytes(), b"original-script")

    def test_interrupted_transaction_recovered_by_new_manager(self):
        put(self.game, self.path, b"original")
        put(self.payload, self.path, b"patch")
        write_json = im._atomic_json

        def interrupt_record(target, value):
            if target.name == "record.json":
                raise KeyboardInterrupt("simulated terminated process")
            return write_json(target, value)

        with patch.object(im, "_atomic_json", side_effect=interrupt_record):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.install(self.payload, [self.path], version="v1")
        self.assertEqual((self.game / self.path).read_bytes(), b"patch")
        with self.assertRaises(InstallError):
            self.manager.original_file(self.path)
        replacement = InstallManager(self.game, process_checker=lambda _: [])
        self.assertTrue(replacement.recover()["recovered"])
        self.assertEqual((self.game / self.path).read_bytes(), b"original")
        self.assertEqual(replacement.read_record()["files"], {})

    def test_recovery_preserves_post_crash_user_change_and_journal(self):
        put(self.payload, self.path, b"patch")
        write_json = im._atomic_json
        with patch.object(im, "_atomic_json", side_effect=lambda target, value:
                          (_ for _ in ()).throw(KeyboardInterrupt()) if target.name == "record.json"
                          else write_json(target, value)):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.install(self.payload, [self.path], version="v1")
        put(self.game, self.path, b"user-change-after-crash")
        with self.assertRaises(ConflictError):
            self.manager.recover()
        self.assertEqual((self.game / self.path).read_bytes(), b"user-change-after-crash")
        self.assertEqual(json.loads((self.manager.state / "transaction.json").read_text())["status"], "pending")

    def test_modified_backup_blocks_uninstall_before_changes(self):
        put(self.game, self.path, b"original")
        record = self.install()
        put(self.manager.state, record["files"][self.path]["backup"], b"changed-backup")
        with self.assertRaises(InstallError):
            self.manager.uninstall()
        self.assertEqual((self.game / self.path).read_bytes(), b"font-patch")

    def test_reject_linked_payload_target_and_state_when_supported(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.payload / "narci_onetwo"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this test host")
        put(outside, "update12.arc", b"outside")
        with self.assertRaises(PathSafetyError):
            self.manager.install(self.payload, [self.path], version="v1")
        link.unlink()
        put(self.payload, self.path, b"patch")
        target_link = self.game / "narci_onetwo/#mjo"
        target_link.symlink_to(outside, target_is_directory=True)
        put(self.payload, "narci_onetwo/#mjo/x.mjo", b"patch")
        with self.assertRaises(PathSafetyError):
            self.manager.install(self.payload, ["narci_onetwo/#mjo/x.mjo"], version="v1")
        target_link.unlink()
        # The earlier rejected operation can create the state lock, so use a fresh root.
        other_game = self.root / "other-game"
        other_game.mkdir()
        add_story(other_game)
        (other_game / ".narcibloom").symlink_to(outside, target_is_directory=True)
        manager = InstallManager(other_game, process_checker=lambda _: [])
        with self.assertRaises(PathSafetyError):
            manager.install(self.payload, [self.path], version="v1")
        self.assertEqual((outside / "update12.arc").read_bytes(), b"outside")

    def test_invalid_record_or_journal_path_cannot_restore_outside_game(self):
        record = self.install()
        record["files"]["../outside"] = record["files"].pop(self.path)
        (self.manager.state / "record.json").write_text(json.dumps(record))
        with self.assertRaises(PathSafetyError):
            self.manager.uninstall()
        self.assertEqual((self.game / self.path).read_bytes(), b"font-patch")

    def test_simultaneous_installer_lock_blocks_second_manager(self):
        with self.manager._locked():
            with self.assertRaises(InstallError):
                InstallManager(self.game, process_checker=lambda _: []).uninstall()


class SteamDiscoveryTests(unittest.TestCase):
    def test_current_and_legacy_libraries_use_manifest_and_local_story_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steam, library = root / "Steam", root / "DLC Library"
            app = library / "steamapps/common/Anthology"
            add_story(app, "narci_iris")
            put(app, "narci_zero/narci_zero.exe", b"partial")
            put(library, "steamapps/appmanifest_426690.acf", b'"AppState" { "appid" "426690" '
                b'"installdir" "Anthology" "buildid" "123" "UserConfig" { "language" "english" } '
                b'"InstalledDepots" { "999" { "manifest" "11" } } }')
            for entry in [f'"1" {{ "path" "{library.as_posix()}" "apps" {{ "426690" "1" }} }}',
                          f'"1" "{library.as_posix()}"']:
                put(steam, "steamapps/libraryfolders.vdf", ('"libraryfolders" { ' + entry + ' }').encode())
                results = discover_installations([steam])
                self.assertEqual(len(results), 1)
                info = results[0]
                self.assertEqual(info.module_ids, ("narci_iris",))
                self.assertIn("narci_zero", info.missing_modules)
                self.assertEqual(info.build_id, "123")
                self.assertEqual(info.language, "english")
                self.assertEqual(info.installed_depots, ("999",))

    def test_bad_app_or_traversal_manifest_is_not_discovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            add_story(root / "steamapps/common/Game")
            for appid, directory in [("999", "Game"), ("426690", "../Game"), ("426690", "C:/Game"),
                                     ("426690", ".."), ("426690", ".")]:
                put(root, "steamapps/appmanifest_426690.acf",
                    f'"AppState" {{ "appid" "{appid}" "installdir" "{directory}" }}'.encode())
                self.assertEqual(discover_installations([root]), [])

    def test_vdf_windows_escapes_and_incomplete_blocks(self):
        self.assertEqual(parse_vdf(r'"path" "C:\\Program Files\\Steam"')["path"], "C:\\Program Files\\Steam")
        for malformed in ['"AppState" { "appid" "426690"', '"key"', '}', '"key" }']:
            with self.assertRaises(ValueError):
                parse_vdf(malformed)


if __name__ == "__main__":
    unittest.main()
