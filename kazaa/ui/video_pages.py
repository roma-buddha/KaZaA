"""Search and Downloaded pages for the local KaZaA video workflow."""
import base64
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..video_backend import (AUDIO_FORMATS, CAPTION_FORMATS, VIDEO_FORMATS,
                             DownloadOptions, parse_links)
from ..video_jobs import ACTIVE, Inspector
from .shell_icons import icon


def label(text, role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(True)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if primary:
        widget.setProperty("role", "primary")
    widget.clicked.connect(callback)
    return widget


def duration(seconds):
    if seconds is None:
        return ""
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class LinkInput(QPlainTextEdit):
    inspect_requested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.inspect_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class VideoCard(QFrame):
    selection_changed = Signal()
    download_requested = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.setProperty("role", "card")
        self.url, self.info = url, None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        self.selected = QCheckBox()
        self.selected.setAccessibleName("Select video")
        self.selected.setEnabled(False)
        self.selected.toggled.connect(self.selection_changed)
        layout.addWidget(self.selected)
        self.thumbnail = label("VIDEO", "muted")
        self.thumbnail.setObjectName("thumbnail")
        self.thumbnail.setFixedSize(112, 64)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.thumbnail)
        details = QVBoxLayout()
        details.setSpacing(5)
        self.title = label("Inspecting link…", "cardTitle")
        self.meta = label(url, "muted")
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status = label("", "muted")
        details.addWidget(self.title)
        details.addWidget(self.meta)
        details.addWidget(self.status)
        layout.addLayout(details, 1)
        actions = QVBoxLayout()
        self.download = button("Download", lambda: self.download_requested.emit(self.url))
        self.download.setEnabled(False)
        self.original = button("Open source", lambda: QDesktopServices.openUrl(QUrl(self.url)))
        self.original.setVisible(False)
        actions.addWidget(self.download)
        actions.addWidget(self.original)
        layout.addLayout(actions)

    def set_result(self, info, error=""):
        self.info = info if info else None
        self.title.setText(info.get("title", "Link unavailable") if info else "Link unavailable")
        if not info:
            self.status.setText(error)
            return
        self.meta.setText(" · ".join(str(value) for value in
                                     (info.get("creator"), info.get("site"), duration(info.get("duration"))) if value))
        self.selected.setAccessibleName("Select " + info["title"])
        self.selected.setEnabled(True)
        self.selected.setChecked(True)
        self.download.setEnabled(True)
        self.original.setVisible(True)
        self.status.setText("Captions available" if any(info.get("captions", {}).values()) else "No captions available")
        try:
            data = base64.b64decode(info.get("thumbnail_data", ""))
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data):
                self.thumbnail.setPixmap(pixmap.scaled(112, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except ValueError:
            pass


class SearchPage(QScrollArea):
    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.queue = queue
        self.inspector = Inspector(self)
        self.cards = {}
        self.current_input = True
        self._updating = True
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)
        layout.addWidget(label("Search", "pageTitle"))
        input_panel = QFrame()
        input_panel.setProperty("role", "panel")
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(16, 16, 16, 14)
        input_layout.setSpacing(12)
        self.input = LinkInput()
        self.input.setPlaceholderText("Paste one or more video links")
        self.input.setAccessibleName("Video links; Enter to inspect, Shift+Enter for another line")
        self.input.setFixedHeight(66)
        self.input.inspect_requested.connect(self.inspect)
        self.input.textChanged.connect(self._input_changed)
        input_layout.addWidget(self.input)
        action_row = QHBoxLayout()
        self.options_toggle = button("Download options", self._toggle_options)
        self.options_toggle.setIcon(icon("chevron_right", "#91887c", 14))
        self.options_toggle.setCheckable(True)
        self.summary = label("Video · MP4 · Best available", "muted")
        action_row.addWidget(self.options_toggle)
        action_row.addWidget(self.summary, 1)
        self.inspect_button = button("Inspect", self.inspect, True)
        action_row.addWidget(self.inspect_button)
        input_layout.addLayout(action_row)
        self.options_panel = QWidget()
        grid = QGridLayout(self.options_panel)
        grid.setContentsMargins(0, 10, 0, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.kind = QComboBox()
        for title, value in (("Video", "video"), ("Audio", "audio"), ("Transcript / subtitles", "transcript")):
            self.kind.addItem(title, value)
        self.format = QComboBox()
        self.quality = QComboBox()
        for column, (title, widget) in enumerate((("Download as", self.kind), ("Format", self.format), ("Quality", self.quality))):
            grid.addWidget(label(title, "muted"), 0, column)
            widget.setAccessibleName(title)
            grid.addWidget(widget, 1, column)
            grid.setColumnStretch(column, 1)
        self.add_captions = QCheckBox("Include captions")
        grid.addWidget(self.add_captions, 2, 0, 1, 3)
        self.caption_fields = QWidget()
        captions_grid = QGridLayout(self.caption_fields)
        self.captions_grid = captions_grid
        captions_grid.setContentsMargins(0, 0, 0, 0)
        captions_grid.setHorizontalSpacing(12)
        self.caption_source = QComboBox()
        self.caption_source.addItem("Creator-provided", "manual")
        self.caption_source.addItem("Automatically generated", "automatic")
        self.language = QComboBox()
        self.caption_format = QComboBox()
        self._fill(self.caption_format, [(fmt.upper() if fmt != "md" else "Markdown", fmt) for fmt in CAPTION_FORMATS])
        for column, (title, widget) in enumerate((("Caption source", self.caption_source), ("Language", self.language), ("Caption format", self.caption_format))):
            field_label = label(title, "muted")
            if widget is self.caption_format:
                self.caption_format_label = field_label
            captions_grid.addWidget(field_label, 0, column)
            widget.setAccessibleName(title)
            captions_grid.addWidget(widget, 1, column)
            captions_grid.setColumnStretch(column, 1)
        grid.addWidget(self.caption_fields, 3, 0, 1, 3)
        grid.addWidget(label("Save to", "muted"), 4, 0, 1, 3)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(str(Path.home() / "Videos" / "KaZaA"))
        self.folder.setAccessibleName("Save folder")
        self.folder.setMinimumWidth(0)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(button("Browse…", self._browse))
        grid.addLayout(folder_row, 5, 0, 1, 3)
        input_layout.addWidget(self.options_panel)
        self.options_panel.hide()
        layout.addWidget(input_panel)
        self.notice = label("", "muted")
        self.notice.hide()
        layout.addWidget(self.notice)
        results_row = QHBoxLayout()
        self.results_label = label("", "muted")
        results_row.addWidget(self.results_label, 1)
        self.download_selected = button("Download selected", self._download_selected, True)
        self.download_selected.setEnabled(False)
        self.download_selected.hide()
        results_row.addWidget(self.download_selected)
        layout.addLayout(results_row)
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(12)
        layout.addLayout(self.cards_layout)
        self.empty = label("Paste a video link to get started.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setContentsMargins(0, 65, 0, 65)
        layout.addWidget(self.empty)
        layout.addStretch()
        self._updating = False
        self._refresh_options()
        self._restore_options(queue.options)
        for combo in (self.kind, self.format, self.quality, self.caption_source, self.language, self.caption_format):
            combo.currentIndexChanged.connect(self._options_changed)
        self.add_captions.toggled.connect(self._options_changed)
        self.folder.editingFinished.connect(self._options_changed)
        self.inspector.item_ready.connect(self._inspected)
        self.inspector.busy_changed.connect(self._busy)
        queue.notice.connect(self.show_notice)

    def _restore_options(self, saved):
        self._updating = True
        for combo, key in ((self.kind, "kind"),):
            index = combo.findData(saved.get(key))
            if index >= 0:
                combo.setCurrentIndex(index)
        self._updating = False
        self._refresh_options()
        self._updating = True
        for combo, key in ((self.format, "format"), (self.caption_format, "caption_format"), (self.caption_source, "caption_source")):
            index = combo.findData(saved.get(key))
            if index >= 0:
                combo.setCurrentIndex(index)
        self.add_captions.setChecked(saved.get("captions") is True)
        if isinstance(saved.get("folder"), str) and saved["folder"]:
            self.folder.setText(saved["folder"])
        self._updating = False
        self._refresh_options()

    def show_notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _toggle_options(self):
        expanded = self.options_toggle.isChecked()
        self.options_panel.setVisible(expanded)
        self.options_toggle.setIcon(icon("chevron_down" if expanded else "chevron_right", "#91887c", 14))

    def _input_changed(self):
        self.input.setFixedHeight(min(132, max(66, self.input.document().blockCount() * 23 + 24)))
        self.current_input = False
        self.inspector.stop()
        for card in self.cards.values():
            card.download.setEnabled(False)
        self.download_selected.setEnabled(False)

    def inspect(self):
        entries = parse_links(self.input.toPlainText())
        if not entries:
            self.show_notice("Paste a video link first.")
            return
        self.show_notice("")
        self.current_input = True
        for card in self.cards.values():
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        for entry in entries:
            card = VideoCard(entry["url"])
            card.selection_changed.connect(self._selection_changed)
            card.download_requested.connect(self._download_one)
            self.cards[entry["url"]] = card
            self.cards_layout.addWidget(card)
            if entry["error"]:
                card.set_result({}, entry["error"])
        self.empty.hide()
        self.download_selected.show()
        self.results_label.setText(f"{len(entries)} link{'s' if len(entries) != 1 else ''}")
        self.inspector.inspect([entry["url"] for entry in entries if not entry["error"]])
        self._selection_changed()

    def _busy(self, busy):
        self.inspect_button.setText("Inspect again" if busy else "Inspect")

    def _inspected(self, generation, url, info, error):
        if url in self.cards and self.current_input:
            self.cards[url].set_result(info, error)
            self._selection_changed()

    def _selected(self):
        return [card for card in self.cards.values() if card.info and card.selected.isChecked()]

    def _selection_changed(self):
        count = len(self._selected())
        self.download_selected.setEnabled(bool(count) and self.current_input)
        self.download_selected.setText(f"Download selected · {count}" if count else "Download selected")
        self._refresh_options()

    @staticmethod
    def _fill(combo, items):
        previous = combo.currentData()
        combo.clear()
        for title, value in items:
            combo.addItem(title, value)
        found = combo.findData(previous)
        if found >= 0:
            combo.setCurrentIndex(found)

    def _refresh_options(self):
        if self._updating:
            return
        self._updating = True
        kind = self.kind.currentData()
        formats = {"video": VIDEO_FORMATS, "audio": AUDIO_FORMATS, "transcript": CAPTION_FORMATS}[kind]
        self._fill(self.format, [(fmt.upper() if fmt != "md" else "Markdown", fmt) for fmt in formats])
        infos = [card.info for card in self._selected()]
        if kind == "video":
            heights = sorted({height for info in infos for height in info.get("heights", [])}, reverse=True)
            qualities = [("Best available", "best")] + [(f"{height}p", str(height)) for height in heights]
        elif kind == "audio" and self.format.currentData() not in ("wav", "flac"):
            qualities = [("Best available", "best")] + [(f"{rate} kbps", rate) for rate in ("320", "256", "192", "128")]
        else:
            qualities = [("Not applicable" if kind == "transcript" else "Source quality", "best")]
        self._fill(self.quality, qualities)
        self.quality.setEnabled(kind != "transcript" and not (kind == "audio" and self.format.currentData() in ("wav", "flac")))
        self.add_captions.setVisible(kind != "transcript")
        self.caption_fields.setVisible(kind == "transcript" or self.add_captions.isChecked())
        self.caption_format.setVisible(kind != "transcript")
        self.caption_format_label.setVisible(kind != "transcript")
        self.captions_grid.setColumnStretch(2, 0 if kind == "transcript" else 1)
        if infos and not any(info.get("captions", {}).get("manual") for info in infos) and any(info.get("captions", {}).get("automatic") for info in infos):
            self.caption_source.setCurrentIndex(self.caption_source.findData("automatic"))
        source = self.caption_source.currentData()
        languages = {}
        for info in infos:
            languages.update(info.get("captions", {}).get(source, {}))
        pairs = [(f"{name} ({code})" if name != code else code, code) for code, name in sorted(languages.items(), key=lambda pair: (pair[0] != "en", pair[0]))]
        self._fill(self.language, pairs or [("No captions available", "")])
        self._updating = False
        self.summary.setText(f"{self.kind.currentText().split(' /')[0]} · {self.format.currentText()} · {self.quality.currentText()}")

    def _options_changed(self):
        if self._updating:
            return
        self._refresh_options()
        self.queue.set_options(self.options().to_dict())

    def options(self):
        return DownloadOptions(kind=self.kind.currentData(), format=self.format.currentData(),
                               quality=self.quality.currentData(), captions=self.add_captions.isChecked(),
                               caption_format=self.caption_format.currentData(), language=self.language.currentData(),
                               caption_source=self.caption_source.currentData(), folder=self.folder.text().strip())

    def _browse(self):
        selected = QFileDialog.getExistingDirectory(self, "Save downloads to", self.folder.text())
        if selected:
            self.folder.setText(selected)
            self._options_changed()

    def _download_one(self, url):
        if self.current_input and self.cards[url].info:
            self._enqueue([self.cards[url]])

    def _download_selected(self):
        self._enqueue(self._selected())

    def _enqueue(self, cards):
        options = self.options()
        queued = 0
        for card in cards:
            try:
                self.queue.submit(card.info, options)
                card.status.setText("Added to Downloaded")
                queued += 1
            except (OSError, ValueError) as exc:
                card.status.setText(str(exc))
        if queued:
            self.queue.set_options(options.to_dict())
            self.show_notice(f"{queued} download{'s' if queued != 1 else ''} added. Follow progress in Downloaded.")


class JobCard(QFrame):
    def __init__(self, queue, job):
        super().__init__()
        self.queue, self.job = queue, job
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        row = QHBoxLayout()
        titles = QVBoxLayout()
        self.title = label("", "cardTitle")
        self.details = label("", "muted")
        titles.addWidget(self.title)
        titles.addWidget(self.details)
        row.addLayout(titles, 1)
        self.cancel_button = button("Cancel", lambda: queue.cancel(self.job["id"]))
        self.retry_button = button("Retry", lambda: queue.retry(self.job["id"]))
        row.addWidget(self.cancel_button)
        row.addWidget(self.retry_button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)
        self.error = label("", "error")
        layout.addWidget(self.error)
        file_row = QHBoxLayout()
        self.files = QComboBox()
        self.files.setAccessibleName("Downloaded file")
        self.files.setMinimumWidth(0)
        file_row.addWidget(self.files, 1)
        self.open_button = button("Open file", lambda: self._open(False))
        self.locate_button = button("Show in folder", lambda: self._open(True))
        file_row.addWidget(self.open_button)
        file_row.addWidget(self.locate_button)
        layout.addLayout(file_row)
        self.update_job(job)

    def update_job(self, job):
        self.job = job
        options, status = job["options"], job["status"]
        self.title.setText(job.get("title", job["url"]))
        quality = options.get("quality", "best")
        quality = "Best available" if quality == "best" else quality + ("p" if options["kind"] == "video" else " kbps")
        details = f"{options['kind'].title()} · {options['format'].upper()} · {quality} · {status.title()}"
        if status == "downloading":
            if job.get("speed"):
                details += f" · {job['speed'] / 1024 / 1024:.1f} MB/s"
            if job.get("eta") is not None:
                details += f" · {duration(job['eta'])} remaining"
        self.details.setText(details)
        self.cancel_button.setVisible(status in ACTIVE)
        self.cancel_button.setEnabled(status != "cancelling")
        self.retry_button.setVisible(status in ("failed", "cancelled", "interrupted"))
        self.error.setText(job.get("error", ""))
        self.error.setVisible(bool(job.get("error")))
        self.progress.setVisible(status in ACTIVE)
        percent = job.get("percent")
        self.progress.setRange(0, 0 if percent is None else 100)
        if percent is not None:
            self.progress.setValue(round(percent))
        self.progress.setAccessibleName(f"{status.title()} progress")
        self.files.clear()
        for path in job.get("files", []):
            self.files.addItem(Path(path).name, path)
        completed = status == "completed"
        for widget in (self.files, self.open_button, self.locate_button):
            widget.setVisible(completed)

    def _open(self, folder):
        path = Path(self.files.currentData() or "")
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))
        else:
            self.error.setText("This file is no longer at its saved location.")
            self.error.show()


class DownloadedPage(QScrollArea):
    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.queue = queue
        self.cards = {}
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(18)
        layout.addWidget(label("Downloaded", "pageTitle"))
        self.empty = label("Your downloads will appear here.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setContentsMargins(0, 90, 0, 90)
        layout.addWidget(self.empty)
        self.active_heading = label("Queue", "sectionTitle")
        self.completed_heading = label("Completed", "sectionTitle")
        layout.addWidget(self.active_heading)
        self.active_layout = QVBoxLayout()
        self.active_layout.setSpacing(12)
        layout.addLayout(self.active_layout)
        layout.addWidget(self.completed_heading)
        self.completed_layout = QVBoxLayout()
        self.completed_layout.setSpacing(12)
        layout.addLayout(self.completed_layout)
        layout.addStretch()
        queue.changed.connect(self.update_job)
        for job in sorted(queue.jobs.values(), key=lambda job: job.get("created", 0), reverse=True):
            self.update_job(job["id"], job)
        self._headings()

    def update_job(self, job_id, job):
        if job_id not in self.cards:
            self.cards[job_id] = JobCard(self.queue, job)
        card = self.cards[job_id]
        card.update_job(job)
        target = self.completed_layout if job["status"] == "completed" else self.active_layout
        if target.indexOf(card) < 0:
            self.active_layout.removeWidget(card)
            self.completed_layout.removeWidget(card)
            target.insertWidget(0, card)
        self._headings()

    def _headings(self):
        self.empty.setVisible(not self.cards)
        self.active_heading.setVisible(self.active_layout.count() > 0)
        self.completed_heading.setVisible(self.completed_layout.count() > 0)
