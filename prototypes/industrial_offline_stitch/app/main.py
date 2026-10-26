"""Run the standalone industrial offline-stitch prototype."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from ui_v2.theme import GLOBAL_QSS
from app.window import OfflineStitchWindow


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if os.environ.get('MCC_OFFSCREEN') else '')
    if not os.environ['QT_QPA_PLATFORM']:
        os.environ.pop('QT_QPA_PLATFORM')
    app = QApplication(sys.argv)
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet(GLOBAL_QSS)
    window = OfflineStitchWindow()
    window.show()
    if '--stool' in sys.argv:
        window.load_stool()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
