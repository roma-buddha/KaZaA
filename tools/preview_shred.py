"""Render only the Shred tab using disposable files and an isolated profile."""
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtWidgets import QApplication
from kazaa.ui.shell import ShellWindow
from kazaa.ui.shred_page import ShredConfirmation

app = QApplication([])
for name in ("segoeui.ttf", "segoeuib.ttf", "georgia.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"], "Fonts", name)))
output = Path(__file__).resolve().parent / "out"
output.mkdir(exist_ok=True)
requested = set(sys.argv[1:])
with tempfile.TemporaryDirectory() as profile:
    folder = Path(profile)
    window = ShellWindow(folder / "shell.json")
    window.navigate("shred")
    window.show()
    app.processEvents()
    if not requested or "empty" in requested:
        window.grab().save(str(output / "shred-empty.png"))
    files = []
    for name, size in (("CiteBetter-descriptives-journal-submission-2026.png", 28412), ("Project budget.xlsx", 158240),
                       ("Passport scan.pdf", 2104880), ("Archive.zip", 8432012)):
        path = folder / name
        with path.open("wb") as file:
            file.write(b"Disposable preview data.")
            file.truncate(size)
        files.append(path)
    window.shred_page.add_files(files)
    for name, theme, size in (("light", "light", (1200, 800)),
                               ("dark", "dark", (1200, 800)),
                               ("wide", "dark", (1920, 900)),
                               ("compact", "light", (820, 600))):
        if requested and name not in requested:
            continue
        window.set_theme(theme)
        window.resize(*size)
        app.processEvents()
        path = output / f"shred-{name}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"Could not save {path}")
        print(path)
    if not requested or "selected" in requested:
        window.resize(1200, 800)
        window.set_theme("dark")
        window.shred_page.table.item(0, 0).setCheckState(Qt.Unchecked)
        window.shred_page.table.setCurrentCell(0, 0)
        window.shred_page.table.selectRow(0)
        window.shred_page.table.setFocus()
        app.processEvents()
        window.grab().save(str(output / "shred-selected.png"))
    if not requested or "progress" in requested:
        page = window.shred_page
        window.resize(1200, 800)
        window.set_theme("dark")
        page.table.item(0, 0).setCheckState(Qt.Checked)
        page.table.clearSelection()
        page.table.setCurrentIndex(QModelIndex())
        page.batch_total, page.batch_done, page.batch_results = 4, 0, []
        page._progress(str(files[0]), 42, "Verifying · pass 1/1")
        page.progress.show()
        page.summary.show()
        page.cancel_button.show()
        page.table.setEnabled(False)
        page.algorithm.setEnabled(False)
        page.shred_button.setEnabled(False)
        app.processEvents()
        window.grab().save(str(output / "shred-progress.png"))
    if not requested or "remove-menu" in requested:
        window.set_theme("dark")
        page = window.shred_page
        page.table.setEnabled(True)
        page.table.selectRow(0)
        point = page.table.visualItemRect(page.table.item(0, 1)).center()
        page.table._context_menu(point)
        app.processEvents()
        page._menu.grab().save(str(output / "shred-remove-menu.png"))
        page._menu.close()
    if not requested or "algorithm" in requested:
        window.set_theme("dark")
        window.shred_page.algorithm.setEnabled(True)
        menu = window.shred_page.algorithm.menu()
        menu.popup(window.shred_page.algorithm.mapToGlobal(QPoint(0, 36)))
        app.processEvents()
        menu.grab().save(str(output / "shred-algorithm.png"))
        menu.close()
    for theme in ("light", "dark"):
        if requested and "confirmation" not in requested:
            continue
        window.set_theme(theme)
        dialog = ShredConfirmation(list(window.shred_page.targets.values()),
                                   window.shred_page.algorithm.currentText(), window)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / f"shred-confirmation-{theme}.png"))
        dialog.close()
        dialog.deleteLater()
    if not requested or "removed" in requested:
        window.resize(1200, 800)
        window.set_theme("dark")
        page = window.shred_page
        page.table.setEnabled(True)
        page.algorithm.setEnabled(True)
        page.progress.hide()
        page.summary.hide()
        page.cancel_button.hide()
        page._check_all(False)
        page.table.item(0, 0).setCheckState(Qt.Checked)
        page.table.setCurrentCell(0, 0)
        page.table.selectRow(0)
        page._remove()
        app.processEvents()
        window.grab().save(str(output / "shred-removed.png"))
    window.close()
