"""VLoader main window: menus, panes, task wiring."""
import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import afterdone, i18n
from ..bridgeserver import BridgeServer
from ..converter import ConvertWorker
from ..downloader import DownloadManager
from ..history import History
from ..settings import Settings
from .activity import ActivityPane
from .dialogs import AboutDialog, HistoryDialog, PreferencesDialog
from .panes import ConvertPane, DownloadPane
from .recorder_window import RecorderWindow

VERSION = "1.0.0"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        i18n.set_language(self.settings.get("language"))
        self.history = History()
        self.downloads = DownloadManager(self.settings, self)
        self.convert_workers = {}   # task_id -> worker
        self._conv_next = 100000
        self._pending_conv = []
        # per-submission options (set by DownloadPane; safe defaults for CLI)
        self._auto_conv_fmt = ""
        self._auto_conv_q = "normal"
        self._open_after = False

        self.setWindowTitle(i18n.tr("app_title"))
        self.resize(980, 640)
        geom = self.settings.get("window_geometry")
        if geom:
            self.restoreGeometry(bytes.fromhex(geom))

        # --- sidebar navigation + stacked pages ---
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(210)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()

        self.download_pane = DownloadPane(self.settings, self._submit_urls)
        self.activity = ActivityPane()
        self.convert_pane = ConvertPane(self.settings, self._submit_convert)
        pages = [("⬇  " + i18n.tr("tab_download"), self.download_pane),
                 ("≡  " + i18n.tr("tab_activity"), self.activity),
                 ("⇄  " + i18n.tr("tab_convert"), self.convert_pane)]
        for label, widget in pages:
            self.nav.addItem(QListWidgetItem(label))
            self.stack.addWidget(widget)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.nav)
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._pages = {"download": 0, "activity": 1, "convert": 2}

        self._build_menus()

        self.status_lbl = QLabel(i18n.tr("status_ready"))
        self.statusBar().addPermanentWidget(self.status_lbl)

        # wiring
        self.downloads.task_progress.connect(self._on_dl_progress)
        self.downloads.task_finished.connect(self._on_dl_finished)
        self.downloads.task_failed.connect(self._on_dl_failed)
        self.downloads.queue_changed.connect(self._refresh_status)

        self.bridge = BridgeServer()
        self.bridge.bridge.url_received.connect(self._url_from_extension)
        self.bridge.start()

    # ---- page switching -------------------------------------------------
    def set_page(self, index):
        self.nav.setCurrentRow(index)

    # ---- menus ----------------------------------------------------------
    def _build_menus(self):
        bar = self.menuBar()

        def menu(key):
            return bar.addMenu(i18n.tr(key))

        def act(m, key, slot, shortcut=None, enabled=True):
            a = QAction(i18n.tr(key), self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setEnabled(enabled)
            m.addAction(a)
            return a

        m = menu("menu_file")
        act(m, "m_add_url", lambda: self._focus_url(False), "Ctrl+O")
        act(m, "m_add_urls", lambda: self._focus_url(True), "Shift+O")
        act(m, "m_load_video", self._load_video, "Ctrl+Shift+O")
        m.addSeparator()
        act(m, "m_history", self._show_history, "Ctrl+H")
        act(m, "m_exit", self.close, "Alt+F4")

        m = menu("menu_edit")
        act(m, "m_check_all", self.activity.add_checkboxes)
        act(m, "m_uncheck_all", self._uncheck_all)
        act(m, "m_invert_check", self._invert_checks)
        act(m, "m_clear_all", self._clear_finished, "Shift+Del")

        m = menu("menu_download")
        act(m, "m_dl_checked", lambda: self._batch("download", True), "F5")
        act(m, "m_pause_checked", lambda: self._batch("pause", True), "F6")
        act(m, "m_stop_checked", lambda: self._batch("stop", True), "F7")
        act(m, "m_dl_all", lambda: self._batch("download", False), "Ctrl+F5")
        act(m, "m_pause_all", lambda: self._batch("pause", False), "Ctrl+F6")
        act(m, "m_stop_all", lambda: self._batch("stop", False), "Ctrl+F7")
        m.addSeparator()
        act(m, "m_open_url", self._open_selected_url, "Ctrl+U")
        act(m, "m_locate", self._locate_selected, "F8")
        act(m, "m_play", self._play_selected, "Ctrl+F8")

        m = menu("menu_option")
        act(m, "m_prefs", self._prefs)
        act(m, "m_recorder", self._recorder)
        ml = m.addMenu(i18n.tr("m_languages"))
        for code, name in i18n.languages().items():
            a = QAction(name, self, checkable=True)
            a.setChecked(code == self.settings.get("language"))
            a.triggered.connect(lambda _, c=code: self._set_language(c))
            ml.addAction(a)

        m = menu("menu_help")
        act(m, "m_about", self._about)

    # ---- download flow --------------------------------------------------
    def _focus_url(self, multiple):
        self.set_page(0)
        if multiple:
            self.download_pane.multi.setChecked(True)
        self.download_pane.url_edit.setFocus()

    def _submit_urls(self, urls, opts):
        if not urls:
            QMessageBox.information(self, i18n.tr("app_title"),
                                    i18n.tr("err_no_url"))
            return
        if opts.get("save_to"):
            self.settings.set("save_to", opts["save_to"])
            self.settings.save()
        if opts.get("quality"):
            self.settings.set("download_quality", opts["quality"])
        self._auto_conv_fmt = opts.get("auto_convert_to") or ""
        self._auto_conv_q = opts.get("conv_quality") or "normal"
        self._open_after = bool(opts.get("open_after"))
        subtitles = opts.get("subtitles")
        transcript_only = bool(opts.get("transcript_only")) and bool(subtitles)
        self.set_page(1)
        for url in urls:
            tid = self.downloads.submit(url, subtitles=subtitles,
                                        transcript_only=transcript_only)
            if tid:
                self.activity.add_task(tid, url, "download",
                                       subtitles=subtitles,
                                       transcript_only=transcript_only)
                self.history.add("download", name=url.split("/")[-1][:80], url=url, status="started")
        self._refresh_status()

    def _on_dl_progress(self, tid, info):
        self.activity.update_task(tid, info)

    def _on_dl_finished(self, tid, res):
        if res.get("stopped"):
            self.activity.set_done(tid, res.get("output", ""), stopped=True)
            self.history.update_last(status="stopped (saved)")
            self._maybe_after_done()
            return
        self.activity.set_done(tid, res.get("output", ""))
        self.history.update_last(status="done", output=res.get("output", ""),
                                 size=res.get("size", 0))
        from ..debuglog import log as dbg
        out = res.get("output", "")
        fmt = getattr(self, "_auto_conv_fmt", "")
        dbg(f"on_dl_finished tid={tid} out={out} auto_conv={fmt}")
        if fmt and out and not res.get("spotify"):
            meta = {"title": res.get("title"), "artist": res.get("artist"),
                    "year": res.get("year")}
            self._queue_convert(out, fmt, getattr(self, "_auto_conv_q", "normal"),
                                delete_original=self.settings.get(
                                    "delete_original_after_conversion"),
                                task_id=tid, meta=meta)
        elif self._open_after and out:
            self.locate_file(out)
        self._maybe_after_done()

    def _on_dl_failed(self, tid, msg):
        self.activity.set_error(tid, msg)
        self.history.update_last(status=msg[:40])
        self._maybe_after_done()

    # ---- convert flow ---------------------------------------------------
    def _load_video(self):
        fs, _ = QFileDialog.getOpenFileNames(
            self, i18n.tr("m_load_video"), "",
            "Video/Audio (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.ts *.m4v "
            "*.mp3 *.m4a *.wav *.flac *.ogg *.wma);;All files (*)")
        if fs:
            self.convert_pane.file_edit.setText(fs[0])
            self.set_page(2)

    def _submit_convert(self, opts):
        self.set_page(1)
        if (opts["src"].lower().endswith((".srt", ".vtt"))
                and opts["fmt"] in ("md", "srt", "vtt")):
            self._convert_transcript(opts)
            return
        self._queue_convert(opts["src"], opts["fmt"], opts["quality"],
                            trim_start=opts.get("trim_start"),
                            trim_end=opts.get("trim_end"),
                            volume=opts.get("volume"),
                            extra=opts.get("merge") or None,
                            delete_original=opts.get("delete_original", False))

    def _convert_transcript(self, opts):
        """Convert a .srt/.vtt transcript to md/srt/vtt (no ffmpeg needed)."""
        from .. import transcripts
        tid = self._conv_next
        self._conv_next += 1
        self.activity.add_task(tid, os.path.basename(opts["src"]), "convert")
        try:
            out = transcripts.convert(opts["src"], opts["fmt"])
            self.activity.set_done(tid, out)
            self.history.add("convert", os.path.basename(opts["src"]),
                             status="done", output=out)
        except Exception as e:  # noqa: BLE001
            self.activity.set_error(tid, f"{type(e).__name__}: {e}")
            self.history.add("convert", os.path.basename(opts["src"]),
                             status=str(e)[:40])
        self._maybe_after_done()

    def _queue_convert(self, src, fmt, quality, trim_start=None, trim_end=None,
                       volume=None, extra=None, delete_original=False,
                       task_id=None, meta=None):
        from ..debuglog import log as dbg
        dbg(f"_queue_convert src={src} fmt={fmt} task_id={task_id}")
        tid = task_id if task_id is not None else self._conv_next
        self._conv_next += 1
        self._pending_conv.append((tid, src, fmt, quality, trim_start, trim_end,
                                   volume, extra, delete_original, meta))
        dbg("queue: pre-add")
        if task_id is None:
            self.activity.add_task(tid, os.path.basename(src), "convert")
        else:
            self.activity.set_pending_convert(tid)
        dbg("queue: pre-history")
        self.history.add("convert", name=os.path.basename(src), status="started")
        dbg("queue: pre-pump")
        self._pump_converts()
        dbg("queue: post-pump")

    def _pump_converts(self):
        limit = max(1, int(self.settings.get("simultaneous_converts")))
        running = sum(1 for w in self.convert_workers.values() if w.isRunning())
        from ..debuglog import log as dbg
        dbg(f"_pump_converts pending={len(self._pending_conv)} running={running}")
        while self._pending_conv and running < limit:
            (tid, src, fmt, quality, ts, te, vol, extra, delo,
             meta) = self._pending_conv.pop(0)
            w = ConvertWorker(src, fmt, quality, ts, te, vol, extra, delo,
                              meta=meta)
            w.progress.connect(lambda info, i=tid: self.activity.update_task(i, info))
            w.finished_ok.connect(lambda res, i=tid, s=src: self._conv_done(i, res, s))
            w.failed.connect(lambda msg, i=tid: self._conv_failed(i, msg))
            self.convert_workers[tid] = w
            self.activity.update_task(tid, {"status": "converting", "percent": 0.0})
            w.start()
            running += 1

    def _conv_done(self, tid, res, src):
        from ..debuglog import log as dbg
        dbg(f"_conv_done tid={tid} out={res.get('output')}")
        self.convert_workers.pop(tid, None)
        if res.get("stopped"):
            self.activity.set_done(tid, res.get("output", ""), stopped=True)
            self.history.update_last(status="stopped (saved)")
            self._maybe_after_done()
            return
        self.activity.set_done(tid, res.get("output", ""))
        self.history.update_last(status="done", output=res.get("output", ""))
        self._pump_converts()
        self._maybe_after_done()

    def _conv_failed(self, tid, msg):
        self.convert_workers.pop(tid, None)
        self.activity.set_error(tid, msg)
        self.history.update_last(status=msg[:40])
        self._pump_converts()
        self._maybe_after_done()

    # ---- batch ops ------------------------------------------------------
    def _batch(self, op, checked_only):
        rows = self.activity.checked_or_selected_rows(checked_only)
        for row in rows:
            t = self.activity.rows.get(row)
            if not t:
                continue
            if op == "pause":
                self.downloads.cancel(t["id"])
                self.activity.set_error(t["id"], "cancelled")
            elif op == "stop":
                self.downloads.cancel(t["id"])
                w = self.convert_workers.get(t["id"])
                if w:
                    w.cancel()
                self.activity.set_error(t["id"], "cancelled")
            elif op == "download" and t["status"] in ("stopped", "error", "queued"):
                self.downloads.resume(t["id"], t["url"])
                self.activity.update_task(t["id"], {"status": "queued"})
        self._refresh_status()

    def pause_task(self, task_id):
        """Pause (non-live): keep partial file for resume."""
        self.downloads.cancel(task_id)
        self.activity.set_error(task_id, "cancelled")

    def stop_task(self, task_id):
        """Stop; for live streams the partial file is repaired and saved."""
        self.downloads.cancel(task_id)

    def resume_task(self, task_id):
        row = next((r for r, t in self.activity.rows.items()
                    if t["id"] == task_id), None)
        if row is None:
            return
        t = self.activity.rows[row]
        self.downloads.resume(task_id, t["url"], subtitles=t.get("subtitles"),
                              transcript_only=t.get("transcript_only", False))
        self.activity.update_task(task_id, {"status": "queued", "live": False})
        bar = self.activity.cellWidget(row, 2)
        if bar:
            bar.setRange(0, 100)
            bar.setValue(0)

    def open_task(self, task_id):
        row = next((r for r, t in self.activity.rows.items()
                    if t["id"] == task_id), None)
        if row is not None and self.activity.rows[row].get("output"):
            self.locate_file(self.activity.rows[row]["output"])

    def _uncheck_all(self):
        for r in range(self.activity.rowCount()):
            it = self.activity.item(r, 0)
            if it:
                it.setCheckState(Qt.Unchecked)

    def _invert_checks(self):
        for r in range(self.activity.rowCount()):
            it = self.activity.item(r, 0)
            if it:
                st = Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked
                it.setCheckState(st)

    def _clear_finished(self):
        for r in reversed(range(self.activity.rowCount())):
            t = self.activity.rows.get(r, {})
            if t.get("status") in ("done", "error", "stopped"):
                self.activity.removeRow(r)

    # ---- helpers --------------------------------------------------------
    def locate_file(self, path):
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def play_file(self, path):
        if os.path.exists(path):
            os.startfile(path) if sys.platform == "win32" else subprocess.Popen(["xdg-open", path])

    def open_url(self, url):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _open_selected_url(self):
        for r in self.activity.selectionModel().selectedRows():
            t = self.activity.rows.get(r.row())
            if t:
                self.open_url(t["url"])

    def _locate_selected(self):
        for r in self.activity.selectionModel().selectedRows():
            t = self.activity.rows.get(r.row())
            if t and t.get("output"):
                self.locate_file(t["output"])

    def _play_selected(self):
        for r in self.activity.selectionModel().selectedRows():
            t = self.activity.rows.get(r.row())
            if t and t.get("output"):
                self.play_file(t["output"])

    def _url_from_extension(self, url):
        self.set_page(1)
        tid = self.downloads.submit(url)
        if tid:
            self.activity.add_task(tid, url, "download")
            self.history.add("download", name=url.split("/")[-1][:80], url=url, status="started")

    # ---- dialogs / settings ----------------------------------------------
    def _prefs(self):
        PreferencesDialog(self.settings, self).exec()

    def _recorder(self):
        RecorderWindow(self.settings, self).exec()

    def _set_language(self, code):
        self.settings.set("language", code)
        self.settings.save()
        QMessageBox.information(self, i18n.tr("prefs_title"),
                                "Restart VLoader to apply the language.")

    def _show_history(self):
        HistoryDialog(self.history, self).exec()

    def _about(self):
        AboutDialog(VERSION, self).exec()

    def _refresh_status(self):
        n = self.activity.active_count()
        self.status_lbl.setText(i18n.tr("status_tasks", n=n) if n else i18n.tr("status_ready"))

    def _maybe_after_done(self):
        action = self.settings.get("after_done")
        if action == "nothing" or self.activity.active_count() > 0:
            return
        txt = afterdone.confirm_text(action)
        if txt:
            r = QMessageBox.question(self, i18n.tr("app_title"),
                                     i18n.tr("confirm_power", action=txt))
            if r != QMessageBox.Yes:
                return
        afterdone.perform(action)
        if action == "exit":
            QApplication.quit()

    def closeEvent(self, e):
        self.settings.set("window_geometry", bytes(self.saveGeometry().toHex()).decode())
        self.settings.save()
        self.bridge.stop()
        super().closeEvent(e)
