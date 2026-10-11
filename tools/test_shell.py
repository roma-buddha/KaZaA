"""Focused, offline checks for the new desktop shell's real interactions."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStackedWidget, QWidget
from kazaa.ui.shell import ShellWindow
from kazaa.ui import shell_preferences


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name, "shell-settings.json")
        self.window = ShellWindow(self.path)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def click(self, widget):
        QTest.mouseClick(widget, Qt.LeftButton)
        self.app.processEvents()

    def test_removed_navigation_and_copy_are_not_in_the_shell(self):
        self.assertFalse(self.window.sidebar.findChildren(QPushButton))
        self.assertFalse(self.window.findChildren(QStackedWidget))
        self.assertFalse(self.window.canvas.findChildren(QWidget))
        self.assertFalse(hasattr(self.window, "navigate"))
        forbidden = {"Local workspace", "On this computer", "Overview", "WORKSPACE",
                     "MEDIA", "COLLECTION", "Downloads", "Music", "Convert", "Recorder", "Library", "Settings"}
        for widget in self.window.findChildren(QLabel):
            self.assertNotIn(widget.text(), forbidden)
        for button in (self.window.theme_toggle, self.window.settings_button):
            self.assertEqual(button.text(), "")
            self.assertFalse(button.isCheckable())
        self.assertFalse(self.window.windowIcon().isNull())

    def test_theme_toggle_updates_every_page_and_saves_choice(self):
        self.click(self.window.theme_toggle)
        self.assertEqual(self.window.preferences["theme"], "dark")
        self.assertTrue(self.window.appearance.theme_buttons["dark"].isChecked())
        self.assertIn("#181817", self.window.styleSheet())
        self.assertEqual(json.loads(self.path.read_text())["theme"], "dark")
        self.click(self.window.settings_button)
        self.click(self.window.appearance.theme_buttons["light"])
        self.assertEqual(self.window.preferences["theme"], "light")
        self.assertIn("#f8f5ee", self.window.styleSheet())

    def test_sidebar_can_collapse_and_restore_its_width(self):
        before = self.window.splitter.sizes()[0]
        self.click(self.window.sidebar_toggle)
        self.assertFalse(self.window.sidebar.isVisible())
        self.assertEqual(self.window.sidebar_toggle.accessibleName(), "Show sidebar")
        self.click(self.window.sidebar_toggle)
        self.assertTrue(self.window.sidebar.isVisible())
        self.assertAlmostEqual(self.window.splitter.sizes()[0], before, delta=1)

    def test_keyboard_resize_is_saved(self):
        handle = self.window.splitter.handle(1)
        before = self.window.splitter.sizes()[0]
        handle.setFocus()
        QTest.keyClick(handle, Qt.Key_Right)
        self.app.processEvents()
        self.assertAlmostEqual(self.window.splitter.sizes()[0], before + 10, delta=1)
        self.assertAlmostEqual(json.loads(self.path.read_text())["sidebar_width"], before + 10, delta=1)

    def test_preferences_restore_after_reopening(self):
        self.window.set_theme("dark")
        self.window.toggle_sidebar()
        self.window.close()
        reopened = ShellWindow(self.path)
        try:
            reopened.show()
            self.app.processEvents()
            self.assertEqual(reopened.preferences["theme"], "dark")
            self.assertNotIn("page", reopened.preferences)
            self.assertFalse(reopened.sidebar.isVisible())
        finally:
            reopened.close()

    def test_invalid_preferences_fall_back_without_crashing(self):
        self.path.write_text('{"theme": [], "page": {}, "sidebar_width": "bad"}')
        self.assertEqual(shell_preferences.load(self.path), shell_preferences.DEFAULTS)
        self.path.write_text("broken JSON")
        self.assertEqual(shell_preferences.load(self.path), shell_preferences.DEFAULTS)

    def test_media_engines_are_not_imported_by_the_shell(self):
        self.assertNotIn("kazaa.downloader", sys.modules)
        self.assertNotIn("kazaa.torrent", sys.modules)

    def test_settings_open_without_selection_and_dismiss_with_escape(self):
        self.click(self.window.settings_button)
        self.assertTrue(self.window.appearance.isVisible())
        self.assertFalse(self.window.settings_button.isChecked())
        QTest.keyClick(self.window.appearance, Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(self.window.appearance.isVisible())
        self.window.show_settings()
        self.click(self.window.appearance.close_button)
        self.assertFalse(self.window.appearance.isVisible())

    def test_previous_page_preference_is_ignored_and_dropped(self):
        self.path.write_text(json.dumps({"page": "music", "theme": "dark", "sidebar_width": 310}))
        loaded = shell_preferences.load(self.path)
        self.assertEqual(loaded["theme"], "dark")
        self.assertEqual(loaded["sidebar_width"], 310)
        self.assertNotIn("page", loaded)
        shell_preferences.save(self.path, loaded)
        self.assertNotIn("page", json.loads(self.path.read_text()))


if __name__ == "__main__":
    unittest.main()
