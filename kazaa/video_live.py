"""Live video/audio recording with a graceful, bounded FFmpeg stop."""
from collections import deque
from pathlib import Path
import subprocess
import threading
import time

from .video_backend import VIDEO_FORMATS, find_ffmpeg


def select_streams(info, options):
    formats = [f for f in (info.get("formats") or [info]) if f.get("url") and not f.get("has_drm")]
    if options.kind == "audio":
        audio = [f for f in formats if f.get("acodec") != "none"]
        if not audio:
            raise ValueError("This live stream has no audio.")
        return [max(audio, key=lambda f: (f.get("vcodec") == "none", f.get("abr") or f.get("tbr") or 0))]
    video = [f for f in formats if f.get("vcodec") != "none" and (f.get("vcodec") or f.get("ext") in VIDEO_FORMATS)]
    if options.quality != "best":
        video = [f for f in video if str(f.get("height")) == options.quality]
    if not video:
        raise ValueError("The requested live video quality is unavailable.")
    selected = max(video, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    streams = [selected]
    if selected.get("acodec") == "none":
        audio = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
        if audio:
            streams.append(max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0))
    return streams


def recording_command(info, options, partial):
    streams = select_streams(info, options)
    command = [find_ffmpeg(), "-y", "-hide_banner", "-loglevel", "warning", "-progress", "pipe:1"]
    for stream in streams:
        if stream["url"].startswith(("http://", "https://")):
            command += ["-rw_timeout", "10000000"]
            headers = stream.get("http_headers") or info.get("http_headers") or {}
            if headers:
                command += ["-headers", "".join(f"{k}: {str(v).replace(chr(13), '').replace(chr(10), '')}\r\n" for k, v in headers.items())]
        command += ["-i", stream["url"]]
    if options.kind == "video":
        command += ["-map", "0:v:0", "-map", "1:a:0?" if len(streams) > 1 else "0:a:0?"]
        if options.format == "webm":
            command += ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "5", "-c:a", "libopus"]
        else:
            command += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    else:
        codecs = {"mp3": "libmp3lame", "m4a": "aac", "flac": "flac", "wav": "pcm_s16le", "ogg": "libvorbis"}
        command += ["-map", "0:a:0", "-vn", "-c:a", codecs[options.format]]
        if options.quality != "best" and options.format not in ("wav", "flac"):
            command += ["-b:a", options.quality + "k"]
        elif options.format == "mp3":
            command += ["-q:a", "0"]
        elif options.format == "ogg":
            command += ["-q:a", "10"]
        elif options.format == "m4a":
            command += ["-b:a", "256k"]
    if options.format in ("mp4", "m4a"):
        command += ["-movflags", "+frag_keyframe+empty_moov"]
    muxers = {"mp4": "mp4", "mkv": "matroska", "webm": "webm", "mp3": "mp3", "m4a": "ipod", "flac": "flac", "wav": "wav", "ogg": "ogg"}
    command += ["-f", muxers[options.format], str(partial)]
    return command


def record_live(info, options, filename, emit, stop_event=None):
    stop_event = stop_event or threading.Event()
    if stop_event.is_set():
        raise ValueError("Recording stopped before any media arrived.")
    # A resumed live broadcast starts a new capture; preserve any older recording.
    base = Path(filename).with_suffix("." + options.format)
    output = base.with_name(f"{base.stem}-live-{time.time_ns()}.{options.format}")
    partial = output.with_name(output.name + ".part")
    process = subprocess.Popen(recording_command(info, options, partial), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    state = {"elapsed": 0.0}
    errors = deque(maxlen=6)

    def read_progress():
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us":
                try:
                    state["elapsed"] = max(0, int(value) / 1000000)
                except ValueError:
                    pass

    def read_errors():
        for line in process.stderr:
            errors.append(line.strip())

    readers = [threading.Thread(target=read_progress, daemon=True), threading.Thread(target=read_errors, daemon=True)]
    for reader in readers:
        reader.start()
    stop_started = None
    try:
        while process.poll() is None:
            if stop_event.is_set() and stop_started is None:
                stop_started = time.monotonic()
                try:
                    process.stdin.write("q\n")
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass
            if stop_started is not None and time.monotonic() - stop_started > 10:
                process.kill()
                raise ValueError("The stream did not stop cleanly; the partial recording was kept.")
            emit("progress", {"status": "recording", "live": True, "percent": None,
                "elapsed": state["elapsed"], "size": partial.stat().st_size if partial.exists() else 0})
            try:
                process.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                pass
        for reader in readers:
            reader.join(timeout=2)
        if process.returncode != 0:
            raise ValueError("Live recording failed: " + (" · ".join(errors) or "FFmpeg stopped unexpectedly."))
        if not partial.exists() or partial.stat().st_size == 0 or state["elapsed"] <= 0:
            raise ValueError("The stream ended before any media was recorded.")
        partial.replace(output)
        return {"files": [str(output.resolve())], "title": info.get("title") or "Live stream",
                "size": output.stat().st_size, "live": True, "elapsed": state["elapsed"], "stopped": stop_event.is_set()}
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
