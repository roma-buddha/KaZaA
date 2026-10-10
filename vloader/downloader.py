"""Download engine: yt-dlp driven QThread workers with queue + concurrency control."""
import os
import re
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal

import yt_dlp

from .settings import Settings
from . import spotify


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

    def __init__(self, url, settings: Settings, quality=None, subtitles=None,
                 transcript_only=False, parent=None):
        super().__init__(parent)
        self.url = url
        self.settings = settings
        self.quality = quality or settings.get("download_quality")
        # subtitles: None or {"format": "md"|"srt"|"vtt", "langs": [...],
        #                     "auto": bool}
        self.subtitles = subtitles
        self.transcript_only = transcript_only
        self._ydl = None
        self._cancelled = False
        self._live = False
        self._partial = ""

    def cancel(self):
        self._cancelled = True

    def _hook(self, d):
        if self._cancelled:
            raise DownloadCancelled()
        if d.get("status") == "downloading":
            if d.get("filename"):
                self._partial = d["filename"]
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            percent = (done / total * 100.0) if total else None
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            elapsed = d.get("_elapsed_str", "").strip()
            name = os.path.basename(d.get("filename", ""))
            info = {
                "status": "downloading", "speed": speed, "eta": eta,
                "size": total, "name": name,
            }
            if self._live:
                info["live"] = True
                info["elapsed"] = elapsed
            elif percent is not None:
                info["percent"] = percent
            self.progress.emit(info)
        elif d.get("status") == "finished":
            self.progress.emit({"status": "postprocessing", "percent": 100.0})

    def run(self):
        if spotify.is_spotify_url(self.url):
            try:
                self.finished_ok.emit(self._download_spotify())
            except DownloadCancelled:
                self.failed.emit("cancelled")
            except spotify.SpotifyError as e:
                self.failed.emit(str(e))
            except Exception as e:  # noqa: BLE001 - surface anything to the UI
                self.failed.emit(f"{type(e).__name__}: {e}")
            return
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
        if self.subtitles:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = bool(self.subtitles.get("auto", True))
            opts["subtitleslangs"] = self.subtitles.get("langs") or ["en"]
            opts["subtitlesformat"] = "vtt"
        if self.transcript_only:
            opts["skip_download"] = True
        # prefer the bundled ffmpeg so merging/convert works out of the box
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = os.path.dirname(ffmpeg)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._ydl = ydl
                # metadata first so live streams get a merge-free format
                pre = ydl.extract_info(self.url, download=False)
                if pre is None:
                    raise DownloadCancelled()
                self._live = bool(
                    pre.get("is_live")
                    or pre.get("live_status") == "is_live"
                    or any((e or {}).get("is_live")
                           for e in (pre.get("entries") or [])))
                if self._live:
                    # Live HLS is handled by a directly managed ffmpeg process:
                    # yt-dlp's FFmpegFD never emits progress hooks and hides the
                    # child process, so pause/stop/control must live here.
                    self.finished_ok.emit(self._download_live(pre))
                    return
                else:
                    info = ydl.process_ie_result(pre, download=True)
                if info is None:
                    raise DownloadCancelled()
                entries = info.get("entries") or [info]
                last = None
                for e in entries:
                    if e:
                        last = e
                name = (last or {}).get("title", self.url)
                out = ydl.prepare_filename(last) if last else ""
                transcripts_done = []
                if self.subtitles and out:
                    transcripts_done = self._convert_subtitles(out)
                if self.transcript_only:
                    out = transcripts_done[0] if transcripts_done else ""
                size = (last or {}).get("filesize") or (last or {}).get("filesize_approx") or 0
                # best single guess if merging produced another ext
                if out and not os.path.exists(out):
                    base, _ext = os.path.splitext(out)
                    for cand in (base + ".mp4", base + ".mkv"):
                        if os.path.exists(cand):
                            out = cand
                            break
                self.finished_ok.emit({"output": out, "name": name, "size": size,
                                       "transcripts": transcripts_done,
                                       "transcript_only": self.transcript_only})
        except DownloadCancelled:
            if self._live and self._partial and os.path.exists(self._partial):
                repaired = self._repair_live(self._partial)
                if repaired:
                    self.finished_ok.emit({"output": repaired, "name": "",
                                           "size": os.path.getsize(repaired),
                                           "stopped": True, "live": True})
                    return
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


    @staticmethod
    def _fmt_elapsed(seconds):
        seconds = int(seconds or 0)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @staticmethod
    def _safe_name(name):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or ""))
        return name.strip(" .") or "live"

    def _download_live(self, pre):
        """Record a live HLS stream with a directly managed ffmpeg process.

        FFmpeg is spawned with stdin=PIPE so Stop can send a graceful 'q'
        (ffmpeg finalizes the mp4 moov box -> immediately playable file),
        and stderr=PIPE so we can parse `time=` for progress.  Returns the
        finished_ok result dict; raises DownloadError on failure.
        """
        info = pre
        if pre.get("entries"):
            info = next((e for e in pre["entries"] if e), pre)
        formats = info.get("formats") or info.get("requested_formats") or []
        vids = sorted(
            (f for f in formats if f.get("vcodec") not in (None, "none")),
            key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        if not vids:
            raise yt_dlp.utils.DownloadError(
                "no downloadable video stream found for this live page")
        q = str(self.quality)
        if q == "worst":
            video = vids[0]
        elif q.isdigit():
            capped = [f for f in vids if (f.get("height") or 0) <= int(q)]
            video = (capped or vids)[-1]
        else:
            video = vids[-1]
        audio = None
        if (video.get("acodec") or "none") == "none":
            auds = sorted(
                (f for f in formats
                 if f.get("vcodec") in (None, "none") and f is not video),
                key=lambda f: f.get("tbr") or 0)
            audio = auds[-1] if auds else None

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise yt_dlp.utils.DownloadError("ffmpeg executable not found")
        out_base = os.path.join(
            self.settings.download_dir(),
            self._safe_name(info.get("title")) + ".mp4")
        out, n = out_base, 1
        while os.path.exists(out) or os.path.exists(out + ".part"):
            out = f"{out_base[:-4]} ({n}).mp4"
            n += 1
        partial = out + ".part"
        self._partial = partial

        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "info"]
        inputs = [video] + ([audio] if audio else [])
        for fmt in inputs:
            headers = fmt.get("http_headers") or info.get("http_headers") or {}
            if headers:
                cmd += ["-headers",
                        "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
            cmd += ["-i", fmt["url"]]
        cmd += ["-map", "0:v:0?"]
        cmd += ["-map", "1:a:0?" if audio else "0:a:0?"]
        cmd += ["-c", "copy", "-f", "mp4", partial]

        state = {"elapsed": None, "tail": []}
        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

        def _reader():
            try:
                for line in proc.stderr:
                    m = time_re.search(line)
                    if m:
                        state["elapsed"] = (int(m.group(1)) * 3600
                                            + int(m.group(2)) * 60
                                            + float(m.group(3)))
                    tail = state["tail"]
                    tail.append(line.strip())
                    del tail[:-20]
            except (OSError, ValueError):
                pass

        self.progress.emit({
            "status": "downloading", "live": True,
            "elapsed": "0:00", "size": 0,
            "name": os.path.basename(out)})
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace")
        self._proc = proc
        threading.Thread(target=_reader, daemon=True).start()

        q_sent = False
        start = time.monotonic()
        last_emit = 0.0
        while True:
            try:
                rc = proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            if self._cancelled and not q_sent and proc.stdin:
                q_sent = True
                try:
                    proc.stdin.write("q\n")
                    proc.stdin.flush()
                except (OSError, ValueError):
                    pass
            now = time.monotonic()
            if now - last_emit >= 1.0:
                last_emit = now
                el = state["elapsed"]
                if el is None:
                    el = now - start
                try:
                    size = os.path.getsize(partial)
                except OSError:
                    size = 0
                self.progress.emit({
                    "status": "downloading", "live": True,
                    "elapsed": self._fmt_elapsed(el), "size": size,
                    "name": os.path.basename(out)})

        stopped = bool(self._cancelled or q_sent)
        if rc == 0 and os.path.exists(partial) and os.path.getsize(partial) > 0:
            os.replace(partial, out)
            return {"output": out, "name": os.path.basename(out),
                    "size": os.path.getsize(out), "live": True,
                    "stopped": stopped}
        if stopped and os.path.exists(partial):
            repaired = self._repair_live(partial)
            if repaired:
                return {"output": repaired,
                        "name": os.path.basename(repaired),
                        "size": os.path.getsize(repaired), "live": True,
                        "stopped": True}
        tail = " | ".join(state["tail"][-5:])
        raise yt_dlp.utils.DownloadError(
            f"ffmpeg exited with code {rc}: {tail or 'no output'}")

    def _fetch_cover(self, url, tmpdir):
        if not url:
            return None
        import urllib.request
        dest = os.path.join(tmpdir, "cover.jpg")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r, \
                    open(dest, "wb") as f:
                f.write(r.read())
            return dest if os.path.getsize(dest) > 1000 else None
        except Exception:  # noqa: BLE001 - cover is optional
            return None

    def _download_spotify(self):
        """Resolve a Spotify link and fetch every track as a tagged MP3.

        Audio comes from a public YouTube search for "artist - title" (the
        same approach every web Spotify downloader uses, since Spotify
        streams are DRM-protected); tags and cover art come from Spotify.
        """
        from .debuglog import log as dbg
        coll = spotify.resolve(self.url)
        tracks = coll["tracks"]
        n = len(tracks)
        dl = self.settings.download_dir()
        if coll["kind"] == "album":
            target_dir = os.path.join(
                dl, f"{self._safe_name(coll.get('artist'))} - "
                   f"{self._safe_name(coll['name'])}".strip(" -"))
        elif coll["kind"] == "playlist":
            target_dir = os.path.join(dl, self._safe_name(coll["name"]))
        else:
            target_dir = dl
        os.makedirs(target_dir, exist_ok=True)
        tmpdir = os.path.join(target_dir, ".vloader-tmp")
        os.makedirs(tmpdir, exist_ok=True)
        cover = self._fetch_cover(coll.get("cover"), tmpdir)
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise yt_dlp.utils.DownloadError("ffmpeg executable not found")

        cell = {"i": 0, "label": coll["name"]}

        def _hook(d):
            if self._cancelled:
                raise DownloadCancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                frac = done / total if total else 0
                self.progress.emit({
                    "status": "downloading",
                    "percent": (cell["i"] + frac) / n * 100.0,
                    "speed": (d.get("_speed_str") or "").strip(),
                    "name": cell["label"]})

        self.progress.emit({"status": "downloading", "percent": 0.0,
                            "name": coll["name"]})
        ok = 0
        first_out = ""
        total_size = 0
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_color": True,
            "retries": 2,
            "windows_filenames": True,
            "progress_hooks": [_hook],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for i, tr in enumerate(tracks):
                if self._cancelled:
                    raise DownloadCancelled()
                cell["i"] = i
                cell["label"] = (f"{i + 1}/{n} · {tr['title']}" if n > 1
                                 else tr["title"])
                try:
                    out = self._spotify_track(
                        ydl, tr, i, n, target_dir, tmpdir, cover, ffmpeg,
                        coll)
                except DownloadCancelled:
                    raise
                except Exception as e:  # noqa: BLE001 - skip bad tracks
                    import traceback
                    dbg(f"spotify track failed: {tr['title']}: {e}\n"
                        + traceback.format_exc())
                    self.progress.emit({
                        "status": "downloading", "percent": (i + 1) / n * 100.0,
                        "name": f"skipped: {tr['title']}"})
                    continue
                ok += 1
                total_size += os.path.getsize(out)
                if not first_out:
                    first_out = out
        try:
            for f in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, f))
            os.rmdir(tmpdir)
        except OSError:
            pass
        if ok == 0:
            raise yt_dlp.utils.DownloadError(
                "could not download any track (no matches found)")
        return {"output": first_out if coll["kind"] == "track" else target_dir,
                "name": coll["name"], "size": total_size, "spotify": True}

    def _spotify_track(self, ydl, tr, i, n, target_dir, tmpdir, cover,
                       ffmpeg, coll):
        """Download one track's audio and encode a tagged 320k MP3."""
        artists = tr.get("artists") or ""
        ydl.params["outtmpl"] = {
            "default": os.path.join(tmpdir, f"{i:03d}.%(ext)s")}
        info = ydl.extract_info(
            f"ytsearch1:{artists} - {tr['title']}", download=True)
        if not info:
            raise yt_dlp.utils.DownloadError("no match found")
        tmp = ydl.prepare_filename(info)
        if not os.path.exists(tmp):
            cands = sorted(
                os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
                if f.startswith(f"{i:03d}."))
            if not cands:
                raise yt_dlp.utils.DownloadError("download vanished")
            tmp = cands[0]

        if coll["kind"] == "track":
            fname = (f"{self._safe_name(artists)} - "
                     f"{self._safe_name(tr['title'])}.mp3")
        elif coll["kind"] == "album":
            fname = f"{i + 1:02d} - {self._safe_name(tr['title'])}.mp3"
        else:
            fname = (f"{i + 1:02d} - {self._safe_name(artists)} - "
                     f"{self._safe_name(tr['title'])}.mp3")
        final = os.path.join(target_dir, fname)
        base, ext = os.path.splitext(final)
        k = 1
        while os.path.exists(final):
            final = f"{base} ({k}){ext}"
            k += 1

        cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel",
               "error", "-i", tmp]
        if cover and os.path.exists(cover):
            cmd += ["-i", cover, "-map", "0:a:0", "-map", "1:v:0",
                    "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
        else:
            cmd += ["-map", "0:a:0"]
        cmd += ["-c:a", "libmp3lame", "-b:a", "320k",
                "-id3v2_version", "3",
                "-metadata", f"title={tr['title']}",
                "-metadata", f"artist={artists}"]
        if tr.get("album"):
            cmd += ["-metadata", f"album={tr['album']}"]
        if n > 1:
            cmd += ["-metadata", f"track={i + 1}"]
        cmd += [final]
        r = subprocess.run(cmd, capture_output=True, timeout=600,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.exists(final):
            raise RuntimeError(
                f"mp3 encode failed: {(r.stderr or b'')[-200:]!r}")
        os.remove(tmp)
        self.progress.emit({"status": "downloading",
                            "percent": (i + 1) / n * 100.0,
                            "name": (f"{i + 1}/{n} · {tr['title']}" if n > 1
                                     else tr["title"])})
        return final

    def _repair_live(self, partial):
        """A live capture stopped mid-stream lacks the mp4 moov box;
        re-mux with ffmpeg so the file is playable. Returns final path."""
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return None
        if partial.endswith(".part"):
            final = partial[:-5]
        else:
            final = partial + ".fixed.mp4"
        try:
            rc = subprocess.run(
                [ffmpeg, "-y", "-nostdin", "-hide_banner",
                 "-err_detect", "ignore_err", "-i", partial,
                 "-c", "copy", "-movflags", "+faststart", final],
                capture_output=True, timeout=300,
                stdin=subprocess.DEVNULL).returncode
            if rc == 0 and os.path.exists(final) and os.path.getsize(final) > 0:
                try:
                    os.remove(partial)
                except OSError:
                    pass
                return final
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def _convert_subtitles(self, out):
        """Convert downloaded vtt/srt sidecars to the requested format.
        Returns the list of produced transcript files."""
        from . import transcripts
        from .debuglog import log as dbg
        done = []
        base, _ = os.path.splitext(out)
        target = self.subtitles.get("format", "md")
        # match by prefix instead of glob: video titles may contain [ ] ( )
        d = os.path.dirname(base) or "."
        pref = os.path.basename(base) + "."
        try:
            names = os.listdir(d)
        except OSError:
            names = []
        sidecars = sorted(os.path.join(d, f) for f in names
                          if f.startswith(pref) and f.lower().endswith((".vtt", ".srt")))
        for sidecar in sidecars:
            if not os.path.exists(sidecar):
                continue
            stem = os.path.basename(sidecar)[len(os.path.basename(base)) + 1:]
            parts = stem.split(".")              # e.g. ["en"], ["en", "auto"]
            lang = parts[0] if parts else ""
            if sidecar.lower().endswith("." + target):
                final = f"{base}.{lang}.{target}"
                if os.path.abspath(sidecar) != os.path.abspath(final):
                    os.replace(sidecar, final)
                    dbg(f"subtitle kept: {final}")
                done.append(final)
                continue
            try:
                new = transcripts.convert(
                    sidecar, target, source_url=self.url,
                    title=os.path.basename(base))
                final = f"{base}.{lang}.{target}"
                if os.path.abspath(new) != os.path.abspath(final):
                    os.replace(new, final)
                dbg(f"subtitle converted: {final}")
                done.append(final)
                if sidecar != final:
                    os.remove(sidecar)
            except Exception as e:  # noqa: BLE001
                dbg(f"subtitle convert failed: {e}")
        return done


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

    def submit(self, url, quality=None, subtitles=None, transcript_only=False):
        url = (url or "").strip()
        if not url:
            return None
        m = re.match(r"^spotify:(track|album|playlist):([A-Za-z0-9]+)$", url)
        if m:
            url = f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
        elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            url = "https://" + url
        task_id = self._next_id
        self._next_id += 1
        self._pending.append((task_id, url, quality, subtitles, transcript_only))
        self.queue_changed.emit()
        self._pump()
        return task_id

    def _pump(self):
        limit = max(1, int(self.settings.get("simultaneous_downloads")))
        while self._pending and len(self._running) < limit:
            task_id, url, quality, subtitles, t_only = self._pending.pop(0)
            w = DownloadWorker(url, self.settings, quality, subtitles, t_only)
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

    def resume(self, task_id, url, quality=None, subtitles=None,
               transcript_only=False):
        self._pending.append((task_id, url, quality, subtitles, transcript_only))
        self.queue_changed.emit()
        self._pump()

    def active_count(self):
        return len(self._running)
