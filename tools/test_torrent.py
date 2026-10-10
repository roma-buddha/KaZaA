"""Torrent engine test: a local in-process seeder feeds TorrentWorker.

Covers: .torrent file download, magnet link download (metadata fetched from
the seeder), cancel semantics (partial data kept), is_torrent_source().
No network outside loopback.
"""
import os
import socket
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402
app = QCoreApplication(sys.argv)

import libtorrent as lt  # noqa: E402

from vloader.settings import Settings  # noqa: E402
from vloader import torrent as tor  # noqa: E402
from vloader.torrent import TorrentWorker, is_torrent_source  # noqa: E402

failures = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        failures.append(msg)
        print(f"  FAIL: {msg}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


tmp = tempfile.mkdtemp(prefix="vloader_torrent_")
srcdir = os.path.join(tmp, "src")
dldir = os.path.join(tmp, "dl")
os.makedirs(srcdir)
os.makedirs(dldir)

PAYLOAD = os.path.join(srcdir, "clip.mp4")
with open(PAYLOAD, "wb") as f:
    f.write(os.urandom(4 * 1024 * 1024))

# --- build a .torrent + magnet for the payload -------------------------
fs = lt.file_storage()
lt.add_files(fs, PAYLOAD)
ct = lt.create_torrent(fs, piece_size=256 * 1024)
lt.set_piece_hashes(ct, srcdir)
entry = ct.generate()               # bdecoded dict in libtorrent 2.1
ti = lt.torrent_info(entry)
tor_path = os.path.join(tmp, "test.torrent")
with open(tor_path, "wb") as f:
    f.write(lt.bencode(entry))
magnet = lt.make_magnet_uri(ti)
print(f"[torrent] payload 4MB, magnet={magnet[:60]}...")

PORT = free_port()
seed = lt.session({
    "listen_interfaces": f"0.0.0.0:{PORT}",
    "enable_dht": False, "enable_lsd": False,
    "enable_upnp": False, "enable_natpmp": False,
})
sh = seed.add_torrent({"ti": ti, "save_path": srcdir})
deadline = time.time() + 15
while not sh.status().is_seeding and time.time() < deadline:
    time.sleep(0.1)
check(sh.status().is_seeding, "seeder is seeding")
print(f"[torrent] seeder on 127.0.0.1:{PORT}")


def run_worker(source, dest_dir, timeout=90, cancel_after=None):
    """Start a TorrentWorker; pump events; return (result, failure, infos)."""
    results, fails, infos = [], [], []
    settings = Settings()
    settings.set("save_to", dest_dir)
    w = TorrentWorker(source, settings, peers=[("127.0.0.1", PORT)])
    w.finished_ok.connect(lambda r: results.append(r))
    w.failed.connect(lambda m: fails.append(m))
    w.progress.connect(lambda i: infos.append(i))
    w.start()
    deadline = time.time() + timeout
    cancelled = False
    while w.isRunning() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.1)
        if (cancel_after and not cancelled
                and infos and infos[-1].get("percent", 0) >= cancel_after):
            w.cancel()
            cancelled = True
    if w.isRunning():
        w.cancel()
        w.wait(5000)
    app.processEvents()
    return results, fails, infos


# --- unit checks ---------------------------------------------------------
print("[1] is_torrent_source")
check(is_torrent_source("magnet:?xt=urn:btih:abc"), "magnet detected")
check(is_torrent_source(tor_path), "local .torrent path detected")
check(is_torrent_source("https://x.io/f.torrent"), "http .torrent detected")
check(not is_torrent_source("https://youtube.com/watch?v=1"), "youtube not torrent")
check(not is_torrent_source("spotify:track:abc"), "spotify not torrent")

# --- case A: .torrent file ----------------------------------------------
print("[2] download via .torrent file")
d1 = os.path.join(dldir, "a")
os.makedirs(d1)
res, fail, infos = run_worker(tor_path, d1)
check(bool(res), f"finished_ok received (fail={fail})")
if res:
    out = res[0]["output"]
    check(os.path.exists(out), f"output exists: {out}")
    if os.path.exists(out):
        with open(out, "rb") as f:
            check(f.read() == open(PAYLOAD, "rb").read(), "bytes identical")
    check(res[0].get("size", 0) > 0, "size reported")
check(any(i.get("percent", 0) > 0 for i in infos), "progress emitted")
check(not fail, "no failure signal")

# --- case B: magnet link -------------------------------------------------
print("[3] download via magnet (metadata from seeder)")
d2 = os.path.join(dldir, "b")
os.makedirs(d2)
res, fail, infos = run_worker(magnet, d2)
check(bool(res), f"finished_ok received (fail={fail})")
if res:
    out = res[0]["output"]
    check(os.path.exists(out) and
          open(out, "rb").read() == open(PAYLOAD, "rb").read(),
          "bytes identical via magnet")

# --- case C: cancel is honored promptly (no peers -> stuck in metadata
#     phase, so the cancel is deterministic) ------------------------------
print("[4] cancel while fetching metadata (no peers)")
d3 = os.path.join(dldir, "c")
os.makedirs(d3)
# a torrent nobody seeds: different info-hash (different content), no peer
# has it, so metadata can never arrive and the worker waits until cancelled
ghost = os.path.join(srcdir, "ghost.bin")
with open(ghost, "wb") as f:
    f.write(os.urandom(512 * 1024))
fsg = lt.file_storage()
lt.add_files(fsg, ghost)
ctg = lt.create_torrent(fsg, piece_size=128 * 1024)
lt.set_piece_hashes(ctg, srcdir)
dead_magnet = lt.make_magnet_uri(lt.torrent_info(ctg.generate()))
settings = Settings()
settings.set("save_to", d3)
w = TorrentWorker(dead_magnet, settings)
fails, infos = [], []
w.failed.connect(lambda m: fails.append(m))
w.progress.connect(lambda i: infos.append(i))
w.start()
time.sleep(0.5)
w.cancel()
t0 = time.time()
while w.isRunning() and time.time() - t0 < 10:
    app.processEvents()
    time.sleep(0.05)
for _ in range(10):              # drain the queued 'cancelled' signal
    app.processEvents()
    time.sleep(0.05)
check(not w.isRunning(), "worker thread exits promptly after cancel")
check("cancelled" in fails, f"cancelled signal (fail={fails})")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("TORRENT TESTS PASSED")
