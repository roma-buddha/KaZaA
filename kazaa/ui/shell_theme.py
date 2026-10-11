"""Ohana AI's desktop colors, adapted to Qt's native widgets."""
from pathlib import Path

LIGHT = {
    "paper": "#f8f5ee", "surface": "#fffdf9", "sidebar": "#f0ede6",
    "ink": "#302d29", "muted": "#6b645c", "line": "#ded8ce",
    "accent": "#7f463e", "accent_soft": "#eee1d9", "on_accent": "#fffdf9",
    "green": "#566749", "green_soft": "#e9ede2", "hover": "#eae5db",
}
DARK = {
    "paper": "#181817", "surface": "#20201e", "sidebar": "#141413",
    "ink": "#e6e0d5", "muted": "#aaa397", "line": "#30302c",
    "accent": "#d5a18c", "accent_soft": "#3b2d28", "on_accent": "#231a16",
    "green": "#b0bf96", "green_soft": "#293024", "hover": "#2c2a26",
}


def stylesheet(c):
    assets = Path(__file__).with_name("assets")
    arrow = (assets / "dropdown.svg").as_posix()
    check = (assets / ("check-dark.svg" if c is DARK else "check-light.svg")).as_posix()
    return f"""
    QWidget {{ color: {c['ink']}; font-family: 'Segoe UI'; font-size: 13px; }}
    QMainWindow, QWidget#root, QWidget#workspace, QWidget#canvas {{ background: {c['paper']}; }}
    QWidget#sidebar {{ background: {c['sidebar']}; }}
    QWidget#topbar {{ background: {c['paper']}; border-bottom: 1px solid {c['line']}; }}
    QLabel {{ background: transparent; border: none; }}
    QLabel[role='heading'] {{ font-family: Georgia; font-size: 22px; }}
    QLabel#wordmark {{ font-family: Georgia; font-size: 29px; font-weight: normal; }}
    QPushButton {{ background: transparent; border: 1px solid transparent;
        border-radius: 5px; padding: 8px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton[role='icon'] {{ color: {c['muted']}; }}
    QPushButton#sidebarToggle:focus {{ border: 1px solid transparent; }}
    QPushButton#windowClose:hover {{ background: #b94a45; }}
    QPushButton[role='nav'] {{ text-align: left; padding: 12px; min-height: 22px; }}
    QPushButton[role='nav']:checked {{ background: {c['accent_soft']}; color: {c['accent']}; }}
    QWidget#page, QScrollArea {{ background: {c['paper']}; border: none; }}
    QFrame[role='panel'], QFrame[role='card'] {{ background: {c['surface']};
        border: 1px solid {c['line']}; border-radius: 8px; }}
    QLabel[role='pageTitle'] {{ font-family: Georgia; font-size: 28px; }}
    QLabel[role='sectionTitle'] {{ font-size: 15px; font-weight: 600; }}
    QLabel[role='cardTitle'] {{ font-size: 15px; font-weight: 600; }}
    QLabel[role='muted'] {{ color: {c['muted']}; font-size: 12px; }}
    QLabel[role='error'] {{ color: {c['accent']}; font-size: 12px; }}
    QLabel#thumbnail {{ background: {c['hover']}; border-radius: 5px; }}
    QPushButton[role='primary'] {{ background: {c['accent']}; color: {c['on_accent']};
        padding: 9px 16px; min-height: 18px; }}
    QPushButton[role='primary']:disabled {{ background: {c['hover']}; color: {c['muted']}; }}
    QPlainTextEdit, QLineEdit, QComboBox {{ background: {c['paper']}; border: 1px solid {c['line']};
        border-radius: 5px; padding: 8px; selection-background-color: {c['accent_soft']}; }}
    QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QComboBox {{ min-height: 18px; }}
    QComboBox::drop-down {{ width: 22px; border: none; }}
    QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['ink']};
        selection-background-color: {c['accent_soft']}; border: 1px solid {c['line']}; }}
    QCheckBox {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['muted']}; border-radius: 3px; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{check}"); }}
    QProgressBar {{ background: {c['hover']}; border: none; border-radius: 2px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 2px; }}
    QScrollBar:vertical {{ background: {c['paper']}; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['line']}; min-height: 24px; border-radius: 4px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QPushButton[role='theme'] {{ background: {c['surface']}; border: 1px solid {c['line']};
        padding: 16px; text-align: left; }}
    QPushButton[role='theme']:checked {{ background: {c['accent_soft']};
        border: 1px solid {c['accent']}; color: {c['accent']}; }}
    QPushButton[role='theme']:focus {{ border: 2px solid {c['accent']}; }}
    QDialog#appearance {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 8px; }}
    QSplitter::handle {{ background: {c['paper']}; border-left: 1px solid {c['line']}; }}
    QSplitter::handle:hover, QSplitter::handle:focus {{ background: {c['accent_soft']}; }}
    """
