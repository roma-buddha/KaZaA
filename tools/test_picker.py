"""Verify the album-version picker: exact-length match, no videos/live/remixes."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import yt_dlp  # noqa: E402

from kazaa.settings import Settings  # noqa: E402
from kazaa.downloader import DownloadWorker  # noqa: E402

failures = []

OPTS = {"quiet": True, "no_color": True, "retries": 1,
        "windows_filenames": True}

CASES = [
    # (title, artists, duration_ms, expect_range_s)
    ("Thriller", "Michael Jackson", 357_466, (330, 385)),   # not the 13:42 short film
    ("Never Gonna Give You Up", "Rick Astley", 213_573, (200, 225)),
    ("saudade, saudade", "MARO", 196_373, (180, 210)),      # not sped-up versions
]

st = Settings()
w = DownloadWorker("", st)
with yt_dlp.YoutubeDL(OPTS) as ydl:
    for title, artists, ms, (lo, hi) in CASES:
        tr = {"title": title, "artists": artists, "duration_ms": ms}
        vid = w._pick_track_match(ydl, tr)
        if not vid:
            print(f"FAIL {artists} - {title}: no match")
            failures.append(f"{title}: no match")
            continue
        try:
            best = ydl.extract_info(
                f"https://www.youtube.com/watch?v={vid}", download=False)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {artists} - {title}: extract failed: {e}")
            failures.append(f"{title}: extract failed")
            continue
        dur = (best or {}).get("duration") or 0
        chan = (best or {}).get("channel") or (best or {}).get("uploader") or ""
        bt = (best or {}).get("title") or ""
        ok = lo <= dur <= hi
        print(f"{'PASS' if ok else 'FAIL'} {artists} - {title}: "
              f"picked {bt!r} by {chan!r} ({dur}s, spotify says {ms // 1000}s)")
        if not ok:
            failures.append(f"{title}: picked {dur}s, want {lo}-{hi}s")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL PICKER TESTS PASSED")
