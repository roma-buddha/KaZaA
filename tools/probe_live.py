"""Probe a Chaturbate room: list HLS formats and live status."""
import json
import sys

import yt_dlp

url = sys.argv[1] if len(sys.argv) > 1 else "https://chaturbate.com/seltin_sweety/"
opts = {"quiet": True, "no_color": True, "skip_download": True}
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
except Exception as e:
    print("EXTRACT_ERROR:", type(e).__name__, str(e)[:500])
    sys.exit(1)

print("is_live:", info.get("is_live"), "| live_status:", info.get("live_status"))
print("title:", info.get("title"))
fmts = info.get("formats") or []
print("formats:", len(fmts))
for f in fmts:
    print(json.dumps({
        "format_id": f.get("format_id"), "height": f.get("height"),
        "width": f.get("width"), "vcodec": f.get("vcodec"),
        "acodec": f.get("acodec"), "protocol": f.get("protocol"),
        "tbr": f.get("tbr"), "url_head": (f.get("url") or "")[:80],
        "has_headers": bool(f.get("http_headers")),
    }))
req = info.get("requested_formats")
if req:
    print("requested_formats:", [(r.get("format_id"), r.get("vcodec"), r.get("acodec")) for r in req])
print("url:", (info.get("url") or "")[:100])
