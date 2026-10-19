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
    parser.add_argument('--mode', help='Registered function: multi_cam / mobile_chain / turntable')
    parser.add_argument('--camera-count', type=int, help='Number of offline 2D camera slots')
    parser.add_argument('--launcher-screenshot', type=Path, help='Render the function entrance without connecting hardware')
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
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QDialog
    from industrial_scan_ui.core.functions import default_registry
    from industrial_scan_ui.app.studio import FunctionLauncher, StudioWindow
    app = QApplication(sys.argv[:1])
    import os
    font = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    registry = default_registry()
    if args.launcher_screenshot:
        dialog = FunctionLauncher(registry)
        dialog.show()
        def save_launcher():
            args.launcher_screenshot.parent.mkdir(parents=True, exist_ok=True)
            app.exit(0 if dialog.grab().save(str(args.launcher_screenshot)) else 1)
        QTimer.singleShot(300, save_launcher)
        return app.exec()
    key, count = args.mode, args.camera_count
    if key is None and args.screenshot is None:
        dialog = FunctionLauncher(registry)
        if dialog.exec() != QDialog.Accepted:
            return 0
        key, count = dialog.selected_key, dialog.camera_count.value()
    try:
        win = StudioWindow(registry, key or 'mobile_chain', camera_count=count, renderer=args.renderer)
    except ValueError as exc:
        parser.error(str(exc))
    win.show()
    if args.screenshot:
        def save():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            if win.workspace.canvas.is_busy:
                QTimer.singleShot(50, save)
                return
            ok = win.grab().save(str(args.screenshot))
            win.workspace.shutdown()
            app.exit(0 if ok else 1)
        QTimer.singleShot(1200, save)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
