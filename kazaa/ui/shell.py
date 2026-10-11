"""The start1 local desktop foundation. Media engines are added in later steps."""
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QScrollArea, QSizePolicy,
                               QSplitter, QSplitterHandle, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..rsrc import asset
from ..settings import config_dir
from . import shell_preferences, shell_theme
from .shell_icons import icon

DESTINATIONS = [
    ("overview", "Overview", "home"), ("activity", "Activity", "activity"),
    ("downloads", "Downloads", "download"), ("music", "Music", "music"),
    ("convert", "Convert", "convert"), ("record", "Recorder", "record"),
    ("library", "Library", "library"), ("settings", "Settings", "settings"),
]
EMPTY_PAGES = {
    "activity": ("A little quiet, for now.", "Your downloads and other tasks will appear here.", "Activity tracking will be added as we build each tool."),
    "downloads": ("Every collection starts with a link.", "A home for the videos and audio you want to keep.", "Download tools are the next step. Nothing is downloading yet."),
    "music": ("Find your next favorite.", "Your space to discover, listen, and collect.", "Music search and playback will be added in a later step."),
    "convert": ("A different format. The same story.", "Make your media work wherever you need it.", "Conversion tools will be added in a later step."),
    "record": ("Keep the moment.", "A place for screen captures and live recordings.", "Recording tools will be added in a later step."),
    "library": ("Room for your favorites.", "The things you keep will feel at home here.", "Your library will grow when the media tools are connected."),
}


def label(text, role=None, wrap=False):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    if role == "status":
        widget.setFixedHeight(28)
        widget.setAlignment(Qt.AlignCenter)
    return widget


class Logo(QLabel):
    def __init__(self, size):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAccessibleName("KazaA logo")
        self.image = QPixmap(asset("logo-start1.png"))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        painter.setClipPath(clip)
        painter.drawPixmap(self.rect(), self.image)


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


