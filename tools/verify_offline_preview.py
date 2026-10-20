"""Real bundled-data acceptance, optionally with native GPU screenshots.

Run --native for hardware-independent desktop OpenGL verification.
Camera SDK initialization, enumeration and capture are forbidden in this check.
"""
import argparse
import os
from pathlib import Path
import sys
import time
import tempfile
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--native', action='store_true')
parser.add_argument('--mode', choices=('multi_cam', 'mobile_chain', 'turntable'))
args = parser.parse_args()
if not args.native:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtWidgets import QApplication, QMessageBox, QDialogButtonBox
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from core.camera_manager import CameraManager
from core.marker_detector import MarkerDetector
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.composition import UiComposition

app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
UiComposition().configure(app)
report = ROOT.parent.parent / '.verify_reports'
report.mkdir(exist_ok=True)


def wait_for(condition, timeout=120):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError('Offline preview did not finish')
        time.sleep(.01)


with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK initialization forbidden')), \
     patch.object(CameraManager, 'find_devices', side_effect=AssertionError('device enumeration forbidden')), \
     patch.object(MarkerDetector, 'detect_3d', side_effect=AssertionError('fixture replay must not redetect')):
    win = MainWindowShell()
    db_temp = tempfile.TemporaryDirectory(prefix='mcc_db_verify_')
    for mode, database in win._frame_databases.items():
        database.directory = Path(db_temp.name) / mode
    bridge = BackendBridge(win)
    bridge.wire_all()
    win.set_backend_bridge(bridge)
    win.show()
    try:
        for mode in ((args.mode,) if args.mode else ('multi_cam', 'mobile_chain', 'turntable')):
            complete = []
            bridge.open_offline_preview(mode, lambda *result: complete.append(result))
            wait_for(lambda: bool(complete))
            assert complete[0][0], complete
            assert bridge.camera_manager.get_connected_ids() == []
            assert win.current_mode() == mode and win.current_presentation() == 'industrial'
            database = bridge.frame_db.databases[mode]
            browser = win._stack.currentWidget()._industrial.frame_browser
            assert len(database.records) == 2 and len(browser._items) == 2
            assert browser.tree.topLevelItemCount() == 1
            assert browser.tree.topLevelItem(0).childCount() == 2
            assert not hasattr(browser, 'image')
            if mode == 'multi_cam':
                assert len(bridge.fixed_workflow.frames_calib) == 2
                def cancel_unsaved():
                    dialog = QApplication.activeModalWidget()
                    assert [dialog.button(flag).text() for flag in (QMessageBox.Save, QMessageBox.Discard, QMessageBox.Cancel)] == ['保存', '放弃修改', '取消']
                    assert dialog.grab().save(str(report / 'session_unsaved_chinese.png'))
                    dialog.button(QMessageBox.Cancel).click()
                QTimer.singleShot(20, cancel_unsaved)
                bridge.projects.guard_switch(mode, lambda: (_ for _ in ()).throw(AssertionError('cancel must keep session')))
                presentation = win.workspace_multi()._industrial
                cameras = win.workspace_multi().camera_grid()
                for view in ('2d', '3d', 'joint'):
                    presentation.view_buttons[view].click()
                    wait_for(lambda: not win.workspace_multi().viewer()._viewer.canvas.is_busy)
                    for _ in range(10):
                        app.processEvents()
                        time.sleep(.02)
                    assert cameras.isHidden() == (view == '3d')
                    assert win.workspace_multi().viewer().isHidden() == (view == '2d')
                    assert win.grab().save(str(report / f'multi_cam_view_{view}.png'))
                QTest.mouseDClick(cameras.card('cam0')._thumb, Qt.LeftButton)
                app.processEvents()
                assert cameras._focused_id == 'cam0' and presentation._multi_view == '2d'
                assert win.grab().save(str(report / 'multi_cam_view_focus.png'))
                presentation.all_cameras_button.click()
                app.processEvents()
                assert presentation._multi_view == 'joint'
                assert presentation.sidebar.isHidden()
                presentation.legacy_toggle.click()
                app.processEvents()
                assert presentation.sidebar.isVisible()
                presentation.legacy_toggle.click()
                # Follow the production reference-switch path using real source RGB.
                import numpy as np
                for reference in ('cam1', 'cam0'):
                    bridge._on_multi_reference_changed(reference)
                    wait_for(lambda: not win.workspace_multi().viewer()._viewer.canvas.is_busy)
                    renderer = win.workspace_multi().viewer()._viewer
                    for layer in renderer._layers:
                        source = bridge._offline_clouds[layer.name]
                        np.testing.assert_array_equal(layer.colors, np.asarray(source.colors))
                for _ in range(10):
                    app.processEvents()
                    time.sleep(.02)
                assert win.grab().save(str(report / 'multi_cam_reference_rgb.png'))
                bridge._on_multi_calibrate()
                wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
                app.processEvents()
                assert win.workspace_multi().current_state() == 'locked'
                assert len(bridge.fixed_workflow.frames_scan) == 2
            elif mode == 'mobile_chain':
                assert len(bridge.mobile_workflow.get_station_evaluations()) == 2
                assert len(win.workspace_mobile().viewer()._merged.points) > 1000000
                mobile = win.workspace_mobile()
                assert mobile._industrial.sidebar.isHidden()
                assert not mobile._eval_card.isVisible() and not mobile._stats_label.isVisible()
                assert win._st_quality.isVisible() and '已接 2 机位' in win._st_quality.full_text
                wait_for(lambda: not mobile.viewer()._viewer.canvas.is_busy and
                         mobile.viewer()._viewer.canvas.displayed_points > 0)
                for _ in range(10):
                    app.processEvents()
                    time.sleep(.02)
                assert win.grab().save(str(report / 'mobile_chain_footer.png'))
                source = ROOT / 'offline_test_data' / 'stool' / 'frame_2.zip'
                bridge._on_mobile_station_selected(1)
                bridge._on_mobile_undo()
                wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
                app.processEvents()
                assert len(bridge.mobile_workflow.get_station_evaluations()) == 1
                assert len(database.records) == 2
                assert any('退出拼接' in row.status for row in database.records.values())
                assert source.exists()
                assert (ROOT / 'offline_test_data' / 'stool' / '.cache' / '2.ply').exists()
            else:
                assert win.workspace_turntable()._industrial.sidebar.isHidden()
                assert win.workspace_turntable().session.frame0 is not None
                assert win.workspace_turntable().session.frame1 is not None
                assert not win.workspace_turntable().btn_capture_frame1.isEnabled()
            viewer = (win.workspace_multi().viewer() if mode == 'multi_cam' else
                      win.workspace_mobile().viewer() if mode == 'mobile_chain' else win.workspace_turntable().viewer)
            canvas = viewer._viewer.canvas
            wait_for(lambda: not canvas.is_busy)
            wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
            uid = next(iter(database.records))
            browser.tree.setCurrentItem(browser._items[uid])
            wait_for(lambda: viewer._database_cloud is not None)
            wait_for(lambda: not viewer._viewer.canvas.is_busy)
            scene = getattr(viewer._viewer.canvas, 'scene', None)
            if scene is not None:
                import numpy as np
                assert scene.bounds is not None and np.isfinite(scene.bounds).all()
                assert scene.stored_points > 1000000
            assert len(viewer._database_cloud.points) == database.records[uid].points
            presentation = win._stack.currentWidget()._industrial
            if mode == 'multi_cam':
                card = win.workspace_multi().camera_grid()._database_card
                assert card.isVisible() and card.current_frame().image_np is not None
                assert presentation.inspector is None
            else:
                inspector = presentation.inspector
                assert not inspector.image_view.image.isNull() and inspector.isVisible()
            assert len(database.records) == 2
            for _ in range(10):
                app.processEvents()
                time.sleep(.02)
            assert win.grab().save(str(report / f'db_{mode}.png'))
            browser.restore_button.click()
            wait_for(lambda: not viewer._viewer.canvas.is_busy)
            assert viewer._database_cloud is None
            with patch('ui_v2.frame_database.QMessageBox.question', return_value=QMessageBox.Yes):
                bridge.frame_db.remove(mode, [uid])
                wait_for(lambda: uid not in browser._items and '已删除' in win._st_hint.text())
                wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
            assert len(database.records) == 1 and uid not in browser._items, (mode, len(database.records), win._st_hint.text())
            bridge.frame_db.archive_context()
            assert len(database.records) == 1
            bridge.frame_db.recover(mode)
            wait_for(lambda: uid in browser._items and '已恢复' in win._st_hint.text())
            wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
            assert len(database.records) == 2 and uid in browser._items
            for _ in range(20):
                app.processEvents()
                time.sleep(.02)
            ribbon = win._industrial_ribbon
            assert not ribbon.isHidden() and win._toolbar.isHidden()
            shot = report / f'offline_{mode}_viewport.png'
            with patch('ui_v2.industrial_ribbon.QFileDialog.getSaveFileName', return_value=(str(shot), '')):
                ribbon.commands[(mode, 'screenshot')].click()
            assert shot.exists() and shot.stat().st_size > 100
            assert win.grab().save(str(report / f'offline_{mode}.png'))
            # Explicit save/new/reopen is isolated in a temporary save root.
            project = bridge.projects.projects[mode]
            project.save_root = Path(db_temp.name) / 'sessions'
            def accept_save_options():
                dialog = QApplication.activeModalWidget()
                buttons = dialog.findChild(QDialogButtonBox)
                assert buttons.button(QDialogButtonBox.Save).text() == '保存'
                assert buttons.button(QDialogButtonBox.Cancel).text() == '取消'
                assert dialog.grab().save(str(report / 'session_save_options_chinese.png'))
                dialog.accept()
            QTimer.singleShot(20, accept_save_options)
            ribbon.commands[(mode, 'save')].click()
            wait_for(lambda: project.saved_path is not None and not project.dirty)
            wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
            path = project.saved_path
            import json
            manifest = json.loads((path / 'session.json').read_text(encoding='utf-8'))
            if mode == 'multi_cam':
                assert not manifest['include_raw'] and not (path / 'data').exists()
            bridge.projects.new(mode, '新项目验证')
            assert browser.tree.topLevelItem(0).childCount() == 0
            bridge.projects.open(path, mode)
            wait_for(lambda: bridge.projects.projects[mode].saved_path == path)
            wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
            assert not bridge.projects.projects[mode].dirty
            if mode == 'mobile_chain':
                assert len(bridge.mobile_workflow.get_station_evaluations()) == 1
                bridge._on_mobile_delete_station(1)
                wait_for(lambda: viewer._merged is None)
                wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
                assert viewer._clouds == {} and viewer._viewer.canvas.total_points == 0
                wait_for(lambda: not viewer._viewer.canvas.is_busy)
                assert viewer._viewer.canvas.displayed_points == 0
                assert len(win.workspace_mobile()._timeline._nodes) == 0
            elif mode == 'multi_cam':
                assert bridge.calibration_engine.pair_results
            else:
                assert win.workspace_turntable().current_frame0 is not None
                assert win.workspace_turntable().current_frame1 is not None
            assert win.grab().save(str(report / f'session_{mode}.png'))
            print('PASS', mode, complete[0][1], flush=True)
    finally:
        # Wait CPU preparation before destroying Qt/OpenGL owners.
        wait_for(lambda: not any(w.isRunning() for w in bridge._workers))
        bridge.cleanup()
        win._dirty = False
        win.close()
        app.processEvents()
        db_temp.cleanup()
