"""Preview the video pages offline using a previously inspected link and history."""
import argparse
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
    if args.metadata:
        info = [json.loads(line)["data"] for line in args.metadata.read_text(encoding="utf-8-sig").splitlines()
                if json.loads(line).get("type") == "result"][0]
        page.input.setPlainText(info["url"])
        card = VideoCard(info["url"])
        page.cards[info["url"]] = card
        page.cards_layout.addWidget(card)
        card.selection_changed.connect(page._selection_changed)
        card.set_result(info)
        page.current_input = True
        page._selection_changed()
        page.empty.hide()
        page.download_selected.show()
        page.results_label.setText("1 link")
    if args.history:
        for job in json.loads(args.history.read_text(encoding="utf-8"))["jobs"]:
            window.downloaded_page.update_job(job["id"], job)
    window.show()
    for name, theme, size, tab, expanded, kind in (
        ("search-light", "light", (1200, 800), "search", False, "video"),
        ("search-dark", "dark", (1200, 800), "search", False, "video"),
        ("search-options", "dark", (1200, 800), "search", True, "video"),
        ("search-compact", "light", (860, 640), "search", True, "audio"),
        ("search-captions", "dark", (1200, 800), "search", True, "transcript"),
        ("downloaded-dark", "dark", (1200, 800), "downloaded", False, "video"),
        ("downloaded-light", "light", (1200, 800), "downloaded", False, "video"),
    ):
        window.resize(*size)
        window.set_theme(theme)
        window.navigate(tab)
        page.options_toggle.setChecked(expanded)
        page._toggle_options()
        page.kind.setCurrentIndex(page.kind.findData(kind))
        app.processEvents()
        path = output / f"{name}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Could not save {path}")
        print(path)
    window.close()
