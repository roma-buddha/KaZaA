"""Ohana AI's desktop colors, adapted to Qt's native widgets."""

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
    QPushButton[role='theme'] {{ background: {c['surface']}; border: 1px solid {c['line']};
        padding: 16px; text-align: left; }}
    QPushButton[role='theme']:checked {{ background: {c['accent_soft']};
        border: 1px solid {c['accent']}; color: {c['accent']}; }}
    QPushButton[role='theme']:focus {{ border: 2px solid {c['accent']}; }}
    QDialog#appearance {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 8px; }}
    QSplitter::handle {{ background: {c['paper']}; border-left: 1px solid {c['line']}; }}
    QSplitter::handle:hover, QSplitter::handle:focus {{ background: {c['accent_soft']}; }}
    """
