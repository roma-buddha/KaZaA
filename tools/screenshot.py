"""Render each page of the themed UI to PNG for visual verification."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from vloader.ui import theme  # noqa: E402
theme.apply(app)
from vloader.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1020, 660)
win.show()

# populate the activity pane with representative rows
a = win.activity
samples = [
    (1, "https://www.youtube.com/watch?v=demo1", {"status": "downloading",
        "percent": 64.0, "speed": "4.2 MB/s", "eta": "00:12", "size": 83_000_000,
        "name": "Keynote - Full HD recording.mp4"}),
    (2, "https://vimeo.com/12345", {"status": "queued", "percent": 0.0,
        "name": "Vimeo - Behind the scenes"}),
    (3, "local: talk.mp4 -> mp3", {"status": "converting", "percent": 31.0,
        "name": "Conference talk.mp3"}),
]
for tid, url, info in samples:
    a.add_task(tid, url)
    if "name" in info:
        pass
    a.update_task(tid, info)
a.set_done(9, "C:/Videos/VLoader/finished-demo.mp4")
a.add_task(9, "https://www.youtube.com/watch?v=demo4")
a.set_done(9)
a.add_task(10, "https://example.com/broken")
a.set_error(10, "HTTP Error 403: Forbidden")
a.rows[a.tasks[1]]["status"] = "downloading"

outdir = os.path.dirname(os.path.abspath(__file__))
app.processEvents()
for name, idx in [("shot_download", 0), ("shot_activity", 1), ("shot_convert", 2)]:
    win.nav.setCurrentRow(idx)
    app.processEvents()
    path = os.path.join(outdir, f"{name}.png")
    win.grab().save(path)
    print("saved", path)

# recorder window too
from vloader.ui.recorder_window import RecorderWindow  # noqa: E402
rec = RecorderWindow(win.settings)
rec.show()
app.processEvents()
rec.grab().save(os.path.join(outdir, "shot_recorder.png"))
print("saved recorder")
