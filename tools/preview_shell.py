"""Render only the new shell, with an isolated profile and no media activity."""
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from kazaa.ui.shell import ShellWindow

output = Path(__file__).resolve().parent / "out"
output.mkdir(exist_ok=True)
app = QApplication([])
# Offscreen Qt does not discover Windows fonts automatically.
if os.name == "nt":
    for name in ["segoeui.ttf", "segoeuib.ttf", "georgia.ttf"]:
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"], "Fonts", name)))
with tempfile.TemporaryDirectory() as profile:
    window = ShellWindow(Path(profile, "shell.json"))
    window.show()
    for name, theme, size, collapsed in [
        ("shell-light", "light", (1200, 800), False),
        ("shell-dark", "dark", (1200, 800), False),
        ("shell-compact", "dark", (860, 640), False),
        ("shell-collapsed", "light", (1200, 800), True),
    ]:
        window.set_theme(theme)
        window.resize(*size)
        window._set_collapsed(collapsed)
        app.processEvents()
        path = output / f"{name}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Could not save {path}")
        print(path)
    for theme in ("light", "dark"):
        window.set_theme(theme)
        window.show_settings()
        app.processEvents()
        path = output / f"appearance-{theme}.png"
        if not window.appearance.grab().save(str(path)):
            raise RuntimeError(f"Could not save {path}")
        print(path)
        window.appearance.close()
    window.close()
