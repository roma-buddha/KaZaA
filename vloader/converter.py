"""Conversion engine: format conversion, trim, volume, merge — via ffmpeg subprocess."""
import os
import re
import subprocess

from PySide6.QtCore import QThread, Signal

from .downloader import find_ffmpeg

VIDEO_FORMATS = ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "xvid"]
AUDIO_FORMATS = ["mp3", "m4a", "wma", "wav", "flac", "ogg"]
ALL_FORMATS = VIDEO_FORMATS + AUDIO_FORMATS

# codec map for outputs
_VCODEC = {
    "mp4": ["-c:v", "libx264", "-c:a", "aac"],
    "mkv": ["-c:v", "libx264", "-c:a", "aac"],
    "avi": ["-c:v", "mpeg4", "-c:a", "mp3"],
    "mov": ["-c:v", "libx264", "-c:a", "aac"],
    "wmv": ["-c:v", "wmv2", "-c:a", "wmav2"],
    "flv": ["-c:v", "flv", "-c:a", "mp3"],
    "webm": ["-c:v", "libvpx", "-c:a", "libvorbis"],
    "xvid": ["-c:v", "libxvid", "-c:a", "mp3"],
    "mp3": ["-vn", "-c:a", "libmp3lame"],
    "m4a": ["-vn", "-c:a", "aac"],
    "wma": ["-vn", "-c:a", "wmav2"],
    "wav": ["-vn", "-c:a", "pcm_s16le"],
    "flac": ["-vn", "-c:a", "flac"],
    "ogg": ["-vn", "-c:a", "libvorbis"],
}

_QUALITY_CRF = {"high": "18", "normal": "23", "low": "28"}


def _output_name(src, fmt):
    base, _ = os.path.splitext(src)
    out = f"{base}.{fmt}"
    n = 1
    while os.path.exists(out):
        out = f"{base} ({n}).{fmt}"
        n += 1
    return out


def build_convert_args(src, fmt, quality="normal", trim_start=None, trim_end=None,
                       volume=None, extra_inputs=None):
    """Build an ffmpeg argv. extra_inputs => merge mode (concat all inputs)."""
    inputs = [src] + list(extra_inputs or [])
    args = [find_ffmpeg() or "ffmpeg", "-y", "-hide_banner"]
    for inp in inputs:
        args += ["-i", inp]
    if len(inputs) > 1:
        # concat filter (re-encodes, safe for mixed codecs)
        n = len(inputs)
        parts = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
        args += ["-filter_complex", f"{parts}concat=n={n}:v=1:a=1[v][a]",
                 "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-map", "0", "-dn"]
        if trim_start:
            args += ["-ss", str(trim_start)]
        if trim_end:
            args += ["-to", str(trim_end)]
        if volume is not None:
            try:
                vol = float(volume)
            except (TypeError, ValueError):
                vol = None
            if vol is not None and vol != 1.0:
                args += ["-af", f"volume={vol}"]
    vcodec = _VCODEC.get(fmt, _VCODEC["mp4"])
    if fmt in AUDIO_FORMATS:
        # force audio-only mapping
        args = [a for a in args if a not in ("-map", "0", "[v]", "[a]", "-dn")]
        args += ["-map", "0:a:0?"] if len(inputs) == 1 else ["-map", "[a]"]
    args += vcodec
    if fmt not in AUDIO_FORMATS and vcodec[1] in ("libx264", "libxvid", "libvpx"):
        args += ["-crf", _QUALITY_CRF.get(quality, "23"), "-preset", "veryfast"]
    if fmt == "mp3":
        args += ["-q:a", "2"]
    if extra_inputs is None:
        args += [ _output_name(src, fmt) ]
    else:
        base = os.path.splitext(src)[0] + "_merged"
        args += [base + "." + fmt]
    return args


class ConvertWorker(QThread):
    progress = Signal(dict)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, src, fmt, quality="normal", trim_start=None, trim_end=None,
                 volume=None, extra_inputs=None, delete_original=False, parent=None):
        super().__init__(parent)
        self.args = build_convert_args(src, fmt, quality, trim_start, trim_end,
                                       volume, extra_inputs)
        self.src = src
        self.delete_original = delete_original
        self._proc = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _parse_progress(self, line, duration_s):
        mm = re.search(r"time=(\d+):(\d+):(\d+)", line)
        if mm and duration_s:
            secs = int(mm[1]) * 3600 + int(mm[2]) * 60 + int(mm[3])
            self.progress.emit({
                "status": "converting",
                "percent": min(100.0, secs / duration_s * 100.0),
            })

    def run(self):
        try:
            self._proc = subprocess.Popen(
                self.args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out_path = self.args[-1]
            duration_s = probe_duration(self.src)
            for line in self._proc.stdout:
                if self._cancelled:
                    break
                self._parse_progress(line, duration_s)
            rc = self._proc.wait()
            if self._cancelled:
                self.failed.emit("cancelled")
            elif rc != 0 or not os.path.exists(out_path):
                self.failed.emit(f"ffmpeg exited with code {rc}")
            else:
                if self.delete_original and os.path.abspath(out_path) != os.path.abspath(self.src):
                    try:
                        os.remove(self.src)
                    except OSError:
                        pass
                self.finished_ok.emit({"output": out_path})
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


def probe_duration(path):
    ffprobe = (find_ffmpeg() or "").replace("ffmpeg.exe", "ffprobe.exe")
    if not os.path.exists(ffprobe):
        return 0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0
