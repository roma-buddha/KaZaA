"""Best-effort media metadata tagging via ffmpeg stream copy.

Writes title/artist/album/year/track/genre without re-encoding. Used for
downloaded audio files and for conversion outputs so music keeps its info.
"""
import os
import subprocess

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav",
              ".wma"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov"}
TAGGABLE_EXTS = AUDIO_EXTS | VIDEO_EXTS


def is_taggable(path):
    return os.path.splitext(path or "")[1].lower() in TAGGABLE_EXTS


def tag_media_file(path, title=None, artist=None, album=None, year=None,
                   track=None, genre=None):
    """Rewrite metadata in-place with a stream copy. Returns True on success.

    year should be a 4-digit string (written to the date field).
    """
    from .downloader import find_ffmpeg  # local import: avoids circulars
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not is_taggable(path) or not os.path.exists(path):
        return False
    meta = []
    for key, val in (("title", title), ("artist", artist), ("album", album),
                     ("date", year), ("track", track), ("genre", genre)):
        if val:
            meta += ["-metadata", f"{key}={val}"]
    if not meta:
        return False
    root, ext = os.path.splitext(path)
    tmp = root + ".tagging" + ext
    cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-i", path, "-c", "copy"]
    if path.lower().endswith(".mp3"):
        cmd += ["-id3v2_version", "3"]
    cmd += meta + [tmp]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300,
                           stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if (r.returncode == 0 and os.path.exists(tmp)
                and os.path.getsize(tmp) > 0):
            os.replace(tmp, path)
            return True
        if os.path.exists(tmp):
            os.remove(tmp)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False
