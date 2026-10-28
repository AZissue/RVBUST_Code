"""Windows/OpenGL regression for reopened DB layers and native checkbox updates.

Run directly with the rvc Python environment. Uses synthetic DB data only.
Offscreen/minimal runs explicitly skip; a native pass requires OpenGL.
"""
import os
import time
from unittest.mock import patch
import numpy as np

if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
import test_postprocess as fixture
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from shiboken6 import isValid
from core.camera_manager import CameraManager
from ui_common.industrial_scene.gpu_canvas import GpuCloudCanvas
from ui_v2 import GLOBAL_QSS


def main():
    case = fixture.PostprocessTests('test_single_db_entry_in_each_mode_and_busy_gate')
    case.setUpClass()
    if case.app.platformName().lower() in ('offscreen', 'minimal'):
        print('[SKIPPED] Native OpenGL platform required', flush=True)
        return
    case.app.setStyleSheet(GLOBAL_QSS)

    def wait(predicate):
        deadline = time.monotonic() + 45
        while not predicate():
            case.app.processEvents()
            time.sleep(.01)
            assert time.monotonic() < deadline, 'native postprocess timeout'
        case.app.processEvents()

    def settle():
        wait(lambda: case.editor._worker is None and not case.editor.viewer.is_busy())
        case.editor.viewer.canvas.repaint()
        case.app.processEvents()

    with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK prohibited')):
        case.setUp()
        try:
            case.editor.close()
            case.app.processEvents()
            source = case.db.ingest(case.source())
            points = np.random.default_rng(86).normal(size=(1_400_000, 3))*[100, 60, 20]
            result = case.db.publish_result(fixture.cloud(points), [source])
            case.browser.set_component_checked(result, 'cloud')
            wait(lambda: bool(case.win.workspace_multi().viewer()._database_clouds))
            wait(lambda: not any(worker.isRunning() for worker in case.bridge._workers))
            for cycle in range(5):
                print(f'OPEN DB {cycle + 1}', flush=True)
                case.editor = case.bridge.open_postprocess()
                assert case.editor is not None
                settle()
                editor = case.editor
                canvas = editor.viewer.canvas
                assert isinstance(canvas, GpuCloudCanvas), 'Unexpected software fallback'
                assert canvas._ready, canvas._failure
                assert len(editor._clouds[result].points) == len(points)
                item = editor.source_browser._component_items[result, 'cloud']
                for visible in (False, True, False, True, False, True):
                    item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                    settle()
                    assert isValid(item) and editor.source_browser._component_items[result, 'cloud'] is item
                    assert bool(editor._display_ids) == visible
                # Exercise Qt's event-driven checkbox path as well as direct setData.
                editor.source_browser.tree.setFocus()
                for visible in (False, True):
                    QTest.keyClick(editor.source_browser.tree, Qt.Key_Space)
                    settle()
                    assert isValid(item) and editor.source_browser._component_items[result, 'cloud'] is item
                    assert bool(editor._display_ids) == visible
                w, h = canvas.width(), canvas.height()
                editor.stage_polygon([(w*.2, h*.2), (w*.8, h*.2), (w*.8, h*.8), (w*.2, h*.8)])
                settle()
                editor.segment_tools.buttons['inside' if cycle % 2 == 0 else 'outside'].click()
                assert editor.segment_tools.buttons['delete'].isEnabled()
                editor.segment_tools.buttons['delete'].click()
                settle()
                assert sum(case.db.records[uid].points for uid, _ in editor._undo[-1][0]) == len(points)
                editor.undo()
                settle()
                editor.downsample('random')
                settle()
                generated = editor._display_ids[0]
                assert generated in case.db.records
                editor.undo()
                settle()
                assert generated in case.db.removed
                editor.close()
                case.app.processEvents()
                print(f'CLOSE DB {cycle + 1}', flush=True)
            assert len(case.db.records) == 2, 'DB sources must not change'
        finally:
            case.tearDown()
            # processEvents alone does not flush deleteLater without app.exec().
            # Delete native widgets while Python/Qt callbacks are still alive.
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            case.app.processEvents()
            case.doCleanups()
    print('PASS: 5 DB reopens; 40 checkbox transitions; 1.4M points; native OpenGL; automatic DB split/downsample and undo; no SDK', flush=True)


if __name__ == '__main__':
    main()
