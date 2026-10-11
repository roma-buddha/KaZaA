"""BitTorrent engine: libtorrent-backed QThread worker.

Same interface as DownloadWorker (progress / finished_ok / failed / cancel),
so the DownloadManager queue and the activity UI consume torrents unchanged.

Supports magnet URIs, local .torrent files and http(s) links to .torrent
files.  Downloads are sequential-by-default so video files are playable
while still downloading (like qBittorrent's "download in sequential order").
"""
import os
import re
import time
import urllib.request

from PySide6.QtCore import QThread, Signal

import libtorrent as lt

from .settings import Settings


def is_torrent_source(url):
    """magnet link or .torrent file/link (local path or http(s))."""
    if not url:
        return False
    low = url.lower().strip()
    if low.startswith("magnet:"):
        return True
    low = low.split("?")[0].split("#")[0]
    return low.endswith(".torrent")


def _fmt_eta(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _fmt_rate(bps):
    if bps >= 1024 * 1024:
        return f"{bps / 1024 / 1024:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"


_SESSION = None


def _session():
    """One shared libtorrent session for the whole app (single DHT node)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = lt.session({
            "listen_interfaces": "0.0.0.0:0",   # ephemeral port
            "enable_dht": True,
            "enable_lsd": True,
            "enable_upnp": False,
            "enable_natpmp": False,
            "announce_to_all_trackers": True,
            "announce_to_all_tiers": True,
            "user_agent": "KazaA/2.0",
        })
    return _SESSION


class TorrentWorker(QThread):
    progress = Signal(dict)          # {status, percent, speed, eta, size, name}
    finished_ok = Signal(dict)       # {output, name, size}
    failed = Signal(str)

    METADATA_TIMEOUT = 180.0

    def __init__(self, source, settings: Settings, sequential=True,
                 peers=None, parent=None):
        """source: magnet URI, path to a .torrent file, or http(s) .torrent
        link.  peers: optional [(ip, port), ...] for tests/manual bootstrap."""
        super().__init__(parent)
        self.source = source.strip()
        self.settings = settings
        self.sequential = sequential
        self._peers = peers or []
        self._cancelled = False
        self._handle = None

    def cancel(self):
        self._cancelled = True

    # -- source loading ----------------------------------------------------
    def _load_params(self):
        src = self.source
        if src.lower().startswith("magnet:"):
            p = lt.parse_magnet_uri(src)
            p.save_path = self.settings.download_dir()
            return p, None
        if re.match(r"^https?://", src, re.I):
            req = urllib.request.Request(src, headers={
                "User-Agent": "Mozilla/5.0 (KazaA)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        else:
            with open(src, "rb") as f:
                raw = f.read()
        try:
            ti = lt.torrent_info(lt.bdecode(raw))
        except Exception:
            ti = lt.torrent_info(raw)
        p = {"ti": ti, "save_path": self.settings.download_dir()}
        return p, ti.name()

    # -- main loop ---------------------------------------------------------
    def run(self):
        from .debuglog import log as dbg
        try:
            params, name_hint = self._load_params()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"cannot load torrent: {type(e).__name__}: {e}")
            return
        ses = _session()
        try:
            h = ses.add_torrent(params)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"cannot add torrent: {type(e).__name__}: {e}")
            return
        self._handle = h
        if self.sequential:
            h.set_sequential_download(True)
        for ip, port in self._peers:
            h.connect_peer((ip, port))

        name = name_hint or h.status().name or os.path.basename(
            self.source)[:60] or "torrent"
        dbg(f"torrent: added {name!r} ({self.source[:80]!r})")

        meta_deadline = time.monotonic() + self.METADATA_TIMEOUT
        last_emit = 0.0
        while not self._cancelled:
            s = h.status()
            now = time.monotonic()
            if not s.has_metadata:
                if now > meta_deadline:
                    ses.remove_torrent(h)
                    self.failed.emit(
                        "no peers found — metadata for this magnet could "
                        "not be downloaded")
                    return
                if now - last_emit >= 1.0:
                    last_emit = now
                    self.progress.emit({
                        "status": "downloading", "percent": 0.0,
                        "speed": f"{s.num_peers} peers",
                        "eta": "metadata…", "size": 0, "name": name})
                time.sleep(0.5)
                continue

            if s.errc and s.errc.value() != 0:
                ses.remove_torrent(h)
                self.failed.emit(f"torrent error: {s.errc.message()}")
                return

            done = s.total_done
            total = s.total_wanted
            rate = s.download_rate
            if now - last_emit >= 1.0:
                last_emit = now
                eta = _fmt_eta((total - done) / rate) if rate > 0 else "∞"
                self.progress.emit({
                    "status": "downloading",
                    "percent": s.progress * 100.0,
                    "speed": f"{_fmt_rate(rate)} · {s.num_peers} peers",
                    "eta": eta, "size": total, "name": name})

            if s.is_seeding or s.progress >= 1.0:
                # note: s.save_path, not the current setting — a torrent
                # already sitting in the session may live elsewhere
                out = os.path.join(s.save_path, s.name)
                dbg(f"torrent: done {out!r} ({total} bytes)")
                self.finished_ok.emit({"output": out, "name": name,
                                       "size": total})
                return
            time.sleep(0.5)

        # cancelled: drop the torrent but KEEP partial data (resume re-adds
        # and libtorrent re-checks existing pieces).
        dbg("torrent: cancelled, keeping partial data")
        try:
            ses.remove_torrent(h)
        except Exception as e:  # noqa: BLE001
            dbg(f"torrent: remove_torrent failed: {e}")
        self._handle = None
        self.failed.emit("cancelled")
