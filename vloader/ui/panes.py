"""Download and Convert panes."""
import os

from PySide6.QtCore import Qt, QThread, QTime, QUrl, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QPushButton,
                               QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from .. import i18n
from ..converter import ALL_FORMATS, AUDIO_FORMATS
from ..downloader import is_bot_check
from ..music import PreviewFetcher

TRANSCRIPT_FORMATS = ["md", "srt", "vtt"]

QUALITIES = ["best", "1080", "720", "480", "360", "240", "worst"]


class DownloadPane(QWidget):
    """URL input + download options (the 'Download Pane')."""

    def __init__(self, settings, on_submit):
        super().__init__()
        self.settings = settings
        self.on_submit = on_submit

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        h = QLabel(i18n.tr("tab_download"))
        h.setObjectName("h1")
        lay.addWidget(h)
        lay.addWidget(QLabel(i18n.tr("url_box")))
        self.multi = QRadioButton(i18n.tr("multiple_urls"))
        self.multi.setChecked(False)
        self.multi.setObjectName("dim")
        lay.addWidget(self.multi)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://...  —  Spotify, magnet link or .torrent also work")
        self.url_edit.returnPressed.connect(self._submit)
        lay.addWidget(self.url_edit)

        row = QHBoxLayout()
        self.paste_btn = QPushButton(i18n.tr("paste_url"))
        self.paste_btn.setProperty("variant", "ghost")
        self.paste_btn.clicked.connect(self._paste)
        row.addWidget(self.paste_btn)
        row.addStretch(1)
        lay.addLayout(row)

        form = QFormLayout()
        self.quality = QComboBox()
        for q in QUALITIES:
            label = i18n.tr("best") if q == "best" else (
                "Worst" if q == "worst" else f"{q}p")
            self.quality.addItem(label, q)
        self.quality.setCurrentIndex(0)
        form.addRow(i18n.tr("download_quality"), self.quality)

        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(settings.get("save_to"))
        self.dir_edit.setPlaceholderText(settings.download_dir())
        b = QPushButton(i18n.tr("browse"))
        b.clicked.connect(self._pick_dir)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(b)
        form.addRow(i18n.tr("save_to"), dir_row)

        self.auto_conv = QComboBox()
        self.auto_conv.addItem("(off)", "")
        for f in ALL_FORMATS:
            self.auto_conv.addItem(f.upper(), f)
        cur = settings.get("auto_convert_to")
        idx = self.auto_conv.findData(cur)
        self.auto_conv.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(i18n.tr("auto_convert"), self.auto_conv)

        self.conv_quality = QComboBox()
        for q in ("high", "normal", "low"):
            self.conv_quality.addItem(i18n.tr(q), q)
        self.conv_quality.setCurrentIndex(1)
        form.addRow(i18n.tr("conv_quality"), self.conv_quality)

        self.spot_fmt = QComboBox()
        for label, v in (("MP3 · 320 kbps", "mp3"),
                         ("FLAC · lossless", "flac"),
                         ("WAV · lossless", "wav")):
            self.spot_fmt.addItem(label, v)
        cur = settings.get("spotify_format")
        idx = self.spot_fmt.findData(cur)
        self.spot_fmt.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(i18n.tr("spotify_format"), self.spot_fmt)

        self.open_after = QCheckBox(i18n.tr("open_folder_after"))
        form.addRow("", self.open_after)

        self.sub_fmt = QComboBox()
        self.sub_fmt.addItem("(off)", "")
        for f in ("md", "srt", "vtt"):
            label = {"md": "Markdown (.md)", "srt": "SubRip (.srt)",
                     "vtt": "WebVTT (.vtt)"}[f]
            self.sub_fmt.addItem(label, f)
        form.addRow(i18n.tr("subtitles"), self.sub_fmt)

        self.sub_langs = QLineEdit()
        self.sub_langs.setPlaceholderText("en, de, ru ...")
        form.addRow(i18n.tr("sub_langs"), self.sub_langs)

        self.sub_auto = QCheckBox(i18n.tr("sub_auto"))
        self.sub_auto.setChecked(True)
        form.addRow("", self.sub_auto)

        self.sub_only = QCheckBox(i18n.tr("transcript_only"))
        self.sub_only.setEnabled(False)
        form.addRow("", self.sub_only)
        self.sub_fmt.currentIndexChanged.connect(
            lambda _i: self.sub_only.setEnabled(bool(self.sub_fmt.currentData())))
        lay.addLayout(form)

        self.start_btn = QPushButton(i18n.tr("start_download"))
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.clicked.connect(self._submit)
        lay.addWidget(self.start_btn)
        lay.addStretch(1)

    def _paste(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)
            self.multi.setChecked("\n" in text or text.count("http") > 1)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, i18n.tr("save_to"),
                                             self.dir_edit.text() or os.path.expanduser("~"))
        if d:
            self.dir_edit.setText(d)

    def _submit(self):
        urls = [u.strip() for u in self.url_edit.text().replace("\r", "").split("\n")
                if u.strip()]
        if not urls:
            urls = [u.strip() for u in self.url_edit.text().split() if "://" in u]
        sub_fmt = self.sub_fmt.currentData()
        subtitles = None
        if sub_fmt:
            langs = [l.strip() for l in self.sub_langs.text().split(",")
                     if l.strip()] or ["en"]
            subtitles = {"format": sub_fmt, "langs": langs,
                         "auto": self.sub_auto.isChecked()}
        opts = {
            "quality": self.quality.currentData(),
            "save_to": self.dir_edit.text().strip(),
            "auto_convert_to": self.auto_conv.currentData(),
            "conv_quality": self.conv_quality.currentData(),
            "spotify_format": self.spot_fmt.currentData(),
            "open_after": self.open_after.isChecked(),
            "subtitles": subtitles,
            "transcript_only": self.sub_only.isChecked() and bool(sub_fmt),
        }
        self.on_submit(urls, opts)


