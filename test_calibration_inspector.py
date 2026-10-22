"""Calibration inspection uses stored frames, correct transforms and read-only workers."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import open3d as o3d
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core.frame_data import FrameData
from ui_v2 import MainWindowShell, GLOBAL_QSS
from ui_v2.backend_bridge import BackendBridge
from ui_v2.calibration_inspector import (
    CalibrationInspector, load_calibration_clouds, residual_rows,
)


def sample_result():
    transform = np.eye(4)
    transform[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    transform[:3, 3] = [100, 200, 300]
    return dict(success=True, T=transform, rms_mm=.3, inlier_ratio=.75, rms_all_mm=1.2,
                details=[dict(code=7, pt_ref=[1, 2, 3], pt_cam_transformed=[1.3, 2, 3],
                              error_mm=.3, is_inlier=True),
                         dict(code=9, pt_ref=[0, 0, 0], pt_cam_transformed=[0, 0, 4],
                              error_mm=4, is_inlier=False)])


class InspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(GLOBAL_QSS)

    def test_transform_direction_visibility_residuals_and_missing_details(self):
        result = sample_result()
        dialog = CalibrationInspector({('ref', 'cam'): result,
                                       ('ref', 'old'): dict(result, details=[])})
        try:
            raw = np.array([[2., 5., 7.], [11., 13., 17.]])
            original = raw.copy()
            dialog.set_clouds({'ref': raw, 'cam': raw})
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 0).text(), '7')
            dialog.error_filter.setCurrentIndex(1)
            np.testing.assert_allclose(np.asarray(dialog.viewer._pcds['cam'].points),
                                      raw @ result['T'][:3, :3].T + result['T'][:3, 3])
            np.testing.assert_array_equal(raw, original)
            self.assertEqual(dialog.table.item(0, 0).text(), '9')
            self.assertEqual(dialog.table.item(0, 5).text(), '离群点')
            self.assertEqual(dialog.table.item(0, 4).text(), '4.000')
            dialog.show_camera.setChecked(False)
            self.assertNotIn('cam', dialog.viewer._pcds)
            dialog.show_camera.setChecked(True)
            dialog.view_choice.setCurrentIndex(1)
            self.assertEqual(len(dialog.viewer._pcds['cam'].points), 2)
            dialog.pair_choice.setCurrentIndex(1)
            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertIn('没有逐点明细', dialog.status.text())
            dialog.show()
            self.app.processEvents()
            self.assertFalse(dialog.grab().isNull())
        finally:
            dialog.reject()
        dialog.set_clouds({})  # Late worker completion must not touch a closed viewer.

    def test_cloud_loader_is_bounded_handles_missing_and_never_initializes_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'points.ply')
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(np.arange(900).reshape(-1, 3))
            o3d.io.write_point_cloud(path, cloud)
            with patch('core.frame_data._import_rvc', side_effect=AssertionError('SDK forbidden')):
                clouds, warnings = load_calibration_clouds({'cam': path, 'missing': None}, limit=100)
            self.assertLessEqual(len(clouds['cam']), 100)
            self.assertIn('missing', warnings[0])
            self.assertEqual(len(o3d.io.read_point_cloud(path).points), 300)

    def test_button_binding_reset_worker_readonly_and_failure(self):
        window = MainWindowShell()
        bridge = BackendBridge(window)
        bridge.wire_all()
        ws = window.workspace_multi()
        try:
            self.assertFalse(ws._btn_visualize_calibration.isEnabled())
            with patch.object(bridge, 'can_change_workspace', return_value=False), \
                    patch.object(bridge, '_run_background') as run:
                bridge._on_multi_visualize_calibration()
                run.assert_not_called()
            bridge.calibration_engine.pair_results = {('ref', 'cam'): sample_result()}
            bridge.fixed_workflow.frames_calib['cam'] = FrameData(1, 'cam')
            ws.on_calibrate_done([dict(pair='cam→ref', rms_mm=.3, inlier_ratio=.75,
                                      T=np.eye(4))], 90, quality_passed=True)
            with patch.object(bridge, '_run_background') as run:
                ws._btn_visualize_calibration.click()
                self.assertEqual(run.call_args.kwargs['name'], 'calibration_inspection')
                self.assertTrue(bridge._calibration_inspector.active)
                run.call_args.args[1](None, '测试读取失败')
                self.assertIn('测试读取失败', bridge._calibration_inspector.status.text())
                bridge._calibration_inspector.reject()
            ws.clear_calibration_results()
            self.assertFalse(ws._btn_visualize_calibration.isEnabled())
            # Actual worker path must bypass all session/DB mutations.
            bridge.projects.prepare = Mock(side_effect=AssertionError('prepare'))
            for name in ('restore', 'archive_context', 'synchronize', '_changed'):
                setattr(bridge.frame_db, name, Mock(side_effect=AssertionError(name)))
            done = Mock()
            bridge._run_background(lambda: 123, done, name='calibration_inspection')
            for _ in range(100):
                if done.called and not bridge._workers:
                    break
                QTest.qWait(20)
            done.assert_called_once_with(123, None)
        finally:
            bridge.cleanup()
            window._dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_invalid_correspondences_are_not_displayed_as_valid_measurements(self):
        self.assertEqual(residual_rows(dict(details=[dict(pt_ref=[float('nan'), 0, 0],
                                                          pt_cam_transformed=[0, 0, 0])])), [])


if __name__ == '__main__':
    unittest.main()
