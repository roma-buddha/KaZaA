"""Activity pane: task list with progress bars, per-task controls."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QMenu,
                               QProgressBar, QTableWidget, QTableWidgetItem)

from .. import i18n

COLOR_SUCCESS = QColor("#3ddc97")
COLOR_ERROR = QColor("#ff5d6c")
COLOR_DIM = QColor("#9aa0b4")
COLOR_ACCENT = QColor("#948aff")


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} GB"


class ActivityPane(QTableWidget):
    COLUMNS = ["col_video", "col_size", "col_progress", "col_speed",
               "col_status", "col_eta"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels([i18n.tr(c) for c in self.COLUMNS])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(44)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tasks = {}   # task_id -> row index
        self.rows = {}    # row -> task dict
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    # ---- row management -------------------------------------------------
    def add_task(self, task_id, url, kind="download"):
        row = self.rowCount()
        self.insertRow(row)
        name = url if len(url) <= 80 else url[:77] + "..."
        self.setItem(row, 0, QTableWidgetItem(name))
        self.setItem(row, 1, QTableWidgetItem(""))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        self.setCellWidget(row, 2, bar)
        self.setItem(row, 3, QTableWidgetItem(""))
        self.setItem(row, 4, QTableWidgetItem(i18n.tr("st_queued")))
        self.setItem(row, 5, QTableWidgetItem(""))
        self.tasks[task_id] = row
        self.rows[row] = {"id": task_id, "url": url, "kind": kind,
                          "status": "queued", "output": "", "percent": 0.0}
        return row

    def _row_of(self, task_id):
        return self.tasks.get(task_id)

    def update_task(self, task_id, info):
        row = self._row_of(task_id)
        if row is None:
            return
        t = self.rows[row]
        t.update({k: v for k, v in info.items() if k in t or k == "percent"})
        if "name" in info and info["name"]:
            self.item(row, 0).setText(str(info["name"]))
        if "size" in info and info["size"]:
            self.item(row, 1).setText(fmt_size(info["size"]))
        if "percent" in info:
            self.cellWidget(row, 2).setValue(int(info["percent"]))
            t["percent"] = info["percent"]
        if "speed" in info:
            self.item(row, 3).setText(str(info["speed"]))
        if "eta" in info:
            self.item(row, 5).setText(str(info["eta"]))
        if "status" in info:
            key = {"starting": "st_starting", "downloading": "st_downloading",
                   "postprocessing": "st_postproc", "converting": "st_converting",
                   "queued": "st_queued"}.get(info["status"], "st_queued")
            item = self.item(row, 4)
            item.setText(i18n.tr(key))
            item.setForeground(COLOR_ACCENT if info["status"] in
                               ("downloading", "converting") else COLOR_DIM)
            t["status"] = info["status"]

    def set_done(self, task_id, output=""):
        row = self._row_of(task_id)
        if row is None:
            return
        self.rows[row]["status"] = "done"
        self.rows[row]["output"] = output
        self.cellWidget(row, 2).setValue(100)
        self.item(row, 4).setText(i18n.tr("st_done"))
        self.item(row, 4).setForeground(COLOR_SUCCESS)
        self.item(row, 3).setText("")
        self.item(row, 5).setText("")

    def set_error(self, task_id, msg):
        row = self._row_of(task_id)
        if row is None:
            return
        self.rows[row]["status"] = "error" if msg != "cancelled" else "stopped"
        key = "st_error" if msg != "cancelled" else "st_stopped"
        self.item(row, 4).setText(i18n.tr(key))
        self.item(row, 4).setForeground(
            COLOR_ERROR if msg != "cancelled" else COLOR_DIM)
        self.item(row, 5).setText("" if msg == "cancelled" else msg[:60])

    def set_pending_convert(self, task_id):
        row = self._row_of(task_id)
        if row is not None:
            self.item(row, 4).setText(i18n.tr("st_pending"))

    def checked_or_selected_rows(self, checked_only=False):
        rows = set()
        if checked_only:
            for r in range(self.rowCount()):
                it = self.item(r, 0)
                if it and it.checkState() == Qt.Checked:
                    rows.add(r)
        else:
            for idx in self.selectionModel().selectedRows():
                rows.add(idx.row())
        return sorted(rows)

    def add_checkboxes(self):
        for r in range(self.rowCount()):
            it = self.item(r, 0)
            if it and it.checkState() == Qt.Unchecked and not it.data(Qt.UserRole):
                it.setCheckState(Qt.Checked)
                it.setData(Qt.UserRole, 1)

    def _menu(self, pos):
        menu = QMenu(self)
        a_locate = menu.addAction(i18n.tr("m_locate"))
        a_play = menu.addAction(i18n.tr("m_play"))
        a_open = menu.addAction(i18n.tr("m_open_url"))
        menu.addSeparator()
        a_pause = menu.addAction(i18n.tr("m_pause_checked"))
        a_stop = menu.addAction(i18n.tr("m_stop_checked"))
        a_del = menu.addAction(i18n.tr("m_remove_sel"))
        act = menu.exec(self.viewport().mapToGlobal(pos))
        if act is None:
            return
        row = self.indexAt(pos).row()
        t = self.rows.get(row, {})
        if act == a_locate and t.get("output"):
            self.window().locate_file(t["output"])
        elif act == a_play and t.get("output"):
            self.window().play_file(t["output"])
        elif act == a_open and t.get("url"):
            self.window().open_url(t["url"])
        elif act in (a_pause, a_stop):
            for r in self.checked_or_selected_rows(checked_only=True):
                self.window().pause_task(self.rows[r]["id"])
        elif act == a_del:
            for r in reversed(self.checked_or_selected_rows()):
                if self.rows.get(r, {}).get("status") in ("done", "error", "stopped", "queued"):
                    self.removeRow(r)

    def active_count(self):
        return sum(1 for t in self.rows.values()
                   if t["status"] in ("queued", "starting", "downloading",
                                      "postprocessing", "converting", "pending"))

    def any_output(self):
        return any(t.get("output") for t in self.rows.values())
