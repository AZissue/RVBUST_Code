"""Shared log lifecycle, honest frame metrics and non-destructive frame actions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import logging
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import numpy as np
HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE.parents[1]/'src'),str(HERE.parent)]
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from ui_common.activity_log import ActivityLogPanel
from ui_v2.widgets.floating_log_panel import FloatingLogPanel
from industrial_scan_ui.app.window import ScanWorkbench
from industrial_scan_ui.core.session import CloudLayer


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_filter_bounds_and_plain_text(self):
        panel=ActivityLogPanel(max_records=3)
        panel.append('discard')
        panel.append('<a>&识别', 'info', '01', '检测')
        panel.append('bad frame', 'error', '02', '拼接')
        panel.append('done', 'success', '03', '拼接')
        self.assertEqual(len(panel.records),3)
        panel.search.setText('[帧 02]');panel._render()
        self.assertEqual(len(panel.visible_records()),1)
        self.assertIn('bad frame',panel._text.toPlainText())
        panel.search.clear();panel.level_filter.setCurrentIndex(1);panel._render()
        self.assertIn('<a>&识别',panel._text.toPlainText())
        panel.deleteLater()

    def test_folding_shared_widget_and_thread_logger_no_duplicates(self):
        panel=FloatingLogPanel()
        self.assertIsInstance(panel,ActivityLogPanel)
        panel.show();self.app.processEvents()
        before=panel.height();panel._toggle_collapse();self.app.processEvents()
        self.assertLess(panel.height(),65)
        panel._toggle_collapse();self.assertEqual(panel.height(),before)
        logger=logging.Logger('offline-feedback')
        panel.attach_logger(logger);panel.attach_logger(logger)
        self.assertEqual(len(logger.handlers),1)
        worker=threading.Thread(target=lambda:logger.warning('worker result',extra={'frame_id':'4'}))
        worker.start();worker.join();self.app.processEvents()
        self.assertEqual(len(panel.records),1)
        self.assertEqual(panel.records[0][1:3],('warn','4'))
        logger.info('own',extra={'activity_owned':True});self.app.processEvents()
        self.assertEqual(len(panel.records),1)
        panel.detach_loggers();self.assertFalse(logger.handlers)
        panel.close();panel.deleteLater()

    def test_incremental_log_follows_latest_and_reopen_scrolls_to_bottom(self):
        panel=ActivityLogPanel(max_records=100)
        panel.show()
        for i in range(80):panel.append(str(i))
        panel._render()
        bar=panel._text.verticalScrollBar();bar.setValue(3)
        panel.append('tail');panel._render()
        self.assertGreater(bar.maximum(), 3)
        self.assertEqual(bar.value(),bar.maximum())
        self.assertEqual(len(panel._text.toPlainText().splitlines()),81)
        bar.setValue(0)
        panel.hide();panel.append('hidden tail');panel.show();self.app.processEvents()
        self.assertEqual(bar.value(),bar.maximum())
        self.assertTrue(panel._text.toPlainText().endswith('hidden tail'))
        bar.setValue(0)
        panel.hide();panel.show();self.app.processEvents()
        self.assertEqual(bar.value(),bar.maximum())
        panel.close();panel.deleteLater()

    def test_frame_selection_failure_undo_and_metadata_without_cloud_rebuild(self):
        win=ScanWorkbench(load_demo=False,renderer='software')
        try:
            win.session.layers=[CloudLayer('帧1',[[0,0,10]],source_points=5000000),CloudLayer('帧2',[[0,0,20]])]
            win._refresh(select=0)
            self.assertIn('未评估',win.quality_card.title.text())
            self.assertIn('内点率 —',win.quality_card.metrics.text())
            with patch.object(win.canvas,'set_layers',wraps=win.canvas.set_layers) as rebuild:
                win.set_frame_registration(is_reference=True)
                self.assertFalse(rebuild.called)
            win._refresh(select=1)
            win.set_frame_registration(reference_id=1,shared_markers=4,inlier_ratio=.5,rms_mm=1.2,accepted=False)
            self.assertIn('配准失败',win.quality_card.title.text())
            self.assertIn('50%',win.quality_card.metrics.text())
            self.assertIn('配准失败',win.tree.topLevelItem(0).child(1).text(0))
            win._refresh(select=0)
            self.assertIn('基准帧',win.quality_card.title.text())
            self.assertIn('5,000,001',win.status.text())
            win.undo_last_frame();self.assertEqual(len(win.session.layers),1)
            win.undo();self.assertEqual(len(win.session.layers),2)
            np.testing.assert_array_equal(win.session.layers[1].points,[[0,0,20]])
            with self.assertRaises(ValueError):win.set_frame_registration(inlier_ratio=1.5)
            with self.assertRaises(ValueError):win.set_frame_registration(rms_mm=float('nan'))
        finally:
            win._dirty=False;win.close();win.deleteLater();self.app.processEvents()

    def test_log_position_and_recapture_controller_contract(self):
        win=ScanWorkbench(renderer='software')
        try:
            win.resize(1000,660);win.show();self.app.processEvents()
            camera=(win.canvas.center.copy(),win.canvas.pan.copy(),win.canvas.rotation.matrix.copy(),win.canvas.zoom)
            win.log_toggle.setChecked(True);self.app.processEvents()
            self.assertTrue(win.logs.isVisible())
            panel=win.marker_inspector
            self.assertEqual(win.logs.parent(),win.content_splitter)
            self.assertEqual(win.logs.width(),win.content_splitter.width())
            self.assertGreaterEqual(win.logs.y(),win.content_splitter.widget(0).height())
            self.assertLessEqual(panel.geometry().bottom(),win.canvas.height())
            self.assertTrue(panel.details_button.isVisible())
            self.assertEqual(win.size().height(),660)
            win.content_splitter.setSizes([250,160]);self.app.processEvents()
            win._log_splitter_moved()
            saved=win._log_height
            self.assertFalse(win.recapture_button.isEnabled())
            calls=[];win.recapture_requested.connect(calls.append)
            win.set_recapture_available(True);win.recapture_button.click()
            self.assertEqual(calls,[0])
            win.logs._btn_collapse.click();self.assertFalse(win.log_toggle.isChecked())
            self.assertFalse(win.logs.isVisible())
            win.log_toggle.setChecked(True);self.app.processEvents()
            self.assertLessEqual(abs(win.logs.height()-saved),2)
            win.logs._btn_close.click();self.app.processEvents()
            self.assertFalse(win.log_toggle.isChecked())
            np.testing.assert_array_equal(win.canvas.center,camera[0])
            np.testing.assert_array_equal(win.canvas.pan,camera[1])
            np.testing.assert_array_equal(win.canvas.rotation.matrix,camera[2])
            self.assertEqual(win.canvas.zoom,camera[3])
            win.set_devices([object()]);self.assertIn('未连接相机',win.status.text())
            win.set_connection_status('相机 1/1 已连接');self.assertIn('1/1',win.status.text())
        finally:
            win._dirty=False;win.close();win.deleteLater();self.app.processEvents()

    def test_failed_result_removes_red_markers_and_file_task_progress(self):
        win=ScanWorkbench(load_demo=False,renderer='software')
        try:
            marker=dict(code=7,x_2d=10,y_2d=20,x_3d=1,y_3d=2,z_3d=30,world=[1,2,30])
            win.session.layers=[CloudLayer('one',[[1,2,30]]),CloudLayer('two',[[1,2,30]])]
            win._refresh(select=0)
            win.set_frame_observation(1,None,[marker],layer_index=0)
            win._refresh(select=1)
            win.set_frame_observation(2,None,[marker],reference_id=1,registration_accepted=True)
            self.assertEqual(win.marker_inspector.display.red_count,1)
            win.set_frame_registration(reference_id=1,accepted=False)
            self.assertEqual(win.marker_inspector.display.red_count,0)
            pending=[]
            win.set_background_runner(lambda work,callback:pending.append(callback))
            win._run(lambda:None,lambda result:None,task='导出点云')
            self.assertEqual((win.progress.minimum(),win.progress.maximum()),(0,0))
            self.assertIn('导出点云',win.status.text())
            pending[0](None,None)
            self.assertEqual(win.progress.maximum(),100)
        finally:
            win._dirty=False;win.close();win.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main(verbosity=2)
