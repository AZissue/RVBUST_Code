"""Offscreen regression shots: selection banner layout and staged segment state."""
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
    segment = '--segment' in sys.argv
    positional = [arg for arg in sys.argv[1:] if not arg.startswith('--')]
    target = Path(positional[0]) if positional else Path(
        'tmp_proto_shot_segment.png' if segment else 'tmp_proto_shot_selection.png')
    app = QApplication(sys.argv[:1])
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    win = PostProcessWorkbench(load_demo=True)
    win.resize(1440, 900)
    win.show()

    def enter_selection():
        win._actions['select'].setChecked(True)
        assert win.overlay.active, 'selection overlay not active'
        width, height = win.canvas.width(), win.canvas.height()
        if segment:
            win.overlay._vertices = [(width * 0.30, height * 0.30), (width * 0.65, height * 0.28),
                                     (width * 0.60, height * 0.70), (width * 0.32, height * 0.72)]
            win.overlay._confirm()
            app.processEvents()
            assert win._segment is not None, 'polygon not staged'
            assert win.seg_in_button.isEnabled() and win.seg_out_button.isEnabled(), \
                'segment buttons not enabled after staging'
        else:
            win.overlay._vertices = [(width * 0.3, height * 0.35), (width * 0.6, height * 0.3)]
            win.overlay._cursor = None
            win.overlay.update()
        app.processEvents()
        ok = bool(win.grab().save(str(target)))
        win.shutdown()
        mode = 'staged segment' if segment else 'drawing selection'
        print((f'[OK] {mode} screenshot saved: ' if ok else '[FAIL] screenshot not saved: ') + str(target))
        app.exit(0 if ok else 1)

    QTimer.singleShot(800, enter_selection)
    QTimer.singleShot(30000, lambda: app.exit(1))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
