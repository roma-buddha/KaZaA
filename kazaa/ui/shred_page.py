"""Ephemeral drag-and-drop queue for verified file overwriting."""
import os
import json
from dataclasses import asdict
from pathlib import Path
from threading import Event
import time

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSignalBlocker, Qt, QThread, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMenu, QProgressBar, QPushButton,
    QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..shredder import ALGORITHMS, LIMITATION, FileTarget, ShredCancelled, ShredError, inspect_file, shred_file
from .video_pages import CenteredPage, button, label
from .torrent_widgets import AllFilesBox


def file_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


class ShredRows(QStyledItemDelegate):
    """Flat rows with a centered checkbox and no per-cell focus outline."""
    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        option.state &= ~QStyle.State_HasFocus
        style = option.widget.style()
        if index.column() != 0:
            style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
            return
        option.features &= ~QStyleOptionViewItem.HasCheckIndicator
        style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        check = QStyleOptionButton()
        check.rect = QRect(option.rect.x() + (option.rect.width() - 17) // 2,
                           option.rect.y() + (option.rect.height() - 17) // 2, 17, 17)
        check.state = option.state & (QStyle.State_Enabled | QStyle.State_Active)
        check.state |= QStyle.State_On if index.data(Qt.CheckStateRole) == Qt.Checked.value else QStyle.State_Off
        style.drawPrimitive(QStyle.PE_IndicatorItemViewItemCheck, check, painter, option.widget)

    def editorEvent(self, event, model, option, index):
        if index.column() != 0:
            return super().editorEvent(event, model, option, index)
        if not option.state & QStyle.State_Enabled or not index.flags() & Qt.ItemIsUserCheckable:
            return False
        clicked = event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and option.rect.contains(event.position().toPoint())
        keyed = event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Space, Qt.Key_Select)
        if clicked or keyed:
            state = Qt.Unchecked if index.data(Qt.CheckStateRole) == Qt.Checked.value else Qt.Checked
            return model.setData(index, state, Qt.CheckStateRole)
        return False


class AlgorithmMenu(QPushButton):
    changed = Signal(str)

    def __init__(self, selected):
        super().__init__("Algorithm")
        self.setObjectName("shredAlgorithm")
        self.setAccessibleName("Overwrite algorithm")
        self.setCursor(Qt.PointingHandCursor)
        self.choices = {}
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        menu = QMenu(self)
        for choice in ALGORITHMS:
            action = menu.addAction(choice.label)
            action.setCheckable(True)
            action.setData(choice.key)
            self.group.addAction(action)
            self.choices[choice.key] = action
        self.setMenu(menu)
        self.group.triggered.connect(lambda action: self.set_algorithm(action.data()))
        self.selected = selected if selected in self.choices else "single"
        self.choices[self.selected].setChecked(True)
        self._tooltip()

    def set_algorithm(self, key):
        if key not in self.choices:
            return
        self.selected = key
        self.choices[key].setChecked(True)
        self._tooltip()
        self.changed.emit(key)

    def _tooltip(self):
        self.setToolTip(f"{self.currentText()} · Every pass is flushed and verified.")
        self.setAccessibleDescription(f"Selected: {self.currentText()}")

    def currentData(self):
        return self.selected

    def currentText(self):
        return self.choices[self.selected].text()


class ShredConfirmation(QDialog):
    def __init__(self, targets, algorithm, parent=None):
        super().__init__(parent)
        self.setObjectName("shredConfirmation")
        self.setWindowTitle("Shred selected files?")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        count = len(targets)
        layout.addWidget(label(f"Shred {count} selected {'file' if count == 1 else 'files'}?", "cardTitle"))
        layout.addWidget(label("Permanently overwrite and delete these files. This cannot be undone.", "muted"))
        layout.addWidget(label(f"{algorithm}. Every pass will be verified.\nCancelling can leave a partially overwritten file.", "muted"))
        layout.addWidget(label(LIMITATION, "muted"))
        controls = QHBoxLayout()
        controls.addStretch()
        self.cancel_button = button("Cancel", self.reject)
        self.cancel_button.setProperty("role", "plain")
        self.cancel_button.setDefault(True)
        self.shred_button = button("Shred", self.accept)
        self.shred_button.setProperty("role", "outline")
        self.shred_button.setAutoDefault(False)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.shred_button)
        layout.addLayout(controls)
        self.cancel_button.setFocus()


