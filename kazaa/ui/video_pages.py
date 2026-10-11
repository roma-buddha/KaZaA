"""Centered search results and download tables for KaZaA."""
import base64
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMenu, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from ..video_backend import AUDIO_FORMATS, CAPTION_FORMATS, VIDEO_FORMATS, DownloadOptions, parse_links
from ..video_jobs import ACTIVE, Inspector


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


def save_folder(queue):
    return queue.options.get("folder") or str(Path.home() / "Videos" / "KaZaA")


def file_size(value):
    if value is None:
        return "—"
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


class CenteredPage(QScrollArea):
    def __init__(self, fraction, parent=None):
        super().__init__(parent)
        self.fraction = fraction
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        self.setWidget(body)
        outer = QHBoxLayout(body)
        outer.setContentsMargins(0, 32, 0, 32)
        self.content = QWidget()
        self.content.setObjectName("pageContent")
        outer.addStretch()
        outer.addWidget(self.content, 0, Qt.AlignTop)
        outer.addStretch()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(24)
        self._fit_width()

    def _fit_width(self):
        width = self.viewport().width()
        self.content.setFixedWidth(max(300, int(width * self.fraction if width >= 850 else width - 48)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_width()


class LinkInput(QPlainTextEdit):
    inspect_requested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.inspect_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class ResultOptions(QWidget):
    changed = Signal()

    def __init__(self, queue):
        super().__init__()
        self.queue, self.info, self._updating = queue, {}, True
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(7)
        self.kind, self.format, self.quality = QComboBox(), QComboBox(), QComboBox()
        for title, value in (("Video", "video"), ("Audio", "audio"), ("Transcript", "transcript")):
            self.kind.addItem(title, value)
        for column, (title, widget) in enumerate((("Download as", self.kind), ("Format", self.format), ("Quality", self.quality))):
            heading = label(title, "muted")
            if widget is self.quality:
                self.quality_label = heading
            self.grid.addWidget(heading, 0, column)
            widget.setAccessibleName(title)
            widget.setMinimumWidth(0)
            self.grid.addWidget(widget, 1, column)
            self.grid.setColumnStretch(column, 1)
        self.caption_fields = QWidget()
        captions_grid = QGridLayout(self.caption_fields)
        captions_grid.setContentsMargins(0, 8, 0, 0)
        captions_grid.setHorizontalSpacing(12)
        captions_grid.setVerticalSpacing(7)
        self.caption_source, self.language = QComboBox(), QComboBox()
        self.caption_source.addItem("Creator-provided", "manual")
        self.caption_source.addItem("Automatic", "automatic")
        for column, (title, widget) in enumerate((("Caption source", self.caption_source), ("Language", self.language))):
            captions_grid.addWidget(label(title, "muted"), 0, column)
            widget.setAccessibleName(title)
            widget.setMinimumWidth(0)
            captions_grid.addWidget(widget, 1, column)
            captions_grid.setColumnStretch(column, 1)
        self.grid.addWidget(self.caption_fields, 2, 0, 1, 3)
        self._updating = False
        self._refresh()
        for combo in (self.kind, self.format, self.quality, self.caption_source, self.language):
            combo.currentIndexChanged.connect(self._changed)

    @staticmethod
    def _fill(combo, items):
        previous = combo.currentData()
        combo.clear()
        for title, value in items:
            combo.addItem(title, value)
        found = combo.findData(previous)
        if found >= 0:
            combo.setCurrentIndex(found)

    def set_info(self, info):
        self.info = info
        saved = self.queue.options
        self._updating = True
        index = self.kind.findData(saved.get("kind"))
        if index >= 0:
            self.kind.setCurrentIndex(index)
        source = saved.get("caption_source", "manual")
        if not info.get("captions", {}).get(source) and info.get("captions", {}).get("automatic"):
            source = "automatic"
        index = self.caption_source.findData(source)
        self.caption_source.setCurrentIndex(max(0, index))
        self._updating = False
        self._refresh()
        self._updating = True
        for combo, key in ((self.format, "format"), (self.quality, "quality"), (self.language, "language")):
            index = combo.findData(saved.get(key))
            if index >= 0:
                combo.setCurrentIndex(index)
        self._updating = False
        self._refresh()

    def _refresh(self):
        if self._updating:
            return
        self._updating = True
        kind = self.kind.currentData()
        formats = {"video": VIDEO_FORMATS, "audio": AUDIO_FORMATS, "transcript": CAPTION_FORMATS}[kind]
        self._fill(self.format, [(fmt.upper() if fmt != "md" else "Markdown", fmt) for fmt in formats])
        if kind == "video":
            qualities = [("Best", "best")] + [(f"{height}p", str(height)) for height in reversed(self.info.get("heights", []))]
        elif kind == "audio" and self.format.currentData() not in ("wav", "flac"):
            qualities = [("Best", "best")] + [(f"{rate} kbps", rate) for rate in ("320", "256", "192", "128")]
        else:
            qualities = [("Source", "best")]
        self._fill(self.quality, qualities)
        quality_visible = kind != "transcript" and not (kind == "audio" and self.format.currentData() in ("wav", "flac"))
        self.quality.setVisible(quality_visible)
        self.quality_label.setVisible(quality_visible)
        self.grid.setColumnStretch(2, 1 if quality_visible else 0)
        self.caption_fields.setVisible(kind == "transcript")
        languages = self.info.get("captions", {}).get(self.caption_source.currentData(), {})
        pairs = [(f"{name} ({code})" if name != code else code, code) for code, name in sorted(languages.items(), key=lambda pair: (pair[0] != "en", pair[0]))]
        self._fill(self.language, pairs or [("Unavailable", "")])
        self._updating = False

    def options(self):
        return DownloadOptions(kind=self.kind.currentData(), format=self.format.currentData(),
            quality=self.quality.currentData(), captions=False, language=self.language.currentData(),
            caption_source=self.caption_source.currentData(), folder=save_folder(self.queue))

    def _changed(self):
        if self._updating:
            return
        self._refresh()
        self.queue.set_options(self.options().to_dict())
        self.changed.emit()


class VideoCard(QFrame):
    selection_changed = Signal()
    download_requested = Signal(str)

    def __init__(self, url, queue):
        super().__init__()
        self.setObjectName("videoResult")
        self.url, self.info = url, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 18, 0, 18)
        layout.setSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.selected = QCheckBox()
        self.selected.setAccessibleName("Select video")
        self.selected.setEnabled(False)
        self.selected.toggled.connect(self.selection_changed)
        row.addWidget(self.selected)
        self.thumbnail = label("", "muted")
        self.thumbnail.setObjectName("thumbnail")
        self.thumbnail.setFixedSize(128, 72)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumbnail)
        details = QVBoxLayout()
        details.setSpacing(5)
        self.title = label("Inspecting…", "cardTitle")
        self.title.setMinimumWidth(0)
        self.meta = label(url, "muted")
        self.meta.setMinimumWidth(0)
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details.addWidget(self.title)
        details.addWidget(self.meta)
        row.addLayout(details, 1)
        layout.addLayout(row)
        self.options_panel = ResultOptions(queue)
        self.options_panel.hide()
        layout.addWidget(self.options_panel)
        actions = QHBoxLayout()
        self.status = label("", "muted")
        actions.addWidget(self.status, 1)
        self.download = button("Download", lambda: self.download_requested.emit(self.url), True)
        self.download.hide()
        actions.addWidget(self.download)
        layout.addLayout(actions)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._source_menu)

    def _source_menu(self, position):
        menu = QMenu(self)
        menu.addAction("Open source", lambda: QDesktopServices.openUrl(QUrl(self.url)))
        menu.exec(self.mapToGlobal(position))

    def set_result(self, info, error=""):
        self.info = info if info else None
        self.title.setText(info.get("title", "Unavailable") if info else "Unavailable")
        if not info:
            self.status.setText(error)
            return
        self.meta.setText(" · ".join(str(value) for value in (info.get("creator"), info.get("site"), duration(info.get("duration"))) if value))
        self.options_panel.set_info(info)
        self.options_panel.show()
        self.selected.setAccessibleName("Select " + info["title"])
        self.selected.setEnabled(True)
        self.selected.setChecked(True)
        self.download.show()
        self.status.setText("")
        try:
            data = base64.b64decode(info.get("thumbnail_data", ""))
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data):
                self.thumbnail.setPixmap(pixmap.scaled(128, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except ValueError:
            pass


class SearchPage(CenteredPage):
    def __init__(self, queue, parent=None):
        super().__init__(0.65, parent)
        self.queue, self.inspector = queue, Inspector(self)
        self.cards = {}
        self.current_input = True
        layout = self.content_layout
        self.input = LinkInput()
        self.input.setObjectName("omniInput")
        self.input.setPlaceholderText("Paste a link or links")
        self.input.setAccessibleName("Video links; Enter to inspect, Shift+Enter for another line")
        self.input.setFixedHeight(132)
        self.input.inspect_requested.connect(self.inspect)
        self.input.textChanged.connect(self._input_changed)
        layout.addWidget(self.input)
        actions = QHBoxLayout()
        actions.addStretch()
        self.inspect_button = button("Inspect", self.inspect, True)
        actions.addWidget(self.inspect_button)
        layout.addLayout(actions)
        self.notice = label("", "muted")
        self.notice.hide()
        layout.addWidget(self.notice)
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(16)
        layout.addLayout(self.cards_layout)
        batch_row = QHBoxLayout()
        batch_row.addStretch()
        self.download_selected = button("Download selected", self._download_selected, True)
        self.download_selected.hide()
        self.download_selected.setEnabled(False)
        batch_row.addWidget(self.download_selected)
        layout.addLayout(batch_row)
        self.inspector.item_ready.connect(self._inspected)
        self.inspector.busy_changed.connect(self._busy)
        queue.notice.connect(self.show_notice)

    def show_notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _input_changed(self):
        self.current_input = False
        self.inspector.stop()
        for card in self.cards.values():
            card.download.setEnabled(False)
        self.download_selected.setEnabled(False)

    def inspect(self):
        entries = parse_links(self.input.toPlainText())
        if not entries:
            self.show_notice("Paste a link first.")
            return
        self.show_notice("")
        self.current_input = True
        for card in self.cards.values():
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        for entry in entries:
            card = VideoCard(entry["url"], self.queue)
            card.selection_changed.connect(self._selection_changed)
            card.download_requested.connect(self._download_one)
            self.cards[entry["url"]] = card
            self.cards_layout.addWidget(card)
            if entry["error"]:
                card.set_result({}, entry["error"])
        self.inspector.inspect([entry["url"] for entry in entries if not entry["error"]])
        self._selection_changed()

    def _busy(self, busy):
        self.inspect_button.setText("Inspect")

    def _inspected(self, generation, url, info, error):
        if url in self.cards and self.current_input:
            self.cards[url].set_result(info, error)
            self._selection_changed()

    def _selected(self):
        return [card for card in self.cards.values() if card.info and card.selected.isChecked()]

    def _selection_changed(self):
        count = len(self._selected())
        self.download_selected.setVisible(len(self.cards) > 1 and bool(count))
        self.download_selected.setEnabled(bool(count) and self.current_input)
        self.download_selected.setText(f"Download selected · {count}")

    def _download_one(self, url):
        if self.current_input and self.cards[url].info:
            self._enqueue([self.cards[url]])

    def _download_selected(self):
        if self.current_input:
            self._enqueue(self._selected())

    def _enqueue(self, cards):
        queued = 0
        for card in cards:
            try:
                self.queue.submit(card.info, card.options_panel.options())
                card.status.setText("Queued")
                queued += 1
            except (OSError, ValueError) as exc:
                card.status.setText(str(exc))
        if queued:
            self.show_notice(f"Added to Downloaded · {queued}")


class DownloadTable(QTableWidget):
    menu_requested = Signal(str, QPoint)

    def __init__(self):
        super().__init__(0, 6)
        self.setObjectName("downloadsTable")
        self.setHorizontalHeaderLabels(["Name", "Format", "Quality", "Source", "Size", "Progress"])
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(64)
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 180)
        for column, width in ((1, 110), (2, 88), (3, 78), (4, 88), (5, 170)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.setColumnWidth(column, width)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def row_for(self, job_id):
        for row in range(self.rowCount()):
            if self.item(row, 0).data(Qt.UserRole) == job_id:
                return row
        return -1

    def _context_menu(self, position):
        row = self.rowAt(position.y())
        if row >= 0:
            self.selectRow(row)
            self.menu_requested.emit(self.item(row, 0).data(Qt.UserRole), self.viewport().mapToGlobal(position))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Menu or (event.key() == Qt.Key_F10 and event.modifiers() & Qt.ShiftModifier):
            row = self.currentRow()
            if row >= 0:
                item = self.item(row, 0)
                self.menu_requested.emit(item.data(Qt.UserRole), self.viewport().mapToGlobal(self.visualItemRect(item).center()))
            event.accept()
        else:
            super().keyPressEvent(event)

    def fit_height(self):
        scrollbar = self.horizontalScrollBar().sizeHint().height() if self.horizontalHeader().length() > self.viewport().width() else 0
        self.setFixedHeight(self.horizontalHeader().height() + self.rowCount() * 64 + scrollbar + 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setColumnWidth(0, max(180, self.viewport().width() - sum(self.columnWidth(c) for c in range(1, 6))))
        self.fit_height()


class DownloadedPage(CenteredPage):
    def __init__(self, queue, parent=None):
        super().__init__(0.70, parent)
        self.queue, self.jobs = queue, {}
        layout = self.content_layout
        self.notice = label("", "error")
        self.notice.hide()
        layout.addWidget(self.notice)
        self.empty = label("No downloads yet", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty)
        self.active_heading = label("In progress", "sectionTitle")
        self.completed_heading = label("Downloaded", "sectionTitle")
        self.active_table, self.completed_table = DownloadTable(), DownloadTable()
        for title, table in ((self.active_heading, self.active_table), (self.completed_heading, self.completed_table)):
            layout.addWidget(title)
            layout.addWidget(table)
            table.menu_requested.connect(self._show_menu)
        queue.changed.connect(self.update_job)
        queue.notice.connect(self._notice)
        for job in sorted(queue.jobs.values(), key=lambda job: job.get("created", 0)):
            self.update_job(job["id"], job)
        self._headings()

    def update_job(self, job_id, job):
        self.jobs[job_id] = job
        table = self.completed_table if job["status"] == "completed" else self.active_table
        other = self.active_table if table is self.completed_table else self.completed_table
        old_row = other.row_for(job_id)
        if old_row >= 0:
            other.removeRow(old_row)
            other.fit_height()
        row = table.row_for(job_id)
        if row < 0:
            row = table.rowCount()
            table.insertRow(row)
            for column in range(table.columnCount()):
                table.setItem(row, column, QTableWidgetItem())
            table.item(row, 0).setData(Qt.UserRole, job_id)
            progress_widget = QWidget()
            progress_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            progress_layout = QVBoxLayout(progress_widget)
            progress_layout.setContentsMargins(8, 9, 8, 9)
            progress_layout.setSpacing(6)
            state = label("", "muted")
            state.setWordWrap(False)
            progress = QProgressBar()
            progress.setFixedHeight(4)
            progress.setTextVisible(False)
            progress_layout.addWidget(state)
            progress_layout.addWidget(progress)
            progress_widget.state, progress_widget.bar = state, progress
            table.setCellWidget(row, 5, progress_widget)
        options = job["options"]
        kind, quality = options["kind"], options.get("quality", "best")
        if kind == "transcript":
            quality = "—"
        elif quality != "best":
            quality += "p" if kind == "video" else " kbps"
        else:
            quality = "Source" if options["format"] in ("flac", "wav") else "Best"
        source = "Torrent" if job.get("source") == "torrent" or job["url"].startswith("magnet:") else "Link"
        size = job.get("size") if job["status"] == "completed" else job.get("total_bytes") or job.get("downloaded_bytes")
        values = [job.get("title", job["url"]), f"{'Text' if kind == 'transcript' else kind.title()} · {options['format'].upper()}", quality, source, file_size(size)]
        for column, value in enumerate(values):
            table.item(row, column).setText(value)
        table.item(row, 0).setToolTip(job.get("error") or values[0])
        table.item(row, 3).setToolTip(job["url"])
        table.item(row, 4).setToolTip("Final file size" if job["status"] == "completed" else "Current stream size; final output may differ")
        widget = table.cellWidget(row, 5)
        percent, status = job.get("percent"), job["status"]
        state = status.title()
        if status == "downloading" and percent is not None:
            state = f"{round(percent)}%"
            if job.get("speed"):
                state += f" · {file_size(job['speed'])}/s"
        widget.state.setText(state)
        widget.setToolTip(job.get("error") or (f"{duration(job['eta'])} remaining" if job.get("eta") is not None else status.title()))
        widget.bar.setVisible(status in ACTIVE)
        widget.bar.setRange(0, 0 if percent is None else 100)
        if percent is not None:
            widget.bar.setValue(round(percent))
        widget.bar.setAccessibleName(f"{status.title()} progress")
        table.fit_height()
        self._headings()

    def _headings(self):
        self.empty.setVisible(not self.jobs)
        for heading, table in ((self.active_heading, self.active_table), (self.completed_heading, self.completed_table)):
            heading.setVisible(table.rowCount() > 0)
            table.setVisible(table.rowCount() > 0)

    def _notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def context_menu(self, job_id):
        job = self.jobs[job_id]
        menu = QMenu(self)
        if job["status"] == "completed":
            files = job.get("files", [])
            if len(files) > 1:
                submenu = menu.addMenu("Open file")
                for path in files:
                    submenu.addAction(Path(path).name, lambda checked=False, file=path: self._open(file, False))
            else:
                action = menu.addAction("Open file", lambda: self._open(files[0], False))
                action.setEnabled(bool(files))
            action = menu.addAction("Show in folder", lambda: self._open(files[0], True))
            action.setEnabled(bool(files))
        elif job["status"] in ACTIVE:
            action = menu.addAction("Cancel", lambda: self.queue.cancel(job_id))
            action.setEnabled(job["status"] != "cancelling")
        elif job["status"] in ("failed", "cancelled", "interrupted"):
            menu.addAction("Retry", lambda: self.queue.retry(job_id))
        return menu

    def _show_menu(self, job_id, position):
        self._menu = self.context_menu(job_id)
        self._menu.popup(position)

    def _open(self, file, folder):
        path = Path(file)
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))
        else:
            self._notice("This file is no longer at its saved location.")
