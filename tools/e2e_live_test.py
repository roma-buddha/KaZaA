"""End-to-end test for live stream recording (Chaturbate-style HLS).

Verifies: progress events with live=True fire, cancel -> graceful stop,
final .mp4 playable (ffprobe duration) with video AND audio streams.
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

from vloader.settings import Settings  # noqa: E402
from vloader.downloader import DownloadWorker, find_ffmpeg  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "https://chaturbate.com/seltin_sweety/"
TESTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(TESTDIR, exist_ok=True)

st = Settings()
st.set("save_to", TESTDIR)

failures = []
events = []
result = {}
err = []

w = DownloadWorker(URL, st)
w.progress.connect(lambda i: events.append(dict(i)))
w.finished_ok.connect(lambda r: result.update(r))
w.failed.connect(lambda m: err.append(m))

print("[live] starting recording of", URL)
w.start()
deadline = time.time() + 40
while time.time() < deadline and w.isRunning():
    app.processEvents()
    w.wait(50)

live_events = [e for e in events if e.get("live")]
print(f"[live] progress events: total={len(events)} live={len(live_events)}")
for e in live_events[:3] + live_events[-3:]:
    print("   ", {k: e.get(k) for k in ("status", "elapsed", "size", "name")})
if not live_events:
    failures.append("no live progress events after 40s")
else:
    elapsed_vals = [e.get("elapsed", "") for e in live_events]
    if len(set(elapsed_vals)) < 2:
        failures.append(f"elapsed not advancing: {elapsed_vals}")

print("[live] sending cancel (graceful stop)")
w.cancel()
stop_deadline = time.time() + 45
while time.time() < stop_deadline and w.isRunning():
    app.processEvents()
    w.wait(50)
for _ in range(20):
    app.processEvents()

if w.isRunning():
    failures.append("worker did not finish within 45s of cancel")
    w.cancel()
    w.wait(10000)

print("[live] result:", {k: result.get(k) for k in ("output", "stopped", "size")})
print("[live] err:", err)
out = result.get("output", "")
if err or not out or not os.path.exists(out):
    failures.append(f"no playable output: err={err} out={out}")
else:
    if os.path.exists(out + ".part"):
        failures.append("leftover .part file after stop")
    ffprobe = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bin", "ffprobe.exe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"
    try:
        p = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", out],
            capture_output=True, text=True, timeout=60)
        meta = json.loads(p.stdout or "{}")
        streams = meta.get("streams", [])
        kinds = sorted(s.get("codec_type", "?") for s in streams)
        dur = float(meta.get("format", {}).get("duration", 0) or 0)
        print(f"[live] streams={kinds} duration={dur:.1f}s size={os.path.getsize(out)}")
        if "video" not in kinds or "audio" not in kinds:
            failures.append(f"missing streams: {kinds}")
        if dur < 10:
            failures.append(f"duration too short: {dur:.1f}s")
    except Exception as e:  # noqa: BLE001
        failures.append(f"ffprobe failed: {e}")

# cleanup test artifacts
for f in list(os.listdir(TESTDIR)):
    if "seltin" in f or "live" in f.lower():
        try:
            os.remove(os.path.join(TESTDIR, f))
            print("   cleaned", f)
        except OSError:
            pass

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("LIVE TEST PASSED")
