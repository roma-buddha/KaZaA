"""Lightweight input routing; torrent libraries stay inside worker processes."""
import base64
from pathlib import Path, PurePosixPath
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit
from urllib.request import url2pathname

from .video_backend import link_key, validate_url


def is_torrent_source(value):
    value = value.strip()
    return value.lower().startswith("magnet:") or urlsplit(value).path.lower().endswith(".torrent")


def magnet_hashes(value):
    hashes = []
    for xt in parse_qs(urlsplit(value).query).get("xt", []):
        if xt.lower().startswith("urn:btih:"):
            digest = xt[9:]
            if re.fullmatch(r"[a-zA-Z2-7]{32}", digest):
                digest = base64.b32decode(digest.upper()).hex()
            if re.fullmatch(r"[0-9a-fA-F]{40}", digest):
                hashes.append("v1:" + digest.lower())
        elif re.fullmatch(r"urn:btmh:1220[0-9a-fA-F]{64}", xt, re.I):
            hashes.append("v2:" + xt[13:].lower())
    if not hashes:
        raise ValueError("This magnet link has no valid BitTorrent info-hash.")
    return sorted(set(hashes))


def local_torrent_path(value):
    if value.lower().startswith("file:"):
        parsed = urlsplit(value)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raise ValueError("Drop a local .torrent file or paste a magnet link.")
        return Path(url2pathname(parsed.path)).resolve()
    return Path(value).expanduser().resolve()


def normalize_source(value):
    value = value.strip().strip('"')
    if not is_torrent_source(value):
        return validate_url(value), "link"
    if value.lower().startswith("magnet:"):
        magnet_hashes(value)
        return value, "torrent"
    parsed = urlsplit(value)
    if parsed.scheme.lower() in ("http", "https"):
        if not parsed.hostname:
            raise ValueError("Paste a full torrent link.")
        return value, "torrent"
    return local_torrent_path(value).as_uri(), "torrent"


def source_key(value):
    value, source = normalize_source(value)
    if source == "link":
        return link_key(value)
    if value.lower().startswith("magnet:"):
        return "|".join(magnet_hashes(value))
    return urlunsplit(urlsplit(value)._replace(fragment=""))


def input_tokens(text):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # A filesystem path is one input even when its filename has spaces.
        if line.lower().strip('"').endswith(".torrent") and not re.match(r"^(https?|magnet):", line, re.I):
            yield line.strip('"')
        else:
            yield from line.split()


def parse_sources(text):
    entries, seen = [], set()
    for raw in input_tokens(text):
        try:
            url, source = normalize_source(raw)
            key, error = source_key(url), ""
        except (ValueError, OSError) as exc:
            url, source, key, error = raw, "torrent" if is_torrent_source(raw) else "link", raw, str(exc)
        if key not in seen:
            entries.append({"url": url, "source": source, "error": error})
            seen.add(key)
    return entries


def output_paths(manifest, folder):
    """Validate Windows names and containment before allowing any disk writes."""
    root, seen, paths = Path(folder).resolve(), set(), {}
    reserved = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
    for item in manifest:
        raw = item["path"].replace("\\", "/")
        parts = raw.split("/")
        if PurePosixPath(raw).is_absolute() or any(
            part in ("", ".", "..") or part.endswith((".", " ")) or reserved.match(part)
            or re.search(r'[<>:"|?*\x00-\x1f]', part) for part in parts
        ):
            raise ValueError("This torrent contains an unsafe or invalid output path: " + raw)
        key = raw.casefold()
        if key in seen:
            raise ValueError("This torrent contains colliding output filenames: " + raw)
        seen.add(key)
        path = root.joinpath(*parts).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Torrent files must stay inside the download folder.")
        paths[item["index"]] = str(path)
    for key in seen:
        if any(parent.as_posix().casefold() in seen for parent in PurePosixPath(key).parents if str(parent) != "."):
            raise ValueError("This torrent contains colliding file and folder names.")
    return paths


def validate_selection(manifest, selected):
    valid = {item["index"] for item in manifest if not item.get("pad")}
    if not selected or any(type(index) is not int or index not in valid for index in selected):
        raise ValueError("Select at least one available torrent file.")
    return sorted(set(selected))
