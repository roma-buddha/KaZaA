"""Spotify link support tests: resolver + full track download e2e."""
import json
import os
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from kazaa import spotify  # noqa: E402
from kazaa.settings import Settings  # noqa: E402
from kazaa.downloader import DownloadWorker  # noqa: E402

TESTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(TESTDIR, exist_ok=True)
failures = []

TRACK = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"  # Rick Astley
ALBUM = "https://open.spotify.com/album/78bpIziExqiI9qztvNFlQu"   # AM
PLAYLIST = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

# ---- 1. URL detection ---------------------------------------------------
checks = [
    (TRACK, True), (ALBUM, True), (PLAYLIST, True),
    ("spotify:track:4uLU6hMCjMI75M1A2tKUQC", True),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://chaturbate.com/seltin_sweety/", False),
]
for url, want in checks:
    got = spotify.is_spotify_url(url)
    print(("PASS" if got == want else "FAIL"), "is_spotify_url:", url[:60])
    if got != want:
        failures.append(f"is_spotify_url({url}) = {got}, want {want}")

# ---- 2. resolve track ---------------------------------------------------
try:
    t = spotify.resolve(TRACK)
    print(f"track: {t['name']} | {t['artist']} | cover={'yes' if t['cover'] else 'no'}")
    if t["name"] != "Never Gonna Give You Up" or "Rick Astley" not in t["artist"]:
        failures.append(f"track metadata wrong: {t}")
    if not t["cover"] or not t["cover"].startswith("http"):
        failures.append("track cover missing")
    if len(t["tracks"]) != 1:
        failures.append("track resolve should return exactly 1 track")
except Exception as e:  # noqa: BLE001
    failures.append(f"track resolve failed: {e}")

# ---- 3. resolve album ---------------------------------------------------
try:
    a = spotify.resolve(ALBUM)
    print(f"album: {a['name']} | {a['artist']} | {len(a['tracks'])} tracks")
    if a["name"] != "AM" or len(a["tracks"]) != 12:
        failures.append(f"album resolve wrong: {a['name']} {len(a['tracks'])}")
    first = a["tracks"][0]
    if first["title"] != "Do I Wanna Know?" or first["album"] != "AM":
        failures.append(f"album first track wrong: {first}")
    if not all(tr["artists"] for tr in a["tracks"]):
        failures.append("album tracks missing artists")
except Exception as e:  # noqa: BLE001
    failures.append(f"album resolve failed: {e}")

# ---- 4. resolve playlist ------------------------------------------------
try:
    p = spotify.resolve(PLAYLIST)
    print(f"playlist: {p['name']} | {len(p['tracks'])} tracks")
    if len(p["tracks"]) < 10:
        failures.append(f"playlist too short: {len(p['tracks'])}")
except Exception as e:  # noqa: BLE001
    failures.append(f"playlist resolve failed: {e}")

# ---- 5. full track download e2e -----------------------------------------
st = Settings()
st.set("save_to", TESTDIR)
res, err, events = {}, [], []
w = DownloadWorker(TRACK, st)
w.progress.connect(lambda i: events.append(dict(i)))
w.finished_ok.connect(lambda r: res.update(r))
w.failed.connect(lambda m: err.append(m))
print("[e2e] downloading Spotify track...")
w.start()
deadline = time.time() + 180
while time.time() < deadline and w.isRunning():
    app.processEvents()
    w.wait(50)
for _ in range(20):
    app.processEvents()
if w.isRunning():
    failures.append("worker timeout")
    w.cancel()
    w.wait(8000)

print("[e2e] result:", {k: res.get(k) for k in ("output", "name", "size")})
print("[e2e] err:", err)
out = res.get("output", "")
if err or not out or not os.path.exists(out):
    failures.append(f"e2e failed: err={err} out={out}")
else:
    if not res.get("spotify"):
        failures.append("result missing spotify flag")
    ffprobe = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bin", "ffprobe.exe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"
    p = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", out],
        capture_output=True, text=True, timeout=60)
    meta = json.loads(p.stdout or "{}")
    streams = meta.get("streams", [])
    kinds = [s.get("codec_type") for s in streams]
    names = [s.get("codec_name") for s in streams]
    dur = float(meta.get("format", {}).get("duration", 0) or 0)
    tags = meta.get("format", {}).get("tags", {})
    print(f"[e2e] streams={list(zip(kinds, names))} dur={dur:.1f}s")
    print(f"[e2e] tags: title={tags.get('title')!r} artist={tags.get('artist')!r}")
    print(f"[e2e]       album={tags.get('album')!r} date={tags.get('date')!r} "
          f"genre={tags.get('genre')!r} track={tags.get('track')!r}")
    if "audio" not in kinds or names[kinds.index("audio")] != "mp3":
        failures.append(f"not an mp3: {names}")
    if "video" not in kinds:
        failures.append("cover art not embedded")
    if not (190 <= dur <= 240):
        failures.append(f"duration off: {dur:.1f}s (expect ~213s)")
    if "Never Gonna" not in str(tags.get("title", "")):
        failures.append(f"title tag wrong: {tags.get('title')!r}")
    if "Rick Astley" not in str(tags.get("artist", "")):
        failures.append(f"artist tag wrong: {tags.get('artist')!r}")
    if "Whenever You Need Somebody" not in str(tags.get("album", "")):
        failures.append(f"album tag wrong (iTunes enrich): {tags.get('album')!r}")
    if str(tags.get("date", ""))[:4] != "1987":
        failures.append(f"year tag wrong: {tags.get('date')!r}")
    if "pop" not in str(tags.get("genre", "")).lower():
        failures.append(f"genre tag wrong: {tags.get('genre')!r}")
    if str(tags.get("track", "")) not in ("1", "1/12"):
        failures.append(f"track number wrong: {tags.get('track')!r}")
    os.remove(out)

# ---- 6. same track as lossless FLAC --------------------------------------
st2 = Settings()
st2.set("save_to", TESTDIR)
st2.set("spotify_format", "flac")
res2, err2 = {}, []
w2 = DownloadWorker(TRACK, st2)
w2.finished_ok.connect(lambda r: res2.update(r))
w2.failed.connect(lambda m: err2.append(m))
print("[e2e] downloading same track as FLAC...")
w2.start()
deadline = time.time() + 180
while time.time() < deadline and w2.isRunning():
    app.processEvents()
    w2.wait(50)
for _ in range(20):
    app.processEvents()
out2 = res2.get("output", "")
print("[e2e] flac result:", {k: res2.get(k) for k in ("output", "size")})
if err2 or not out2.endswith(".flac") or not os.path.exists(out2):
    failures.append(f"flac e2e failed: err={err2} out={out2}")
else:
    p = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", out2],
        capture_output=True, text=True, timeout=60)
    meta = json.loads(p.stdout or "{}")
    streams = meta.get("streams", [])
    kinds = [(s.get("codec_type"), s.get("codec_name")) for s in streams]
    tags = meta.get("format", {}).get("tags", {})
    print(f"[e2e] flac streams={kinds} tags: title={tags.get('title')!r} "
          f"album={tags.get('album')!r}")
    if ("audio", "flac") not in kinds:
        failures.append(f"not flac: {kinds}")
    if ("video", "mjpeg") not in kinds:
        failures.append("flac cover art not embedded")
    if "Never Gonna" not in str(tags.get("title", "")):
        failures.append(f"flac title tag wrong: {tags.get('title')!r}")
    if "Whenever You Need Somebody" not in str(tags.get("album", "")):
        failures.append(f"flac album tag wrong: {tags.get('album')!r}")
    os.remove(out2)

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL SPOTIFY TESTS PASSED")
