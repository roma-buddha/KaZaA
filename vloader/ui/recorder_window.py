"""Screen recorder window: region overlay + record controls."""
import os
import subprocess
import time

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QRadioButton,
                               QVBoxLayout, QWidget)

from .. import i18n
from ..recorder import Recorder


class RegionOverlay(QWidget):
    """Transparent full-screen overlay; drag to select the recording region."""

    region_selected = Signal(QRect)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setWindowState(Qt.WindowFullScreen)
        self.origin = None
        self.rect = QRect()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 80))
        if not self.rect.isNull():
            p.setPen(QPen(QColor(0, 255, 0), 2))
            p.drawRect(self.rect)
            p.fillRect(self.rect, QColor(0, 255, 0, 20))
        p.end()

    def mousePressEvent(self, e):
        self.origin = e.position().toPoint()
        self.rect = QRect(self.origin, self.origin)

    def mouseMoveEvent(self, e):
        if self.origin is not None:
            self.rect = QRect(self.origin, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self.origin is not None and self.rect.width() > 20 and self.rect.height() > 20:
            self.region_selected.emit(self.rect)
        self.origin = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.region_selected.emit(QRect())


class RecorderWindow(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(i18n.tr("rec_title"))
        self.rec = Recorder(self)
        self.rect = None
        self.start_ts = 0

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(i18n.tr("rec_hint")))

        self.rb_region = QRadioButton(i18n.tr("rec_region"))
        self.rb_full = QRadioButton(i18n.tr("rec_full"))
        self.rb_full.setChecked(True)
        lay.addWidget(self.rb_region)
        lay.addWidget(self.rb_full)

        self.audio = QCheckBox(i18n.tr("rec_audio"))
        self.audio.setChecked(bool(settings.get("recorder_audio")))
        lay.addWidget(self.audio)

        note = QLabel(i18n.tr("rec_note"))
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        self.btn_start = QPushButton(i18n.tr("rec_start"))
        self.btn_start.setProperty("variant", "primary")
        self.btn_start.clicked.connect(self.start_recording)
        self.btn_stop = QPushButton(i18n.tr("rec_stop"))
        self.btn_stop.setProperty("variant", "danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_recording)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)

        self.timer_lbl = QLabel("--:--")
        lay.addWidget(self.timer_lbl)

        from PySide6.QtCore import QTimer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self.rec.state_changed.connect(self._state)
        self.rec.finished.connect(self._saved)
        self.rec.start_hotkeys(self._hotkey_toggle, self.stop_recording)

    # ---- recording ------------------------------------------------------
    def start_recording(self):
        rect = None
        if self.rb_region.isChecked():
            if not self._pick_region():
                return
            rect = (self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height())
        self.settings.set("recorder_audio", self.audio.isChecked())
        if self.rec.start(rect, self.audio.isChecked(),
                          int(self.settings.get("recorder_framerate"))):
            self.start_ts = time.time()
            self.timer.start(1000)
        else:
            QMessageBox.warning(self, i18n.tr("rec_title"),
                                "ffmpeg/gdigrab unavailable.")

    def _pick_region(self):
        self.hide()
        ov = RegionOverlay()
        done = []
        ov.region_selected.connect(lambda r: (done.append(r), ov.close()))
        ov.show()
        from PySide6.QtWidgets import QApplication
        while not done:
            QApplication.processEvents()
            time.sleep(0.02)
        self.show()
        r = done[0]
        if r.isNull():
            return False
        self.rect = r
        return True

    def stop_recording(self):
        self.rec.stop()
        self.timer.stop()

    def _hotkey_toggle(self):
        if self.rec.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def _tick(self):
        s = int(time.time() - self.start_ts)
        self.timer_lbl.setText(f"{s//60:02d}:{s%60:02d}")

    def _state(self, st):
        rec = st == "recording"
        self.btn_start.setEnabled(not rec)
        self.btn_stop.setEnabled(rec)

    def _saved(self, path):
        self.timer.stop()
        QMessageBox.information(self, i18n.tr("rec_saved"), path)

    def closeEvent(self, e):
        if self.rec.is_recording:
            self.stop_recording()
        super().closeEvent(e)
