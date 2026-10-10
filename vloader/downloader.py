"""Download engine: yt-dlp driven QThread workers with queue + concurrency control."""
import os
import re

from PySide6.QtCore import QObject, QThread, Signal

import yt_dlp

from .settings import Settings


class DownloadCancelled(Exception):
    pass


def quality_to_formatsel(quality):
    if quality == "best":
        return "bestvideo*+bestaudio/best"
    if quality == "worst":
        return "worst"
    try:
        h = int(quality)
    except (TypeError, ValueError):
        return "bestvideo*+bestaudio/best"
    # pick the best stream not exceeding the requested height
    return (f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/"
            f"bestvideo*+bestaudio/best")


class DownloadWorker(QThread):
    progress = Signal(dict)          # {status, percent, speed, eta, size, name}
    finished_ok = Signal(dict)       # {output, name, size}
    failed = Signal(str)

    def __init__(self, url, settings: Settings, quality=None, parent=None):
        super().__init__(parent)
        self.url = url
        self.settings = settings
        self.quality = quality or settings.get("download_quality")
        self._ydl = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _hook(self, d):
        if self._cancelled:
            raise DownloadCancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            percent = (done / total * 100.0) if total else 0.0
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            name = os.path.basename(d.get("filename", ""))
            self.progress.emit({
                "status": "downloading", "percent": percent, "speed": speed,
                "eta": eta, "size": total, "name": name,
            })
        elif d.get("status") == "finished":
            self.progress.emit({"status": "postprocessing", "percent": 100.0})

    def run(self):
        outtmpl = os.path.join(
            self.settings.download_dir(), "%(title).180B [%(id)s].%(ext)s")
        opts = {
            "format": quality_to_formatsel(self.quality),
            "outtmpl": outtmpl,
            "progress_hooks": [self._hook],
            "continuedl": True,
            "noplaylist": False,
            "ignoreerrors": False,
            "retries": 3,
            "windows_filenames": True,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_color": True,
        }
        # prefer the bundled ffmpeg so merging/convert works out of the box
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = os.path.dirname(ffmpeg)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._ydl = ydl
                info = ydl.extract_info(self.url, download=True)
                if info is None:
                    raise DownloadCancelled()
                entries = info.get("entries") or [info]
                last = None
                for e in entries:
                    if e:
                        last = e
                name = (last or {}).get("title", self.url)
                out = ydl.prepare_filename(last) if last else ""
                size = (last or {}).get("filesize") or (last or {}).get("filesize_approx") or 0
                # best single guess if merging produced another ext
                if out and not os.path.exists(out):
                    base, _ext = os.path.splitext(out)
                    for cand in (base + ".mp4", base + ".mkv"):
                        if os.path.exists(cand):
                            out = cand
                            break
                self.finished_ok.emit({"output": out, "name": name, "size": size})
        except DownloadCancelled:
            self.failed.emit("cancelled")
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            cause = getattr(e, "exc_info", None)
            if cause and cause[0] is DownloadCancelled or "Cancelled" in msg:
                self.failed.emit("cancelled")
            else:
                self.failed.emit(msg)
        except Exception as e:  # noqa: BLE001 - surface anything to the UI
            self.failed.emit(f"{type(e).__name__}: {e}")


def find_ffmpeg():
    """Return path to ffmpeg.exe: source-tree bin/, frozen bundle, then PATH."""
    import sys
    candidates = []
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(here, "bin", "ffmpeg.exe"))
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(meipass, "bin", "ffmpeg.exe"))
        candidates.append(os.path.join(exe_dir, "bin", "ffmpeg.exe"))
    for c in candidates:
        if os.path.exists(c):
            return c
    from shutil import which
    return which("ffmpeg")


class DownloadManager(QObject):
    """Queues workers, enforces the simultaneous-download limit."""
    task_progress = Signal(int, dict)     # task_id, info dict
    task_finished = Signal(int, dict)
    task_failed = Signal(int, str)
    queue_changed = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._next_id = 1
        self._pending = []       # list of (task_id, url, quality)
        self._running = {}       # task_id -> worker

    def submit(self, url, quality=None):
        url = (url or "").strip()
        if not url:
            return None
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            url = "https://" + url
        task_id = self._next_id
        self._next_id += 1
        self._pending.append((task_id, url, quality))
        self.queue_changed.emit()
        self._pump()
        return task_id

    def _pump(self):
        limit = max(1, int(self.settings.get("simultaneous_downloads")))
        while self._pending and len(self._running) < limit:
            task_id, url, quality = self._pending.pop(0)
            w = DownloadWorker(url, self.settings, quality)
            w.progress.connect(lambda info, tid=task_id: self.task_progress.emit(tid, info))
            w.finished_ok.connect(lambda res, tid=task_id: self._done(tid, res))
            w.failed.connect(lambda msg, tid=task_id: self._fail(tid, msg))
            self._running[task_id] = w
            self.task_progress.emit(task_id, {"status": "starting", "percent": 0.0})
            w.start()
        self.queue_changed.emit()

    def _done(self, task_id, res):
        self._cleanup(task_id)
        self.task_finished.emit(task_id, res)

    def _fail(self, task_id, msg):
        self._cleanup(task_id)
        self.task_failed.emit(task_id, msg)

    def _cleanup(self, task_id):
        w = self._running.pop(task_id, None)
        if w:
            w.wait(3000)
        self._pump()

    def cancel(self, task_id):
        """Pause/stop: cancel a running worker; partial file stays for resume."""
        w = self._running.get(task_id)
        if w:
            w.cancel()
        else:
            self._pending = [p for p in self._pending if p[0] != task_id]
            self.queue_changed.emit()

    def resume(self, task_id, url, quality=None):
        self._pending.append((task_id, url, quality))
        self.queue_changed.emit()
        self._pump()

    def active_count(self):
        return len(self._running)
