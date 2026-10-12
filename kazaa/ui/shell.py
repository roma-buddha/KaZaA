"""Minimal local app frame: branding, sidebar, and appearance controls."""
from pathlib import Path
import sys

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel,
                               QFileDialog, QLineEdit, QMessageBox, QPushButton,
                               QSplitter, QSplitterHandle, QStackedWidget, QVBoxLayout, QWidget)

from ..rsrc import asset
from ..settings import config_dir
from . import shell_preferences, shell_theme
from .shell_icons import icon
from .shell_frame import ShellFrame
from ..video_jobs import VideoQueue
from .video_pages import DownloadedPage, SearchPage, save_folder
from .shred_page import ShredPage


class SidebarHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Resize sidebar")
        self.setToolTip("Drag to resize · Arrow keys when focused")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            width = self.splitter().sizes()[0]
            width += 10 if event.key() == Qt.Key_Right else -10
            width = max(200, min(420, width))
            self.splitter().setSizes([width, max(1, self.splitter().width() - width)])
            self.splitter().splitterMoved.emit(width, 1)
            event.accept()
        else:
            super().keyPressEvent(event)


class SidebarSplitter(QSplitter):
    def createHandle(self):
        return SidebarHandle(self.orientation(), self)


class AppearanceDialog(QDialog):
    theme_changed = Signal(str)
    dismissed = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("appearance")
        self.setWindowTitle("Settings")
        self.setAccessibleName("Settings")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(18)
        header = QHBoxLayout()
        heading = QLabel("Settings")
        heading.setProperty("role", "heading")
        header.addWidget(heading)
        header.addStretch()
        self.close_button = QPushButton()
        self.close_button.setProperty("role", "icon")
        self.close_button.setFixedSize(36, 36)
        self.close_button.setAccessibleName("Close appearance settings")
        self.close_button.setToolTip("Close")
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        options = QHBoxLayout()
        options.setSpacing(12)
        self.theme_buttons = {}
        self.theme_group = QButtonGroup(self)
        for mode, title in [("light", "Light"), ("dark", "Dark")]:
            button = QPushButton(title)
            button.setProperty("role", "theme")
            button.setIconSize(QSize(20, 20))
            button.setMinimumHeight(72)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(f"{title} theme")
            button.clicked.connect(lambda checked=False, theme=mode: self.theme_changed.emit(theme))
            self.theme_group.addButton(button)
            self.theme_buttons[mode] = button
            options.addWidget(button, 1)
        layout.addLayout(options)
        folder_label = QLabel("Download folder")
        folder_label.setProperty("role", "muted")
        layout.addWidget(folder_label)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(save_folder(parent.download_queue))
        self.folder.setAccessibleName("Download folder")
        self.folder.setMinimumWidth(0)
        self.folder.editingFinished.connect(self._save_folder)
        folder_row.addWidget(self.folder, 1)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.browse_button)
        layout.addLayout(folder_row)
        self.close_button.setCursor(Qt.PointingHandCursor)

    def _save_folder(self):
        queue = self.parentWidget().download_queue
        folder = self.folder.text().strip()
        if folder:
            queue.set_options({**queue.options, "folder": folder})
        else:
            self.folder.setText(save_folder(queue))

    def _browse_folder(self):
        selected = QFileDialog.getExistingDirectory(self.parentWidget(), "Download folder", self.folder.text())
        if selected:
            self.folder.setText(selected)
            self._save_folder()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.dismissed.emit()

    def sync(self, mode, colors):
        self.theme_buttons[mode].setChecked(True)
        for key, button in self.theme_buttons.items():
            button.setIcon(icon("sun" if key == "light" else "moon",
                                colors["accent"] if key == mode else colors["muted"]))
        self.close_button.setIcon(icon("close", colors["muted"]))


