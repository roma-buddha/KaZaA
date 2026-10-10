"""Crash-recovery test: a live .part left by a killed app gets repaired
into a playable mp4 on the next launch's startup sweep.

Simulates the user's scenario: ffmpeg recording to a .part is hard-killed
(no moov atom written), the live registry still holds the entry, and
recover_interrupted_live() must re-mux it into a playable file.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(ROOT, "bin", "ffmpeg.exe")
FFPROBE = os.path.join(ROOT, "bin", "ffprobe.exe")

failures = []


def probe_duration(path):
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60)
    meta = json.loads(p.stdout or "{}")
    kinds = sorted(s.get("codec_type") for s in meta.get("streams", []))
    dur = float(meta.get("format", {}).get("duration", 0) or 0)
    return kinds, dur


tmpdir = tempfile.mkdtemp(prefix="vloader_recover_")
os.environ["APPDATA"] = tmpdir          # isolate the live registry
workdir = os.path.join(tmpdir, "dl")
os.makedirs(workdir, exist_ok=True)

from vloader.downloader import (  # noqa: E402
    _register_live, _read_live_registry, recover_interrupted_live)

final = os.path.join(workdir, "thecherie 2026-10-10 23_30.mp4")
partial = final + ".part"

# 1) simulate a recording killed mid-stream: ffmpeg writes mp4, hard-killed
proc = subprocess.Popen(
    [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
     "-f", "lavfi", "-i", "testsrc=duration=60:size=320x240:rate=10",
     "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
     "-c:a", "aac", "-f", "mp4", partial],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)
proc.kill()          # hard kill: moov box never written
proc.wait()
if not os.path.exists(partial) or os.path.getsize(partial) == 0:
    failures.append("test setup: partial was not created")
    print("[recover] FAIL setup, partial missing")
    sys.exit(1)
print(f"[recover] partial created ({os.path.getsize(partial)} bytes), "
      "ffmpeg hard-killed (no moov)")

# (a lavfi source carries a fixed duration, so ffprobe can still read this
# synthetic .part; a real live HLS capture has none. the repair pipeline is
# what matters here.)
try:
    _, dur0 = probe_duration(partial)
except Exception:
    dur0 = 0
print(f"[recover] un-repaired probe duration={dur0:.2f}s "
      "(synthetic artifact, not asserted)")

# 2) register it as if the app died mid-recording
_register_live(partial, final, "https://chaturbate.com/thecherie/")

# 3) fresh file -> sweep must keep the entry (orphan ffmpeg may still write)
kept = recover_interrupted_live(min_age=9999.0)
if kept:
    failures.append(f"fresh .part was repaired despite min_age guard: {kept}")
if partial not in _read_live_registry():
    failures.append("fresh .part entry was dropped by the sweep")
else:
    print("[recover] fresh .part correctly kept (min_age guard)")

# 4) stale file -> sweep must repair into a playable mp4 and clear the entry
time.sleep(1.1)
recovered = recover_interrupted_live(min_age=0.0)
print(f"[recover] sweep returned {recovered}")
if not recovered or not any(p == final for p in recovered):
    failures.append(f"sweep did not recover expected file: {recovered}")
elif not os.path.exists(final):
    failures.append(f"recovered file missing on disk: {final}")
else:
    kinds, dur = probe_duration(final)
    print(f"[recover] repaired streams={kinds} duration={dur:.2f}s")
    if "video" not in kinds or "audio" not in kinds:
        failures.append(f"repaired file missing streams: {kinds}")
    if dur < 1:
        failures.append(f"repaired duration too short: {dur}")
if os.path.exists(partial):
    failures.append("partial not cleaned after repair")
reg = _read_live_registry()
if reg:
    failures.append(f"registry not cleared: {reg}")
else:
    print("[recover] registry cleared after repair")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("LIVE RECOVERY TEST PASSED")
