"""Centered search results and download tables for KaZaA."""
import base64
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMenu, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from ..video_backend import AUDIO_FORMATS, CAPTION_FORMATS, VIDEO_FORMATS, DownloadOptions
from ..video_jobs import ACTIVE, Inspector
from ..sources import input_tokens, is_torrent_source, parse_sources, source_key


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


def date_added(value):
    try:
        return datetime.fromtimestamp(value).strftime("%d.%m.%y") if value is not None else "—"
    except (ValueError, TypeError, OSError, OverflowError):
        return "—"


def source_details(job):
    if job.get("source") != "torrent":
        return job["url"]
    health = job.get("torrent_health")
    if not health:
        return "Torrent\nHealth not available yet."
    monitoring = job["status"] in ("starting", "downloading")
    state = ("Active" if health["active"] else "Looking for peers") if monitoring else job["status"].title()
    counts = []
    for key, title in (("seeds", "Seeds"), ("peers", "Peers")):
        reported = health.get("reported_" + key, -1)
        counts.append(f"{title}: {health[key]} connected" + (f" · {reported} reported" if reported >= 0 else ""))
    observed = datetime.fromtimestamp(health["observed"]).strftime("%d.%m.%y %H:%M:%S")
    return "<b>Torrent · " + escape(state) + "</b><br>" + "<br>".join(counts) + "<br>Last checked: " + observed


