from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from ui.theme import stylesheet


def create_application(argv: list[str] | None = None) -> QApplication:
    surface = QSurfaceFormat()
    surface.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surface.setVersion(3, 2)
    surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface.setSamples(4)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Metrology Studio")
    app.setOrganizationName("MetrologyStudio")
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())
    return app


def run(argv: list[str] | None = None, screenshot: str = "", quit_after: int = 0) -> int:
    app = create_application(argv)
    window = MainWindow()
    window.show()
    if screenshot:
        target = Path(screenshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        def capture() -> None:
            window.screen().grabWindow(int(window.winId())).save(str(target))
            app.quit()
        QTimer.singleShot(1800, capture)
    elif quit_after > 0:
        QTimer.singleShot(quit_after, app.quit)
    return app.exec()
