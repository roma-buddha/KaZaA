"""Small, consistent stroke icons drawn locally, without network assets."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "home": '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
    "music": '<path d="M9 18V5l11-2v13M9 8l11-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="17" cy="16" rx="3" ry="3"/>',
    "convert": '<path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/>',
    "record": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/><circle cx="12" cy="10.5" r="2.5"/>',
    "library": '<rect x="3" y="4" width="5" height="16" rx="1"/><path d="M12 4v16m4-16 5 15"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "settings": '<path d="m9 3-1 3-3 1-2 4 2 3 1 4 4 1 2 2 4-1 1-3 3-1 1-4-2-3-1-4-4-1z"/><circle cx="12" cy="12" r="3"/>',
    "sidebar": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m6-13-3 4 3 4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
    "moon": '<path d="M20.5 14.1A9 9 0 0 1 9.9 3.5 9 9 0 1 0 20.5 14.1z"/>',
    "arrow": '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
}


def icon(name, color, size=20):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.6" '
           f'stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>')
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size * 2, size * 2))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
