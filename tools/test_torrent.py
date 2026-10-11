"""Torrent engine test: a local in-process seeder feeds TorrentWorker.

Covers: .torrent file download, magnet link download (metadata fetched from
the seeder), cancel semantics (partial data kept), is_torrent_source().
No network outside loopback.
"""
import os
import socket
import sys
import tempfile
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "minimal"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402
app = QCoreApplication(sys.argv)

import libtorrent as lt  # noqa: E402

from kazaa.settings import Settings  # noqa: E402
from kazaa import torrent as tor  # noqa: E402
from kazaa.torrent import TorrentWorker, is_torrent_source  # noqa: E402

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


tmp = tempfile.mkdtemp(prefix="kazaa_torrent_")
os.environ["APPDATA"] = os.path.join(tmp, "profile")
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

PORT = 0
seed = lt.session({
    "listen_interfaces": f"127.0.0.1:{PORT}",
    "enable_dht": False, "enable_lsd": False,
    "enable_upnp": False, "enable_natpmp": False,
})
tor._SESSION = lt.session({"listen_interfaces": "127.0.0.1:0", "enable_dht": False,
                          "enable_lsd": False, "enable_upnp": False, "enable_natpmp": False})
sh = seed.add_torrent({"ti": ti, "save_path": srcdir})
deadline = time.time() + 15
while (not sh.status().is_seeding or not seed.listen_port()) and time.time() < deadline:
    time.sleep(0.1)
check(sh.status().is_seeding, "seeder is seeding")
PORT = seed.listen_port()
check(PORT > 0, "seeder has an assigned loopback port")
if not PORT:
    for alert in seed.pop_alerts():
        print(type(alert).__name__, alert.message())
    raise SystemExit("The local test seeder could not listen.")
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

print("[5] new torrent backend: metadata, selection, resume and cleanup")
from pathlib import Path
from unittest.mock import patch
from kazaa import torrent_backend as backend

bundle = Path(srcdir, "Bundle")
bundle.mkdir()
(bundle / "first.bin").write_bytes(os.urandom(6 * 1024 * 1024))
(bundle / "nested").mkdir()
(bundle / "nested/second.bin").write_bytes(os.urandom(6 * 1024 * 1024))
multi_fs = lt.file_storage()
lt.add_files(multi_fs, str(bundle))
multi_create = lt.create_torrent(multi_fs, piece_size=128 * 1024, flags=lt.create_torrent.v1_only)
lt.set_piece_hashes(multi_create, srcdir)
multi_ti = lt.torrent_info(multi_create.generate())
multi_path = Path(tmp, "bundle with spaces.torrent")
multi_path.write_bytes(lt.bencode(multi_create.generate()))
multi_seed = seed.add_torrent({"ti": multi_ti, "save_path": srcdir})
deadline = time.monotonic() + 15
while not multi_seed.status().is_seeding and time.monotonic() < deadline:
    time.sleep(0.05)
check(multi_seed.status().is_seeding, "multi-file loopback seeder is ready")

class DeadlineStop:
    def __init__(self, seconds=45):
        self.deadline = time.monotonic() + seconds
        self.stopped = False
    def is_set(self):
        return self.stopped or time.monotonic() > self.deadline

sessions = []
bootstrap_stop = threading.Event()
bootstrap_threads = []
session_settings = {"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False,
                    "enable_upnp": False, "enable_natpmp": False}
request_base = {"cache_dir": str(Path(tmp, "cache")), "peers": [("127.0.0.1", PORT)],
                "session_settings": session_settings}
original_session = backend.session
def track_session(engine, request):
    result = original_session(engine, request)
    sessions.append(result)
    if "options" in request:
        # File rechecking can discard an early bootstrap connection. Keep
        # advertising the local seeder, as discovery would in a real swarm.
        def bootstrap():
            while not bootstrap_stop.wait(0.5):
                for torrent_handle in result.get_torrents():
                    status = torrent_handle.status()
                    if status.state == lt.torrent_status.downloading and not status.num_peers:
                        torrent_handle.connect_peer(("127.0.0.1", PORT))
        thread = threading.Thread(target=bootstrap, daemon=True)
        bootstrap_threads.append(thread)
        thread.start()
    return result

