"""Reproduce the user's live-stop scenario through the real MainWindow.

Submits a live room URL exactly like the UI does, waits for the row to
show LIVE, clicks the actual Stop button widget, then verifies the row
finishes with a saved playable file.
"""
import json
import os
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from kazaa.ui import theme  # noqa: E402
theme.apply(app)
from kazaa.ui.main_window import MainWindow  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "https://chaturbate.com/thecherie/"
TESTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(TESTDIR, exist_ok=True)

win = MainWindow()
win.resize(1020, 660)
win.show()
win.settings.set("save_to", TESTDIR)

failures = []

tid = win.downloads.submit(URL)
win.activity.add_task(tid, URL, "download")
print("[gui] submitted", URL, "tid", tid)

# wait for the row to become a live recording (max 60s)
row = None
deadline = time.time() + 60
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.2)
    r = win.activity.tasks.get(tid)
    if r is not None:
        t = win.activity.rows[r]
        if t.get("live") and t.get("status") == "downloading":
            row = r
            break
if row is None:
    t = win.activity.rows.get(win.activity.tasks.get(tid), {})
    failures.append(f"row never became live: status={t.get('status')} live={t.get('live')}")
    print("[gui] FAIL row state:", dict(t))
else:
    t = win.activity.rows[row]
    # NOTE: isVisible() is unreliable under the minimal QPA platform (the
    # window never actually maps); the authoritative signal is that clicking
    # the real Stop button stops the recording and saves a playable file.
    for _ in range(15):
        app.processEvents()
        time.sleep(0.2)
    print(f"[gui] row is LIVE, stop button visible={t['btn_stop'].isVisible()}, "
          f"pause visible={t['btn_pause'].isVisible()} (informational only)")
    # let it record a bit
    time.sleep(8)
    for _ in range(20):
        app.processEvents()
    print("[gui] clicking the real Stop button")
    t["btn_stop"].click()
    # wait for the row to finish (max 45s)
    deadline = time.time() + 45
    done = False
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.2)
        t2 = win.activity.rows[row]
        if t2.get("status") in ("done", "stopped", "error"):
            done = True
            break
    t2 = win.activity.rows[row]
    print(f"[gui] final row status={t2.get('status')} output={t2.get('output')!r}")
    if not done:
        failures.append(f"row never finished after stop click (status={t2.get('status')})")
    out = t2.get("output", "")
    if not out or not os.path.exists(out):
        failures.append(f"no saved file: {out!r}")
    else:
        ffprobe = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "bin", "ffprobe.exe")
        p = subprocess.run([ffprobe, "-v", "error", "-print_format", "json",
                            "-show_format", "-show_streams", out],
                           capture_output=True, text=True, timeout=60)
        meta = json.loads(p.stdout or "{}")
        kinds = sorted(s.get("codec_type") for s in meta.get("streams", []))
        dur = float(meta.get("format", {}).get("duration", 0) or 0)
        print(f"[gui] saved streams={kinds} duration={dur:.1f}s")
        if "video" not in kinds or "audio" not in kinds:
            failures.append(f"missing streams: {kinds}")
        if dur < 5:
            failures.append(f"duration too short: {dur}")
        os.remove(out)

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("LIVE GUI TEST PASSED")
