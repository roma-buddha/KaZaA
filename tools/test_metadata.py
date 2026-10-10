"""Metadata tagging tests: tagger helper + ConvertWorker meta carry-through."""
import json
import os
import subprocess
import sys

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from vloader import tagger  # noqa: E402
from vloader.converter import ConvertWorker  # noqa: E402
from vloader.downloader import find_ffmpeg  # noqa: E402

TESTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(TESTDIR, exist_ok=True)
failures = []
FFMPEG = find_ffmpeg()
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")


def probe_tags(path):
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
         path], capture_output=True, text=True, timeout=60)
    return json.loads(p.stdout or "{}").get("format", {}).get("tags", {})


def make_sine_mp3(path):
    subprocess.run(
        [FFMPEG, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:a", "libmp3lame", "-b:a", "128k", path],
        capture_output=True, timeout=60, check=True)


# ---- 1. tag an mp3 in place ------------------------------------------------
mp3 = os.path.join(TESTDIR, "tagger_test.mp3")
make_sine_mp3(mp3)
ok = tagger.tag_media_file(
    mp3, title="Test Song", artist="Test Artist", album="Test Album",
    year="1999", track="3", genre="Rock")
tags = probe_tags(mp3)
print(("PASS" if ok else "FAIL"), "tag mp3 ->", tags)
expect = {"title": "Test Song", "artist": "Test Artist",
          "album": "Test Album", "genre": "Rock"}
for k, v in expect.items():
    if str(tags.get(k, "")) != v:
        failures.append(f"mp3 tag {k}: {tags.get(k)!r} != {v!r}")
if str(tags.get("date", tags.get("TYER", "")))[:4] != "1999":
    failures.append(f"mp3 year tag: {tags!r}")
if str(tags.get("track", "")).split("/")[0] != "3":
    failures.append(f"mp3 track tag: {tags.get('track')!r}")
os.remove(mp3)

# ---- 2. mp4 also taggable (video container) --------------------------------
mp4 = os.path.join(TESTDIR, "tagger_test.mp4")
subprocess.run(
    [FFMPEG, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
     "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4],
    capture_output=True, timeout=60, check=True)
ok = tagger.tag_media_file(mp4, title="Video Title", artist="Chan Name",
                           year="2020")
tags = probe_tags(mp4)
print(("PASS" if ok and tags.get("title") == "Video Title" else "FAIL"),
      "tag mp4 ->", {k: tags.get(k) for k in ("title", "artist", "date")})
if tags.get("title") != "Video Title":
    failures.append(f"mp4 title tag: {tags!r}")
os.remove(mp4)

# ---- 3. ConvertWorker carries meta into its output -------------------------
src = os.path.join(TESTDIR, "meta_src.mp3")
out = os.path.join(TESTDIR, "meta_src.m4a")  # converter derives the name
make_sine_mp3(src)
res, err = {}, []
c = ConvertWorker(src, "m4a", "normal",
                  meta={"title": "Carried Title", "artist": "Carried Artist",
                        "year": "2001"})
c.finished_ok.connect(lambda r: res.update(r))
c.failed.connect(lambda m: err.append(m))
c.start()
waited = 0
while c.isRunning() and waited < 60000:
    app.processEvents()
    c.wait(50)
    waited += 50
for _ in range(10):
    app.processEvents()
tags = probe_tags(out) if os.path.exists(out) else {}
print(("PASS" if not err and tags.get("title") == "Carried Title" else "FAIL"),
      "convert carries meta ->",
      {k: tags.get(k) for k in ("title", "artist", "date")})
if err or tags.get("title") != "Carried Title":
    failures.append(f"convert meta carry failed: err={err} tags={tags}")
for f in (src, out):
    if os.path.exists(f):
        os.remove(f)

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL METADATA TESTS PASSED")