try:
    with patch.object(backend, "session", side_effect=track_session):
        info = backend.inspect_torrent({**request_base, "url": multi_path.as_uri()}, DeadlineStop())
        check(not sessions, "local torrent inspection does not create a network session")
        import json
        import subprocess
        worker_request = {**request_base, "action": "inspect", "source": "torrent", "url": multi_path.as_uri()}
        process = subprocess.run([sys.executable, "-m", "kazaa.video_worker"], input=json.dumps(worker_request),
                                 capture_output=True, text=True, encoding="utf-8", timeout=15)
        messages = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
        check(process.returncode == 0 and messages[-1]["type"] == "result" and
              messages[-1]["data"]["hashes"] == info["hashes"], "isolated worker routes torrent inspection correctly")
        moved = multi_path.with_suffix(".moved")
        multi_path.rename(moved)
        magnet_info = backend.inspect_torrent({**request_base, "url": lt.make_magnet_uri(multi_ti)}, DeadlineStop())
        check(info["hashes"] == magnet_info["hashes"], "file and magnet resolve to the same torrent")
        check(not sessions[-1].get_torrents(), "inspection removes its torrent handle")
        check(not list(Path(tmp, "cache/inspection").rglob("*.bin")), "magnet inspection downloads no payload files")
        selected_index = next(item["index"] for item in info["manifest"] if item["path"].endswith("first.bin"))
        second_index = next(item["index"] for item in info["manifest"] if item["path"].endswith("second.bin"))
        destination = Path(tmp, "modern-download")
        resume = Path(tmp, "modern.resume")
        request = {**request_base, "url": info["url"], "torrent": {**info, "resume_file": str(resume)},
                   "options": {"folder": str(destination), "selected_files": [selected_index]}}
        stop = DeadlineStop()
        progress = []
        def pause_after_progress(kind, data):
            progress.append(data)
            if data.get("downloaded_bytes", 0) > 0:
                stop.stopped = True
        try:
            # Keep the loopback transfer active long enough to observe progress
            # and request a pause before the selected payload completes.
            pause_request = {**request, "session_settings": {
                **session_settings, "download_rate_limit": 1024 * 1024,
                "ignore_limits_on_local_network": False}}
            backend.download_torrent(pause_request, pause_after_progress, stop)
            check(False, "download pauses after receiving some payload")
        except ValueError as exc:
            check(str(exc) == "Cancelled", "pause returns the existing cancellation contract")
        check(resume.is_file(), "pause saves resume data")
        check(any(data.get("torrent_health", {}).get("seeds", 0) > 0 and
                  data["torrent_health"]["active"] for data in progress),
              "worker progress reports observed loopback seed and torrent health")
        check(not sessions[-1].get_torrents(), "pause removes its torrent handle")
        result = backend.download_torrent(request, lambda *args: None, DeadlineStop())
        first_output = destination / next(f["path"] for f in info["manifest"] if f["index"] == selected_index)
        second_output = destination / next(f["path"] for f in info["manifest"] if f["index"] == second_index)
        check(first_output.read_bytes() == (bundle / "first.bin").read_bytes(), "selected file bytes survive pause/resume")
        check(not second_output.exists(), "unselected file is not materialized")
        check(result["size"] == 6 * 1024 * 1024, "completion size counts only selected files")
        check(not sessions[-1].get_torrents(), "completion stops sharing and removes the torrent handle")
        resume.write_bytes(b"corrupt resume data")
        result = backend.download_torrent({**request, "owned_files": result["files"],
                                         "options": {"folder": str(destination), "selected_files": [second_index]}},
                                        lambda *args: None, DeadlineStop())
        check(second_output.read_bytes() == (bundle / "nested/second.bin").read_bytes(), "corrupt resume falls back to checking existing files")
        check(first_output.is_file() and len(result["files"]) == 2, "additional selection preserves previous output files")
        check(not sessions[-1].get_torrents(), "additional selection leaves no seeding session")
        process = subprocess.run([sys.executable, "-m", "kazaa.video_worker"],
                                 input=json.dumps({**request, "action": "download", "source": "torrent", "owned_files": result["files"]}),
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        messages = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
        check(process.returncode == 0 and messages[-1]["type"] == "result" and
              first_output.read_bytes() == (bundle / "first.bin").read_bytes(), "isolated worker routes torrent downloads correctly")
        try:
            backend.inspect_torrent({**request_base, "url": dead_magnet, "metadata_timeout": 0.2}, DeadlineStop())
            check(False, "unavailable metadata times out")
        except ValueError as exc:
            check("metadata" in str(exc), "unavailable metadata gives a clear timeout error")
        check(not sessions[-1].get_torrents(), "metadata failure removes its torrent handle")
except Exception as exc:
    import traceback
    traceback.print_exc()
    check(False, "new backend failed: " + str(exc))
finally:
    bootstrap_stop.set()
    for thread in bootstrap_threads:
        thread.join(timeout=2)

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("TORRENT TESTS PASSED")
