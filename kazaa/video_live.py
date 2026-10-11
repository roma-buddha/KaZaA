"""Live video/audio recording with a graceful, bounded FFmpeg stop."""
from collections import deque
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

from .video_backend import VIDEO_FORMATS, find_ffmpeg, output_quality, video_quality


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
            command += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-forced-idr", "1", "-flags", "+cgop"]
        command += ["-force_key_frames", "expr:gte(t,n_forced*2)"]
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


def finalize_recording(partial, output, options):
    """Publish a conventional indexed MP4/M4A, keeping the capture on failure."""
    if options.format not in ("mp4", "m4a"):
        partial.replace(output)
        return
    temporary = output.with_name(output.name + ".finalizing")
    ffmpeg = find_ffmpeg()
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe" if Path(ffmpeg).suffix.lower() == ".exe" else "ffprobe")
    probe = str(ffprobe) if ffprobe.is_file() else shutil.which("ffprobe")
    try:
        if not probe:
            raise ValueError("FFprobe is required to validate the finished recording.")
        result = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-xerror",
            "-i", str(partial), "-map", "0", "-c", "copy", "-movflags", "+faststart",
            "-f", "mp4" if options.format == "mp4" else "ipod", str(temporary)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError(result.stderr.strip()[-1000:] or "FFmpeg could not finalize the recording.")
        result = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_type:format=duration",
            "-of", "json", str(temporary)], capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError("The finished recording could not be read.")
        metadata = json.loads(result.stdout)
        if not temporary.is_file() or not temporary.stat().st_size or float(metadata.get("format", {}).get("duration", 0)) <= 0:
            raise ValueError("The finished recording contains no media.")
        if not any(stream.get("codec_type") == options.kind for stream in metadata.get("streams", [])):
            raise ValueError("The finished recording is missing its media stream.")
        temporary.replace(output)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError(f"Recording finalization failed; the partial recording was kept at {partial}: {exc}") from exc
    # The published file is already validated; cleanup must not turn it into a failure.
    try:
        partial.unlink()
    except OSError:
        pass


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
    quality = video_quality(select_streams(info, options)[0]) if options.kind == "video" else ""
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
                "elapsed": state["elapsed"], "size": partial.stat().st_size if partial.exists() else 0,
                "actual_quality": quality})
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
        emit("progress", {"status": "processing", "live": True, "percent": None,
                          "elapsed": state["elapsed"], "size": partial.stat().st_size,
                          "actual_quality": quality})
        finalize_recording(partial, output, options)
        return {"files": [str(output.resolve())], "title": info.get("title") or "Live stream",
                "size": output.stat().st_size, "live": True, "elapsed": state["elapsed"], "stopped": stop_event.is_set(),
                "actual_quality": output_quality(output, options, select_streams(info, options)[0])}
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
