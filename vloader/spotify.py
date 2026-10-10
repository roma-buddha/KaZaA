"""Spotify link support.

Spotify's audio streams are DRM-protected and cannot be ripped directly.
Like every "Spotify downloader" web service, we resolve the track list and
metadata from the link, then fetch the audio from a public source (YouTube
search) and write proper MP3 tags + cover art. Metadata comes from Spotify's
public embed pages (no API key required).
"""
import json
import re
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class SpotifyError(Exception):
    pass


_KIND_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?(track|album|playlist)/([A-Za-z0-9]+)")
_URI_RE = re.compile(r"^spotify:(track|album|playlist):([A-Za-z0-9]+)$")


def is_spotify_url(url):
    url = (url or "").strip()
    return bool(_URI_RE.match(url) or "spotify.link" in url
                or _KIND_RE.search(url))


def _parse(url):
    url = (url or "").strip()
    m = _URI_RE.match(url)
    if m:
        return m.group(1), m.group(2)
    m = _KIND_RE.search(url)
    if m:
        return m.group(1), m.group(2)
    if "spotify.link" in url:
        # short link: follow the redirect to the open.spotify.com target
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            final = urllib.request.urlopen(req, timeout=20).geturl()
        except Exception as e:  # noqa: BLE001
            raise SpotifyError(f"cannot resolve Spotify short link: {e}")
        m = _KIND_RE.search(final) or _URI_RE.match(final)
        if m:
            return m.group(1), m.group(2)
    raise SpotifyError("not a Spotify track, album or playlist link")


def _find_entity(obj, kind):
    if isinstance(obj, dict):
        if obj.get("type") == kind and "name" in obj:
            return obj
        for v in obj.values():
            r = _find_entity(v, kind)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_entity(v, kind)
            if r:
                return r
    return None


def _fetch_entity(kind, ident):
    url = f"https://open.spotify.com/embed/{kind}/{ident}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=20).read().decode(
            "utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raise SpotifyError(f"cannot reach Spotify: {e}")
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S)
    if not m:
        raise SpotifyError("unexpected response from Spotify embed page")
    try:
        data = json.loads(m.group(1))
    except ValueError:
        raise SpotifyError("cannot parse Spotify embed data")
    ent = _find_entity(data, kind)
    if not ent:
        raise SpotifyError("Spotify page not found (wrong link or private)")
    return ent


def _cover_url(ent):
    imgs = (ent.get("visualIdentity") or {}).get("image") or []
    if imgs:
        return imgs[-1].get("url")
    arts = ent.get("coverArt") or []
    if arts:
        return max(arts, key=lambda c: c.get("maxWidth") or 0).get("url")
    return None


def resolve(url):
    """Return {'kind', 'name', 'artist', 'cover', 'tracks': [...]}.

    Each track: title, artists, album, duration_ms.
    """
    kind, ident = _parse(url)
    ent = _fetch_entity(kind, ident)
    cover = _cover_url(ent)
    if kind == "track":
        title = ent.get("title") or ent.get("name") or "track"
        artists = ", ".join(a.get("name", "") for a in ent.get("artists") or [])
        tracks = [{"title": title, "artists": artists, "album": "",
                   "duration_ms": ent.get("duration") or 0}]
        return {"kind": kind, "name": title, "artist": artists,
                "cover": cover, "tracks": tracks}
    name = ent.get("name") or ""
    artist = ent.get("subtitle") or ""
    tracks = [{
        "title": t.get("title") or "",
        "artists": t.get("subtitle") or "",
        "album": name if kind == "album" else "",
        "duration_ms": t.get("duration") or 0,
    } for t in (ent.get("trackList") or [])]
    if not tracks:
        raise SpotifyError("no tracks found (empty or private collection)")
    return {"kind": kind, "name": name, "artist": artist,
            "cover": cover, "tracks": tracks}
