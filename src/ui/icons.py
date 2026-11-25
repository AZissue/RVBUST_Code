from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton


PATHS = {
    "metrix": "M12 2.5 21 7.5v9l-9 5-9-5v-9z M7 16V9l5 4 5-4v7",
    "files": "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9H3z M7 11h10 M7 14h7",
    "settings": "M4 6h5m4 0h7 M4 12h10m4 0h2 M4 18h2m4 0h10 "
                "M9 4v4h4V4z M14 10v4h4v-4z M6 16v4h4v-4z",
    "new-file": "M7 3h7l4 4v5 M14 3v5h4 M11 21H6V3h1 M17 13v8m-4-4h8",
    "open-file": "M3 17V6h6l2 2h8v3 M3 19l3-8h16l-3 8z",
    "search": "M15.5 15.5 20 20 M17 11a6 6 0 1 1-12 0 6 6 0 0 1 12 0z",
    "clear": "M7 7l10 10 M17 7 7 17",
    "enter": "M20 5v8H4 M9 8l-5 5 5 5",
    "folder-location": "M3 19V6h6l2 2h9v11z M11 15l6-4m-4 0h4v4",
    "back": "M20 12H4 M10 6l-6 6 6 6",
    "next": "M4 12h16 M14 6l6 6-6 6",
    "prepare": "M9 5H5v16h14V5h-4 M9 8V3h6v5z M8 12h8m-8 4h6",
    "scan": "M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5 M4 12h16",
    "inspect": "M12 3v4m0 10v4 M3 12h4m10 0h4 M18 12a6 6 0 1 1-12 0 6 6 0 0 1 12 0z",
    "report": "M6 3h8l4 4v14H6z M14 3v5h4 M9 17v-2m3 2v-5m3 5v-3",
    "model": "M12 3 20 7.5v9L12 21l-8-4.5v-9z M4 7.5l8 4.5 8-4.5 M12 12v9",
    "reset": "M4 10a8 8 0 1 1 1.7 7 M4 5v5h5",
    "expand": "M5 9l7 7 7-7",
    "collapse": "M9 5l7 7-7 7",
    "check": "M5 12l4 4L19 6",
    "empty": "M8 12h8",
}


@lru_cache(maxsize=None)
def icon(name: str, size: int = 16) -> QIcon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="none" stroke="#e4eaf3" stroke-width="1.65" '
        f'stroke-linecap="round" stroke-linejoin="round" d="{PATHS[name]}"/>'
        '</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for scale in (1, 1.5, 2, 3):
        pixels = round(size * scale)
        image = QPixmap(pixels, pixels)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        with QPainter(image) as painter:
            renderer.render(painter)
        result.addPixmap(image)
    return result


def set_button_icon(button: QAbstractButton, name: str, size: int = 16) -> None:
    button.setIcon(icon(name, size))
    button.setIconSize(QSize(size, size))