class CenteredPage(QScrollArea):
    def __init__(self, fraction, parent=None, breakpoint=850):
        super().__init__(parent)
        self.fraction = fraction
        self.breakpoint = breakpoint
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
        self.content.setFixedWidth(max(300, int(width * self.fraction if width >= self.breakpoint else width - 48)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_width()


class LinkInput(QPlainTextEdit):
    inspect_requested = Signal()
    sources_added = Signal(str)

    def canInsertFromMimeData(self, data):
        return data.hasUrls() or super().canInsertFromMimeData(data)

    def insertFromMimeData(self, data):
        text = "\n".join(url.toString(QUrl.FullyEncoded) for url in data.urls()) if data.hasUrls() else data.text()
        if any(is_torrent_source(entry["url"]) for entry in parse_sources(text)):
            self.sources_added.emit(text)
        else:
            super().insertFromMimeData(data)

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
        self.grid = QHBoxLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(7)
        self.kind, self.format, self.quality = QComboBox(), QComboBox(), QComboBox()
        for title, value in (("Video", "video"), ("Audio", "audio"), ("Transcript", "transcript")):
            self.kind.addItem(title, value)
        for title, widget, width in (("Download as", self.kind, 100), ("Format", self.format, 78), ("Quality", self.quality, 84)):
            widget.setAccessibleName(title)
            widget.setToolTip(title)
            widget.setFixedWidth(width)
            self.grid.addWidget(widget)
        self.caption_fields = QWidget()
        captions_grid = QHBoxLayout(self.caption_fields)
        captions_grid.setContentsMargins(0, 0, 0, 0)
        captions_grid.setSpacing(7)
        self.caption_source, self.language = QComboBox(), QComboBox()
        self.caption_source.addItem("Creator", "manual")
        self.caption_source.addItem("Automatic", "automatic")
        for title, widget, width in (("Caption source", self.caption_source, 102), ("Language", self.language, 105)):
            widget.setAccessibleName(title)
            widget.setToolTip(title)
            widget.setFixedWidth(width)
            captions_grid.addWidget(widget)
        self.grid.addWidget(self.caption_fields)
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
        self.kind.setCurrentIndex(self.kind.findData("video"))
        self.kind.model().item(self.kind.findData("transcript")).setEnabled(not info.get("live"))
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
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(8)
        self.strip = QScrollArea()
        self.strip.setFrameShape(QFrame.NoFrame)
        self.strip.setWidgetResizable(True)
        self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.strip.setFixedHeight(86)
        row_body = QWidget()
        row_body.setObjectName("resultRow")
        self.strip.setWidget(row_body)
        row_body.setAutoFillBackground(False)
        row = QHBoxLayout(row_body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.selected = QCheckBox()
        self.selected.setAccessibleName("Select video")
        self.selected.setEnabled(False)
        self.selected.toggled.connect(self.selection_changed)
        row.addWidget(self.selected)
        self.thumbnail = label("", "muted")
        self.thumbnail.setObjectName("thumbnail")
        self.thumbnail.setFixedSize(96, 54)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumbnail)
        details_widget = QWidget()
        details_widget.setMinimumWidth(240)
        details = QVBoxLayout(details_widget)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(3)
        self.title = label("Inspecting…", "cardTitle")
        self.title.setMinimumWidth(0)
        self.meta = label(url, "muted")
        self.meta.setMinimumWidth(0)
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details.addWidget(self.title)
        details.addWidget(self.meta)
        row.addWidget(details_widget, 1, Qt.AlignVCenter)
        self.options_panel = ResultOptions(queue)
        self.options_panel.hide()
        row.addWidget(self.options_panel)
        self.download = button("Download", lambda: self.download_requested.emit(self.url), True)
        self.download.hide()
        row.addWidget(self.download)
        layout.addWidget(self.strip)
        self.status = label("", "muted")
        self.status.hide()
        layout.addWidget(self.status)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._source_menu)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_preview()

    def _fit_preview(self):
        row = self.strip.widget().layout()
        width = max(self.strip.viewport().width(), row.minimumSize().width())
        scrollbar = self.strip.horizontalScrollBar().sizeHint().height() if row.minimumSize().width() > self.strip.viewport().width() else 0
        self.strip.setFixedHeight(max(86, row.heightForWidth(width) + scrollbar))

    def _source_menu(self, position):
        menu = QMenu(self)
        menu.addAction("Open source", lambda: QDesktopServices.openUrl(QUrl(self.url)))
        menu.exec(self.mapToGlobal(position))

    def set_result(self, info, error=""):
        self.info = info if info else None
        self.title.setText(info.get("title", "Unavailable") if info else "Unavailable")
        if not info:
            self.status.setText(error)
            self.status.show()
            return
        self.meta.setText(" · ".join(str(value) for value in ("LIVE" if info.get("live") else None, info.get("creator"), info.get("site"), duration(info.get("duration"))) if value))
        self.options_panel.set_info(info)
        self.options_panel.show()
        self.selected.setAccessibleName("Select " + info["title"])
        self.selected.setEnabled(True)
        self.selected.setChecked(True)
        self.download.show()
        self.download.setEnabled(True)
        self.download.setText("Record" if info.get("live") else "Download")
        self.status.setText("")
        try:
            data = base64.b64decode(info.get("thumbnail_data", ""))
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data):
                self.thumbnail.setPixmap(pixmap.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except ValueError:
            pass
        self._fit_preview()


class SearchPage(CenteredPage):
    open_download = Signal(str)

    def __init__(self, queue, parent=None):
        super().__init__(0.65, parent, breakpoint=1100)
        self.queue, self.inspector = queue, Inspector(self, cache_dir=queue.path.parent / "torrent-cache")
        self.cards = {}
        self.current_input = True
        layout = self.content_layout
        self.input = LinkInput()
        self.input.setObjectName("omniInput")
        self.input.setPlaceholderText("Paste links or magnets, or drop .torrent files")
        self.input.setAccessibleName("Links, magnets or torrent files; Enter to inspect, Shift+Enter for another line")
        self.input.setFixedHeight(132)
        self.input.inspect_requested.connect(self.inspect)
        self.input.sources_added.connect(self._add_sources)
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
        queue.changed.connect(self._queue_changed)
        queue.removed.connect(lambda _: self._queue_changed())

    def _queue_changed(self, *args):
        for card in self.cards.values():
            if card.info and card.info.get("source") == "torrent":
                card.refresh_existing()
                if not self.current_input:
                    card.download.setEnabled(False)

    def _add_sources(self, text):
        with QSignalBlocker(self.input):
            current = self.input.toPlainText().strip()
            self.input.setPlainText(current + ("\n" if current else "") + text)
        # Adding sources leaves existing previews/workers intact. Only Inspect
        # (or Enter) creates previews and starts fetching metadata.

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
        entries = parse_sources(self.input.toPlainText())
        if not entries:
            self.show_notice("Paste a link first.")
            return
        self._inspect_entries(entries, append=self.current_input and bool(self.cards))

    def _inspect_entries(self, entries, append=False):
        self.show_notice("")
        self.current_input = True
        if not append:
            for card in self.cards.values():
                self.cards_layout.removeWidget(card)
                card.deleteLater()
            self.cards.clear()
        known = {source_key(url) for url in self.cards if self.cards[url].info}
        inspecting = {url for generation, url in self.inspector.pending if generation == self.inspector.generation}
        inspecting.update(worker.request["url"] for worker, generation in self.inspector.workers.items()
                          if generation == self.inspector.generation)
        pending = []
        for entry in entries:
            old = self.cards.get(entry["url"])
            if old and (old.info or entry["url"] in inspecting):
                continue
            if not entry["error"] and source_key(entry["url"]) in known:
                continue
            if old:
                self.cards_layout.removeWidget(old)
                old.deleteLater()
            if entry["source"] == "torrent":
                from .torrent_widgets import TorrentCard
                card = TorrentCard(entry["url"], self.queue)
            else:
                card = VideoCard(entry["url"], self.queue)
            card.selection_changed.connect(self._selection_changed)
            card.download_requested.connect(self._download_one)
            self.cards[entry["url"]] = card
            self.cards_layout.addWidget(card)
            if entry["error"]:
                card.set_result({}, entry["error"])
            else:
                pending.append(entry["url"])
        if append:
            self.inspector.append(pending)
        else:
            self.inspector.inspect(pending)
        for card in self.cards.values():
            card.download.setEnabled(bool(card.info))
            if hasattr(card, "_selection_changed"):
                card._selection_changed()
        self._selection_changed()

    def _busy(self, busy):
        self.inspect_button.setText("Inspect")

    def _inspected(self, generation, url, info, error):
        if url in self.cards and self.current_input:
            self.cards[url].set_result(info, error)
            self._selection_changed()

    def _selected(self):
        return [card for card in self.cards.values() if card.info and card.selected.isChecked()
                and (not hasattr(card, "can_download") or card.can_download())]

    def _selection_changed(self):
        count = len(self._selected())
        self.download_selected.setVisible(len(self.cards) > 1 and bool(count))
        self.download_selected.setEnabled(bool(count) and self.current_input)
        self.download_selected.setText(f"Download selected · {count}")

    def _download_one(self, url):
        if self.current_input and url in self.cards and self.cards[url].info:
            card = self.cards[url]
            if getattr(card, "existing_job", None):
                self.open_download.emit(card.existing_job)
                self._remove_submitted([card.url])
            else:
                self._enqueue([card])

    def _download_selected(self):
        if self.current_input:
            self._enqueue(self._selected())

    def _enqueue(self, cards):
        submitted = set()
        for card in cards:
            try:
                self.queue.submit(card.info, card.options_panel.options())
                submitted.add(card.url)
            except (OSError, ValueError) as exc:
                card.status.setText(str(exc))
                card.status.show()
        self._remove_submitted(submitted)

    def _remove_submitted(self, urls):
        submitted = {source_key(url) for url in urls}
        for url in urls:
            card = self.cards.pop(url, None)
            if card:
                self.cards_layout.removeWidget(card)
                card.hide()
                card.deleteLater()
        if submitted:
            remaining = []
            for raw in input_tokens(self.input.toPlainText()):
                try:
                    if source_key(raw) in submitted:
                        continue
                except ValueError:
                    pass  # Preserve invalid inputs and their existing error cards.
                remaining.append(raw)
            # Editing the input normally cancels inspection and disables all cards.
            # Queue cleanup must keep the other results ready to download.
            with QSignalBlocker(self.input):
                self.input.setPlainText("\n".join(remaining))
        self._selection_changed()


class DownloadTable(QTableWidget):
    menu_requested = Signal(str, QPoint)
    clear_requested = Signal()

    def __init__(self):
        super().__init__(0, 11)
        self.setObjectName("downloadsTable")
        self.setHorizontalHeaderLabels(["Name", "Type", "Format", "Quality", "Source", "Size", "Progress",
                                        "Speed", "ETA", "Added", "Downloaded"])
        self.horizontalHeaderItem(8).setToolTip("Estimated time remaining")
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(42)
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 200)
        for column, width in ((1, 72), (2, 78), (3, 140), (4, 72), (5, 84), (6, 120), (7, 100), (8, 92), (9, 92), (10, 104)):
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
            if not self.item(row, 0).isSelected():
                self.clear_requested.emit()
                self.selectionModel().select(self.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows)
            self.menu_requested.emit(self.item(row, 0).data(Qt.UserRole), self.viewport().mapToGlobal(position))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if (self.rowAt(int(event.position().y())) < 0 or
                    not event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.clear_requested.emit()
        # Preserve selected rows until the context-menu handler chooses its target.
        if event.button() == Qt.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clear_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Menu or (event.key() == Qt.Key_F10 and event.modifiers() & Qt.ShiftModifier):
            row = self.currentRow()
            if row >= 0:
                item = self.item(row, 0)
                self._context_menu(self.visualItemRect(item).center())
            event.accept()
        else:
            super().keyPressEvent(event)

    def fit_height(self):
        scrollbar = self.horizontalScrollBar().sizeHint().height() if self.horizontalHeader().length() > self.viewport().width() else 0
        self.setFixedHeight(self.horizontalHeader().height() + self.rowCount() * 42 + scrollbar + 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setColumnWidth(0, max(200, self.viewport().width() - sum(self.columnWidth(c) for c in range(1, self.columnCount()))))
        self.fit_height()


class DeleteDownloadDialog(QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        jobs = [job] if isinstance(job, dict) else job
        multiple = len(jobs) > 1
        self.setObjectName("deleteDownload")
        self.setWindowTitle("Delete download · KaZaA")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label(f"{len(jobs)} selected downloads" if multiple else jobs[0].get("title") or "Download", "cardTitle"))
        layout.addWidget(label("Choose what to delete. Files are moved to the Recycle Bin.", "muted"))
        self.choices = {}
        titles = (("entry", "Remove entries only — keep files"),
                  ("file", "Delete files only — keep entries"),
                  ("both", "Delete entries and files")) if multiple else (
                  ("entry", "Remove entry only — keep the file"),
                  ("file", "Delete file only — keep the entry"),
                  ("both", "Delete entry and file"))
        for mode, title in titles:
            choice = QRadioButton(title)
            choice.setEnabled(mode == "entry" or any(item.get("files") for item in jobs))
            self.choices[mode] = choice
            layout.addWidget(choice)
        self.choices["entry"].setChecked(True)
        controls = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.delete_button = controls.addButton("Delete", QDialogButtonBox.AcceptRole)
        self.delete_button.setProperty("role", "primary")
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def mode(self):
        return next(mode for mode, choice in self.choices.items() if choice.isChecked())


class DownloadedPage(CenteredPage):
    def __init__(self, queue, parent=None):
        super().__init__(0.94, parent)
        self.queue, self.jobs = queue, {}
        for background in (self.widget(), self.content, self.viewport()):
            background.installEventFilter(self)
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
            table.clear_requested.connect(self._clear_selection)
            table.cellDoubleClicked.connect(lambda row, column, table=table:
                self._open_download(table.item(row, 0).data(Qt.UserRole)))
        queue.changed.connect(self.update_job)
        queue.removed.connect(self.remove_job)
        queue.notice.connect(self._notice)
        for job in sorted(queue.jobs.values(), key=lambda job: job.get("created", 0)):
            self.update_job(job["id"], job)
        self._headings()

    def update_job(self, job_id, job):
        self.jobs[job_id] = job
        table = self.completed_table if job["status"] == "completed" else self.active_table
        other = self.active_table if table is self.completed_table else self.completed_table
        old_row = other.row_for(job_id)
        was_selected = old_row >= 0 and other.item(old_row, 0).isSelected()
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
            progress_layout.setContentsMargins(8, 4, 8, 4)
            progress_layout.setSpacing(3)
            state = label("", "muted")
            state.setWordWrap(False)
            progress = QProgressBar()
            progress.setFixedHeight(4)
            progress.setTextVisible(False)
            progress_layout.addWidget(state)
            progress_layout.addWidget(progress)
            progress_widget.state, progress_widget.bar = state, progress
            table.setCellWidget(row, 6, progress_widget)
        if was_selected:
            table.selectionModel().select(table.model().index(row, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows)
        options = job["options"]
        kind = options["kind"]
        quality = job.get("actual_quality") or "—"
        source = "Torrent" if job.get("source") == "torrent" or job["url"].startswith("magnet:") else "Link"
        size = job.get("size") if job["status"] == "completed" or job.get("live") else job.get("total_bytes") or job.get("downloaded_bytes")
        values = [job.get("title", job["url"]), 'Text' if kind == 'transcript' else kind.title(), options.get('format', '—').upper(), quality, source, file_size(size)]
        for column, value in enumerate(values):
            table.item(row, column).setText(value)
        table.item(row, 3).setToolTip(quality)
        speed = job.get("speed") if job["status"] in ("downloading", "recording") else None
        eta = job.get("eta") if job["status"] == "downloading" and not job.get("live") else None
        for column, value in ((7, f"{file_size(speed)}/s" if speed is not None else "—"),
                              (8, duration(eta) if eta is not None else "—"),
                              (9, date_added(job.get("created"))), (10, date_added(job.get("completed")))):
            table.item(row, column).setText(value)
            table.item(row, column).setToolTip(value)
        table.item(row, 0).setToolTip(job.get("error") or values[0])
        table.item(row, 4).setToolTip(source_details(job))
        table.item(row, 5).setToolTip("Final file size" if job["status"] == "completed" else "Current stream size; final output may differ")
        widget = table.cellWidget(row, 6)
        percent, status = job.get("percent"), job["status"]
        state = status.title()
        if status == "recording":
            state = f"Recording · {duration(job.get('elapsed', 0))}"
        if status == "downloading" and percent is not None:
            state = f"{round(percent)}%"
        if status == "completed":
            state = "File deleted" if job.get("files_deleted") else "100%"
        widget.state.setText(state)
        widget.setToolTip(job.get("error") or (f"{duration(job['eta'])} remaining" if job.get("eta") is not None else status.title()))
        widget.bar.setVisible(status in ACTIVE)
        widget.bar.setRange(0, 0 if percent is None else 100)
        if percent is not None:
            widget.bar.setValue(round(percent))
        widget.bar.setAccessibleName(f"{status.title()} progress")
        table.fit_height()
        self._headings()

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)
        for table in (self.active_table, self.completed_table):
            row = table.row_for(job_id)
            if row >= 0:
                table.removeRow(row)
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

    def selected_jobs(self):
        return [table.item(index.row(), 0).data(Qt.UserRole)
                for table in (self.active_table, self.completed_table)
                for index in table.selectionModel().selectedRows()]

    def _clear_selection(self):
        for table in (self.active_table, self.completed_table):
            table.clearSelection()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._clear_selection()
        return super().eventFilter(watched, event)

    def _can_delete(self, job_ids):
        return all(job_id in self.jobs and self.jobs[job_id]["status"] not in ACTIVE
                   and job_id not in self.queue.workers for job_id in job_ids)

    def context_menu(self, job_id, job_ids=None):
        job = self.jobs[job_id]
        menu = QMenu(self)
        if job_ids and len(job_ids) > 1:
            action = menu.addAction(f"Delete selected… ({len(job_ids)})", lambda: self._delete(job_ids))
            action.setEnabled(self._can_delete(job_ids))
            menu.setToolTipsVisible(True)
            if not action.isEnabled():
                action.setToolTip("Stop active downloads before deleting the selection.")
            return menu
        if job["status"] == "completed":
            files = job.get("files", [])
            available = bool(files) and not job.get("files_deleted")
            if len(files) > 1:
                submenu = menu.addMenu("Open file")
                for path in files:
                    action = submenu.addAction(Path(path).name, lambda checked=False, file=path: self._open(file, False))
                    action.setEnabled(available)
                submenu.setEnabled(available)
            else:
                action = menu.addAction("Open file", lambda: self._open(files[0], False))
                action.setEnabled(available)
            action = menu.addAction("Show in folder", lambda: self._open(files[0], True))
            action.setEnabled(available)
        elif job["status"] in ACTIVE:
            if not job.get("live") and job["status"] in ("queued", "starting", "downloading"):
                menu.addAction("Pause", lambda: self.queue.pause(job_id))
            action = menu.addAction("Stop", lambda: self.queue.stop_job(job_id))
            action.setEnabled(job["status"] not in ("pausing", "stopping", "cancelling"))
        elif job["status"] == "paused":
            menu.addAction("Resume", lambda: self.queue.resume(job_id))
            menu.addAction("Stop", lambda: self.queue.stop_job(job_id))
        elif job["status"] == "stopped":
            menu.addAction("Record again" if job.get("live") else "Resume", lambda: self.queue.retry(job_id))
        elif job["status"] in ("failed", "cancelled", "interrupted"):
            menu.addAction("Retry", lambda: self.queue.retry(job_id))
        if job.get("source") == "torrent":
            action = menu.addAction("Choose files…", lambda: self._choose_files(job_id))
            action.setEnabled(job["status"] not in ACTIVE and job_id not in self.queue.workers)
        action = menu.addAction("Delete…", lambda: self._delete(job_id))
        action.setEnabled(self._can_delete([job_id]))
        menu.setToolTipsVisible(True)
        if not action.isEnabled():
            action.setToolTip("Stop this download before deleting it.")
        return menu

    def _choose_files(self, job_id):
        from .torrent_widgets import TorrentFilesDialog
        dialog = TorrentFilesDialog(self.jobs[job_id], self)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.queue.select_torrent_files(job_id, dialog.selector.selected_files())
                self._notice("")
            except (OSError, ValueError) as exc:
                self._notice(str(exc))
        dialog.deleteLater()

    def _delete(self, job_id):
        job_ids = [job_id] if isinstance(job_id, str) else list(dict.fromkeys(job_id))
        if not self._can_delete(job_ids):
            self._notice("Stop active downloads before deleting the selection.")
            return
        dialog = DeleteDownloadDialog([self.jobs[item] for item in job_ids], self)
        if dialog.exec() == QDialog.Accepted:
            failures = []
            if not self._can_delete(job_ids):
                failures.append("Stop active downloads before deleting the selection.")
            else:
                for item in job_ids:
                    title = self.jobs[item].get("title") or "Download"
                    try:
                        self.queue.delete(item, dialog.mode())
                    except (OSError, ValueError) as exc:
                        failures.append(f"{title}: {exc}")
            self._notice("\n".join(failures))
        dialog.deleteLater()

    def _show_menu(self, job_id, position):
        self._menu = self.context_menu(job_id, self.selected_jobs())
        self._menu.popup(position)

    def _open_download(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job["status"] != "completed":
            return
        files = job.get("files", [])
        if not files or job.get("files_deleted"):
            self._notice("This file is no longer at its saved location.")
        elif len(files) == 1:
            self._open(files[0], False)
        else:
            self._menu = self.context_menu(job_id)
            self._menu.actions()[0].menu().popup(QCursor.pos())

    def _open(self, file, folder):
        path = Path(file)
        if path.is_file():
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))
            self._notice("" if opened else "Could not open this location." if folder else
                         "Could not open this file. Check the default app for this file type.")
        else:
            self._notice("This file is no longer at its saved location.")