class ConvertPane(QWidget):
    """File conversion: format, quality, trim, volume, merge."""

    def __init__(self, settings, on_convert):
        super().__init__()
        self.settings = settings
        self.on_convert = on_convert

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        h = QLabel(i18n.tr("tab_convert"))
        h.setObjectName("h1")
        lay.addWidget(h)
        form = QFormLayout()

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        b = QPushButton(i18n.tr("browse_file"))
        b.clicked.connect(self._pick_file)
        file_row.addWidget(self.file_edit)
        file_row.addWidget(b)
        form.addRow(i18n.tr("browse_file"), file_row)

        self.fmt = QComboBox()
        for f in ALL_FORMATS + TRANSCRIPT_FORMATS:
            self.fmt.addItem(f.upper(), f)
        self.fmt.setCurrentIndex(0)
        form.addRow(i18n.tr("convert_to"), self.fmt)

        self.quality = QComboBox()
        for q in ("high", "normal", "low"):
            self.quality.addItem(i18n.tr(q), q)
        self.quality.setCurrentIndex(1)
        form.addRow(i18n.tr("conv_quality"), self.quality)

        adv = QGroupBox(i18n.tr("cut_video"))
        adv_lay = QFormLayout(adv)
        self.cut_check = QCheckBox(i18n.tr("cut_video"))
        self.start_t = QTimeEdit(QTime(0, 0, 0))
        self.end_t = QTimeEdit(QTime(0, 1, 0))
        adv_lay.addRow(self.cut_check)
        adv_lay.addRow(i18n.tr("start_time"), self.start_t)
        adv_lay.addRow(i18n.tr("end_time"), self.end_t)
        lay.addLayout(form)
        lay.addWidget(adv)

        vol_row = QHBoxLayout()
        self.vol_check = QCheckBox(i18n.tr("volume"))
        self.vol_spin = QDoubleSpinBox()
        self.vol_spin.setRange(0.1, 5.0)
        self.vol_spin.setValue(1.5)
        self.vol_spin.setSingleStep(0.1)
        vol_row.addWidget(self.vol_check)
        vol_row.addWidget(self.vol_spin)
        vol_row.addStretch(1)
        lay.addLayout(vol_row)

        merge_box = QGroupBox(i18n.tr("merge_files"))
        ml = QVBoxLayout(merge_box)
        self.merge_list = QListWidget()
        ab = QPushButton(i18n.tr("add_file"))
        ab.clicked.connect(self._add_merge_file)
        db = QPushButton("Remove")
        db.clicked.connect(lambda: [self.merge_list.takeItem(i.row())
                                      for i in self.merge_list.selectedIndexes()])
        ml.addWidget(self.merge_list)
        mr = QHBoxLayout()
        mr.addWidget(ab); mr.addWidget(db); mr.addStretch(1)
        ml.addLayout(mr)
        lay.addWidget(merge_box)

        self.del_orig = QCheckBox(i18n.tr("del_after"))
        lay.addWidget(self.del_orig)

        self.start_btn = QPushButton(i18n.tr("start_convert"))
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.clicked.connect(self._go)
        lay.addWidget(self.start_btn)
        lay.addStretch(1)

    def _pick_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("browse_file"), "",
            "Video/Audio (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.ts *.m4v "
            "*.mp3 *.m4a *.wav *.flac *.ogg *.wma);;All files (*)")
        if f:
            self.file_edit.setText(f)

    def _add_merge_file(self):
        fs, _ = QFileDialog.getOpenFileNames(
            self, i18n.tr("add_file"), "",
            "Video/Audio (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.ts *.m4v "
            "*.mp3 *.m4a *.wav *.flac *.ogg *.wma);;All files (*)")
        for f in fs:
            self.merge_list.addItem(f)

    @staticmethod
    def _t2s(t: QTime):
        return t.hour() * 3600 + t.minute() * 60 + t.second()

    def _go(self):
        src = self.file_edit.text().strip()
        if not src:
            return
        self.on_convert({
            "src": src,
            "fmt": self.fmt.currentData(),
            "quality": self.quality.currentData(),
            "trim_start": self._t2s(self.start_t) if self.cut_check.isChecked() else None,
            "trim_end": self._t2s(self.end_t) if self.cut_check.isChecked() else None,
            "volume": self.vol_spin.value() if self.vol_check.isChecked() else None,
            "merge": [self.merge_list.item(i).text()
                      for i in range(self.merge_list.count())],
            "delete_original": self.del_orig.isChecked(),
        })


