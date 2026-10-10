"""YouTube music search + audio preview helpers."""
import os
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

import yt_dlp

from .downloader import (YOUTUBE_ALT_CLIENT, find_ffmpeg, is_bot_check,
                         ydl_cookie_opts)

PREVIEW_SECONDS = 20


def _extract(url_or_query, settings=None, flat=False):
    """Run yt-dlp extraction, tolerating YouTube's intermittent bot wall:
    once with the configured browser cookies (if any), and once more with an
    alternate player client before surfacing a concise error."""
    base = {"quiet": True, "noplaylist": True, "socket_timeout": 20}
    if flat:
        base["extract_flat"] = False
    base.update(ydl_cookie_opts(settings))
    try:
        with yt_dlp.YoutubeDL(base) as ydl:
            return ydl.extract_info(url_or_query, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if not is_bot_check(msg) or ydl_cookie_opts(settings):
            raise
        try:
            with yt_dlp.YoutubeDL({**base, **YOUTUBE_ALT_CLIENT}) as ydl:
                return ydl.extract_info(url_or_query, download=False)
        except yt_dlp.utils.DownloadError as e2:
            raise RuntimeError(
                "YouTube asks for sign-in (bot check). Enable browser "
                f"cookies in Options, or retry later. [{str(e2)[:100]}]")


def search(query, limit=15, settings=None):
    """Search YouTube for music videos; return [{id,title,artist,duration,url}]."""
    info = _extract(f"ytsearch{limit}:{query}", settings, flat=True)
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


def direct_audio_url(watch_url, settings=None):
    """Resolve a watch URL to a direct audio-only stream URL (m4a preferred,
    so the preview plays on the Windows media backend)."""
    info = _extract(watch_url, settings)
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

    def __init__(self, watch_url, parent=None, settings=None):
        super().__init__(parent)
        self.watch_url = watch_url
        self.settings = settings

    def run(self):
        try:
            url = direct_audio_url(self.watch_url, self.settings)
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
