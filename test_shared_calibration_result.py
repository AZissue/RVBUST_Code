"""Portable calibration window: missing-data truth, immutable display and selection."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ui_common.calibration_result import CalibrationResultDialog, residual_rows


def result():
    transform = np.eye(4)
    transform[:3, 3] = [10, 20, 30]
    return dict(success=True, T=transform, rms_mm=.2, inlier_ratio=.75,
                details=[dict(code=7, pt_ref=[1, 2, 3], pt_cam_transformed=[1.2, 2, 3], is_inlier=True),
                         dict(code=9, pt_ref=[4, 5, 6], pt_cam_transformed=[4, 5, 8], is_inlier=False)])


class SharedCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, data=None, **kwargs):
        dialog = CalibrationResultDialog({('参考帧', '待对齐帧'): data if data is not None else result()}, **kwargs)
        self.addCleanup(dialog.reject)
        return dialog

    def test_snapshot_cloud_ownership_and_transform_applied_once(self):
        source = result()
        dialog = self.dialog(source)
        source['T'][0, 3] = 999
        source['details'][0]['pt_cam_transformed'][0] = 999
        # Saved correspondence points are already transformed.
        np.testing.assert_allclose(np.asarray(dialog.viewer._pcds['待对齐帧'].points)[-1], [1.2, 2, 3])
        cloud = np.array([[1., 2., 3.], [4., 5., 6.]])
        dialog.set_clouds({'待对齐帧': cloud, '参考帧': cloud})
        cloud[:] = 999
        dialog.view_choice.setCurrentIndex(0)
        np.testing.assert_allclose(np.asarray(dialog.viewer._pcds['待对齐帧'].points), [[11, 22, 33], [14, 25, 36]])
        self.assertEqual(dialog.matrix.item(0, 3).text(), '10')

    def test_chart_table_and_3d_selection_are_linked_and_filter_clears_selection(self):
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.table.item(0, 0).text(), '9')
        dialog.table.selectRow(0)
        self.assertEqual(dialog.chart.selected_index, 0)
        self.assertTrue(dialog.viewer.canvas.marker_centers)
        markers = dialog.viewer.canvas._cloud_markers
        np.testing.assert_allclose(markers[0][1][0], [4, 5, 6])
        np.testing.assert_allclose(markers[1][1][0], [4, 5, 8])
        width = (dialog.chart.width() - 24) / 2
        QTest.mouseClick(dialog.chart, Qt.LeftButton, pos=QPoint(int(12 + 1.5 * width), 60))
        self.assertEqual(dialog.table.currentRow(), 1)
        self.assertEqual(dialog.chart.selected_index, 1)
        dialog.error_filter.setCurrentIndex(2)
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.chart.selected_index, -1)
        self.assertFalse(dialog.viewer.canvas._cloud_markers)
        self.assertIn('最大 2.000 mm', dialog.point_summary.text())

    def test_missing_or_invalid_metrics_and_transform_do_not_invent_success(self):
        dialog = self.dialog(dict(details=None, rms_mm=float('nan'), inlier_ratio=1.2, T=[[1]]),
                             rms_limit_mm=2, min_inlier_ratio=.5)
        self.assertIn('内点 RMS —', dialog.summary.text())
        self.assertIn('内点率 —', dialog.summary.text())
        self.assertIn('未评估', dialog.summary.text())
        self.assertEqual(dialog.matrix.item(0, 0).text(), '—')
        self.assertEqual(dialog.table.rowCount(), 0)
        dialog.set_clouds({'待对齐帧': np.ones((3, 3)), '参考帧': np.ones((3, 3))})
        dialog.view_choice.setCurrentIndex(0)
        self.assertNotIn('待对齐帧', dialog.viewer._pcds)
        self.assertIn('缺少有效变换矩阵', dialog.status.text())

    def test_thresholds_are_caller_supplied_and_failure_cannot_pass(self):
        dialog = self.dialog(rms_limit_mm=.1, min_inlier_ratio=.5)
        self.assertIn('未通过', dialog.summary.text())
        failed = result()
        failed['success'] = False
        other = self.dialog(failed, rms_limit_mm=2, min_inlier_ratio=.5)
        self.assertIn('未通过', other.summary.text())
        unspecified = self.dialog()
        self.assertIn('未评估', unspecified.summary.text())

    def test_unknown_classification_empty_and_late_callbacks_are_safe(self):
        unknown = result()
        for row in unknown['details']:
            row.pop('is_inlier')
        dialog = self.dialog(unknown)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.table.item(0, 5).text(), '未知')
        empty = CalibrationResultDialog({})
        self.addCleanup(empty.reject)
        self.assertIn('暂无标定结果', empty.summary.text())
        dialog.reject()
        dialog.set_clouds({'late': np.ones((3, 3))})
        self.assertFalse(dialog.active)
        self.assertNotIn('late', dialog.clouds)

    def test_compact_window_keeps_error_header_readable(self):
        from PySide6.QtGui import QFontMetrics
        dialog = self.dialog()
        dialog.resize(760, 520)
        dialog.show()
        self.app.processEvents()
        header = dialog.table.horizontalHeader()
        text_width = QFontMetrics(header.font()).horizontalAdvance('误差(mm)')
        self.assertGreaterEqual(dialog.table.columnWidth(4), text_width + 6)
        self.assertEqual((dialog.width(), dialog.height()), (760, 520))

    def test_malformed_correspondences_are_skipped(self):
        self.assertEqual(residual_rows(dict(details=[None, 'bad', dict(pt_ref=['x', 0, 0]),
            dict(pt_ref=[1e308, 0, 0], pt_cam_transformed=[-1e308, 0, 0])])), [])


if __name__ == '__main__':
    unittest.main()
