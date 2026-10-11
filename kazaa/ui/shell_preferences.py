"""Only the new shell's preferences; previous media settings stay separate."""
import json
from pathlib import Path

DEFAULTS = {"theme": "light", "sidebar_width": 250,
            "sidebar_collapsed": False, "page": "search"}


def load(path):
    data = dict(DEFAULTS)
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(saved, dict):
        return data
    if saved.get("theme") in ("light", "dark"):
        data["theme"] = saved["theme"]
    if saved.get("page") in ("search", "downloaded"):
        data["page"] = saved["page"]
    width = saved.get("sidebar_width")
    if type(width) is int:
        data["sidebar_width"] = max(200, min(420, width))
    if type(saved.get("sidebar_collapsed")) is bool:
        data["sidebar_collapsed"] = saved["sidebar_collapsed"]
    return data


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
