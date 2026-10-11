"""Spotify link support.

Spotify's audio streams are DRM-protected and cannot be ripped directly.
Like every "Spotify downloader" web service, we resolve the track list and
metadata from the link, then fetch the audio from a public source (YouTube
search) and write proper MP3 tags + cover art. Metadata comes from Spotify's
public embed pages (no API key required).
"""
import json
import re
import time
import urllib.parse
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

    Each track: title, artists, album, year, track_no, genre, duration_ms.
    """
    kind, ident = _parse(url)
    ent = _fetch_entity(kind, ident)
    cover = _cover_url(ent)
    year = ((ent.get("releaseDate") or {}).get("isoString") or "")[:4]

    def _tr(title, artists, album, dur, yr=""):
        return {"title": title, "artists": artists, "album": album,
                "year": yr, "track_no": 0, "genre": "",
                "duration_ms": dur}

    if kind == "track":
        title = ent.get("title") or ent.get("name") or "track"
        artists = ", ".join(a.get("name", "") for a in ent.get("artists") or [])
        tracks = [_tr(title, artists, "", ent.get("duration") or 0, year)]
        return {"kind": kind, "name": title, "artist": artists,
                "cover": cover, "tracks": tracks}
    name = ent.get("name") or ""
    artist = ent.get("subtitle") or ""
    tracks = [_tr(t.get("title") or "", t.get("subtitle") or "",
                  name if kind == "album" else "",
                  t.get("duration") or 0, year if kind == "album" else "")
              for t in (ent.get("trackList") or [])]
    if not tracks:
        raise SpotifyError("no tracks found (empty or private collection)")
    return {"kind": kind, "name": name, "artist": artist,
            "cover": cover, "tracks": tracks}


# ---- iTunes enrichment (public Search API, no key) -----------------------

_ITUNES = "https://itunes.apple.com/search"


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def _itunes_get(params):
    url = _ITUNES + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get(
                "results") or []
    except Exception:  # noqa: BLE001 - enrichment is best-effort
        return []


def _art_1200(url):
    return re.sub(r"\d+x\d+bb?\.", "1200x1200bb.", url or "")


def _itunes_song(artist, title):
    results = _itunes_get(
        {"term": f"{artist} {title}", "entity": "song", "limit": 8})
    if not results:
        return None
    want_t, want_a = _norm(title), _norm(artist)
    best = None
    for r in results:
        rt, ra = _norm(r.get("trackName")), _norm(r.get("artistName"))
        if rt == want_t and (want_a in ra or ra in want_a):
            best = r
            break
        if best is None and rt == want_t:
            best = r
    best = best or results[0]
    return {"album": best.get("collectionName") or "",
            "year": (best.get("releaseDate") or "")[:4],
            "track_no": best.get("trackNumber") or 0,
            "genre": best.get("primaryGenreName") or "",
            "art": _art_1200(best.get("artworkUrl100"))}


def _itunes_album(artist, album):
    results = _itunes_get(
        {"term": f"{artist} {album}", "entity": "album", "limit": 6})
    if not results:
        return None
    want = _norm(album)
    best = next((r for r in results
                 if _norm(r.get("collectionName")) == want), results[0])
    return {"year": (best.get("releaseDate") or "")[:4],
            "genre": best.get("primaryGenreName") or "",
            "art": _art_1200(best.get("artworkUrl100"))}


def _fill(track, key, val):
    if val and not track.get(key):
        track[key] = val


def enrich(coll):
    """Fill missing album/year/track_no/genre from the iTunes Search API.

    Only empty fields are filled; lookups are cached per collection.
    Upgrades the cover to iTunes' 1200px artwork when available.
    """
    tracks = coll.get("tracks") or []
    if coll.get("kind") == "album":
        hit = _itunes_album(coll.get("artist") or "", coll.get("name") or "")
        if hit:
            for t in tracks:
                _fill(t, "year", hit["year"])
                _fill(t, "genre", hit["genre"])
            if hit.get("art"):
                coll["cover"] = hit["art"]
        return
    cache = {}
    for t in tracks:
        key = (_norm(t.get("artists")), _norm(t.get("title")))
        if key not in cache:
            cache[key] = _itunes_song(t.get("artists") or "",
                                      t.get("title") or "")
            time.sleep(0.15)
        hit = cache[key]
        if not hit:
            continue
        _fill(t, "album", hit["album"])
        _fill(t, "year", hit["year"])
        _fill(t, "track_no", hit["track_no"])
        _fill(t, "genre", hit["genre"])
        if coll.get("kind") == "track" and hit.get("art"):
            coll["cover"] = hit["art"]
