"""Robot hand-eye capture, DB and explicit project-session integration tests."""
from pathlib import Path
import unittest
from unittest.mock import Mock

import numpy as np

import test_ui_frame_database as fixture
from core.frame_data import FrameData
from core.robot_handeye import HandEyeResult


class RobotSessionTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source

    def robot(self):
        mode = 'robot_stitch'
        self.win.set_mode(mode, [])
        self.bridge._current_mode = mode
        self.win.set_presentation('industrial')
        workspace = self.win.workspace_robot()
        matrix = np.eye(4)
        matrix[:3, 3] = [20, -10, 120]
        ok, message, handeye = HandEyeResult.from_matrix(matrix, 'mm', True)
        self.assertTrue(ok, message)
        self.assertTrue(workspace.load_handeye(handeye))
        workspace.on_manual_pose('400,100,420', '0,0,15', 'ZYX', 'mm', 'absolute')
        return workspace, self.bridge.projects.projects[mode]

    def test_offline_capture_reuses_db_frames_and_publishes_sources(self):
        self.bridge.open_offline_preview('robot_stitch')
        self.wait(lambda: getattr(self.win, '_offline_preview', False) and
            self.win.workspace_robot().workflow.get_frame_count() == 0 and
            len(self.bridge.frame_db.databases['robot_stitch'].records) == 2)
        workspace, project = self.robot()
        raw_ids = list(project.database.records)
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count() == 1)
        self.assertEqual(workspace.workflow.frames[0].database_id, raw_ids[0])
        self.assertEqual(len(project.database.records), 2)
        self.bridge._on_robot_publish()
        self.assertFalse(any(row.kind == 'result' for row in project.database.records.values()))
        self.assertIn('VERIFIED', self.win._st_hint.text())
        workspace.workflow.handeye.validated = True
        workspace.workflow.tip_report = {'verdict': 'PASS'}
        workspace._refresh_actions()
        self.win._industrial_ribbon.commands[('robot_stitch', 'stitch')].click()
        self.wait(lambda: any(row.kind == 'result' for row in project.database.records.values()))
        result = next(row for row in project.database.records.values() if row.kind == 'result')
        self.assertEqual(result.source_ids, raw_ids[:1])
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count() == 2)
        workspace.on_capture()
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(workspace.workflow.get_frame_count(), 2)
        self.assertIn('耗尽', self.win._st_hint.text())

    def test_online_capture_uses_shared_camera_and_archives_raw_frame(self):
        workspace, project = self.robot()
        frame = self.source(7)
        self.bridge.camera_manager.get_connected_ids = Mock(return_value=['cam0'])
        self.bridge.camera_manager.capture = Mock(
            side_effect=lambda camera_id: self.bridge.frame_db.capture(frame))
        workspace.set_devices([fixture.DeviceInfo(serial='A', backend_ref=0)])
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count() == 1)
        self.bridge.camera_manager.capture.assert_called_once_with('cam0')
        self.assertEqual(len(project.database.records), 1)
        self.assertEqual(workspace.workflow.frames[0].database_id,
            next(iter(project.database.records)))
        record = next(iter(project.database.records.values()))
        self.assertEqual(record.purpose, '机器人原始帧',
            (self.bridge._current_mode, record))

    def test_db_selection_and_checkbox_overlay_use_robot_workspace(self):
        workspace, project = self.robot()
        frame = self.source(1)
        uid = project.database.ingest(frame)
        browser = self.bridge.frame_db.browsers['robot_stitch']
        browser.tree.setCurrentItem(browser._items[uid])
        self.wait(lambda: workspace.viewer()._database_cloud is not None)
        browser.set_component_checked(uid, 'cloud', True)
        self.wait(lambda: workspace.viewer()._database_clouds)
        self.assertEqual(self.bridge.frame_db.overlay.requested['robot_stitch'], [uid])

    def test_missing_referenced_frame_preserves_current_project(self):
        import json
        workspace, project = self.robot()
        project.save_root = Path(self.temp.name) / 'sessions'
        frame = self.source(1)
        project.database.ingest(frame)
        workspace.set_capture_provider(lambda: frame)
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count() == 1)
        saved = project.save(self.bridge.projects.describe('robot_stitch', True))
        project.dirty = False
        manifest = json.loads((saved / 'session.json').read_text(encoding='utf-8'))
        manifest['workflow']['captures'][0]['frame']['uid'] = 'f' * 32
        (saved / 'session.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.bridge.projects.open(saved, 'robot_stitch')
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIn('会话载入失败', self.win._st_hint.text())
        self.assertIs(self.bridge.projects.projects['robot_stitch'], project)
        self.assertEqual(workspace.workflow.get_frame_count(), 1)

    def test_project_roundtrip_restores_handeye_pose_frames_and_cloud(self):
        workspace, project = self.robot()
        project.save_root = Path(self.temp.name) / 'sessions'
        frames = [self.source(1), self.source(2), self.source(3)]
        for frame in frames:
            project.database.ingest(frame)
        iterator = iter(frames)
        workspace.set_capture_provider(lambda: next(iterator, None))
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count() == 1)
        workspace.on_capture()
        self.wait(lambda: workspace.workflow.get_frame_count() == 2)
        snapshot = workspace.workflow.snapshot()
        saved = project.save(self.bridge.projects.describe('robot_stitch', True))
        project.dirty = False
        self.bridge.projects.new('robot_stitch', '新机器人项目')
        self.assertEqual(self.win.workspace_robot().workflow.get_frame_count(), 0)
        self.bridge.offline_preview = True
        self.win._offline_preview = True
        workspace.offline_preview = True
        self.bridge.projects.open(saved, 'robot_stitch')
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIn('已载入会话', self.win._st_hint.text())
        restored = self.win.workspace_robot().workflow
        self.assertEqual(restored.get_frame_count(), 2)
        self.assertEqual(restored.snapshot(), snapshot)
        np.testing.assert_allclose(
            np.asarray(restored.get_merged_pointcloud().points),
            np.asarray(workspace.workflow.get_merged_pointcloud().points))
        self.assertFalse(self.bridge.projects.projects['robot_stitch'].dirty)
        workspace.on_capture()
        self.wait(lambda: restored.get_frame_count() == 3)
        self.assertIsNotNone(restored.pose_source)
        self.assertEqual(restored.frames[-1].database_id, frames[2].database_id)

    def test_save_completion_preserves_changes_made_after_snapshot(self):
        from unittest.mock import patch
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        workspace, project = self.robot()
        project.save_root = Path(self.temp.name) / 'sessions'
        original_save = project.save

        def save_with_later_change(data, *, include_raw=None):
            project.change_version += 1
            project.dirty = True
            return original_save(data, include_raw=include_raw)

        with patch.object(project, 'save', side_effect=save_with_later_change):
            QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
            self.bridge.projects.save('robot_stitch')
            self.wait(lambda: project.saved_path is not None)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertTrue(project.dirty)


if __name__ == '__main__':
    unittest.main()
