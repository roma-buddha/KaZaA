"""Cancellable workers, bounded queue and atomic local download history."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from PySide6.QtCore import QObject, QThread, Signal

from .video_backend import DownloadOptions, validate_url

ACTIVE = {"queued", "starting", "downloading", "processing", "cancelling"}


class ProcessWorker(QThread):
    progress = Signal(dict)
    result = Signal(dict)
    error = Signal(str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self._cancelled = False
        self._process = None

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


class Inspector(QObject):
    item_ready = Signal(int, str, dict, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None, worker_factory=ProcessWorker):
        super().__init__(parent)
        self.worker_factory = worker_factory
        self.generation = 0
        self.pending = []
        self.workers = {}

    def inspect(self, urls):
        self.generation += 1
        for worker in self.workers:
            worker.cancel()
        self.pending = [(self.generation, url) for url in urls]
        self.busy_changed.emit(bool(self.pending or self.workers))
        self._pump()
        return self.generation

    def _pump(self):
        while self.pending and len(self.workers) < 2:
            generation, url = self.pending.pop(0)
            worker = self.worker_factory({"action": "inspect", "url": url}, self)
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
    notice = Signal(str)

    def __init__(self, path, parent=None, worker_factory=ProcessWorker):
        super().__init__(parent)
        self.path = Path(path)
        self.worker_factory = worker_factory
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
                    validate_url(job["url"])
                    DownloadOptions.from_dict(job["options"])
                except (ValueError, TypeError):
                    continue
                if job["status"] in ACTIVE:
                    job["status"] = "interrupted"
                    job["error"] = "Interrupted when the app closed. Retry to continue."
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
        except OSError as exc:
            self.notice.emit(f"Could not save download history: {exc}")

    def set_options(self, options):
        self.options = copy.deepcopy(options)
        self.save()

    def submit(self, info, options):
        options.validate(info)
        url = validate_url(info["url"])
        snapshot = options.to_dict()
        if any(job["url"] == url and job["options"] == snapshot and job["status"] in ACTIVE
               for job in self.jobs.values()):
            raise ValueError("This download is already in the queue.")
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {"id": job_id, "url": url, "title": info["title"],
                            "options": snapshot, "status": "queued", "percent": None,
                            "files": [], "created": time.time(), "error": ""}
        self._changed(job_id)
        self._pump()
        return job_id

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
            worker = self.worker_factory({"action": "download", "id": job_id,
                                          "url": job["url"], "options": copy.deepcopy(job["options"])}, self)
            self.workers[job_id] = worker
            job["status"] = "starting"
            worker.progress.connect(lambda data, i=job_id: self._progress(i, data))
            worker.result.connect(lambda result, i=job_id: self._done(i, result))
            worker.error.connect(lambda error, i=job_id: self._error(i, error))
            worker.finished.connect(lambda i=job_id: self._finished(i))
            self._changed(job_id)
            worker.start()

    def _progress(self, job_id, data):
        if self.jobs[job_id]["status"] == "cancelling":
            return
        self.jobs[job_id].update(data)
        self._changed(job_id, time.monotonic() - self._last_save > 1)

    def _done(self, job_id, result):
        job = self.jobs[job_id]
        if job["status"] == "cancelling":
            self._error(job_id, "Cancelled")
            return
        if not result.get("files") or not all(Path(path).is_file() for path in result["files"]):
            self._error(job_id, "No output files were produced.")
            return
        job.update(result)
        job.update(status="completed", percent=100, error="")
        self._changed(job_id)

    def _error(self, job_id, error):
        job = self.jobs[job_id]
        cancelled = error == "Cancelled" or job["status"] == "cancelling"
        status = "interrupted" if self._closing else "cancelled" if cancelled else "failed"
        job.update(status=status, error="Interrupted when the app closed. Retry to continue." if self._closing else error)
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
            self.workers[job_id].cancel()
        else:
            job.update(status="cancelled", error="Cancelled")
        self._changed(job_id)

    def retry(self, job_id):
        if job_id in self.workers or self.jobs[job_id]["status"] not in ("failed", "cancelled", "interrupted"):
            return
        self.jobs[job_id].update(status="queued", error="", percent=None, files=[])
        self._changed(job_id)
        self._pump()

    def stop(self):
        self._closing = True
        for job_id, worker in self.workers.items():
            self.jobs[job_id]["status"] = "interrupted"
            worker.cancel()
        for job in self.jobs.values():
            if job["status"] in ACTIVE:
                job["status"] = "interrupted"
        self.save()
