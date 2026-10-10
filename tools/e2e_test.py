"""Headless end-to-end test: download -> convert -> trim -> volume -> merge."""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from vloader.settings import Settings  # noqa: E402
from vloader.downloader import DownloadWorker  # noqa: E402
from vloader.converter import ConvertWorker, probe_duration  # noqa: E402

TESTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(TESTDIR, exist_ok=True)
URL = "https://download.samplelib.com/mp4/sample-5s.mp4"   # small public test clip

st = Settings()
st.set("save_to", TESTDIR)

failures = []


def wait_thread(t, timeout=120):
    """Run the worker; block while pumping the Qt event loop so queued
    signals deliver (proven pattern for the minimal platform plugin)."""
    t.start()
    waited = 0
    while t.isRunning() and waited < timeout * 1000:
        app.processEvents()
        t.wait(50)
        waited += 50
    for _ in range(20):
        app.processEvents()
    if t.isRunning():
        failures.append("timeout waiting for thread")
        if hasattr(t, "cancel"):
            t.cancel()
        t.wait(5000)
        return False
    return True


# ---- 1. download -------------------------------------------------------
res = {}
err = []
w = DownloadWorker(URL, st)
w.finished_ok.connect(lambda r: res.update(r))
w.failed.connect(lambda m: err.append(m))
print("[1] downloading", URL)
wait_thread(w)
if err or not res.get("output"):
    failures.append(f"download failed: {err}")
else:
    src = res["output"]
    print("    ->", src, os.path.getsize(src), "bytes")

if not failures:
    # ---- 2. convert mp4 -> mkv ------------------------------------------
    res2, err2 = {}, []
    c = ConvertWorker(src, "mkv", "normal")
    c.finished_ok.connect(lambda r: res2.update(r))
    c.failed.connect(lambda m: err2.append(m))
    print("[2] converting mp4 -> mkv")
    wait_thread(c)
    if err2 or not os.path.exists(res2.get("output", "")):
        failures.append(f"convert failed: {err2}")

if not failures:
    # ---- 3. trim + volume to mp4 ----------------------------------------
    res3, err3 = {}, []
    c = ConvertWorker(src, "mp4", "high", trim_start=1, trim_end=4, volume=0.5)
    c.finished_ok.connect(lambda r: res3.update(r))
    c.failed.connect(lambda m: err3.append(m))
    print("[3] trim 1s-4s + volume 0.5 -> mp4")
    wait_thread(c)
    if err3 or not os.path.exists(res3.get("output", "")):
        failures.append(f"trim failed: {err3}")
    else:
        d = probe_duration(res3["output"])
        print(f"    trimmed duration: {d:.1f}s (expect ~3s)")
        if not (2.0 <= d <= 4.5):
            failures.append(f"trim duration wrong: {d}")

if not failures:
    # ---- 4. merge two files ----------------------------------------------
    res4, err4 = {}, []
    c = ConvertWorker(src, "mp4", "low", extra_inputs=[res2["output"]])
    c.finished_ok.connect(lambda r: res4.update(r))
    c.failed.connect(lambda m: err4.append(m))
    print("[4] merging 2 clips -> mp4")
    wait_thread(c, 180)
    if err4 or not os.path.exists(res4.get("output", "")):
        failures.append(f"merge failed: {err4}")
    else:
        d = probe_duration(res4["output"])
        print(f"    merged duration: {d:.1f}s (expect ~10s)")
        if d < 8:
            failures.append(f"merge duration wrong: {d}")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL TESTS PASSED")
for f in sorted(os.listdir(TESTDIR)):
    print("  ", f, os.path.getsize(os.path.join(TESTDIR, f)), "bytes")
