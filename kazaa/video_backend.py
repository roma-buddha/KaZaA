"""Video inspection and export, independent of the legacy media/torrent manager."""
import base64
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from shutil import which
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from . import transcripts

VIDEO_FORMATS = ("mp4", "mkv", "webm")
AUDIO_FORMATS = ("mp3", "m4a", "flac", "wav", "ogg")
CAPTION_FORMATS = ("srt", "vtt", "txt", "md")


def validate_url(value):
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() == "magnet" or parsed.path.lower().endswith(".torrent"):
        raise ValueError("Torrent support is planned.")
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("Paste a full http:// or https:// video link.")
    host = parsed.hostname.lower()
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/playlist":
            raise ValueError("Paste individual video links; playlists are not supported yet.")
        if parsed.path == "/watch" and parse_qs(parsed.query).get("v"):
            value = "https://www.youtube.com/watch?v=" + parse_qs(parsed.query)["v"][0]
    return value


def link_key(value):
    return urlunsplit(urlsplit(validate_url(value))._replace(fragment=""))


def parse_links(text):
    entries, seen = [], set()
    for raw in re.split(r"\s+", text.strip()):
        if not raw:
            continue
        try:
            url, error = validate_url(raw), ""
        except ValueError as exc:
            url, error = raw, str(exc)
        key = link_key(url) if not error else url
        if key in seen:
            continue
        seen.add(key)
        entries.append({"url": url, "error": error})
    return entries


def find_ffmpeg():
    # Same bundled/frozen/PATH precedence as the existing download engine.
    roots = [Path(__file__).resolve().parent.parent / "bin"]
    if getattr(sys, "frozen", False):
        roots += [Path(getattr(sys, "_MEIPASS", "")) / "bin", Path(sys.executable).parent / "bin"]
    for root in roots:
        for name in ("ffmpeg.exe", "ffmpeg"):
            if (root / name).is_file():
                return str(root / name)
    return which("ffmpeg")


def video_quality(info):
    """Resolution of the selected stream, rather than the requested preset."""
    streams = [info, *(info.get("requested_formats") or [])]
    height = next((stream.get("height") for stream in streams if stream.get("height")), None)
    return f"{int(height)}p" if height else ""


def output_quality(path, options, info=None):
    """Inspect the final output, including bitrate changes from audio conversion."""
    if options.kind == "transcript":
        return ""
    ffmpeg = find_ffmpeg()
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe") if ffmpeg else None
    probe = str(sibling) if sibling and sibling.is_file() else which("ffprobe")
    if probe:
        try:
            result = subprocess.run([probe, "-v", "error", "-show_streams", "-of", "json", str(path)],
                capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            streams = json.loads(result.stdout).get("streams", [])
            stream = next((s for s in streams if s.get("codec_type") == options.kind), {})
            if options.kind == "video" and stream.get("height"):
                return video_quality(stream)
            if options.kind == "audio":
                if options.format in ("flac", "wav"):
                    rate = int(stream.get("sample_rate") or 0)
                    bits = int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 0)
                    parts = [f"{rate / 1000:g} kHz"] if rate else []
                    if bits:
                        parts.append(f"{bits}-bit")
                    return " · ".join(parts)
                bitrate = int(stream.get("bit_rate") or 0)
                if bitrate:
                    return f"{round(bitrate / 1000)} kbps"
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            pass  # A missing probe must not turn a successful export into a failure.
    return video_quality(info or {}) if options.kind == "video" else ""