class ShredProgress(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        # Qt already insets embedded widgets by the table item's 8px padding.
        layout.setContentsMargins(3, 0, 3, 0)
        layout.setSpacing(3)
        self.state = label("Ready", "muted")
        self.state.setWordWrap(False)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.state)
        layout.addWidget(self.bar)


class ShredTable(QTableWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__(0, 6)
        self.setObjectName("shredTable")
        self.setAccessibleName("Files to shred; drop files from Windows Explorer")
        self.setHorizontalHeaderLabels(["", "Name", "Type", "Path", "Size", "Progress"])
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setItemDelegate(ShredRows(self))
        self.setMinimumHeight(240)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(42)
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setMinimumSectionSize(46)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, 46)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.master = AllFilesBox(parent=header.viewport())
        self.master.setTristate(True)
        self.master.setAccessibleName("Select or deselect all files to shred")
        self.master.setToolTip("Select all / deselect all")
        header.sectionResized.connect(self._position_master)
        header.geometriesChanged.connect(self._position_master)
        self.empty = QLabel("Drop files here\nor add them from your computer", self.viewport())
        self.empty.setProperty("role", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.empty.setWordWrap(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.viewport().width()
        compact = width < 650
        type_width, size_width, progress_width = (76, 84, 96) if compact else (76, 84, 136)
        name_width = max(145, int((width - 46 - type_width - size_width - progress_width) * 0.65))
        widths = ((0, 46), (1, name_width), (2, type_width), (4, size_width), (5, progress_width))
        for column, width in widths:
            self.setColumnWidth(column, width)
        self.empty.setGeometry(self.viewport().rect())
        self._position_master()

    def _position_master(self, *args):
        header = self.horizontalHeader()
        self.master.setGeometry(header.sectionViewportPosition(0) + (header.sectionSize(0) - 17) // 2,
                                (header.height() - 17) // 2, 17, 17)

    def refresh_empty(self):
        self.empty.setVisible(self.rowCount() == 0)

    def _accept(self, event):
        if self.isEnabled() and event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return True
        event.ignore()
        return False

    def dragEnterEvent(self, event):
        self._accept(event)

    def dragMoveEvent(self, event):
        self._accept(event)

    def dropEvent(self, event):
        if self._accept(event):
            self.files_dropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])


class ShredWorker(QThread):
    progress = Signal(str, int, str)
    result = Signal(str, str, str)

    def __init__(self, targets, algorithm, parent=None):
        super().__init__(parent)
        self.targets, self.algorithm = tuple(targets), algorithm
        self.cancel = Event()

    def run(self):
        for target in self.targets:
            if self.cancel.is_set():
                self.result.emit(target.path, "kept", "Not started · file kept")
                continue
            last = 0

            def advanced(percent, description):
                nonlocal last
                now = time.monotonic()
                if now - last >= 0.08 or percent == 100:
                    last = now
                    self.progress.emit(target.path, percent, description)

            self.progress.emit(target.path, 0, "Opening file…")
            try:
                shred_file(target, self.algorithm, self.cancel, advanced)
            except ShredCancelled as error:
                self.result.emit(target.path, "cancelled", str(error))
            except Exception as error:
                # A failure never becomes a success; subsequent files can proceed.
                self.result.emit(target.path, "error", f"Failed · {error}")
            else:
                self.result.emit(target.path, "shredded", "Shredded · verified")


class ShredPage(CenteredPage):
    algorithm_changed = Signal(str)
    files_shredded = Signal(list)
    files_released = Signal(list)

    def __init__(self, algorithm="single", parent=None, queue_path=None):
        super().__init__(0.75, parent)
        self.worker = None
        self.targets = {}
        self.results = {}
        self.queue_path = Path(queue_path) if queue_path else None
        self.pending_downloads = {}
        self.queue_error = ""
        self.batch_total = self.batch_done = 0
        layout = self.content_layout
        layout.setSpacing(16)
        layout.addWidget(label("Shred", "pageTitle"))
        controls = QHBoxLayout()
        self.add_button = button("Add files…", self._browse)
        self.remove_button = button("Remove", self._remove)
        self.remove_button.setToolTip("Remove checked files from this list")
        controls.addWidget(self.add_button)
        controls.addStretch()
        controls.addWidget(self.remove_button)
        layout.addLayout(controls)
        self.table = ShredTable()
        self.table.files_dropped.connect(self.add_files)
        self.table.itemChanged.connect(self._selection_changed)
        self.table.master.clicked.connect(lambda _: self._check_all(self.table.master.checkState() != Qt.Unchecked))
        layout.addWidget(self.table)
        options = QHBoxLayout()
        options.addStretch()
        self.cancel_button = button("Cancel", self.stop)
        self.cancel_button.hide()
        options.addWidget(self.cancel_button)
        self.algorithm = AlgorithmMenu(algorithm)
        self.algorithm.changed.connect(self.algorithm_changed)
        options.addWidget(self.algorithm)
        self.shred_button = button("Shred selected", self._confirm_shred, True)
        options.addWidget(self.shred_button)
        layout.addLayout(options)
        self.summary = label("", "muted")
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Shredding progress")
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.notice = label("", "error")
        self.notice.hide()
        layout.addWidget(self.notice)
        layout.addWidget(label(LIMITATION, "muted"))
        self._selection_changed()
        self._load_pending()

    def _write_pending(self, pending):
        if self.queue_error:
            raise OSError(self.queue_error)
        if self.queue_path is None:
            return
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.queue_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"files": [asdict(target) for target in pending.values()]},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.queue_path)

    def _load_pending(self):
        if self.queue_path is None or not self.queue_path.exists():
            return
        try:
            saved = json.loads(self.queue_path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or not isinstance(saved.get("files"), list):
                raise ValueError("Invalid pending file list")
            pending = {}
            for record in saved["files"]:
                if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not os.path.isabs(record["path"]):
                    raise ValueError("Invalid pending file identity")
                if any(type(record.get(key)) is not int or record[key] < 0 for key in ("size", "device", "inode", "modified")):
                    raise ValueError("Invalid pending file identity")
                target = FileTarget(**record)
                pending[target.path] = target
            self.pending_downloads = pending
        except (OSError, ValueError, TypeError) as error:
            self.queue_error = f"Could not restore pending Shred files: {error}. The saved list was kept."
            self.notice.setText(self.queue_error)
            self.notice.show()
            return
        with QSignalBlocker(self.table):
            for target in pending.values():
                self._append_target(target)
                try:
                    if inspect_file(target.path) != target:
                        raise ShredError("File changed since it was queued. Remove it and add it again to confirm the new file.")
                except (OSError, ValueError, ShredError) as error:
                    row = self._row(target.path)
                    self.results[target.path] = "error"
                    self.table.item(row, 0).setCheckState(Qt.Unchecked)
                    widget = self.table.cellWidget(row, 5)
                    widget.state.setText("Check file")
                    widget.setToolTip(str(error))
        self.table.refresh_empty()
        self._selection_changed()

    def enqueue_files(self, paths):
        """Durable, all-or-nothing handoff from Downloads; never starts shredding."""
        targets = []
        for path in paths:
            try:
                target = inspect_file(path)
            except ShredError as error:
                raise ValueError(str(error)) from error
            if self.worker and any(os.path.normcase(t.path) == os.path.normcase(target.path) for t in self.worker.targets):
                raise ValueError("This file is already being shredded. Wait for that operation to finish.")
            existing = next((t for t in self.targets.values() if os.path.normcase(t.path) == os.path.normcase(target.path)), None)
            if existing and existing != target:
                raise ValueError("File changed in Shred. Remove it and add it again before handing it over.")
            targets.append(existing or target)
        pending = dict(self.pending_downloads)
        pending.update({target.path: target for target in targets})
        self._write_pending(pending)  # History removal is allowed only after durable acceptance.
        self.pending_downloads = pending
        with QSignalBlocker(self.table):
            for target in targets:
                if target.path not in self.targets:
                    self._append_target(target)
        self.table.refresh_empty()
        self._selection_changed()

    def _append_target(self, target):
        row = self.table.rowCount()
        self.table.insertRow(row)
        checked = QTableWidgetItem()
        checked.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        checked.setCheckState(Qt.Checked)
        checked.setData(Qt.UserRole, target.path)
        checked.setToolTip("Include this file")
        self.table.setItem(row, 0, checked)
        values = (Path(target.path).name, Path(target.path).suffix.lstrip(".").upper() or "File",
                  str(Path(target.path).parent), file_size(target.size), "")
        for column, value in enumerate(values, 1):
            item = QTableWidgetItem(value)
            item.setToolTip(target.path if column in (1, 3) else value)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, column, item)
        self.table.setCellWidget(row, 5, ShredProgress())
        self.table.cellWidget(row, 5).setAutoFillBackground(False)
        self.targets[target.path] = target

    def selected_targets(self):
        return [self.targets[self.table.item(row, 0).data(Qt.UserRole)]
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.Checked and
            self.results.get(self.table.item(row, 0).data(Qt.UserRole)) != "shredded"]

    def add_files(self, paths):
        if self.worker:
            return
        errors = []
        with QSignalBlocker(self.table):
            for path in paths:
                try:
                    target = inspect_file(path)
                except (OSError, ValueError, ShredError) as error:
                    errors.append(f"{Path(path).name}: {error}")
                    continue
                key = os.path.normcase(target.path)
                if any(os.path.normcase(p) == key for p in self.targets):
                    continue
                self._append_target(target)
        self.notice.setText("\n".join(errors[:4]) + (f"\n…and {len(errors) - 4} more." if len(errors) > 4 else ""))
        self.notice.setVisible(bool(errors))
        self.table.refresh_empty()
        self._selection_changed()

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files to shred")
        self.add_files(paths)

    def _check_all(self, selected):
        if self.worker:
            return
        with QSignalBlocker(self.table):
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if self.results.get(item.data(Qt.UserRole)) != "shredded":
                    item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
        self._selection_changed()

    def _remove(self):
        if self.worker:
            return
        removing = {target.path for target in self.selected_targets()}
        released = [path for path in removing if path in self.pending_downloads]
        pending = {path: target for path, target in self.pending_downloads.items() if path not in removing}
        if released:
            try:
                self._write_pending(pending)
            except OSError as error:
                self.notice.setText(f"Could not remove pending files: {error}")
                self.notice.show()
                return
            self.pending_downloads = pending
        with QSignalBlocker(self.table):
            for row in reversed(range(self.table.rowCount())):
                item = self.table.item(row, 0)
                path = item.data(Qt.UserRole)
                if item.checkState() == Qt.Checked:
                    self.table.removeRow(row)
                    self.targets.pop(path, None)
                    self.results.pop(path, None)
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())
        self.table.refresh_empty()
        self._selection_changed()
        if released:
            self.files_released.emit(released)

    def _selection_changed(self, *args):
        targets = self.selected_targets()
        self.shred_button.setEnabled(bool(targets) and self.worker is None)
        self.remove_button.setEnabled(self.worker is None and bool(targets))
        with QSignalBlocker(self.table.master):
            self.table.master.setCheckState(Qt.Unchecked if not targets else
                Qt.Checked if len(targets) == len(self.targets) else Qt.PartiallyChecked)
        self.table.master.setEnabled(self.worker is None and bool(self.targets))
        if not self.worker:
            count = len(targets)
            self.summary.setText(f"{count} {'file' if count == 1 else 'files'} selected · {file_size(sum(t.size for t in targets))}")

    def _confirm_shred(self):
        targets = self.selected_targets()
        if not targets or self.worker:
            return
        dialog = ShredConfirmation(targets, self.algorithm.currentText(), self)
        confirmed = dialog.exec() == QDialog.Accepted
        dialog.deleteLater()
        if confirmed:
            self.start_shredding(targets)

    def start_shredding(self, targets):
        if self.worker or not targets:
            return
        self.batch_total, self.batch_done = len(targets), 0
        self.batch_results = []
        self.notice.hide()
        self.worker = ShredWorker(targets, self.algorithm.currentData(), self)
        self.worker.progress.connect(self._progress)
        self.worker.result.connect(self._result)
        self.worker.finished.connect(self._finished)
        for widget in (self.table, self.add_button, self.algorithm):
            widget.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.cancel_button.show()
        self.progress.setValue(0)
        self.progress.show()
        self.summary.setText(f"Shredding {self.batch_total} files…")
        self._selection_changed()
        self.worker.start()

    def _row(self, path):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == path:
                return row
        return -1

    def _progress(self, path, percent, description):
        row = self._row(path)
        if row >= 0:
            widget = self.table.cellWidget(row, 5)
            widget.state.setText(f"{percent}%")
            widget.bar.setValue(percent)
            widget.bar.setAccessibleName(f"{description} · {percent}%")
            widget.bar.show()
            widget.setToolTip(description)
        overall = int((self.batch_done * 100 + percent) / self.batch_total)
        self.progress.setValue(overall)
        self.progress.setToolTip(f"{overall}% of batch processed")
        self.summary.setText(f"{overall}% · {self.batch_done + 1}/{self.batch_total} · {Path(path).name}")

    def _result(self, path, state, description):
        self.results[path] = state
        self.batch_results.append(state)
        self.batch_done += 1
        row = self._row(path)
        if row >= 0:
            with QSignalBlocker(self.table):
                if state == "shredded":
                    self.table.removeRow(row)
                    self.targets.pop(path, None)
                    self.results.pop(path, None)
                    if path in self.pending_downloads:
                        self.pending_downloads.pop(path)
                        try:
                            self._write_pending(self.pending_downloads)
                        except OSError as error:
                            self.notice.setText(f"File shredded, but the pending list could not be saved: {error}")
                            self.notice.show()
                else:
                    widget = self.table.cellWidget(row, 5)
                    widget.state.setText({"error": "Failed", "cancelled": "Cancelled", "kept": "Not started"}[state])
                    widget.bar.hide()
                    widget.setToolTip(description)
        self.table.refresh_empty()
        self._selection_changed()
        self.progress.setValue(int(self.batch_done * 100 / self.batch_total))
        if state == "shredded":
            self.files_shredded.emit([path])

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        for widget in (self.table, self.add_button, self.algorithm):
            widget.setEnabled(True)
        self.cancel_button.hide()
        self.progress.hide()
        self._selection_changed()
        shredded = self.batch_results.count("shredded")
        self.summary.setText(f"{shredded} shredded · {self.batch_total - shredded} incomplete")
        if self.batch_total != shredded:
            self.notice.setText("Some files were not confirmed shredded. Hover over their status for details. Interrupted files may be partially overwritten.")
            self.notice.show()

    def stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setText("Cancelling…")
            self.cancel_button.setEnabled(False)