class ShellWindow(QMainWindow):
    def __init__(self, preferences_path=None):
        super().__init__()
        self.preferences_path = Path(preferences_path) if preferences_path else Path(config_dir(), "shell-settings.json")
        self.preferences = shell_preferences.load(self.preferences_path)
        self._ready = False
        self.icon_buttons = []
        self.empty_icons = []
        self.setWindowTitle("KazaA · v2. revival")
        self.setWindowIcon(QIcon(asset("logo-start1.png")))
        self.resize(1200, 800)
        self.setMinimumSize(820, 600)

        self.splitter = SidebarSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(420)
        self.splitter.addWidget(self.sidebar)
        self._build_sidebar()

        self.workspace = QWidget()
        self.workspace.setObjectName("workspace")
        self.workspace.setMinimumWidth(500)
        self.splitter.addWidget(self.workspace)
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        workspace_layout.addWidget(self.stack, 1)
        self.page_indices = {}
        for key, title, glyph in DESTINATIONS:
            self.page_indices[key] = self.stack.count()
            self.stack.addWidget(self._build_page(key, title, glyph))
        self.splitter.setStretchFactor(1, 1)
        width = self.preferences["sidebar_width"]
        self.splitter.setSizes([width, self.width() - width])
        self.splitter.splitterMoved.connect(self._sidebar_resized)
        self._apply_theme()
        self.navigate(self.preferences["page"])
        self._set_collapsed(self.preferences["sidebar_collapsed"])
        self._ready = True
        for sequence, callback in [("Ctrl+B", self.toggle_sidebar), ("Ctrl+,", lambda: self.navigate("settings")),
                                   ("Ctrl+Shift+L", self.toggle_theme)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    def _button(self, text, glyph, role=None):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setIconSize(QSize(18, 18))
        button.setMinimumHeight(42)
        if role:
            button.setProperty("role", role)
        self.icon_buttons.append((button, glyph))
        return button

    def _build_sidebar(self):
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.addWidget(Logo(68))
        brand.addWidget(label("KazaA", "brand"))
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(25)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # The sidebar's scrolling surface must inherit the sidebar color.
        scroll.setObjectName("sidebarScroll")
        navigation = QWidget()
        navigation.setObjectName("sidebarNavigation")
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, title, glyph in DESTINATIONS:
            if key == "settings":
                continue
            if key in ("overview", "downloads", "library"):
                if key != "overview":
                    navigation_layout.addSpacing(22)
                section = {"overview": "WORKSPACE", "downloads": "MEDIA", "library": "COLLECTION"}[key]
                heading = label(section, "eyebrow")
                heading.setContentsMargins(12, 0, 0, 8)
                navigation_layout.addWidget(heading)
            button = self._button(title, glyph)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, destination=key: self.navigate(destination))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            navigation_layout.addWidget(button)
        navigation_layout.addStretch()
        scroll.setWidget(navigation)
        layout.addWidget(scroll, 1)
        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 12, 0, 0)
        settings = self._button("Settings", "settings")
        settings.setProperty("nav", True)
        settings.setCheckable(True)
        settings.clicked.connect(lambda: self.navigate("settings"))
        self.nav_group.addButton(settings)
        self.nav_buttons["settings"] = settings
        footer_layout.addWidget(settings)
        self.preference_feedback = label("On this computer", "muted")
        self.preference_feedback.setContentsMargins(12, 6, 0, 0)
        footer_layout.addWidget(self.preference_feedback)
        layout.addWidget(footer)

    def _build_topbar(self):
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(64)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)
        self.sidebar_toggle = self._button("", "sidebar", "icon")
        self.sidebar_toggle.setFixedSize(42, 42)
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        layout.addWidget(self.sidebar_toggle)
        self.breadcrumb = label("Overview", "muted")
        layout.addWidget(self.breadcrumb)
        layout.addStretch()
        layout.addWidget(label("Local workspace", "status"))
        self.theme_toggle = self._button("Light", "sun")
        self.theme_toggle.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_toggle)
        return topbar

    def _build_page(self, key, title, glyph):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("page")
        outer = QHBoxLayout(container)
        outer.setContentsMargins(40, 44, 40, 32)
        outer.addStretch()
        content = QWidget()
        content.setMaximumWidth(960)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        outer.addWidget(content, 1)
        outer.addStretch()
        if key == "overview":
            self._overview(body)
        elif key == "settings":
            self._settings(body)
        else:
            body.addWidget(label(title, "heading"))
            body.addWidget(label("Your local workspace", "muted"))
            body.addSpacing(28)
            heading, description, note = EMPTY_PAGES[key]
            panel, panel_layout = self._panel()
            panel_layout.setContentsMargins(32, 58, 32, 58)
            panel_layout.addWidget(self._empty_icon(glyph), 0, Qt.AlignHCenter)
            panel_layout.addSpacing(14)
            for text, role in [(heading, "subheading"), (description, "muted"), (note, "muted")]:
                line = label(text, role, True)
                line.setAlignment(Qt.AlignCenter)
                panel_layout.addWidget(line)
            body.addWidget(panel)
        body.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _panel(self):
        panel = QFrame()
        panel.setProperty("role", "panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        return panel, layout

    def _empty_icon(self, glyph):
        widget = label("", "emptyIcon")
        widget.setFixedSize(64, 64)
        widget.setAlignment(Qt.AlignCenter)
        self.empty_icons.append((widget, glyph))
        return widget

    def _overview(self, body):
        eyebrow_row = QHBoxLayout()
        eyebrow_row.addWidget(label("YOUR WORKSPACE", "eyebrow"))
        eyebrow_row.addStretch()
        eyebrow_row.addWidget(label("v2. revival", "tag"))
        body.addLayout(eyebrow_row)
        body.addWidget(label("Your media, at home.", "heading"))
        body.addWidget(label("A little space for music, video, and the things you want to keep.", "muted", True))
        body.addSpacing(24)
        panel, panel_layout = self._panel()
        panel_layout.setContentsMargins(32, 36, 32, 32)
        panel_layout.addWidget(Logo(108), 0, Qt.AlignHCenter)
        panel_layout.addSpacing(8)
        title = label("Welcome back to KazaA.", "subheading", True)
        title.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title)
        description = label("A fresh start for your collection. Everything begins here,\non your own computer.", "muted", True)
        description.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(description)
        panel_layout.addSpacing(10)
        settings = self._button("Make it yours", "arrow", "primary")
        settings.setMinimumWidth(162)
        settings.clicked.connect(lambda: self.navigate("settings"))
        panel_layout.addWidget(settings, 0, Qt.AlignHCenter)
        body.addWidget(panel)
        body.addSpacing(16)
        body.addWidget(label("EXPLORE YOUR SPACE", "eyebrow"))
        links = QHBoxLayout()
        links.setSpacing(12)
        for text, glyph, destination in [("Downloads", "download", "downloads"), ("Music", "music", "music"),
                                         ("Your library", "library", "library")]:
            button = self._button(text, glyph, "secondary")
            button.setMinimumHeight(58)
            button.clicked.connect(lambda checked=False, key=destination: self.navigate(key))
            links.addWidget(button, 1)
        body.addLayout(links)

    def _settings(self, body):
        body.addWidget(label("Settings", "heading"))
        body.addWidget(label("A workspace that feels like you.", "muted"))
        body.addSpacing(28)
        panel, panel_layout = self._panel()
        panel_layout.addWidget(label("Appearance", "subheading"))
        panel_layout.addWidget(label("Choose a theme. Your preference stays on this computer.", "muted", True))
        panel_layout.addSpacing(10)
        themes = QHBoxLayout()
        themes.setSpacing(14)
        self.theme_buttons = {}
        self.theme_group = QButtonGroup(self)
        for key, text, glyph in [("light", "Light\nPaper", "sun"), ("dark", "Dark\nWarm night", "moon")]:
            button = self._button(text, glyph, "theme")
            button.setMinimumHeight(90)
            button.setCheckable(True)
            button.setAccessibleName(f"{key.title()} theme")
            button.clicked.connect(lambda checked=False, mode=key: self.set_theme(mode))
            self.theme_group.addButton(button)
            self.theme_buttons[key] = button
            themes.addWidget(button, 1)
        panel_layout.addLayout(themes)
        body.addWidget(panel)
        body.addSpacing(12)
        body.addWidget(label("Keyboard shortcuts", "subheading"))
        body.addWidget(label("Ctrl+B    Toggle sidebar\nCtrl+,    Open settings\nCtrl+Shift+L    Switch theme", "muted"))

    def navigate(self, page):
        if page not in self.page_indices:
            return
        self.stack.setCurrentIndex(self.page_indices[page])
        self.nav_buttons[page].setChecked(True)
        self.breadcrumb.setText(self.nav_buttons[page].text())
        self.preferences["page"] = page
        self._refresh_icons()
        self._save()

    def set_theme(self, theme):
        if theme not in ("light", "dark"):
            return
        self.preferences["theme"] = theme
        self._apply_theme()
        self._save()

    def toggle_theme(self):
        self.set_theme("dark" if self.preferences["theme"] == "light" else "light")

    def _apply_theme(self):
        self.colors = shell_theme.DARK if self.preferences["theme"] == "dark" else shell_theme.LIGHT
        self.setStyleSheet(shell_theme.stylesheet(self.colors) + f"""
            QScrollArea#sidebarScroll, QWidget#sidebarNavigation,
            QScrollArea#sidebarScroll > QWidget > QWidget {{ background: {self.colors['sidebar']}; }}
        """)
        mode = self.preferences["theme"]
        self.theme_toggle.setText(mode.title())
        self.theme_toggle.setToolTip(f"Switch to {'light' if mode == 'dark' else 'dark'} theme · Ctrl+Shift+L")
        self.theme_toggle.setAccessibleName(self.theme_toggle.toolTip())
        self.theme_buttons[mode].setChecked(True)
        self._refresh_icons()

    def _refresh_icons(self):
        for button, glyph in self.icon_buttons:
            if button is self.theme_toggle:
                glyph = "moon" if self.preferences["theme"] == "dark" else "sun"
            color = self.colors["accent"] if button.isChecked() else self.colors["muted"]
            if button.property("role") == "primary":
                color = self.colors["on_accent"]
            button.setIcon(icon(glyph, color))
        for widget, glyph in self.empty_icons:
            widget.setPixmap(icon(glyph, self.colors["accent"], 28).pixmap(28, 28))

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
            self.preference_feedback.setText("On this computer")
        except OSError:
            self.preference_feedback.setText("Could not save preferences")

    def closeEvent(self, event):
        self._save()
        super().closeEvent(event)
