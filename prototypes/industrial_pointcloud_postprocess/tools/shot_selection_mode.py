"""Offscreen regression shot: selection mode banner must not overlap the canvas HUD."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from industrial_pointcloud_postprocess.app.window import PostProcessWorkbench
    app = QApplication(sys.argv[:1])
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    win = PostProcessWorkbench(load_demo=True)
    win.resize(1440, 900)
    win.show()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('tmp_proto_shot_selection.png')

    def enter_selection():
        win._actions['select'].setChecked(True)
        assert win.overlay.active, 'selection overlay not active'
        win.overlay._vertices = [(win.canvas.width() * 0.3, win.canvas.height() * 0.35),
                                 (win.canvas.width() * 0.6, win.canvas.height() * 0.3)]
        win.overlay._cursor = None
        win.overlay.update()
        app.processEvents()
        ok = bool(win.grab().save(str(target)))
        win.shutdown()
        print(('[OK] selection-mode screenshot saved: ' if ok else '[FAIL] screenshot not saved: ') + str(target))
        app.exit(0 if ok else 1)

    QTimer.singleShot(800, enter_selection)
    QTimer.singleShot(30000, lambda: app.exit(1))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
