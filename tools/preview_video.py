"""Preview the video pages offline using a previously inspected link and history."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from kazaa.ui.shell import ShellWindow
from kazaa.ui.video_pages import VideoCard

parser = argparse.ArgumentParser()
parser.add_argument("--metadata", type=Path)
parser.add_argument("--history", type=Path)
parser.add_argument("--only", nargs="+", help="Render only the named previews")
args = parser.parse_args()
app = QApplication([])
if os.name == "nt":
    for name in ("segoeui.ttf", "segoeuib.ttf", "georgia.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"], "Fonts", name)))
output = Path(__file__).resolve().parent / "out"
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as profile:
    window = ShellWindow(Path(profile, "shell.json"))
    page = window.search_page
    window.show()
    app.processEvents()
    if not args.only or "search-empty" in args.only:
        window.grab().save(str(output / "search-empty.png"))
    card = None
    if args.metadata:
        info = [json.loads(line)["data"] for line in args.metadata.read_text(encoding="utf-8-sig").splitlines()
                if json.loads(line).get("type") == "result"][0]
        page.input.setPlainText(info["url"])
        card = VideoCard(info["url"], window.download_queue)
        page.cards[info["url"]] = card
        page.cards_layout.addWidget(card)
        card.selection_changed.connect(page._selection_changed)
        card.set_result(info)
        page.current_input = True
        page._selection_changed()
    if args.history:
        jobs = json.loads(args.history.read_text(encoding="utf-8"))["jobs"]
        for job in jobs:
            window.downloaded_page.update_job(job["id"], job)
        if jobs:
            active = copy.deepcopy(jobs[0])
            active.update(id="preview-active", status="downloading", percent=37,
                          speed=1800000, total_bytes=24000000, downloaded_bytes=8880000,
                          options={**active["options"], "kind": "video", "format": "mp4", "quality": "720"})
            window.downloaded_page.update_job(active["id"], active)
    for name, theme, size, tab, kind in (
        ("search-light", "light", (1600, 900), "search", "video"),
        ("search-dark", "dark", (1600, 900), "search", "video"),
        ("search-compact", "light", (860, 640), "search", "audio"),
        ("search-captions", "dark", (1200, 800), "search", "transcript"),
        ("downloaded-dark", "dark", (1600, 900), "downloaded", "video"),
        ("downloaded-light", "light", (1600, 900), "downloaded", "video"),
        ("downloaded-compact", "light", (860, 640), "downloaded", "video"),
    ):
        if args.only and name not in args.only:
            continue
        window.resize(*size)
        window.set_theme(theme)
        window.navigate(tab)
        if card:
            card.options_panel.kind.setCurrentIndex(card.options_panel.kind.findData(kind))
        app.processEvents()
        path = output / f"{name}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Could not save {path}")
        print(path)
    if not args.only or "video-settings" in args.only:
        window.show_settings()
        app.processEvents()
        window.appearance.grab().save(str(output / "video-settings.png"))
    window.close()
