"""Robot hand-eye fourth workspace and industrial presentation tests."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import open3d as o3d

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy
from ui_v2 import LauncherDialog, MainWindowShell
from ui_v2.widgets.device_table import DeviceInfo
from core.frame_data import FrameData
from core.robot_handeye import HandEyeResult


class RobotWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_launcher_has_robot_industrial_entry_and_single_camera_rule(self):
        dialog = LauncherDialog()
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(hasattr(dialog, 'MODE_ROBOT'))
        mode = dialog.MODE_ROBOT
        self.assertIn(mode, dialog._industrial_cards)
        self.assertNotIn(mode, dialog._cards)
        dialog._industrial_cards[mode].clicked.emit()
        self.assertEqual(dialog.selected_presentation(), 'industrial')
        dialog.set_devices([DeviceInfo(serial='A', checked=True, backend_ref=0)])
        self.assertTrue(dialog._btn_connect.isEnabled())
        dialog.set_devices([
            DeviceInfo(serial='A', checked=True, backend_ref=0),
            DeviceInfo(serial='B', checked=True, backend_ref=1)])
        self.assertFalse(dialog._btn_connect.isEnabled())

    def test_shell_switches_robot_and_applies_industrial_layout(self):
        win = MainWindowShell()
        self.addCleanup(win.deleteLater)
        win.set_mode(LauncherDialog.MODE_ROBOT, [])
        self.assertIs(win._stack.currentWidget(), win.workspace_robot())
        win.set_presentation('industrial')
        self.assertTrue(win.workspace_robot()._industrial.active)
        self.assertIn((LauncherDialog.MODE_ROBOT, 'capture'),
            win._industrial_ribbon.commands)
        win.resize(1440, 900)
        win.show()
        self.app.processEvents()
        self.assertGreater(win.workspace_robot()._industrial.sidebar.height(), 300)
        self.assertTrue(win.workspace_robot()._industrial.frame_browser.isVisible())
        matrix = np.eye(4)
        matrix[:3, 3] = [20, -10, 120]
        ok, message, handeye = HandEyeResult.from_matrix(matrix, 'mm', True)
        self.assertTrue(ok, message)
        self.assertTrue(win.workspace_robot().load_handeye(handeye))
        self.assertEqual(win._st_step.text(), 'matrix_loaded')

    def test_workspace_capture_updates_cloud_and_dirty_state(self):
        from ui_v2.workspaces.robot_workspace import RobotWorkspace
        workspace = RobotWorkspace()
        self.addCleanup(workspace.deleteLater)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.ply'
            cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
                np.array([[1., 2., 500.], [10., 20., 600.]])))
            o3d.io.write_point_cloud(str(path), cloud)
            frame = FrameData(1, 'cam0', image_np=np.zeros((2, 2, 3), np.uint8),
                is_offline=True, offline_pointmap_path=str(path))
            frame.database_id = 'b' * 32
            workspace.set_capture_provider(lambda: frame)
            matrix = np.eye(4)
            matrix[:3, 3] = [20, -10, 120]
            ok, message, handeye = HandEyeResult.from_matrix(matrix, 'mm', True)
            self.assertTrue(ok, message)
            self.assertTrue(workspace.load_handeye(handeye))
            workspace.on_manual_pose('400,100,420', '0,0,15', 'ZYX', 'mm', 'absolute')
            dirty = QSignalSpy(workspace.dirty_changed)
            workspace.on_capture()
            self.assertEqual(workspace.workflow.get_frame_count(), 1)
            self.assertEqual(dirty.count(), 1)
            self.assertIn('base', workspace.viewer()._clouds)
            self.assertIsNotNone(workspace.viewer()._merged)
            workspace.on_pose_kind('csv')
            workspace.on_capture()
            self.assertEqual(workspace.workflow.get_frame_count(), 1)
            self.assertFalse(workspace.panel.btn_capture.isEnabled())
            workspace.set_capture_provider(None)
            workspace.set_devices([])
            self.assertFalse(workspace.panel.btn_capture.isEnabled())
            workspace.on_clear()
            self.assertEqual(workspace.workflow.get_frame_count(), 0)
            self.assertEqual(workspace.viewer()._clouds, {})

    def test_shared_task_gate_and_stale_capture_callback(self):
        from ui_v2.workspaces.robot_workspace import RobotWorkspace
        workspace = RobotWorkspace()
        self.addCleanup(workspace.deleteLater)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.ply'
            o3d.io.write_point_cloud(str(path), o3d.geometry.PointCloud(
                o3d.utility.Vector3dVector(np.array([[1., 2., 500.]]))))
            frame = FrameData(1, 'cam0', image_np=np.zeros((2, 2, 3), np.uint8),
                is_offline=True, offline_pointmap_path=str(path))
            frame.database_id = 'b' * 32
            workspace.set_capture_provider(lambda: frame)
            matrix = np.eye(4)
            matrix[:3, 3] = [20, -10, 120]
            _, _, handeye = HandEyeResult.from_matrix(matrix, 'mm', True)
            workspace.load_handeye(handeye)
            workspace.on_manual_pose('400,100,420', '0,0,15', 'ZYX', 'mm', 'absolute')
            workspace.set_task_gate(lambda: False)
            workspace.on_capture()
            self.assertEqual(workspace.workflow.get_frame_count(), 0)
            workspace.workflow.tip_report = {'verdict': 'PASS'}
            workspace.on_tip_check()
            self.assertEqual(workspace.workflow.tip_report, {'verdict': 'PASS'})
            workspace.set_task_gate(None)
            result = workspace._capture_job()
            self.assertTrue(result[0])
            token = workspace._generation
            workspace.on_clear()
            workspace._on_capture_done(result, None, token)
            self.assertEqual(workspace.viewer()._clouds, {})
            self.assertEqual(workspace.workflow.get_frame_count(), 0)

    def test_industrial_clear_removes_business_image_and_compact_layout(self):
        win = MainWindowShell()
        self.addCleanup(win.deleteLater)
        win.set_mode(LauncherDialog.MODE_ROBOT, [])
        win.set_presentation('industrial')
        workspace = win.workspace_robot()
        matrix = np.eye(4)
        matrix[:3, 3] = [20, -10, 120]
        _, _, handeye = HandEyeResult.from_matrix(matrix, 'mm', True)
        workspace.load_handeye(handeye)
        workspace._display_2d(np.zeros((2, 2, 3), np.uint8))
        workspace.on_clear()
        self.assertIsNone(workspace._industrial._business_marker_image[0][0])
        win.resize(1050, 650)
        win.show()
        self.app.processEvents()
        self.assertTrue(workspace._industrial.sidebar.isVisible())
        self.assertTrue(workspace._industrial.frame_browser.isVisible())


if __name__ == '__main__':
    unittest.main()
