"""Isolated yt-dlp process: structured messages allow cancellation of FFmpeg too."""
import json
import sys
from pathlib import Path

from .video_backend import inspect_video, perform_download


def emit(kind, data):
    print(json.dumps({"type": kind, "data": data}, ensure_ascii=False), flush=True)


def main():
    # Pipes on Windows otherwise inherit a legacy code page, corrupting non-Latin titles.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    try:
        request = json.load(sys.stdin)
        class StopRequest:
            def is_set(self):
                return bool(request.get("control_file") and Path(request["control_file"]).exists())
        if request.get("source") == "torrent":
            from .torrent_backend import inspect_torrent, download_torrent
            result = inspect_torrent(request, StopRequest()) if request["action"] == "inspect" else download_torrent(request, emit, StopRequest())
        elif request["action"] == "inspect":
            result = inspect_video(request["url"])
        else:
            result = perform_download(request, emit, StopRequest())
        emit("result", result)
        return 0
    except Exception as exc:
        emit("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
