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


def stylesheet(colors):
    c = colors
    return f"""
    QWidget {{ color: {c['ink']}; font-family: 'Segoe UI'; font-size: 13px; }}
    QMainWindow, QWidget#workspace, QWidget#page {{ background: {c['paper']}; }}
    QWidget#sidebar {{ background: {c['sidebar']}; }}
    QWidget#topbar {{ background: {c['paper']}; border-bottom: 1px solid {c['line']}; }}
    QWidget#sidebarFooter {{ border-top: 1px solid {c['line']}; }}
    QLabel {{ background: transparent; border: none; }}
    QLabel[role='muted'] {{ color: {c['muted']}; }}
    QLabel[role='eyebrow'] {{ color: {c['muted']}; font-size: 11px; font-weight: 600; }}
    QLabel[role='heading'] {{ font-family: Georgia; font-size: 34px; font-weight: 400; }}
    QLabel[role='subheading'] {{ font-family: Georgia; font-size: 24px; font-weight: 400; }}
    QLabel[role='brand'] {{ font-family: Georgia; font-size: 24px; }}
    QLabel[role='status'] {{ color: {c['green']}; background: {c['green_soft']};
        border-radius: 5px; padding: 6px 10px; font-size: 11px; }}
    QLabel[role='tag'] {{ color: {c['muted']}; border: 1px solid {c['line']};
        border-radius: 5px; padding: 5px 9px; font-size: 11px; }}
    QLabel[role='emptyIcon'] {{ background: {c['accent_soft']}; border-radius: 14px; }}
    QPushButton {{ background: transparent; border: 1px solid transparent;
        border-radius: 5px; padding: 8px 12px; min-height: 24px; text-align: left; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:pressed {{ background: {c['accent_soft']}; }}
    QPushButton:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton[nav='true'] {{ padding: 9px 12px; color: {c['muted']}; }}
    QPushButton[nav='true']:checked {{ background: {c['accent_soft']};
        color: {c['accent']}; font-weight: 600; }}
    QPushButton[role='icon'] {{ padding: 8px; text-align: center; }}
    QPushButton[role='secondary'] {{ background: {c['surface']}; border: 1px solid {c['line']}; }}
    QPushButton[role='secondary']:hover {{ background: {c['hover']}; }}
    QPushButton[role='primary'] {{ background: {c['accent']}; color: {c['on_accent']};
        text-align: center; padding: 10px 18px; }}
    QPushButton[role='primary']:hover {{ background: {c['ink']}; color: {c['surface']}; }}
    QFrame[role='panel'] {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 8px; }}
    QFrame[role='panel'] QLabel {{ border: none; background: transparent; }}
    QPushButton[role='theme'] {{ background: {c['surface']}; border: 1px solid {c['line']};
        padding: 20px; font-size: 14px; }}
    QPushButton[role='theme']:checked {{ border: 1px solid {c['accent']};
        color: {c['accent']}; background: {c['accent_soft']}; }}
    QScrollArea {{ border: none; background: {c['paper']}; }}
    QScrollArea > QWidget > QWidget {{ background: {c['paper']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QSplitter::handle {{ background: {c['paper']}; border-left: 1px solid {c['line']}; }}
    QSplitter::handle:hover, QSplitter::handle:focus {{ background: {c['accent_soft']}; }}
    """
