"""Run with the rvc Python; --screenshot PATH also works with Qt offscreen."""
from pathlib import Path
import argparse
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))


def main():
    parser = argparse.ArgumentParser(description='MCC independent industrial scan UI prototype')
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from industrial_scan_ui.app.window import ScanWorkbench
    app = QApplication(sys.argv[:1])
    win = ScanWorkbench()
    win.show()
    if args.screenshot:
        def save():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            ok = win.grab().save(str(args.screenshot))
            app.exit(0 if ok else 1)
        QTimer.singleShot(300, save)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