@dataclass(frozen=True)
class DownloadOptions:
    kind: str = "video"
    format: str = "mp4"
    quality: str = "best"
    captions: bool = False
    caption_format: str = "srt"
    language: str = "en"
    caption_source: str = "manual"
    folder: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})

    def validate(self, info, require_tools=True):
        formats = {"video": VIDEO_FORMATS, "audio": AUDIO_FORMATS, "transcript": CAPTION_FORMATS}
        if self.kind not in formats or self.format not in formats[self.kind]:
            raise ValueError("Choose a supported output format.")
        if not self.folder:
            raise ValueError("Choose a save folder.")
        if info.get("live") and (self.kind == "transcript" or self.captions):
            raise ValueError("Live streams support video or audio recording; transcripts are available after the broadcast.")
        if self.kind == "video":
            if not info.get("has_video"):
                raise ValueError("This link has no video stream.")
            if self.quality != "best" and self.quality not in {str(h) for h in info.get("heights", [])}:
                raise ValueError(f"{self.quality}p is not available for this video.")
        if self.kind == "audio":
            if not info.get("has_audio"):
                raise ValueError("This link has no audio stream.")
            if self.quality not in ("best", "128", "192", "256", "320"):
                raise ValueError("Choose a supported audio quality.")
        if self.kind == "transcript" or self.captions:
            if self.caption_source not in ("manual", "automatic") or self.caption_format not in CAPTION_FORMATS:
                raise ValueError("Choose a supported caption format and source.")
            if self.language not in info.get("captions", {}).get(self.caption_source, {}):
                raise ValueError("The selected caption language/source is unavailable for this video.")
        if require_tools and self.kind != "transcript" and not find_ffmpeg():
            raise ValueError("FFmpeg is needed for video/audio export. Install it or place it in bin/.")


def runtime_options():
    options = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
               "socket_timeout": 15, "retries": 2, "extractor_retries": 2,
               "windows_filenames": True, "no_color": True}
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        options["ffmpeg_location"] = str(Path(ffmpeg).parent)
    node = which("node")
    if node:
        options["js_runtimes"] = {"node": {"path": node}}
    return options


def summarize(info, url):
    if not info or info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("Paste an individual video link, not a playlist or channel.")
    formats = info.get("formats") or [info]
    caption_tracks = {}
    for key, field in (("manual", "subtitles"), ("automatic", "automatic_captions")):
        caption_tracks[key] = {lang: tracks[0].get("name", lang)
                               for lang, tracks in (info.get(field) or {}).items() if tracks}
    return {"url": url, "title": info.get("title") or url,
            "live": bool(info.get("is_live") or info.get("live_status") == "is_live"),
            "creator": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration"), "site": info.get("extractor_key") or urlsplit(url).hostname,
            "has_video": any(f.get("vcodec") != "none" and
                             (f.get("vcodec") or f.get("ext") in VIDEO_FORMATS + ("mov", "avi"))
                             for f in formats),
            "has_audio": any(f.get("acodec") != "none" and
                             (f.get("acodec") or f.get("ext") in VIDEO_FORMATS + AUDIO_FORMATS)
                             for f in formats),
            "heights": sorted({int(f["height"]) for f in formats
                               if f.get("height") and f.get("vcodec") not in (None, "none")}),
            "captions": caption_tracks}


def inspect_video(url, thumbnail=True):
    import yt_dlp
    url = validate_url(url)
    with yt_dlp.YoutubeDL(runtime_options()) as ydl:
        raw = ydl.extract_info(url, download=False)
    result = summarize(raw, url)
    if not result["live"]:
        # Direct HLS URLs do not always carry the extractor's live flag.
        for fmt in raw.get("formats") or [raw]:
            if "m3u8" not in (fmt.get("protocol") or ""):
                continue
            try:
                request = Request(fmt["url"], headers=fmt.get("http_headers") or raw.get("http_headers") or {})
                with urlopen(request, timeout=8) as response:
                    playlist = response.read(256 * 1024).decode("utf-8", errors="replace")
                if "#EXTINF:" in playlist:
                    result["live"] = "#EXT-X-ENDLIST" not in playlist
                    break
            except (OSError, ValueError, KeyError):
                continue
    if thumbnail and raw.get("thumbnail"):
        try:
            request = Request(raw["thumbnail"], headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=10) as response:
                if response.headers.get_content_type().startswith("image/"):
                    data = response.read(2 * 1024 * 1024 + 1)
                    if len(data) <= 2 * 1024 * 1024:
                        result["thumbnail_data"] = base64.b64encode(data).decode("ascii")
        except (OSError, ValueError):
            pass  # Metadata remains usable if the optional thumbnail fails.
    return result


