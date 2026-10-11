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
from PySide6.QtWidgets import QApplication
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

    def test_sidebar_navigation_updates_page_and_selection(self):
        for key, button in self.window.nav_buttons.items():
            self.click(button)
            self.assertTrue(button.isChecked())
            self.assertEqual(self.window.stack.currentIndex(), self.window.page_indices[key])
            self.assertEqual(self.window.breadcrumb.text(), button.text())

    def test_theme_toggle_updates_every_page_and_saves_choice(self):
        self.click(self.window.theme_toggle)
        self.assertEqual(self.window.preferences["theme"], "dark")
        self.assertTrue(self.window.theme_buttons["dark"].isChecked())
        self.assertIn("#181817", self.window.styleSheet())
        self.assertEqual(json.loads(self.path.read_text())["theme"], "dark")
        self.window.navigate("settings")
        self.click(self.window.theme_buttons["light"])
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
        self.window.navigate("music")
        self.window.toggle_sidebar()
        self.window.close()
        reopened = ShellWindow(self.path)
        try:
            reopened.show()
            self.app.processEvents()
            self.assertEqual(reopened.preferences["theme"], "dark")
            self.assertEqual(reopened.breadcrumb.text(), "Music")
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


if __name__ == "__main__":
    unittest.main()
