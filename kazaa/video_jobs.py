"""Cancellable workers, bounded queue and atomic local download history."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading
import tempfile
import uuid

from PySide6.QtCore import QObject, QThread, Signal

from .video_backend import DownloadOptions, link_key, validate_url
from .sources import normalize_source, output_paths, validate_selection

ACTIVE = {"queued", "starting", "downloading", "recording", "processing", "cancelling", "pausing", "stopping"}


class ProcessWorker(QThread):
    progress = Signal(dict)
    result = Signal(dict)
    error = Signal(str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = dict(request)
        self._controls = tempfile.TemporaryDirectory(prefix="kazaa-worker-") if request.get("action") == "download" else None
        if self._controls:
            self.request["control_file"] = str(Path(self._controls.name, "stop"))
        self._cancelled = False
        self._process = None
        self._stop_requested = False

    def stop(self):
        if self._stop_requested:
            return
        self._stop_requested = True
        if self._process and self._process.poll() is not None:
            return
        if self._controls:
            Path(self.request["control_file"]).touch()
        def deadline():
            process = self._process
            if process and process.poll() is None:
                self.cancel()
        # Live captures may need ten seconds to stop, then a bounded MP4 remux
        # and validation. Keep the worker alive through that finalization.
        timer = threading.Timer(150 if self.request.get("live") else 15, deadline)
        timer.daemon = True
        timer.start()

    def cancel(self):
        self._cancelled = True
        process = self._process
        if process and process.poll() is None:
            if os.name == "nt":
                # Stop our isolated process and its FFmpeg/JS children, without blocking the UI.
                subprocess.Popen(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def run(self):
        try:
            if self._cancelled:
                self.error.emit("Cancelled")
                return
            interpreter = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable
            self._process = subprocess.Popen(
                [interpreter, "-m", "kazaa.video_worker"],
                cwd=str(Path(__file__).resolve().parent.parent),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt")
            if self._cancelled:
                self.cancel()
            self._process.stdin.write(json.dumps(self.request))
            self._process.stdin.close()
            result, error = None, ""
            diagnostic = []
            for line in self._process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    diagnostic.append(line.strip())
                    diagnostic = diagnostic[-4:]
                    continue
                if not isinstance(message, dict):
                    continue
                kind, data = message.get("type"), message.get("data")
                if kind == "progress" and not self._cancelled:
                    self.progress.emit(data)
                elif kind == "result":
                    result = data
                elif kind == "error":
                    error = data
            code = self._process.wait()
            if self._cancelled:
                self.error.emit("Cancelled")
            elif code or result is None:
                self.error.emit(error or "\n".join(diagnostic) or "The media worker stopped unexpectedly.")
            else:
                self.result.emit(result)
        except Exception as exc:
            self.error.emit("Cancelled" if self._cancelled else str(exc))
        finally:
            if self._process:
                if self._process.poll() is None:
                    self.cancel()
                    self._process.wait(timeout=10)
                for stream in (self._process.stdin, self._process.stdout):
                    if stream and not stream.closed:
                        stream.close()
            if self._controls:
                self._controls.cleanup()


class Inspector(QObject):
    item_ready = Signal(int, str, dict, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None, worker_factory=ProcessWorker, cache_dir=None):
        super().__init__(parent)
        self.worker_factory = worker_factory
        self.generation = 0
        self.pending = []
        self.workers = {}
        self.cache_dir = str(cache_dir or Path(tempfile.gettempdir(), "kazaa-torrent-cache"))

    def inspect(self, urls):
        self.generation += 1
        for worker in self.workers:
            worker.cancel()
        self.pending = [(self.generation, url) for url in urls]
        self.busy_changed.emit(bool(self.pending or self.workers))
        self._pump()
        return self.generation

    def append(self, urls):
        self.pending.extend((self.generation, url) for url in urls)
        self.busy_changed.emit(bool(self.pending or self.workers))
        self._pump()

    def _pump(self):
        while self.pending and len(self.workers) < 2:
            generation, url = self.pending.pop(0)
            _, source = normalize_source(url)
            worker = self.worker_factory({"action": "inspect", "url": url, "source": source,
                                          "cache_dir": self.cache_dir}, self)
            self.workers[worker] = generation
            worker.result.connect(lambda result, g=generation, u=url: self._deliver(g, u, result, ""))
            worker.error.connect(lambda error, g=generation, u=url: self._deliver(g, u, {}, error))
            worker.finished.connect(lambda w=worker: self._finished(w))
            worker.start()
        if not self.pending and not self.workers:
            self.busy_changed.emit(False)

    def _deliver(self, generation, url, result, error):
        if generation == self.generation:
            self.item_ready.emit(generation, url, result, error)

    def _finished(self, worker):
        self.workers.pop(worker, None)
        worker.deleteLater()
        self._pump()

    def stop(self):
        self.generation += 1
        self.pending.clear()
        for worker in self.workers:
            worker.cancel()


class VideoQueue(QObject):
    changed = Signal(str, dict)
    removed = Signal(str)
    notice = Signal(str)

    def __init__(self, path, parent=None, worker_factory=ProcessWorker, shred_files=None):
        super().__init__(parent)
        self.path = Path(path)
        self.worker_factory = worker_factory
        self.shred_files = shred_files
        self.jobs = {}
        self.options = {}
        self.workers = {}
        self._closing = False
        self._last_save = 0
        self._load()

    def _load(self):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                return
            self.options = saved.get("options") if isinstance(saved.get("options"), dict) else {}
            for job in saved.get("jobs", []):
                if not isinstance(job, dict) or not all(k in job for k in ("id", "url", "options", "status")):
                    continue
                if not isinstance(job["options"], dict) or not isinstance(job["id"], str):
                    continue
                try:
                    if job.get("source") == "torrent":
                        normalize_source(job["url"])
                        validate_selection(job["torrent"]["manifest"], job["options"]["selected_files"])
                        output_paths(job["torrent"]["manifest"], job["options"]["folder"])
                    else:
                        validate_url(job["url"])
                        DownloadOptions.from_dict(job["options"])
                except (ValueError, TypeError, KeyError, OSError):
                    continue
                if job.get("pending_shred_files") and job["status"] in ACTIVE | {"interrupted"}:
                    job.update(status="stopped", speed=None, eta=None)
                elif job["status"] in ("pausing", "stopping", "cancelling"):
                    job["status"] = {"pausing": "paused", "stopping": "stopped", "cancelling": "cancelled"}[job["status"]]
                elif job["status"] in ACTIVE | {"interrupted"}:
                    job.update(status="queued", error="", speed=None, eta=None)
                self.jobs[job["id"]] = job
        except (OSError, ValueError, TypeError):
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"options": self.options, "jobs": list(self.jobs.values())},
                                            ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
            self._last_save = time.monotonic()
            return True
        except OSError as exc:
            self.notice.emit(f"Could not save download history: {exc}")
            return False

    def start_pending(self):
        self._pump()

    def set_options(self, options):
        self.options = copy.deepcopy(options)
        self.save()

    def submit(self, info, options):
        if info.get("source") == "torrent":
            return self.submit_torrent(info, options)
        options.validate(info)
        url = validate_url(info["url"])
        key = link_key(url)
        snapshot = options.to_dict()
        if any(job.get("source") != "torrent" and link_key(job["url"]) == key and
               job["options"].get("kind", "video") == options.kind and
               job["options"].get("format", "mp4") == options.format for job in self.jobs.values()):
            raise ValueError(f"This link is already in Downloads as {options.kind.title()} {options.format.upper()}. "
                             "Choose a different type or format, or use the existing entry.")
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {"id": job_id, "url": url, "title": info["title"],
                            "options": snapshot, "source": "link", "live": bool(info.get("live")), "status": "queued", "percent": None,
                            "files": [], "created": time.time(), "error": ""}
        self._changed(job_id)
        self._pump()
        return job_id

    def torrent_match(self, hashes):
        identities = set(hashes)
        return next((job["id"] for job in self.jobs.values() if job.get("source") == "torrent"
                     and identities & set(job["torrent"]["hashes"])), None)

    def submit_torrent(self, info, options):
        if self.torrent_match(info["hashes"]):
            raise ValueError("This torrent is already in Downloads. Choose files in its existing entry.")
        selected = validate_selection(info["manifest"], options["selected_files"])
        output_paths(info["manifest"], options["folder"])
        job_id = uuid.uuid4().hex
        torrent = {key: copy.deepcopy(info[key]) for key in ("hashes", "manifest", "metadata_file")}
        torrent["resume_file"] = str(self.path.parent / "torrent-cache" / (job_id + ".resume"))
        self.jobs[job_id] = {"id": job_id, "url": info["url"], "title": info["title"], "source": "torrent",
                            "torrent": torrent, "options": {"kind": "torrent", "folder": options["folder"], "selected_files": selected},
                            "status": "queued", "percent": None, "files": [], "created": time.time(), "error": ""}
        self._changed(job_id)
        self._pump()
        return job_id

    def select_torrent_files(self, job_id, selected):
        job = self.jobs[job_id]
        if job.get("source") != "torrent" or job["status"] in ACTIVE or job_id in self.workers:
            raise ValueError("Pause or stop this torrent before choosing files.")
        if job.get("pending_shred_files"):
            raise ValueError("Remove these files from Shred before resuming this download.")
        job["options"]["selected_files"] = validate_selection(job["torrent"]["manifest"], selected)
        job.update(status="queued", error="", percent=None, completed=None, speed=None, eta=None, files_deleted=False)
        self._changed(job_id)
        self._pump()

    def _changed(self, job_id, persist=True):
        self.changed.emit(job_id, copy.deepcopy(self.jobs[job_id]))
        if persist:
            self.save()

    def _pump(self):
        if self._closing:
            return
        for job in self.jobs.values():
            if len(self.workers) >= 2:
                break
            if job["status"] != "queued":
                continue
            job_id = job["id"]
            request = {"action": "download", "id": job_id, "source": job.get("source", "link"),
                       "url": job["url"], "live": job.get("live", False), "options": copy.deepcopy(job["options"])}
            if job.get("source") == "torrent":
                request.update(torrent=copy.deepcopy(job["torrent"]), owned_files=list(job.get("files", [])))
            worker = self.worker_factory(request, self)
            self.workers[job_id] = worker
            job["status"] = "starting"
            worker.progress.connect(lambda data, i=job_id: self._progress(i, data))
            worker.result.connect(lambda result, i=job_id: self._done(i, result))
            worker.error.connect(lambda error, i=job_id: self._error(i, error))
            worker.finished.connect(lambda i=job_id: self._finished(i))
            self._changed(job_id)
            worker.start()

    def _progress(self, job_id, data):
        if self.jobs[job_id].get("source") == "torrent" and "files" in data:
            self.jobs[job_id]["files"] = data["files"]
        finishing_live = (self.jobs[job_id].get("live") and data.get("status") == "processing"
                          and self.jobs[job_id]["status"] == "stopping")
        if self._closing or (self.jobs[job_id]["status"] in ("cancelling", "pausing", "stopping") and not finishing_live):
            return
        self.jobs[job_id].update(data)
        self._changed(job_id, time.monotonic() - self._last_save > 1)

    def _done(self, job_id, result):
        job = self.jobs[job_id]
        if job["status"] in ("cancelling", "pausing") or (job["status"] == "stopping" and not job.get("live")) or (self._closing and job["status"] in ("paused", "stopped", "cancelled")):
            self._error(job_id, "Cancelled")
            return
        if not result.get("files") or (job.get("source") != "torrent" and not all(Path(path).is_file() for path in result["files"])):
            self._error(job_id, "No output files were produced.")
            return
        if job.get("source") == "torrent":
            paths = output_paths(job["torrent"]["manifest"], job["options"]["folder"])
            if not all(Path(paths[i]).is_file() for i in job["options"]["selected_files"]):
                self._error(job_id, "The selected torrent files were not produced.")
                return
        job.update(result)
        job.update(status="completed", percent=100, error="", completed=time.time(), speed=None, eta=None)
        self._changed(job_id)

    def _error(self, job_id, error):
        job = self.jobs[job_id]
        cancelled = error == "Cancelled" or job["status"] == "cancelling"
        status = (job["status"] if job["status"] in ("paused", "stopped", "cancelled") else "interrupted") if self._closing else "paused" if job["status"] == "pausing" else "stopped" if job["status"] == "stopping" else "cancelled" if cancelled else "failed"
        if job.get("live") and error == "Cancelled" and status == "stopped":
            error = "Recording interrupted; any partial recording was kept."
        job.update(status=status, error="" if self._closing or (status in ("paused", "stopped") and error == "Cancelled") else error,
                   speed=None, eta=None)
        self._changed(job_id)

    def _finished(self, job_id):
        worker = self.workers.pop(job_id, None)
        if worker:
            worker.deleteLater()
        self._pump()

    def cancel(self, job_id):
        job = self.jobs[job_id]
        if job_id in self.workers:
            job["status"] = "cancelling"
            worker = self.workers[job_id]
            worker.stop() if job.get("source") == "torrent" else worker.cancel()
        else:
            job.update(status="cancelled", error="Cancelled")
        self._changed(job_id)

    def retry(self, job_id):
        if job_id in self.workers or self.jobs[job_id]["status"] not in ("failed", "cancelled", "interrupted", "paused", "stopped"):
            return
        job = self.jobs[job_id]
        if job.get("pending_shred_files"):
            self.notice.emit("Remove these files from Shred before resuming this download.")
            return
        job.update(status="queued", error="", percent=None, files=job.get("files", []) if job.get("source") == "torrent" else [],
                                 total_bytes=None, downloaded_bytes=None, speed=None, eta=None,
                                 completed=None, actual_quality="", files_deleted=False)
        self._changed(job_id)
        self._pump()

    def delete(self, job_id, mode="entry"):
        """Remove history and/or hand recorded output files to the Shred queue."""
        if mode not in ("entry", "file", "both"):
            raise ValueError("Choose whether to remove the entry, the file, or both.")
        job = self.jobs[job_id]
        if job_id in self.workers or job["status"] in ACTIVE:
            raise ValueError("Stop this download or recording before deleting it.")
        if mode in ("file", "both"):
            paths = list(dict.fromkeys(job.get("files", [])))
            if job.get("source") == "torrent":
                allowed = set(output_paths(job["torrent"]["manifest"], job["options"]["folder"]).values())
                if any(str(Path(path).resolve()) not in allowed for path in paths):
                    raise ValueError("Only this torrent's output files can be deleted.")
            # Preflight every output before handing anything over; never queue directories.
            existing = []
            for path in paths:
                if Path(path).is_dir():
                    raise ValueError("Only this entry's output files can be deleted.")
                try:
                    Path(path).lstat()
                except FileNotFoundError:
                    continue
                existing.append(path)
            if existing:
                if self.shred_files is None:
                    raise ValueError("Shred queue is unavailable. The entry and files were kept.")
                self.shred_files(existing)  # Must save/accept every file or raise before history changes.
            job["pending_shred_files"] = existing
            job["files_deleted"] = not existing
        if mode in ("entry", "both"):
            self.jobs.pop(job_id)
            if not self.save():
                self.jobs[job_id] = job
                self._changed(job_id, persist=False)
                raise OSError("Could not save the removal. The entry was kept.")
            self.removed.emit(job_id)
        else:
            self._changed(job_id, persist=False)
            if not self.save():
                raise OSError("The files are in Shred, but their updated download history could not be saved.")

    def _shred_result(self, paths, deleted):
        confirmed = {os.path.normcase(os.path.abspath(path)) for path in paths}
        changed = False
        for job_id, job in self.jobs.items():
            pending = job.get("pending_shred_files", [])
            remaining = [path for path in pending if os.path.normcase(os.path.abspath(path)) not in confirmed]
            if len(pending) == len(remaining):
                continue
            job["pending_shred_files"] = remaining
            if deleted:
                job["files_deleted"] = not remaining and not any(Path(path).exists() for path in job.get("files", []))
            else:
                job["files_deleted"] = False
            self._changed(job_id, persist=False)
            changed = True
        if changed:
            self.save()

    def files_shredded(self, paths):
        self._shred_result(paths, deleted=True)

    def files_released(self, paths):
        self._shred_result(paths, deleted=False)

    def pause(self, job_id):
        job = self.jobs[job_id]
        if job.get("live") or job["status"] not in ("queued", "starting", "downloading"):
            return
        if job_id in self.workers:
            job["status"] = "pausing"
            worker = self.workers[job_id]
            worker.stop() if job.get("source") == "torrent" else worker.cancel()
        else:
            job["status"] = "paused"
        self._changed(job_id)

    def resume(self, job_id):
        if self.jobs[job_id]["status"] == "paused":
            self.retry(job_id)

    def stop_job(self, job_id):
        job = self.jobs[job_id]
        if job["status"] not in ACTIVE | {"paused"}:
            return
        if job_id in self.workers:
            job["status"] = "stopping"
            worker = self.workers[job_id]
            worker.stop() if job.get("live") or job.get("source") == "torrent" else worker.cancel()
        else:
            job.update(status="stopped", error="")
        self._changed(job_id)

    def stop(self):
        if self._closing:
            return
        self._closing = True
        for job_id, worker in self.workers.items():
            job = self.jobs[job_id]
            job["status"] = {"pausing": "paused", "stopping": "stopped", "cancelling": "cancelled"}.get(job["status"], "interrupted")
            worker.stop() if job.get("live") or job.get("source") == "torrent" else worker.cancel()
        for job in self.jobs.values():
            if job["status"] in ACTIVE:
                job["status"] = "interrupted"
        self.save()