def export_options(options, job_id):
    opts = runtime_options()
    opts.update({"outtmpl": str(Path(options.folder) / f"%(title).140B [%(id)s] {job_id[:8]}.%(ext)s"),
                 "continuedl": True, "overwrites": False})
    processors = []
    if options.kind == "video":
        opts["format"] = ("bestvideo*+bestaudio/best" if options.quality == "best" else
                          f"bestvideo[height={options.quality}]+bestaudio/best[height={options.quality}]")
        opts["merge_output_format"] = options.format
        processors.append({"key": "FFmpegVideoConvertor", "preferedformat": options.format})
    elif options.kind == "audio":
        opts["format"] = "bestaudio/best"
        processors.append({"key": "FFmpegExtractAudio", "preferredcodec": "vorbis" if options.format == "ogg" else options.format,
                           "preferredquality": "0" if options.quality == "best" else options.quality})
    else:
        opts["skip_download"] = True
    if options.kind == "transcript" or options.captions:
        opts.update({"writesubtitles": options.caption_source == "manual",
                     "writeautomaticsub": options.caption_source == "automatic",
                     "subtitleslangs": [options.language], "subtitlesformat": "vtt/srt/best"})
    opts["postprocessors"] = processors
    return opts


def perform_download(request, emit, stop_event=None):
    import yt_dlp
    url = validate_url(request["url"])
    options = DownloadOptions.from_dict(request["options"])
    opts = export_options(options, request["id"])
    def progress(data):
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        percent = 100 * data.get("downloaded_bytes", 0) / total if total else None
        emit("progress", {"status": "downloading" if data.get("status") == "downloading" else "processing",
                          "percent": percent, "speed": data.get("speed"), "eta": data.get("eta"),
                          "downloaded_bytes": data.get("downloaded_bytes"), "total_bytes": total,
                          **({"actual_quality": video_quality(data.get("info_dict") or {})} if options.kind == "video" else {})})
    moved = []
    def postprocess(data):
        emit("progress", {"status": "processing", "percent": None, "speed": None, "eta": None})
        filepath = data.get("info_dict", {}).get("filepath")
        if filepath:
            moved.append(filepath)
    opts["progress_hooks"] = [progress]
    opts["postprocessor_hooks"] = [postprocess]
    with yt_dlp.YoutubeDL(opts) as ydl:
        raw = ydl.extract_info(url, download=False)
        metadata = summarize(raw, url)
        metadata["live"] = metadata["live"] or request.get("live", False)
        options.validate(metadata)
        Path(options.folder).mkdir(parents=True, exist_ok=True)
        if metadata["live"]:
            from .video_live import record_live
            return record_live(raw, options, ydl.prepare_filename(raw), emit, stop_event)
        info = ydl.process_ie_result(raw, download=True)
        if not info:
            raise ValueError("The site returned no downloadable media.")
        files = []
        if options.kind != "transcript":
            candidates = [info.get("filepath"), *reversed(moved), ydl.prepare_filename(info)]
            original = Path(ydl.prepare_filename(info))
            candidates.append(str(original.with_suffix("." + options.format)))
            for candidate in candidates:
                if candidate and Path(candidate).is_file() and Path(candidate).suffix == "." + options.format:
                    files.append(str(Path(candidate).resolve()))
                    break
            if not files:
                raise ValueError("The requested media file was not produced.")
        if options.kind == "transcript" or options.captions:
            track = (info.get("requested_subtitles") or {}).get(options.language) or {}
            source = track.get("filepath")
            if not source or not Path(source).is_file():
                raise ValueError("The site did not provide the requested captions.")
            if not transcripts.parse_cues(source):
                raise ValueError("The caption file contains no transcript text.")
            target = options.format if options.kind == "transcript" else options.caption_format
            output = source if Path(source).suffix == "." + target else transcripts.convert(
                source, target, source_url=url, title=info.get("title"))
            files.append(str(Path(output).resolve()))
            if output != source:
                Path(source).unlink()  # Only this job's downloaded intermediate caption file.
        return {"files": files, "title": info.get("title") or url,
                "size": sum(Path(path).stat().st_size for path in files),
                "actual_quality": output_quality(files[0], options, info)}
