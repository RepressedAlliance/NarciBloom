"""Player entry-point decisions and Tk integration with an artificial backend."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("narcibloom_gui", TOOLS / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class EntryPointTests(unittest.TestCase):
    def test_chinese_package_uses_chinese_ui_but_font_package_follows_system(self):
        with patch.object(app.locale, "getlocale", return_value=("Japanese_Japan", None)):
            self.assertEqual(app.default_language("font"), "ja")
            self.assertEqual(app.default_language("chinese"), "zh")
        with patch.object(app.locale, "getlocale", return_value=("Chinese (Simplified)_China", None)):
            self.assertEqual(app.default_language("font"), "zh")
        with patch.object(app.locale, "getlocale", return_value=("de_DE", None)):
            self.assertEqual(app.default_language("font"), "en")
        with patch.object(sys, "argv", ["NarciBloom-Chinese"]):
            self.assertEqual(app.default_mode(), "chinese")

    def test_companion_archive_does_not_choose_an_unrelated_or_ambiguous_rar(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "unrelated.rar").write_bytes(b"test")
            self.assertIsNone(app.companion_archive(folder))
            (folder / "translation1.1.rar").write_bytes(b"test")
            self.assertEqual(app.companion_archive(folder).name, "translation1.1.rar")
            (folder / "other1.1.rar").write_bytes(b"test")
            self.assertIsNone(app.companion_archive(folder))
            (folder / app.ARCHIVE_NAME).write_bytes(b"test")
            self.assertEqual(app.companion_archive(folder).name, app.ARCHIVE_NAME)


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except Exception as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.backend = types.SimpleNamespace(available_games=lambda: [], scan_game=lambda path: {
            "path": path, "modules": [], "installed_version": None})

    def destroy_root(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()

    def create(self, mode="font", language="en"):
        with patch.dict(sys.modules, {"installer_app_backend": self.backend}):
            window = app.InstallerApp(self.root, mode=mode, language=language)
        # Tests drive asynchronous results explicitly; do not run auto-discovery.
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        return window

    def test_unsupported_story_remains_visible_but_cannot_be_selected(self):
        window = self.create()
        window.apply_scan({"path": str(TOOLS), "installed_version": None, "modules": [
            {"id": "narci_onetwo", "title": "1 + 2", "language": "ja", "supported": True},
            {"id": "narci_iris", "title": "Iris", "language": "unknown", "supported": False},
        ]})
        window.select_all(True)
        self.assertEqual([value.get() for _, value, _ in window.story_choices], [True, False])
        self.assertEqual(str(window.story_choices[1][2].cget("state")), "disabled")
        self.assertIn("unsupported", window.story_choices[1][2].cget("text"))
        self.assertEqual(str(window.install_button.cget("state")), "normal")
        window.path.set(str(TOOLS.parent))
        self.assertEqual(str(window.install_button.cget("state")), "disabled")

    def test_chinese_gui_and_busy_state_disable_changes_keep_log_copy_available(self):
        window = self.create("chinese", "zh")
        window.apply_scan({"path": str(TOOLS), "installed_version": "test", "modules": [
            {"id": "narci_onetwo", "title": "1＋2", "language": "zh-CN", "supported": True}]})
        window.busy = True
        window.update_controls()
        self.assertEqual(str(window.install_button.cget("state")), "disabled")
        self.assertEqual(str(window.uninstall_button.cget("state")), "disabled")
        self.assertEqual(str(window.copy_button.cget("state")), "normal")
        self.assertEqual(str(window.story_choices[0][2].cget("state")), "disabled")
        window.progress_callback({"message": "synthetic-progress"})
        window.poll_events()
        self.assertIn("synthetic-progress", window.log.get("1.0", "end"))

    def test_pending_recovery_is_visible_without_blocking_recovery_action(self):
        window = self.create()
        info = {"path": str(TOOLS), "installed_version": None, "recovery_required": True,
                "modules": [{"id": "narci_onetwo", "title": "1 + 2", "language": "unknown", "supported": True}]}
        window.apply_scan(info)
        self.assertIn("recovery", window.scan_status(info))
        self.assertIn("recovery", window.log.get("1.0", "end"))
        self.assertEqual(str(window.install_button.cget("state")), "normal")
        self.assertEqual(str(window.uninstall_button.cget("state")), "normal")

    def test_backend_missing_produces_recoverable_player_message(self):
        with patch.object(app.importlib, "import_module", side_effect=ImportError("synthetic missing backend")):
            window = app.InstallerApp(self.root, mode="font", language="en")
        self.assertIsNone(window.backend)
        self.assertIn("installer_app_backend", window.status.get())
        self.assertIn("synthetic missing backend", window.log.get("1.0", "end"))
        self.assertEqual(str(window.install_button.cget("state")), "disabled")

    def test_work_runs_off_ui_thread_and_reenables_controls_on_completion(self):
        window = self.create()
        entered, release = threading.Event(), threading.Event()
        received = []

        def worker():
            entered.set()
            release.wait(2)
            return threading.get_ident()

        window.start_task(worker, received.append)
        self.assertTrue(entered.wait(1))
        self.assertTrue(window.busy)
        self.assertEqual(str(window.game_selector.cget("state")), "disabled")
        release.set()
        event = window.events.get(timeout=2)
        window.events.put(event)
        window.poll_events()
        self.assertFalse(window.busy)
        self.assertNotEqual(received, [threading.get_ident()])
        self.assertEqual(str(window.game_selector.cget("state")), "normal")

    def test_small_screen_keeps_actions_status_and_readable_log_in_three_languages(self):
        window = self.create("chinese", "ja")
        window.apply_scan({"path": str(TOOLS), "installed_version": "preview", "modules": [
            {"id": str(index), "title": "Synthetic story", "language": "ja", "supported": True}
            for index in range(5)]})
        self.root.attributes("-alpha", 0)
        self.root.deiconify()
        self.root.geometry("960x720")
        for language in ("ja", "en", "zh"):
            with self.subTest(language=language):
                window.interface.set(next(name for name, key in app.LANGUAGES.items() if key == language))
                window.change_language()
                self.root.update()
                self.assertGreaterEqual(window.log.winfo_height(), 50)
                root_bottom = self.root.winfo_rooty() + self.root.winfo_height()
                for widget in (window.install_button, window.uninstall_button, window.status_label):
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), root_bottom)


if __name__ == "__main__":
    unittest.main()
