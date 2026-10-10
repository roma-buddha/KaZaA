"""VLoader visual theme — dark, modern, applied app-wide via Qt style sheets."""

ACCENT = "#7c6cff"
ACCENT_HOVER = "#948aff"
ACCENT_PRESSED = "#6557e8"
ACCENT_SOFT = "rgba(124, 108, 255, 0.14)"

BG = "#12141c"
PANEL = "#1a1d29"
CARD = "#1f2333"
INPUT = "#171a26"
BORDER = "#2a2f42"
TEXT = "#e8eaf2"
TEXT_DIM = "#9aa0b4"
DANGER = "#ff5d6c"
SUCCESS = "#3ddc97"

FONT = "Segoe UI"

QSS = f"""
* {{
    font-family: "{FONT}", "Inter", sans-serif;
    font-size: 10pt;
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{
    background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 4px 8px; border-radius: 6px;
}}

/* ---------- sidebar navigation ---------- */
QListWidget#nav {{
    background: {PANEL};
    border: none;
    border-right: 1px solid {BORDER};
    padding: 12px 8px;
    outline: none;
}}
QListWidget#nav::item {{
    height: 44px;
    padding: 0 16px;
    margin: 2px 4px;
    border-radius: 8px;
    color: {TEXT_DIM};
}}
QListWidget#nav::item:hover {{ background: {CARD}; color: {TEXT}; }}
QListWidget#nav::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT};
    border-left: 3px solid {ACCENT};
}}

/* ---------- generic widgets ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    selection-background-color: {ACCENT};
    selection-color: white;
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none; width: 28px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {TEXT_DIM};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {ACCENT};
    selection-color: white;
    padding: 4px;
}}

QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 18px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #262b3e; border-color: #343a52; }}
QPushButton:pressed {{ background: #2d3350; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {PANEL}; }}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT_HOVER});
    border: none;
    color: white;
    font-weight: 600;
    padding: 10px 22px;
}}
QPushButton[variant="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_HOVER}, stop:1 {ACCENT});
}}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[variant="danger"] {{
    background: {DANGER}; border: none; color: white; font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{ background: #ff707d; }}
QPushButton[variant="ghost"] {{
    background: transparent; border: 1px solid {BORDER}; color: {TEXT_DIM};
}}
QPushButton[variant="ghost"]:hover {{ color: {TEXT}; border-color: {ACCENT}; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {TEXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {INPUT};
}}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    image: none;
}}

/* ---------- cards / groups ---------- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 14px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px; top: 2px;
    color: {TEXT_DIM};
    font-size: 9pt;
    letter-spacing: 1px;
}}

QLabel#h1 {{
    font-size: 16pt; font-weight: 700; color: {TEXT};
}}
QLabel#h2 {{
    font-size: 12pt; font-weight: 600; color: {TEXT};
}}
QLabel#dim {{ color: {TEXT_DIM}; }}

/* ---------- progress ---------- */
QProgressBar {{
    background: {INPUT};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    font-size: 8pt;
    color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 #4fc3f7);
}}

/* ---------- table ---------- */
QTableWidget {{
    background: {PANEL};
    alternate-background-color: {CARD};
    border: none;
    gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QTableWidget::item {{ padding: 6px 10px; border: none; }}
QTableWidget::item:hover {{ background: #232838; }}
QHeaderView::section {{
    background: {PANEL};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 10px 12px;
    font-weight: 600;
    font-size: 9pt;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QTableCornerButton::section {{ background: {PANEL}; border: none; }}

/* ---------- menus ---------- */
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 8px 14px; background: transparent; }}
QMenuBar::item:selected {{ background: {CARD}; border-radius: 6px; }}
QMenu {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 28px 8px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 10px; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: #2e3448; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3a415c; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: #2e3448; border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: #3a415c; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---------- status bar & misc ---------- */
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QTabWidget::pane {{ border: none; }}
QSplitter::handle {{ background: {BORDER}; }}
QListWidget {{
    background: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QMessageBox {{ background: {BG}; }}
"""


def apply(app):
    app.setStyleSheet(QSS)
    from PySide6.QtGui import QFont
    app.setFont(QFont(FONT, 10))
