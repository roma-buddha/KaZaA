"""Transcript handling: parse VTT/SRT cue files, export to SRT / VTT / Markdown."""
import html
import os
import re

TIMESTAMP = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{3})")

LANG_NAMES = {
    "en": "English", "de": "German", "es": "Spanish", "fr": "French",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
}


def _to_seconds(m):
    return (int(m["h"]) * 3600 + int(m["m"]) * 60 + int(m["s"])
            + int(m["ms"]) / 1000.0)


def _fmt_ts_srt(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_ts_vtt(seconds):
    return _fmt_ts_srt(seconds).replace(",", ".")


def _fmt_ts_md(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _clean_text(lines):
    text = " ".join(l.strip() for l in lines if l.strip())
    text = re.sub(r"<[^>]+>", "", text)            # vtt tags: <c>, <00:00:01.000>, <v Speaker>
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_cues(path):
    """Parse a .vtt or .srt file into [(start_s, end_s, text), ...]."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as stream:
        raw = stream.read()
    if not raw.strip():
        return []
    if path.lower().endswith(".srt") or "-->" not in raw.splitlines()[0] and \
       raw.lstrip().startswith("1"):
        return _parse_srt(raw)
    return _parse_vtt(raw)


def _parse_vtt(raw):
    cues = []
    current = None          # (start, end, [lines])
    for line in raw.replace("\r\n", "\n").split("\n"):
        ts = TIMESTAMP.search(line)
        if "-->" in line and ts:
            start = _to_seconds(TIMESTAMP.search(line))
            end_m = re.search(r"-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{3})", line)
            end = _to_seconds(TIMESTAMP.search(end_m.group(1))) if end_m else start
            current = [start, end, []]
        elif current is not None:
            if line.strip():
                current[2].append(line)
            else:
                text = _clean_text(current[2])
                if text:
                    cues.append((current[0], current[1], text))
                current = None
    if current is not None:
        text = _clean_text(current[2])
        if text:
            cues.append((current[0], current[1], text))
    return cues


def _parse_srt(raw):
    cues = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        m = re.search(r"(\d{1,2}:\d{2}:\d{2},\d{3})\s*-->\s*"
                      r"(\d{1,2}:\d{2}:\d{2},\d{3})", block)
        if not m:
            continue
        start = _to_seconds(TIMESTAMP.search(m.group(1)))
        end = _to_seconds(TIMESTAMP.search(m.group(2)))
        # text = lines after the timestamp line
        text_lines = []
        seen_ts = False
        for l in lines:
            if "-->" in l:
                seen_ts = True
                continue
            if seen_ts or TIMESTAMP.search(l) is None:
                if seen_ts:
                    text_lines.append(l)
        if not text_lines:      # timestamp on first line, text follows
            idx = next((i for i, l in enumerate(lines) if "-->" in l), 0)
            text_lines = lines[idx + 1:]
        text = _clean_text(text_lines)
        if text:
            cues.append((start, end, text))
    return cues


def to_srt(cues):
    out = []
    for i, (start, end, text) in enumerate(cues, 1):
        out.append(f"{i}\n{_fmt_ts_srt(start)} --> {_fmt_ts_srt(end)}\n{text}\n")
    return "\n".join(out)


def to_vtt(cues):
    out = ["WEBVTT\n"]
    for start, end, text in cues:
        out.append(f"{_fmt_ts_vtt(start)} --> {_fmt_ts_vtt(end)}\n{text}\n")
    return "\n".join(out)


def to_markdown(cues, title="", source_url="", lang="", with_timestamps=True):
    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    meta = []
    if lang:
        meta.append(f"- Language: {LANG_NAMES.get(lang, lang)}")
    if source_url:
        meta.append(f"- Source: {source_url}")
    if meta:
        lines.extend(meta)
        lines.append("")
    if not cues:
        lines.append("_No transcript available._")
        return "\n".join(lines) + "\n"
    for start, _end, text in cues:
        if with_timestamps:
            lines.append(f"- **[{_fmt_ts_md(start)}]** {text}")
        else:
            lines.append(text)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def convert(src, target_fmt, source_url="", with_timestamps=True, title=None):
    """Convert a .vtt/.srt transcript to 'srt', 'vtt', 'txt' or 'md'.
    Returns the output path."""
    cues = parse_cues(src)
    base, _ = os.path.splitext(src)
    if title is None:
        title = os.path.basename(base)
    if target_fmt == "txt":
        out = f"{base}.txt"
        content = "\n".join(text for _start, _end, text in cues) + "\n"
    elif target_fmt == "md":
        out = f"{base}.md"
        content = to_markdown(cues, title=title, source_url=source_url,
                              with_timestamps=with_timestamps)
    elif target_fmt == "srt":
        out = f"{base}.srt"
        content = to_srt(cues)
    elif target_fmt == "vtt":
        out = f"{base}.vtt"
        content = to_vtt(cues)
    else:
        raise ValueError(f"unsupported transcript format: {target_fmt}")
    if os.path.abspath(out) == os.path.abspath(src):
        raise ValueError("source and target are the same file")
    with open(out, "w", encoding="utf-8") as f:
        f.write(content)
    return out
