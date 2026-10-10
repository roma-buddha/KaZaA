"""Music feature test: search shape, preview fetch, mp3 conversion path."""
import json
import os
import subprocess
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication(sys.argv)

failures = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        failures.append(msg)
        print(f"  FAIL: {msg}")


# --- unit: quality selector ----------------------------------------------
from vloader.downloader import quality_to_formatsel  # noqa: E402
check(quality_to_formatsel("music").startswith("bestaudio"),
      "music quality selects audio-only")

# --- UI smoke: MainWindow builds with the Music pane ----------------------
from vloader.ui import theme  # noqa: E402
theme.apply(app)
from vloader.ui.main_window import MainWindow  # noqa: E402
win = MainWindow()
check(win._pages.get("music") == 3, "music page registered")
check(win.music_pane is not None, "music pane exists")
check(win.music_pane.table.columnCount() == 4, "results table has 4 columns")

# --- live search (network) -------------------------------------------------
from vloader import music  # noqa: E402
print("[net] searching YouTube (may take a few seconds)...")
try:
    results = music.search("mairo megurine luka", limit=8)
except Exception as e:  # noqa: BLE001
    results = []
    print(f"  network search unavailable: {type(e).__name__}: {e}")

if results:
    check(len(results) >= 5, f"got {len(results)} results")
    r0 = results[0]
    check(all(k in r0 for k in ("id", "title", "artist", "duration", "url")),
          "result shape complete")
    check(r0["url"].startswith("https://www.youtube.com/watch?v="),
          "watch URL built")
    print(f"  first result: {r0['title']!r} by {r0['artist']!r} "
          f"({r0['duration']}s)")

    # --- preview fetch -----------------------------------------------------
    print("[net] fetching 20s preview...")
    done, failed = [], []
    f = music.PreviewFetcher(r0["url"])
    f.done.connect(lambda p: done.append(p))
    f.failed.connect(lambda m: failed.append(m))
    f.start()
    t0 = time.time()
    while f.isRunning() and time.time() - t0 < 120:
        app.processEvents()
        time.sleep(0.2)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)
    if done:
        path = done[0]
        check(os.path.exists(path) and os.path.getsize(path) > 10000,
              f"preview file fetched ({os.path.getsize(path)} bytes)")
        ffprobe = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "bin", "ffprobe.exe")
        p = subprocess.run([ffprobe, "-v", "error", "-print_format", "json",
                            "-show_format", path],
                           capture_output=True, text=True, timeout=60)
        meta = json.loads(p.stdout or "{}")
        dur = float(meta.get("format", {}).get("duration", 0) or 0)
        check(5 <= dur <= 25, f"preview duration {dur:.1f}s (expect ~20s)")
        try:
            os.remove(path)
        except OSError:
            pass
    else:
        check(False, f"preview fetch failed: {failed}")

    # --- download -> mp3 pipeline (through the real manager) ---------------
    print("[net] downloading first result as music...")
    tmpdl = tempfile.mkdtemp(prefix="vloader_music_")
    win.settings.set("save_to", tmpdl)
    tid = win.downloads.submit(r0["url"], quality="music")
    check(tid is not None, "submitted to manager")
    win._music_meta[tid] = {"title": r0["title"], "artist": r0["artist"]}
    win.activity.add_task(tid, r0["url"], "download")
    t0 = time.time()
    finished = []
    win.downloads.task_finished.connect(lambda i, res: finished.append(res))
    while not finished and time.time() - t0 < 180:
        app.processEvents()
        time.sleep(0.3)
    check(bool(finished), "download finished")
    if finished:
        # the window's own task_finished -> _on_dl_finished wiring queues
        # the mp3 convert; just wait for the convert pipeline to drain
        t0 = time.time()
        while time.time() - t0 < 90:
            app.processEvents()
            time.sleep(0.3)
            outs = [f for f in os.listdir(tmpdl) if f.lower().endswith(".mp3")]
            if outs:
                break
        outs = [f for f in os.listdir(tmpdl) if f.lower().endswith(".mp3")]
        check(bool(outs), f"mp3 produced: {outs}")
        # wait for the convert worker to fully finish (tag + cleanup)
        t0 = time.time()
        while (win.convert_workers or win._pending_conv) and time.time() - t0 < 90:
            app.processEvents()
            time.sleep(0.3)
        app.processEvents()
        if outs:
            mp3 = os.path.join(tmpdl, outs[0])
            check(os.path.getsize(mp3) > 50000, "mp3 has content")
            left = [f for f in os.listdir(tmpdl)
                    if not f.lower().endswith(".mp3")]
            check(not left, f"intermediate removed (left={left})")
            p = subprocess.run([ffprobe, "-v", "error", "-print_format",
                                "json", "-show_format", mp3],
                               capture_output=True, text=True, timeout=60,
                               encoding="utf-8", errors="replace")
            fmt = json.loads(p.stdout or "{}").get("format", {})
            tags = fmt.get("tags", {})
            check(tags.get("title") == r0["title"], f"title tag: {tags.get('title')!r}")
            check(tags.get("artist") == r0["artist"],
                  f"artist tag: {tags.get('artist')!r}")
else:
    print("  (search unavailable — skipping live cases)")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("MUSIC TESTS PASSED")