class ShellWindow(ShellFrame):
    def __init__(self, preferences_path=None):
        super().__init__()
        self.preferences_path = Path(preferences_path) if preferences_path else Path(config_dir(), "shell-settings.json")
        self.preferences = shell_preferences.load(self.preferences_path)
        self._ready = False
        self._save_error_reported = False
        self.setWindowTitle("KaZaA · v2. revival")
        self.setWindowIcon(QIcon(asset("icon-start1.ico")))
        self.resize(1200, 800)
        self.setMinimumSize(820, 600)
        self.splitter = SidebarSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.topbar = self._build_topbar()
        root_layout.addWidget(self.topbar)
        root_layout.addWidget(self.splitter, 1)
        self.setCentralWidget(root)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(420)
        self.splitter.addWidget(self.sidebar)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 22, 14, 24)
        sidebar_layout.setSpacing(4)
        self.navigation_group = QButtonGroup(self)
        self.navigation_buttons = {}
        for key, title in (("search", "Search"), ("downloaded", "Downloads"), ("shred", "Shred")):
            button = QPushButton(title)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.setAccessibleName(title)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda checked=False, page=key: self.navigate(page))
            self.navigation_group.addButton(button)
            self.navigation_buttons[key] = button
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch()

        self.workspace = QWidget()
        self.workspace.setObjectName("workspace")
        self.workspace.setMinimumWidth(500)
        self.splitter.addWidget(self.workspace)
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self.canvas = QStackedWidget()
        self.canvas.setObjectName("canvas")
        self.canvas.setAccessibleName("Workspace")
        workspace_layout.addWidget(self.canvas, 1)
        self.download_queue = VideoQueue(self.preferences_path.parent / "video-downloads.json", self)
        self.search_page = SearchPage(self.download_queue)
        self.downloaded_page = DownloadedPage(self.download_queue)
        self.shred_page = ShredPage(self.preferences["shred_algorithm"],
                                   queue_path=self.preferences_path.parent / "shred-queue.json")
        self.download_queue.shred_files = self.shred_page.enqueue_files
        self.shred_page.files_shredded.connect(self.download_queue.files_shredded)
        self.shred_page.files_released.connect(self.download_queue.files_released)
        self.shred_page.algorithm_changed.connect(self._shred_algorithm_changed)
        self.search_page.open_download.connect(self._open_download)
        self.canvas.addWidget(self.search_page)
        self.canvas.addWidget(self.downloaded_page)
        self.canvas.addWidget(self.shred_page)
        self.appearance = AppearanceDialog(self)
        self.appearance.theme_changed.connect(self.set_theme)
        self.appearance.dismissed.connect(self._settings_dismissed)

        self.splitter.setStretchFactor(1, 1)
        width = self.preferences["sidebar_width"]
        self.splitter.setSizes([width, self.width() - width])
        self.splitter.splitterMoved.connect(self._sidebar_resized)
        self._apply_theme()
        self._set_collapsed(self.preferences["sidebar_collapsed"])
        self._ready = True
        self.navigate(self.preferences["page"])
        for sequence, callback in [("Ctrl+B", self.toggle_sidebar), ("Ctrl+,", self.show_settings),
                                   ("Ctrl+Shift+L", self.toggle_theme)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        focus_links = QShortcut(QKeySequence("Ctrl+L"), self)
        focus_links.activated.connect(self._focus_links)
        self.initialize_frame()
        QTimer.singleShot(0, self.download_queue.start_pending)

    def navigate(self, page):
        if page not in self.navigation_buttons:
            return
        self.preferences["page"] = page
        self.canvas.setCurrentWidget({"search": self.search_page, "downloaded": self.downloaded_page,
                                     "shred": self.shred_page}[page])
        self.navigation_buttons[page].setChecked(True)
        for key, button in self.navigation_buttons.items():
            button.setIcon(icon(key, self.colors["accent"] if key == page else self.colors["muted"]))
        self._save()

    def _focus_links(self):
        self.navigate("search")
        self.search_page.input.setFocus()

    def _shred_algorithm_changed(self, algorithm):
        self.preferences["shred_algorithm"] = algorithm
        self._save()

    def _icon_button(self, accessible_name):
        button = QPushButton()
        button.setProperty("role", "icon")
        button.setFixedSize(42, 42)
        button.setIconSize(QSize(18, 18))
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.TabFocus)
        return button

    def _build_topbar(self):
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(58)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(20, 0, 8, 0)
        layout.setSpacing(4)
        self.wordmark = QLabel()
        self.wordmark.setObjectName("wordmark")
        self.wordmark.setAccessibleName("KaZaA")
        self.wordmark.setTextFormat(Qt.RichText)
        self.wordmark.setContentsMargins(0, 0, 14, 0)
        layout.addWidget(self.wordmark)
        self.sidebar_toggle = self._icon_button("Hide sidebar · Ctrl+B")
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        layout.addWidget(self.sidebar_toggle)
        self.theme_toggle = self._icon_button("Switch theme")
        self.theme_toggle.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_toggle)
        self.settings_button = self._icon_button("Settings · Ctrl+,")
        self.settings_button.clicked.connect(self.show_settings)
        layout.addWidget(self.settings_button)
        layout.addStretch()
        self.minimize_button = self._icon_button("Minimize")
        self.minimize_button.clicked.connect(self.showMinimized)
        self.maximize_button = self._icon_button("Maximize")
        self.maximize_button.clicked.connect(self.toggle_maximized)
        self.close_button = self._icon_button("Close")
        self.close_button.setObjectName("windowClose")
        self.close_button.clicked.connect(self.close)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.setFixedSize(42, 36)
            layout.addWidget(button)
        return topbar

    def update_window_controls(self):
        if not hasattr(self, "colors"):
            return
        action = "Restore" if self.isMaximized() else "Maximize"
        self.maximize_button.setToolTip(action)
        self.maximize_button.setAccessibleName(action)
        self.maximize_button.setIcon(icon(action.lower(), self.colors["muted"]))

    def show_settings(self):
        self.appearance.adjustSize()
        anchor = self.settings_button.mapToGlobal(QPoint(self.settings_button.width(),
                                                       self.settings_button.height() + 10))
        screen = self.screen().availableGeometry()
        x = max(screen.left(), min(anchor.x() - self.appearance.width(), screen.right() - self.appearance.width()))
        y = min(anchor.y(), screen.bottom() - self.appearance.height())
        self.appearance.move(x, y)
        self.appearance.show()
        self.appearance.theme_buttons[self.preferences["theme"]].setFocus()

    def _settings_dismissed(self):
        button = self.settings_button
        if not button.rect().contains(button.mapFromGlobal(QCursor.pos())):
            # A popup grabs the mouse, so its opener can miss the normal leave event.
            QApplication.sendEvent(button, QEvent(QEvent.Leave))
            button.setAttribute(Qt.WA_UnderMouse, False)
            button.update()

    def set_theme(self, theme):
        if theme not in ("light", "dark"):
            return
        self.preferences["theme"] = theme
        self._apply_theme()
        self._save()

    def toggle_theme(self):
        self.set_theme("dark" if self.preferences["theme"] == "light" else "light")

    def _apply_theme(self):
        mode = self.preferences["theme"]
        self.colors = shell_theme.DARK if mode == "dark" else shell_theme.LIGHT
        style = shell_theme.stylesheet(self.colors)
        self.setStyleSheet(style)
        self.appearance.setStyleSheet(style)
        self.sidebar_toggle.setIcon(icon("sidebar", self.colors["muted"]))
        self.theme_toggle.setIcon(icon("moon" if mode == "dark" else "sun", self.colors["muted"]))
        tooltip = f"Switch to {'light' if mode == 'dark' else 'dark'} theme · Ctrl+Shift+L"
        self.theme_toggle.setToolTip(tooltip)
        self.theme_toggle.setAccessibleName(tooltip)
        self.settings_button.setIcon(icon("settings", self.colors["muted"]))
        for key, button in self.navigation_buttons.items():
            button.setIcon(icon(key, self.colors["accent"] if button.isChecked() else self.colors["muted"]))
        self.wordmark.setText(f"Ka<span style='color:{self.colors['accent']}'>Z</span>aA")
        self.minimize_button.setIcon(icon("minimize", self.colors["muted"]))
        self.close_button.setIcon(icon("close", self.colors["muted"]))
        self.update_window_controls()
        self.appearance.sync(mode, self.colors)

    def toggle_sidebar(self):
        self._set_collapsed(not self.preferences["sidebar_collapsed"])
        self._save()

    def _set_collapsed(self, collapsed):
        self.preferences["sidebar_collapsed"] = collapsed
        self.sidebar.setVisible(not collapsed)
        self.splitter.handle(1).setVisible(not collapsed)
        if not collapsed:
            width = self.preferences["sidebar_width"]
            self.splitter.setSizes([width, max(1, self.splitter.width() - width)])
        action = "Show" if collapsed else "Hide"
        self.sidebar_toggle.setToolTip(f"{action} sidebar · Ctrl+B")
        self.sidebar_toggle.setAccessibleName(f"{action} sidebar")

    def _sidebar_resized(self, position, index):
        if not self.preferences["sidebar_collapsed"]:
            self.preferences["sidebar_width"] = max(200, min(420, self.splitter.sizes()[0]))
            self._save()

    def _save(self):
        if not self._ready:
            return
        try:
            shell_preferences.save(self.preferences_path, self.preferences)
            self._save_error_reported = False
        except OSError as error:
            print(f"Could not save appearance preferences: {error}", file=sys.stderr)
            if not self._save_error_reported:
                self._save_error_reported = True
                QMessageBox.warning(self, "Preferences", "Your appearance preferences could not be saved.")

    def _open_download(self, job_id):
        self.navigate("downloaded")
        for table in (self.downloaded_page.active_table, self.downloaded_page.completed_table):
            row = table.row_for(job_id)
            if row >= 0:
                table.selectRow(row)
                table.scrollToItem(table.item(row, 0))

    def closeEvent(self, event):
        self.shred_page.stop()
        self.search_page.inspector.stop()
        self.download_queue.stop()
        if self.search_page.inspector.workers or self.download_queue.workers or self.shred_page.worker:
            event.ignore()
            self.setEnabled(False)
            QTimer.singleShot(100, self.close)
            return
        self.appearance.close()
        self._save()
        super().closeEvent(event)
