"""Adaptive 2D layouts retain frame objects/action ports; dialogs use Chinese."""
import os
import sys
from pathlib import Path
import unittest
import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from ui_v2 import MainWindowShell
from ui_v2.widgets.device_table import DeviceInfo
from ui_v2.dialogs import ChineseMessageBox, localize_buttons
from core.frame_data import FrameData


class MulticamViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindowShell()
        self.win.resize(1600, 950)
        self.win.set_mode('multi_cam', [DeviceInfo(serial=str(i), backend_ref=i) for i in range(2)])
        self.win.set_presentation('industrial')
        self.ws = self.win.workspace_multi()
        self.presentation = self.ws._industrial
        self.grid = self.ws.camera_grid()
        self.win.show()
        self.flush()
        for cid in self.grid.camera_ids():
            self.grid.set_frame(cid, FrameData(1, cid, image_np=np.zeros((204, 244, 3), np.uint8)))
        self.flush()

    def flush(self):
        for _ in range(5):
            self.app.processEvents()

    def tearDown(self):
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def test_joint_overlay_collapses_up_without_resizing_3d_or_stopping_previews(self):
        self.assertEqual(self.presentation._multi_view, 'joint')
        self.assertEqual(self.grid._last_cols, 1)
        cards = list(self.grid._cards.values())
        self.assertGreater(self.ws.viewer().width(), self.grid.width())
        self.presentation.preview_all.click()
        viewport_size = self.presentation.viewport.size()
        viewer_size = self.ws.viewer().size()
        self.assertTrue(all(c._btn_preview.isChecked() for c in cards))
        self.presentation.preview_toggle.click()
        self.flush()
        self.assertTrue(self.grid.isHidden() or self.presentation.preview_images.isHidden())
        self.assertTrue(all(c._btn_preview.isChecked() for c in cards))
        self.assertLessEqual(self.presentation.preview_panel.height(), 55)
        self.assertEqual(self.presentation.viewport.size(), viewport_size)
        self.assertEqual(self.ws.viewer().size(), viewer_size)
        self.presentation.preview_toggle.click()
        self.presentation.preview_stop.click()
        self.assertTrue(all(not c._btn_preview.isChecked() for c in cards))
        self.flush()
        for card in cards:
            self.assertFalse(card._thumb._fill)
            self.assertLess(card._marker_badge.y(), card._btn_capture.y())
            for button in (card._btn_preview, card._btn_capture, card._btn_detect):
                self.assertGreaterEqual(button.width(), 48)

    def test_overlay_tracks_canvas_top_after_resize_and_full_2d_collapse(self):
        from PySide6.QtCore import QPoint
        p = self.presentation
        for width, height in ((1450, 900), (1600, 1000)):
            self.win.resize(width, height)
            self.flush()
            canvas = self.ws.viewer().viewer().canvas
            expected_top = canvas.mapTo(p.viewport, QPoint(0, 0)).y() + 12
            self.assertEqual(p.preview_panel.y(), expected_top)
            self.assertEqual(p.preview_panel.x()+p.preview_panel.width(), p.viewport.width()-12)
        p.set_multi_view('2d')
        self.flush()
        p.preview_toggle.click()
        self.flush()
        self.assertEqual(p._multi_view, 'joint')
        self.assertFalse(self.ws.viewer().isHidden())
        self.assertIs(p.preview_panel.parentWidget(), p.viewport)
        self.assertLessEqual(p.preview_panel.height(), 55)

    def test_calibration_panel_and_log_can_expand(self):
        ws = self.ws
        ws.on_calibrate_done([dict(pair='cam1→cam0', rms_mm=.2, inlier_ratio=.9,
                                  level='ok', T=np.eye(4))], 90, True)
        ws.set_state('calibrated')
        self.flush()
        self.assertTrue(ws._result_card.isVisible())
        self.assertTrue(ws._gate_card.isVisible())
        self.assertTrue(ws._matrix_values.isHidden())
        self.assertEqual(ws._result_table.item(0, 0).text(), 'cam1→cam0')
        from PySide6.QtWidgets import QGroupBox
        self.assertFalse(any(group.title() == '标定参数'
                             for group in self.presentation.calibration_panel.findChildren(QGroupBox)))
        self.assertTrue(ws._btn_scan_capture.isEnabled())
        ws.on_calibrate_done([], 0, False)
        ws.set_state('calibrated')
        self.assertFalse(ws._btn_scan_capture.isEnabled())
        self.win._btn_log.setChecked(True)
        self.flush()
        before = self.win._log_panel.height()
        split = self.win._content_split
        split.moveSplitter(250, 1)
        self.flush()
        self.assertGreater(self.win._log_panel.height(), before)
        self.assertGreaterEqual(self.win._log_panel._text.height(), 30)
        self.assertLessEqual(self.win._log_panel.body.geometry().bottom(), self.win._log_panel.height())

    def test_sidebar_scrolls_without_db_footer_or_gate_overlap_when_logs_expand(self):
        from PySide6.QtWidgets import QTreeWidgetItem
        from PySide6.QtCore import QPoint
        p = self.presentation
        browser = p.frame_browser
        for index in range(20):
            QTreeWidgetItem(browser.tree, [f'帧 {index:03d} · cam0', '5,013,504'])
        browser.details.setText('cam0 · 已入库\n原始PLY + 2D PNG · 联动查看')
        self.ws.on_calibrate_done([dict(pair='cam1→cam0', rms_mm=.61,
                                       inlier_ratio=.74, level='warn')], 73, True)
        self.win._btn_log.setChecked(True)
        for sizes in ([380, 380], [210, 600]):
            self.win._content_split.setSizes(sizes)
            self.flush()
            self.assertLess(browser.tree.geometry().bottom(), browser.footer.y())
            self.assertLess(browser.details.geometry().bottom(), browser.open_button.y())
            self.assertLess(browser.open_button.geometry().bottom(), browser.manage_button.y())
            self.assertLess(browser.geometry().bottom(), p.calibration_panel.y())
            self.assertGreater(p.side_scroll.verticalScrollBar().maximum(), 0)
            p.side_scroll.verticalScrollBar().setValue(p.side_scroll.verticalScrollBar().maximum())
            self.flush()
            gate_position = p.calibration_panel.mapTo(p.side_scroll.viewport(), QPoint(0, 0))
            self.assertLess(gate_position.y(), p.side_scroll.viewport().height())
            self.assertGreater(gate_position.y()+p.calibration_panel.height(), 0)
        p.maximize(True)
        self.assertTrue(p.side_scroll.isHidden())
        p.maximize(False)
        self.assertFalse(p.side_scroll.isHidden())

    def test_database_calibration_node_opens_new_panel_and_clear_removes_matrix(self):
        browser = self.presentation.frame_browser
        browser.database.project_title = '测试项目'
        browser.database.has_calibration = True
        browser.refresh()
        root = browser.tree.topLevelItem(0)
        parameters = root.child(0).child(0)
        self.assertEqual(parameters.text(0), '标定参数')
        self.presentation.calibration_panel.hide()
        browser.tree.setCurrentItem(parameters)
        self.flush()
        self.assertTrue(self.presentation.calibration_panel.isVisible())
        self.ws.on_calibrate_done([dict(pair='cam1→cam0', rms_mm=.2, inlier_ratio=.9,
                                       T=np.eye(4))], 95, True)
        self.ws.clear_calibration_results()
        self.assertEqual(self.ws._matrix_values.toPlainText(), '')

    def test_fill_switch_and_quality_levels_use_business_limits(self):
        from types import SimpleNamespace
        from ui_v2.backend_bridge import _pairs_from_engine
        for rms, ratio, expected in ((1.8, .9, 'warn'), (2.01, .9, 'fail'), (.2, .49, 'fail')):
            pairs = _pairs_from_engine(SimpleNamespace(pair_results={('cam0', 'cam1'):
                dict(success=True, rms_mm=rms, inlier_ratio=ratio, T=np.eye(4))}))
            self.assertEqual(pairs[0]['level'], expected)
            np.testing.assert_array_equal(pairs[0]['T'], np.eye(4))
        self.presentation.fill_button.click()
        self.assertTrue(all(c._thumb._fill for c in self.grid._cards.values()))

    def test_db_tree_is_first_panel_and_preview_buttons_follow_backend_gates(self):
        self.assertIs(self.presentation.side_column.widget(0), self.presentation.frame_browser)
        self.assertFalse(hasattr(self.presentation, 'device_overview'))
        card = self.grid.card('cam0')
        spy = QSignalSpy(self.ws.card_preview_toggled)
        card._btn_preview.click()
        self.assertTrue(card._btn_preview.isChecked())
        self.assertEqual(spy.count(), 1)
        card.set_controls_enabled(False)
        self.presentation.camera_status.refresh()
        self.assertFalse(card._btn_preview.isEnabled())
        self.assertFalse(card._btn_preview.isChecked())
        self.assertIn('2/2', self.win._industrial_ribbon.camera_status.text())

    def test_layout_presets_show_all_cameras_and_overlay_keeps_full_3d_viewport(self):
        for count in (1, 2, 3, 4, 6):
            self.grid.set_cameras([f'cam{i}' for i in range(count)])
            self.presentation.set_multi_view('joint')
            self.flush()
            self.assertEqual(self.grid._last_cols, 1)
            self.assertIs(self.presentation.preview_panel.parentWidget(), self.presentation.viewport)
            self.assertLessEqual(abs(self.presentation.viewport.width()-self.presentation.grid.width()), 2)
            for columns in range(1, 5):
                self.presentation.set_multi_view('2d')
                self.presentation.layout_choice.setCurrentIndex(columns)
                self.presentation._change_camera_layout()
                self.flush()
                self.assertEqual(self.presentation._multi_view, '2d')
                self.assertEqual(self.grid._last_cols, min(columns, count))
                self.assertEqual(sum(not c.isHidden() for c in self.grid._cards.values()), count)
            self.presentation.layout_choice.setCurrentIndex(0)

    def test_freeze_preserves_display_but_keeps_latest_frame_for_unlock(self):
        card = self.grid.card('cam0')
        old = card._thumb._pixmap.toImage()
        card._freeze.setChecked(True)
        latest = FrameData(8, 'cam0', image_np=np.full((204, 244, 3), 200, np.uint8))
        self.grid.set_frame('cam0', latest)
        self.assertIs(card.current_frame(), latest)
        self.assertEqual(card._thumb._pixmap.toImage(), old)
        card._freeze.setChecked(False)
        self.assertEqual(card._thumb._pixmap.toImage().pixelColor(20, 20).red(), 200)
        card._freeze.setChecked(True)
        self.grid.set_frame('cam0', None)
        self.assertFalse(card._freeze.isChecked())
        self.assertIsNone(card._thumb._pixmap)

    def test_image_export_and_header_task_feedback(self):
        import tempfile
        from unittest.mock import patch
        from PySide6.QtGui import QImage
        card = self.grid.card('cam0')
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'preview.png')
            with patch('ui_v2.widgets.camera_grid.QFileDialog.getSaveFileName', return_value=(path, 'PNG')):
                card._save_button.click()
            self.assertFalse(QImage(path).isNull())
        self.assertLessEqual(self.win._industrial_ribbon.workflow_status.geometry().right(),
                             self.win._industrial_ribbon.log_button.x())
        self.win.show_loading('正在计算外参')
        self.assertFalse(self.win._task_progress.isHidden())
        self.win.hide_loading()
        self.assertTrue(self.win._task_progress.isHidden())

    def test_floating_history_preview_and_neutral_calibration_chrome(self):
        p = self.presentation
        p.show_database_image(FrameData(99, 'cam1', image_np=np.ones((204, 244, 3), np.uint8)))
        self.flush()
        self.assertLessEqual(p.preview_panel.width(), 380)
        self.assertEqual(p.preview_panel.parentWidget(), p.viewport)
        self.assertLessEqual(abs(p.viewport.width()-p.grid.width()), 2)
        self.assertFalse(self.grid._database_card._thumb._fill)
        self.assertEqual(self.grid._database_card._kind.text(), '只读')
        self.assertEqual(self.presentation.preview_all.parentWidget(), p.preview_panel)
        self.assertIn('background:#292929', self.ws._gate_card.styleSheet())
        self.assertTrue(self.ws._matrix_values.isHidden())
        preview = self.grid._database_card
        QTest.mouseDClick(preview._thumb, Qt.LeftButton)
        self.flush()
        self.assertEqual(p._multi_view, '2d')
        self.assertIs(self.grid._database_card, preview)
        QTest.mouseDClick(preview._thumb, Qt.LeftButton)
        self.flush()
        self.assertEqual(p._multi_view, 'joint')
        self.assertLessEqual(p.preview_panel.width(), 380)
        self.win.set_presentation('classic')
        self.flush()
        self.assertNotIn('QFrame#multiGateCard', self.ws._gate_card.styleSheet())

    def test_view_modes_and_double_click_focus_keep_exact_frames_and_actions(self):
        original = {cid: card.current_frame() for cid, card in self.grid._cards.items()}
        capture = QSignalSpy(self.ws.card_capture_requested)
        # The production grid cards continue using their existing signal ports.
        for _ in range(2):
            self.presentation.view_buttons['2d'].click()
            self.flush()
            self.assertTrue(self.ws.viewer().isHidden())
            self.assertGreaterEqual(self.grid._last_cols, 2)
            self.presentation.view_buttons['3d'].click()
            self.assertTrue(self.grid.isHidden())
            self.assertFalse(self.ws.viewer().isHidden())
            self.presentation.view_buttons['joint'].click()
            self.flush()
        card = self.grid.card('cam0')
        spy = QSignalSpy(card.capture_requested)
        QTest.mouseDClick(card._thumb, Qt.LeftButton)
        self.flush()
        self.assertEqual(self.grid._focused_id, 'cam0')
        self.assertEqual(self.presentation._multi_view, '2d')
        self.assertTrue(self.grid.card('cam1').isHidden())
        self.presentation.all_cameras_button.click()
        self.flush()
        self.assertEqual(self.presentation._multi_view, 'joint')
        self.assertFalse(self.grid.card('cam1').isHidden())
        card.set_controls_enabled(True)
        card._btn_capture.click()
        self.assertEqual(spy.count(), 1)
        self.assertEqual(capture.count(), 1)
        for cid, frame in original.items():
            self.assertIs(self.grid.card(cid).current_frame(), frame)

    def test_many_cameras_scroll_and_classic_restore_without_stale_cards(self):
        self.grid.set_cameras([f'cam{i}' for i in range(6)])
        self.presentation.view_buttons['2d'].click()
        self.flush()
        self.assertEqual(len(self.grid._cards), 6)
        self.assertGreaterEqual(self.grid._last_cols, 2)
        for card in self.grid._cards.values():
            self.assertFalse(card.isHidden())
            self.assertGreaterEqual(card.height(), 210)
        self.presentation.set_multi_view('2d')
        self.win.set_presentation('classic')
        self.flush()
        for card in self.grid._cards.values():
            self.assertFalse(hasattr(card, '_overview_original'))
            self.assertEqual(card.minimumWidth(), 300)
        self.win.set_presentation('industrial')
        self.flush()
        self.assertEqual(self.presentation._multi_view, '2d')
        self.presentation.maximize(True)
        self.assertFalse(self.ws.viewer().isHidden())
        self.presentation.maximize(False)
        self.assertTrue(self.ws.viewer().isHidden())

    def test_database_preview_uses_2d_area_without_mutating_live_frames(self):
        original = {cid: card.current_frame() for cid, card in self.grid._cards.items()}
        archived = FrameData(99, 'disconnected_camera', image_np=np.ones((120, 160, 3), np.uint8))
        self.presentation.set_multi_view('3d')
        self.presentation.show_database_image(archived)
        self.flush()
        self.assertEqual(self.presentation._multi_view, 'joint')
        preview = self.grid._database_card
        self.assertIs(preview.current_frame(), archived)
        self.assertTrue(preview.isVisible())
        self.assertTrue(preview._btn_capture.isHidden())
        self.assertIsNone(self.presentation.inspector)
        for cid, frame in original.items():
            self.assertIs(self.grid.card(cid).current_frame(), frame)
            self.assertTrue(self.grid.card(cid).isHidden())
        updated = FrameData(2, 'cam0', image_np=np.zeros((120, 160, 3), np.uint8))
        self.grid.set_frame('cam0', updated)
        self.assertIs(preview.current_frame(), archived)
        self.presentation.show_database_image(archived)
        self.presentation.restore_business_image()
        self.flush()
        self.assertIsNone(self.grid._database_card)
        self.assertIs(self.grid.card('cam0').current_frame(), updated)
        self.assertTrue(all(card.isVisible() for card in self.grid._cards.values()))

    def test_legacy_controls_collapse_restore_and_keep_reference_colors(self):
        import open3d as o3d
        p = self.presentation
        self.assertTrue(p.sidebar.isHidden())
        self.assertFalse(p.frame_browser.isHidden())
        p.legacy_toggle.click()
        self.flush()
        self.assertFalse(p.sidebar.isHidden())
        p.legacy_toggle.click()
        p.maximize(True)
        p.maximize(False)
        self.assertTrue(p.sidebar.isHidden())
        self.win.set_presentation('classic')
        self.assertFalse(self.ws._left_widget.isHidden())
        self.win.set_presentation('industrial')
        self.assertTrue(p.sidebar.isHidden())
        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector([[1., 2., 3.], [4., 5., 6.]])
        colors = np.array([[.8, .1, .2], [.2, .3, .4]])
        cloud.colors = o3d.utility.Vector3dVector(colors)
        viewer = self.ws.viewer()
        viewer.set_pointcloud('cam0', cloud)
        viewer.set_pointcloud('cam1', cloud)
        for ref in ('cam1', 'cam0', None):
            viewer.set_reference(ref)
            for layer in viewer.viewer()._layers:
                np.testing.assert_array_equal(layer.colors, colors)
        np.testing.assert_array_equal(np.asarray(cloud.colors), colors)

    def test_save_dialog_labels_and_standard_result_flags_are_chinese(self):
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        localize_buttons(box)
        self.assertEqual(box.button(QDialogButtonBox.Save).text(), '保存')
        self.assertEqual(box.button(QDialogButtonBox.Cancel).text(), '取消')
        observed = []
        def cancel():
            dialog = self.app.activeModalWidget()
            observed.append([dialog.button(flag).text() for flag in (QMessageBox.Save, QMessageBox.Discard, QMessageBox.Cancel)])
            dialog.button(QMessageBox.Cancel).click()
        QTimer.singleShot(0, cancel)
        result = ChineseMessageBox.warning(self.win, '会话未保存', '保存或放弃修改？',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        self.assertEqual(result, QMessageBox.Cancel)
        self.assertEqual(observed, [['保存', '放弃修改', '取消']])


if __name__ == '__main__':
    unittest.main()