class _MusicSearchWorker(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, query, parent=None, settings=None):
        super().__init__(parent)
        self.query = query
        self.settings = settings

    def run(self):
        from .. import music
        try:
            self.done.emit(music.search(self.query, settings=self.settings))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class MusicPane(QWidget):
    """Search YouTube music: clean list, 20s preview, mp3 download."""

    def __init__(self, on_download, parent=None, settings=None):
        super().__init__(parent)
        self.on_download = on_download
        self.settings = settings
        self._results = []
        self._search_worker = None
        self._fetcher = None
        self._preview_row = None       # row currently previewing (-1 = none)
        self._preview_btns = {}        # row -> button
        self._preview_files = []

        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.8)
        self._player.setAudioOutput(self._audio)
        self._player.mediaStatusChanged.connect(self._media_status)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        h = QLabel(i18n.tr("tab_music"))
        h.setObjectName("h1")
        lay.addWidget(h)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(i18n.tr("music_search_ph"))
        self.search_edit.returnPressed.connect(self._search)
        row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton(i18n.tr("music_search"))
        self.search_btn.clicked.connect(self._search)
        row.addWidget(self.search_btn)
        lay.addLayout(row)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("dim")
        lay.addWidget(self.status_lbl)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            i18n.tr("music_col_title"), i18n.tr("music_col_channel"),
            i18n.tr("music_col_length"), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 210)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

    # ---- search ----------------------------------------------------------
    def _search(self):
        query = self.search_edit.text().strip()
        if not query or (self._search_worker and self._search_worker.isRunning()):
            return
        self._stop_preview()
        self.status_lbl.setText(i18n.tr("music_searching"))
        self.search_btn.setEnabled(False)
        self._search_worker = _MusicSearchWorker(query, self, self.settings)
        self._search_worker.done.connect(self._show_results)
        self._search_worker.failed.connect(self._search_failed)
        self._search_worker.start()

    def _search_failed(self, msg):
        self.search_btn.setEnabled(True)
        if is_bot_check(msg):
            self.status_lbl.setText(i18n.tr("music_bot_hint"))
        else:
            self.status_lbl.setText(i18n.tr("music_failed", msg=msg))

    def _show_results(self, results):
        self.search_btn.setEnabled(True)
        self._results = results
        self.table.setRowCount(0)
        self._preview_btns = {}
        if not results:
            self.status_lbl.setText(i18n.tr("music_none"))
            return
        self.status_lbl.setText(i18n.tr("music_found", n=len(results)))
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["title"]))
            self.table.setItem(row, 1, QTableWidgetItem(r["artist"]))
            self.table.setItem(row, 2, QTableWidgetItem(self._fmt_len(
                r["duration"])))
            btns = QWidget()
            bl = QHBoxLayout(btns)
            bl.setContentsMargins(4, 2, 4, 2)
            bl.setSpacing(6)
            prev = QPushButton(i18n.tr("music_preview"))
            prev.setFixedWidth(88)
            prev.clicked.connect(lambda _, x=row: self._toggle_preview(x))
            dl = QPushButton(i18n.tr("music_download"))
            dl.setFixedWidth(88)
            dl.clicked.connect(lambda _, res=r: self.on_download(res))
            bl.addStretch(1)
            bl.addWidget(prev)
            bl.addWidget(dl)
            self.table.setCellWidget(row, 3, btns)
            self._preview_btns[row] = prev

    @staticmethod
    def _fmt_len(sec):
        if not sec:
            return ""
        return f"{sec // 60}:{sec % 60:02d}"

    # ---- preview ---------------------------------------------------------
    def _toggle_preview(self, row):
        if self._preview_row == row:
            self._stop_preview()
            return
        if row >= len(self._results):
            return
        self._stop_preview()
        self.status_lbl.setText(i18n.tr("music_previewing"))
        self._fetcher = PreviewFetcher(
            self._results[row]["url"], self, settings=self.settings)
        self._fetcher.done.connect(lambda p, x=row: self._play_preview(x, p))
        self._fetcher.failed.connect(self._preview_failed)
        self._fetcher.start()
        self._preview_row = row

    def _play_preview(self, row, path):
        self._preview_files.append(path)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        if row in self._preview_btns:
            self._preview_btns[row].setText(i18n.tr("music_stop"))
        self.status_lbl.setText(i18n.tr("music_preview_hint"))

    def _preview_failed(self, msg):
        self.status_lbl.setText(i18n.tr("music_failed", msg=msg))
        self._preview_row = None

    def _media_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status in (QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia):
            self._stop_preview()

    def _stop_preview(self):
        self._player.stop()
        if self._fetcher and self._fetcher.isRunning():
            self._fetcher.terminate()
            self._fetcher.wait(2000)
        self._fetcher = None
        if self._preview_row in self._preview_btns:
            self._preview_btns[self._preview_row].setText(
                i18n.tr("music_preview"))
        self._preview_row = None

    def cleanup(self):
        """Delete temp preview files (called on main window close)."""
        self._stop_preview()
        for p in self._preview_files:
            try:
                os.remove(p)
            except OSError:
                pass
        self._preview_files = []
