"""Compact torrent file selection, shared by Search and Downloads."""
from pathlib import PurePosixPath

from PySide6.QtCore import QSignalBlocker, Qt, QSize, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QHeaderView, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .video_pages import button, file_size, label, save_folder


class FileRows(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), 24)


class AllFilesBox(QCheckBox):
    def nextCheckState(self):
        self.setCheckState(Qt.Unchecked if self.checkState() == Qt.Checked else Qt.Checked)


class TorrentFiles(QWidget):
    changed = Signal()

    def __init__(self, manifest, selected=None, parent=None, master=None):
        super().__init__(parent)
        self.manifest, self.items = manifest, {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.master = master if master is not None else AllFilesBox("All files")
        self.master.setTristate(True)
        self.master.setAccessibleName("Select or deselect all torrent files")
        self.master.clicked.connect(lambda: self.select_all(self.master.checkState() != Qt.Unchecked))
        if master is None:
            layout.addWidget(self.master)
        self.tree = QTreeWidget()
        self.tree.setObjectName("torrentFiles")
        self.tree.setAccessibleName("Torrent folders and files")
        self.tree.setHeaderLabels(["Name", "Size"])
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegate(FileRows(self.tree))
        self.tree.setIndentation(16)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 94)
        folders = {}
        selected = set(selected if selected is not None else [item["index"] for item in manifest if not item.get("pad")])
        for file in manifest:
            if file.get("pad"):
                continue
            parent_item = self.tree.invisibleRootItem()
            parts = PurePosixPath(file["path"]).parts
            for depth in range(1, len(parts)):
                path = "/".join(parts[:depth])
                if path not in folders:
                    item = QTreeWidgetItem(parent_item, [parts[depth - 1], ""])
                    item.setFlags(item.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.Unchecked)
                    item.setToolTip(0, path)
                    folders[path] = item
                parent_item = folders[path]
            item = QTreeWidgetItem(parent_item, [parts[-1], file_size(file["size"])])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(0, Qt.UserRole, file["index"])
            item.setToolTip(0, file["path"])
            item.setCheckState(0, Qt.Checked if file["index"] in selected else Qt.Unchecked)
            self.items[file["index"]] = item
        self.tree.expandAll()
        self.tree.expanded.connect(self._fit_height)
        self.tree.collapsed.connect(self._fit_height)
        self.tree.header().geometriesChanged.connect(self._fit_height)
        self._fit_height()
        layout.addWidget(self.tree)
        controls = QHBoxLayout()
        controls.setSpacing(4)
        controls.addStretch()
        self.summary = label("", "muted")
        controls.addWidget(self.summary)
        layout.addLayout(controls)
        self.tree.itemChanged.connect(self._changed)
        self._changed()

    def _fit_height(self, *args):
        def visible_rows(parent):
            return sum(1 + (visible_rows(parent.child(i)) if parent.child(i).isExpanded() else 0)
                       for i in range(parent.childCount()))
        self.tree.setFixedHeight(self.tree.header().sizeHint().height() +
                                 24 * max(1, visible_rows(self.tree.invisibleRootItem())))

    def selected_files(self):
        return sorted(index for index, item in self.items.items() if item.checkState(0) == Qt.Checked)

    def select_all(self, checked):
        with QSignalBlocker(self.tree):
            for item in self.items.values():
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        self._changed()

    def _changed(self, *args):
        selected = set(self.selected_files())
        size = sum(item["size"] for item in self.manifest if item["index"] in selected)
        self.summary.setText(f"{len(selected)} / {len(self.items)} files · {file_size(size)}")
        with QSignalBlocker(self.master):
            self.master.setCheckState(Qt.Unchecked if not selected else
                                     Qt.Checked if len(selected) == len(self.items) else Qt.PartiallyChecked)
        self.changed.emit()


class TorrentCard(QFrame):
    selection_changed = Signal()
    download_requested = Signal(str)

    def __init__(self, url, queue):
        super().__init__()
        self.setObjectName("videoResult")
        self.url, self.queue, self.info, self.existing_job = url, queue, None, None
        self.options_panel = self
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        self.selected = AllFilesBox()
        self.selected.setEnabled(False)
        self.selected.toggled.connect(self.selection_changed)
        row.addWidget(self.selected, 0, Qt.AlignTop)
        details = QVBoxLayout()
        details.setSpacing(3)
        self.title = label("Inspecting torrent…", "cardTitle")
        self.meta = label("Fetching metadata; files will download after selection.", "muted")
        details.addWidget(self.title)
        details.addWidget(self.meta)
        row.addLayout(details, 1)
        self.download = button("Download", lambda: self.download_requested.emit(self.url), True)
        self.download.hide()
        row.addWidget(self.download)
        layout.addLayout(row)
        self.status = label("", "error")
        self.status.hide()
        layout.addWidget(self.status)
        self.file_selector = None

    def set_result(self, info, error=""):
        self.info = info or None
        self.title.setText(info.get("title", "Unavailable") if info else "Unavailable")
        self.status.setText(error)
        self.status.setVisible(bool(error))
        if not info:
            return
        self.meta.setText("Torrent · " + file_size(info["size"]))
        self.file_selector = TorrentFiles(info["manifest"], parent=self, master=self.selected)
        self.layout().addWidget(self.file_selector)
        self.file_selector.changed.connect(self._selection_changed)
        self.selected.setEnabled(True)
        self.download.show()
        self.refresh_existing()

    def refresh_existing(self):
        self.existing_job = self.queue.torrent_match(self.info["hashes"]) if self.info else None
        self.download.setText("Open in Downloads" if self.existing_job else "Download")
        self.selected.setEnabled(bool(self.info) and not self.existing_job)
        if self.existing_job:
            self.selected.setChecked(False)
        self._selection_changed()

    def can_download(self):
        return bool(self.info and self.file_selector.selected_files() and not self.existing_job)

    def _selection_changed(self):
        self.download.setEnabled(bool(self.existing_job or self.can_download()))
        self.selection_changed.emit()

    def options(self):
        return {"folder": save_folder(self.queue), "selected_files": self.file_selector.selected_files()}


class TorrentFilesDialog(QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.setObjectName("torrentSelection")
        self.setWindowTitle("Choose files · KaZaA")
        self.resize(620, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label(job["title"], "cardTitle"))
        self.selector = TorrentFiles(job["torrent"]["manifest"], job["options"]["selected_files"], self)
        layout.addWidget(self.selector)
        controls = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.download = controls.addButton("Download selected", QDialogButtonBox.AcceptRole)
        self.download.setProperty("role", "primary")
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        self.selector.changed.connect(lambda: self.download.setEnabled(bool(self.selector.selected_files())))
        layout.addWidget(controls)
