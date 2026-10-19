"""Run with an installed Python environment or the packaged executable."""
from pathlib import Path
import argparse
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))


def main():
    parser = argparse.ArgumentParser(description='MCC independent industrial scan UI prototype')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--renderer', choices=['auto', 'gpu', 'software'], default='auto')
    parser.add_argument('--self-test-io', action='store_true', help='Validate bundled point-cloud I/O without hardware')
    args = parser.parse_args()
    if args.self_test_io:
        import tempfile
        import numpy as np
        from industrial_scan_ui.core.session import CloudLayer, read_cloud, write_cloud
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'roundtrip.ply'
            points = np.array([[1., 2., 3.], [4., 5., 6.]])
            write_cloud(path, [CloudLayer('selftest', points)])
            np.testing.assert_allclose(read_cloud(path).points, points)
        return 0
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from industrial_scan_ui.app.window import ScanWorkbench
    app = QApplication(sys.argv[:1])
    win = ScanWorkbench(renderer=args.renderer)
    win.show()
    if args.screenshot:
        def save():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            ok = win.grab().save(str(args.screenshot))
            app.exit(0 if ok else 1)
        QTimer.singleShot(1200, save)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
