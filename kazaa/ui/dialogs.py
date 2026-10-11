"""Preferences dialog + History dialog + About."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import i18n

AFTER_DONE = ["nothing", "exit", "shutdown", "restart", "logoff", "hibernate", "standby"]


class PreferencesDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(i18n.tr("prefs_title"))
        lay = QVBoxLayout(self)

        tabs = QTabWidget()
        # ---- General ----
        gen = QWidget()
        form = QFormLayout(gen)
        dir_row = QHBoxLayout()
        self.dir = QLineEdit(settings.get("save_to"))
        b = QPushButton(i18n.tr("browse"))
        b.clicked.connect(self._pick_dir)
        dir_row.addWidget(self.dir)
        dir_row.addWidget(b)
        form.addRow(i18n.tr("save_to"), dir_row)

        self.q = QComboBox()
        for v, lbl in [("best", i18n.tr("best")), ("1080", "1080p"), ("720", "720p"),
                       ("480", "480p"), ("360", "360p"), ("240", "240p"),
                       ("worst", "Worst")]:
            self.q.addItem(lbl, v)
        self.q.setCurrentIndex(max(0, [self.q.itemData(i) for i in range(self.q.count())]
                                   .index(settings.get("download_quality"))))
        form.addRow(i18n.tr("download_quality"), self.q)

        self.sim_dl = QSpinBox(); self.sim_dl.setRange(1, 10)
        self.sim_dl.setValue(int(settings.get("simultaneous_downloads")))
        form.addRow(i18n.tr("p_sim_dl"), self.sim_dl)

        self.sim_cv = QSpinBox(); self.sim_cv.setRange(1, 10)
        self.sim_cv.setValue(int(settings.get("simultaneous_converts")))
        form.addRow(i18n.tr("p_sim_cv"), self.sim_cv)

        self.after = QComboBox()
        for a in AFTER_DONE:
            self.after.addItem(i18n.tr(f"ad_{a}"), a)
        self.after.setCurrentIndex(AFTER_DONE.index(settings.get("after_done")))
        form.addRow(i18n.tr("after_done"), self.after)

        self.ytc = QComboBox()
        for v, lbl in [("", i18n.tr("p_yt_off")), ("chrome", i18n.tr("p_yt_chrome")),
                       ("edge", i18n.tr("p_yt_edge")),
                       ("firefox", i18n.tr("p_yt_firefox"))]:
            self.ytc.addItem(lbl, v)
        cur = settings.get("yt_cookies") or ""
        self.ytc.setCurrentIndex(max(0, [self.ytc.itemData(i)
                                         for i in range(self.ytc.count())]
                                      .index(cur)))
        form.addRow(i18n.tr("p_yt_cookies"), self.ytc)
        tabs.addTab(gen, i18n.tr("p_general"))

        # ---- Extensions ----
        ext = QWidget()
        ev = QVBoxLayout(ext)
        ev.addWidget(QLabel(i18n.tr("ext_desc")))
        root = self._project_root()
        for key, sub in [("ext_chrome", "extensions/chrome"),
                         ("ext_firefox", "extensions/firefox")]:
            row = QHBoxLayout()
            row.addWidget(QLabel(i18n.tr(key)))
            le = QLineEdit(f"{root}\\{sub}")
            le.setReadOnly(True)
            row.addWidget(le)
            ob = QPushButton(i18n.tr("open_folder"))
            ob.clicked.connect(lambda _, p=f"{root}\\{sub}": self._open(p))
            row.addWidget(ob)
            ev.addLayout(row)
        note = QLabel(i18n.tr("ext_note"))
        note.setWordWrap(True)
        ev.addWidget(note)
        ev.addStretch(1)
        tabs.addTab(ext, i18n.tr("p_ext"))

        lay.addWidget(tabs)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _project_root(self):
        import os
        return os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, i18n.tr("save_to"))
        if d:
            self.dir.setText(d)

    def _open(self, path):
        import os
        import subprocess
        os.makedirs(path, exist_ok=True)
        subprocess.Popen(["explorer", path])

    def accept(self):
        s = self.settings
        s.set("save_to", self.dir.text().strip())
        s.set("download_quality", self.q.currentData())
        s.set("simultaneous_downloads", self.sim_dl.value())
        s.set("simultaneous_converts", self.sim_cv.value())
        s.set("after_done", self.after.currentData())
        s.set("yt_cookies", self.ytc.currentData())
        s.save()
        super().accept()


class HistoryDialog(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("history_title"))
        self.resize(720, 420)
        lay = QVBoxLayout(self)
        cols = ["time", "kind", "name", "status", "size"]
        t = QTableWidget(len(history.items), len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        for r, it in enumerate(reversed(history.items)):
            for c, k in enumerate(cols):
                t.setItem(r, c, QTableWidgetItem(str(it.get(k, ""))[:90]))
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


class AboutDialog(QDialog):
    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("m_about"))
        lay = QVBoxLayout(self)
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt
        from ..rsrc import asset
        logo = QLabel()
        logo.setPixmap(QPixmap(asset("logo.png")).scaledToWidth(
            320, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        lay.addWidget(logo)
        tb = QTextBrowser()
        tb.setHtml(i18n.tr("about_text", ver=version).replace("\n", "<br>"))
        lay.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
