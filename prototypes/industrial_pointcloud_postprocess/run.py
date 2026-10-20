"""Run with an installed Python environment. Offline prototype, no camera hardware."""
from pathlib import Path
import argparse
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'src'))
sys.path.insert(0, str(HERE.parent))


def main():
    parser = argparse.ArgumentParser(description='MCC independent industrial point-cloud postprocess prototype')
    parser.add_argument('files', nargs='*', help='Point-cloud files to open directly (ply/pcd/xyz/pts, mm)')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--renderer', choices=['auto', 'gpu', 'software'], default='auto')
    parser.add_argument('--self-test-io', action='store_true', help='Validate bundled point-cloud I/O without Qt')
    args = parser.parse_args()
    if args.self_test_io:
        import tempfile
        import numpy as np
        from industrial_pointcloud_postprocess.core.session import CloudLayer, read_cloud, write_cloud
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'roundtrip.ply'
            points = np.array([[1., 2., 3.], [4., 5., 6.]])
            write_cloud(path, [CloudLayer('selftest', points)])
            np.testing.assert_allclose(read_cloud(path).points, points)
        print('[OK] self-test-io: PLY write/read roundtrip passed')
        return 0
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from industrial_pointcloud_postprocess.app.window import PostProcessWorkbench
    app = QApplication(sys.argv[:1])
    import os
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    win = PostProcessWorkbench(load_demo=not args.files, renderer=args.renderer)
    for file in args.files:
        try:
            from industrial_pointcloud_postprocess.core.session import read_cloud
            win.add_layer(read_cloud(file, 'mm'))
            win.log(f'打开 {file}（假定源单位 mm）。')
        except Exception as exc:
            win.log(f'打开失败 {file}：{exc}', 'error')
    win.show()
    if args.screenshot:
        state = {'stable': 0, 'done': False}

        def finish(ok):
            if state['done']:
                return
            state['done'] = True
            win.shutdown()
            app.exit(0 if ok else 1)

        def save():
            if state['done']:
                return
            if win._busy or win.canvas.is_busy or not win.session.layers:
                state['stable'] = 0
                QTimer.singleShot(100, save)
                return
            state['stable'] += 1
            if state['stable'] < 5:
                QTimer.singleShot(100, save)
                return
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            finish(bool(win.grab().save(str(args.screenshot))))

        QTimer.singleShot(600, save)
        QTimer.singleShot(30000, lambda: finish(False))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
