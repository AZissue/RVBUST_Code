from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


PATHS = {
    "new": '<path d="M12 5v14M5 12h14"/>',
    "open": '<path d="M3 7v12h18V9H9L7 7H3Z"/><path d="M3 7V5h6l2 2"/>',
    "save": '<path d="M5 3h12l4 4v14H3V3h2Z"/><path d="M7 3v6h9V3M7 21v-8h10v8"/>',
    "upload": '<path d="M12 16V3M7 8l5-5 5 5M4 14v7h16v-7"/>',
    "project": '<path d="M4 4h16v16H4Z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "folder": '<path d="M3 6h7l2 2h9v11H3V6Z"/>',
    "part": '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
    "scan": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><circle cx="12" cy="12" r="3"/>',
    "cloud": '<circle cx="7" cy="8" r="1"/><circle cx="12" cy="6" r="1"/><circle cx="17" cy="9" r="1"/><circle cx="8" cy="14" r="1"/><circle cx="14" cy="13" r="1"/><circle cx="18" cy="16" r="1"/><circle cx="11" cy="18" r="1"/>',
    "mesh": '<path d="m12 3 8 5v8l-8 5-8-5V8l8-5Z"/><path d="m4 8 8 5 8-5M12 13v8M8 5.5l8 12M16 5.5l-8 12"/>',
    "cad": '<path d="M4 17 17 4l3 3L7 20H4v-3Z"/><path d="m13 8 3 3M10 11l2 2M7 14l3 3"/>',
    "measure": '<path d="m3 16 13-13 5 5L8 21l-5-5Z"/><path d="m12 7 2 2M9 10l2 2M6 13l2 2"/>',
    "report": '<path d="M6 3h9l4 4v14H6V3Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
}


@lru_cache(maxsize=64)
def icon(name: str, color: str = "#A9BED2", size: int = 18) -> QIcon:
    paths = PATHS.get(name, PATHS["part"])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)
