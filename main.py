import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.project.library import ProjectLibrary
from src.ui.start_window import StartWindow
from src.ui.style import configure_ui


def create_start_window(projects_directory: Path) -> StartWindow:
    return StartWindow(ProjectLibrary(projects_directory))


def main() -> int:
    app = QApplication(sys.argv)
    configure_ui(app)
    window = create_start_window(Path(__file__).resolve().parent / "projects")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
