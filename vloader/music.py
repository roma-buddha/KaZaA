"""YouTube music search + audio preview helpers."""
import os
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

import yt_dlp

from .downloader import find_ffmpeg

PREVIEW_SECONDS = 20


def search(query, limit=15):
    """Search YouTube for music videos; return [{id,title,artist,duration,url}]."""
    opts = {"quiet": True, "noplaylist": True, "socket_timeout": 20,
            "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    out = []
    for e in (info.get("entries") or []):
        if not e or not e.get("id"):
            continue
        out.append({
            "id": e["id"],
            "title": (e.get("title") or "").strip(),
            "artist": (e.get("uploader") or e.get("channel") or "").strip(),
            "duration": int(e.get("duration") or 0),
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        })
    return out


def direct_audio_url(watch_url):
    """Resolve a watch URL to a direct audio-only stream URL (m4a preferred,
    so the preview plays on the Windows media backend)."""
    opts = {"quiet": True, "noplaylist": True, "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(watch_url, download=False)
    auds = [f for f in (info.get("formats") or [])
            if f.get("acodec") not in (None, "none")
            and f.get("vcodec") in (None, "none") and f.get("url")]
    if not auds:
        raise RuntimeError("no audio-only stream found for this video")
    best = sorted(auds, key=lambda f: (f.get("ext") == "m4a",
                                       f.get("abr") or 0))[ -1]
    return best["url"]


class PreviewFetcher(QThread):
    """Download the first PREVIEW_SECONDS of a song to a temp file."""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, watch_url, parent=None):
        super().__init__(parent)
        self.watch_url = watch_url

    def run(self):
        try:
            url = direct_audio_url(self.watch_url)
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                self.failed.emit("ffmpeg not found")
                return
            fd, dest = tempfile.mkstemp(prefix="vloader_preview_",
                                        suffix=".m4a")
            os.close(fd)
            rc = subprocess.run(
                [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-t", str(PREVIEW_SECONDS), "-i", url, "-c", "copy", dest],
                capture_output=True, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ).returncode
            if rc == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0:
                self.done.emit(dest)
            else:
                try:
                    os.remove(dest)
                except OSError:
                    pass
                self.failed.emit("could not fetch preview audio")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
