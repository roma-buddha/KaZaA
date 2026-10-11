"""Focused, offline checks for the new desktop shell's real interactions."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, Qt
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

    def test_only_search_and_downloaded_navigation_are_available(self):
        self.assertEqual(set(self.window.navigation_buttons), {"search", "downloaded"})
        self.assertEqual(len(self.window.sidebar.findChildren(QPushButton)), 2)
        self.assertEqual(self.window.canvas.count(), 2)
        self.click(self.window.navigation_buttons["downloaded"])
        self.assertEqual(self.window.canvas.currentWidget(), self.window.downloaded_page)
        self.click(self.window.navigation_buttons["search"])
        self.assertEqual(self.window.canvas.currentWidget(), self.window.search_page)
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
            self.assertEqual(reopened.preferences["page"], "search")
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
        self.assertEqual(loaded["page"], "search")
        shell_preferences.save(self.path, loaded)
        self.assertEqual(json.loads(self.path.read_text())["page"], "search")

    def test_wordmark_and_controls_stay_visible_when_sidebar_is_hidden(self):
        self.assertEqual(self.window.wordmark.accessibleName(), "KaZaA")
        self.assertFalse(hasattr(self.window, "brand_icon"))
        self.window.toggle_sidebar()
        self.assertTrue(self.window.wordmark.isVisible())
        for button in (self.window.sidebar_toggle, self.window.theme_toggle,
                       self.window.settings_button, self.window.minimize_button,
                       self.window.maximize_button, self.window.close_button):
            self.assertTrue(button.isVisible())
            self.assertEqual(button.parentWidget(), self.window.topbar)

    def test_sidebar_toggle_does_not_keep_a_selected_state(self):
        self.click(self.window.sidebar_toggle)
        self.click(self.window.sidebar_toggle)
        self.window.sidebar_toggle.setFocus()
        self.assertFalse(self.window.sidebar_toggle.isCheckable())
        QTest.keyClick(self.window.sidebar_toggle, Qt.Key_Space)
        self.app.processEvents()
        self.assertFalse(self.window.sidebar.isVisible())

    def test_maximize_restore_and_minimize_controls(self):
        self.assertTrue(self.window.windowFlags() & Qt.FramelessWindowHint)
        self.click(self.window.maximize_button)
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.window.maximize_button.accessibleName(), "Restore")
        self.click(self.window.maximize_button)
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.maximize_button.accessibleName(), "Maximize")
        self.click(self.window.minimize_button)
        self.assertTrue(self.window.isMinimized())
        self.window.showNormal()

    def test_close_control_saves_preferences(self):
        self.window.set_theme("dark")
        self.click(self.window.close_button)
        self.assertFalse(self.window.isVisible())
        self.assertEqual(json.loads(self.path.read_text())["theme"], "dark")

    def test_native_header_hit_regions_keep_buttons_out_of_drag_area(self):
        def hit(point):
            return self.window._frame_hit_test(point, self.window.width(), self.window.height(), 6)
        self.assertEqual(hit(QPoint(1, 1)), 13)
        self.assertEqual(hit(QPoint(self.window.width() - 1, self.window.height() - 1)), 17)
        self.assertEqual(hit(QPoint(600, 29)), 2)
        self.assertEqual(hit(self.window.settings_button.mapTo(self.window, self.window.settings_button.rect().center())), 1)
        self.assertEqual(hit(self.window.maximize_button.mapTo(self.window, self.window.maximize_button.rect().center())), 9)
        self.window.showMaximized()
        self.app.processEvents()
        self.assertNotEqual(hit(QPoint(1, 1)), 13)


if __name__ == "__main__":
    unittest.main()
