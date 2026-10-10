"""Download and Convert panes."""
import os

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QRadioButton,
                               QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from .. import i18n
from ..converter import ALL_FORMATS, AUDIO_FORMATS

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
            "https://...  —  or a Spotify track / album / playlist link")
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
