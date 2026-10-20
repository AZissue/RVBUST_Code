"""Project actions exercise production save/load, close choices and empty views."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

import test_ui_frame_database as fixture
from core.chain_stitcher import ChainNode, ChainEdge
from core.frame_data import FrameData
from test_frame_database import PLY


class SessionUiTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait

    def mobile(self):
        self.win.set_mode('mobile_chain', [])
        self.bridge._current_mode = 'mobile_chain'
        controller = self.bridge.projects
        project = controller.projects['mobile_chain']
        project.save_root = Path(self.temp.name) / 'sessions'
        self.bridge.mobile_workflow.start_chaining()
        controller.prepare('mobile_chain')
        chain = self.bridge.mobile_workflow._chain_stitcher
        for i in (1, 2):
            source = Path(self.temp.name) / f'frame{i}.ply'
            source.write_bytes(PLY)
            frame = FrameData(i, 'cam0', image_np=np.full((2, 2, 3), i, np.uint8),
                is_offline=True, offline_pointmap_path=str(source))
            uid = project.database.ingest(frame)
            frame.camera_name = sid = f'station_{i}'
            frame.offline_pointmap_path = str(project.database.directory / 'frames' / uid / 'pointmap.ply')
            transform = np.eye(4)
            transform[0, 3] = (i-1)*10
            chain.nodes[sid] = ChainNode(sid, frame, [], transform, .01*(i-1))
            chain.pose_graph.add_node(sid, transform)
            self.bridge.mobile_workflow.station_manager._stations[sid] = frame
        chain._reference_id = 'station_1'
        edge = ChainEdge('station_2', 'station_1', chain.nodes['station_2'].T_world.copy(), .01, 1., 5)
        chain.edges.append(edge)
        chain.pose_graph.add_edge(edge.from_id, edge.to_id, edge.T)
        self.bridge.mobile_workflow.station_manager._station_seq = 2
        ws = self.win.workspace_mobile()
        ws.set_stations(self.bridge.mobile_workflow.get_station_evaluations())
        ws.viewer().set_pointcloud_merged(self.bridge.mobile_workflow.get_merged_pointcloud())
        return controller, project

    def save_ui(self):
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
        self.win._industrial_ribbon.commands[('mobile_chain', 'save')].click()
        self.wait(lambda: '会话已保存' in self.win._st_hint.text())
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))

    def test_save_load_exact_poses_and_single_raw_pair_then_continue_delete(self):
        controller, project = self.mobile()
        self.save_ui()
        saved = project.saved_path
        self.assertTrue((saved / 'session.json').exists())
        self.assertEqual(len(list((saved / 'data' / 'frames').iterdir())), 2)
        self.assertFalse((saved / 'stations').exists())
        self.assertFalse(project.dirty)
        old_draft = project.directory
        controller.new('mobile_chain', '第二个工件')
        self.assertFalse(old_draft.exists())
        self.assertIsNone(self.win.workspace_mobile().viewer()._merged)
        controller.open(saved, 'mobile_chain')
        self.wait(lambda: '已载入会话' in self.win._st_hint.text())
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        chain = self.bridge.mobile_workflow._chain_stitcher
        self.assertEqual(list(chain.nodes), ['station_1', 'station_2'])
        self.assertEqual(chain.nodes['station_2'].T_world[0, 3], 10)
        self.assertEqual(chain.nodes['station_2'].frame.image_np[0, 0, 0], 2)
        self.assertFalse(controller.projects['mobile_chain'].dirty)
        self.bridge._on_mobile_delete_station(2)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(len(self.bridge.mobile_workflow.get_station_evaluations()), 1)
        self.bridge._on_save_session()
        self.wait(lambda: not controller.projects['mobile_chain'].dirty)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(len(json.loads((saved / 'session.json').read_text(encoding='utf-8'))['workflow']['nodes']), 1)
        self.assertEqual(len(list(project.save_root.iterdir())), 1)

    def test_deleting_final_station_clears_2d_3d_and_raw_db_stays(self):
        controller, project = self.mobile()
        self.bridge._on_mobile_delete_station(2)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.bridge._on_mobile_delete_station(1)
        ws = self.win.workspace_mobile()
        self.wait(lambda: ws.viewer()._merged is None)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertEqual(ws._station_count, 0)
        self.assertEqual(ws.viewer()._clouds, {})
        self.assertIsNone(ws.live_view()._current_pixmap)
        self.assertIsNone(ws.live_view().marker_context[0])
        self.assertEqual(len(project.database.records), 2)

    def test_export_goes_to_explicit_path_and_survives_discarding_draft(self):
        controller, project = self.mobile()
        exported = Path(self.temp.name) / 'export' / 'result.ply'
        with patch('ui_v2.backend_bridge.QFileDialog.getSaveFileName', return_value=(str(exported), '')):
            self.bridge._on_mobile_save()
            self.wait(lambda: exported.exists())
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.bridge.cleanup()
        self.assertFalse(project.directory.exists())
        self.assertTrue(exported.exists())
        self.assertTrue(exported.with_name('result_report.json').exists())

    def test_close_cancel_discard_and_save_failure_do_not_publish_draft(self):
        controller, project = self.mobile()
        event = QCloseEvent()
        with patch('ui_v2.session_projects.QMessageBox.warning', return_value=QMessageBox.Cancel):
            self.win._close_event_impl(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(project.save_root.exists())
        with patch('ui_v2.session_projects.QMessageBox.warning', return_value=QMessageBox.Save), \
             patch.object(project, 'save', side_effect=OSError('disk full')):
            QTimer.singleShot(1, lambda: self.accept_save_dialog_when_visible())
            self.win._close_event_impl(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(project.dirty)
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        with patch('ui_v2.session_projects.QMessageBox.warning', return_value=QMessageBox.Discard):
            self.win._close_event_impl(event)
        self.assertTrue(event.isAccepted())
        self.bridge.cleanup()
        self.assertFalse(project.directory.exists())
        self.assertFalse(project.save_root.exists())

    def accept_save_dialog_when_visible(self):
        dialog = QApplication.activeModalWidget()
        if dialog and dialog.windowTitle() == '保存会话':
            dialog.accept()
        else:
            QTimer.singleShot(1, self.accept_save_dialog_when_visible)

    def test_new_button_creates_named_root_and_discards_only_draft(self):
        controller, old = self.mobile()
        with patch('ui_v2.session_projects.QInputDialog.getText', return_value=('测试工件', True)), \
             patch('ui_v2.session_projects.QMessageBox.warning', return_value=QMessageBox.Discard):
            self.win._industrial_ribbon.commands[('mobile_chain', 'new')].click()
        new = controller.projects['mobile_chain']
        browser = self.win.workspace_mobile()._industrial.frame_browser
        self.assertIn('测试工件', browser.tree.topLevelItem(0).text(0))
        self.assertEqual(browser.tree.topLevelItem(0).childCount(), 0)
        self.assertFalse(old.directory.exists())
        self.assertFalse(new.save_root.exists())

    def test_wrong_mode_open_keeps_existing_project_and_view(self):
        controller, project = self.mobile()
        self.save_ui()
        saved = project.saved_path
        old_multi = controller.projects['multi_cam']
        self.bridge._current_mode = 'multi_cam'
        self.win.set_mode('multi_cam', [])
        controller.open(saved, 'multi_cam')
        self.wait(lambda: '会话载入失败' in self.win._st_hint.text())
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertIs(controller.projects['multi_cam'], old_multi)

    def test_legacy_multi_import_owns_pair_without_modifying_source(self):
        from core.offline_session import OfflineSession
        legacy = OfflineSession()
        legacy.create_new(str(Path(self.temp.name) / 'legacy'))
        source = Path(self.temp.name) / 'legacy_input.ply'
        source.write_bytes(PLY)
        frame = FrameData(1, 'cam0', image_np=np.zeros((2, 2, 3), np.uint8),
            is_offline=True, offline_pointmap_path=str(source), kind='calib')
        legacy.add_frame('cam0', frame)
        original = {path.relative_to(legacy.session_dir): path.read_bytes()
            for path in Path(legacy.session_dir).rglob('*') if path.is_file()}
        controller = self.bridge.projects
        controller.open(legacy.session_dir, 'multi_cam', legacy=True)
        self.wait(lambda: '已载入会话' in self.win._st_hint.text())
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        project = controller.projects['multi_cam']
        self.assertTrue(project.dirty)
        self.assertIsNone(project.saved_path)
        self.assertEqual(len(project.database.records), 1)
        for relative, data in original.items():
            self.assertEqual((Path(legacy.session_dir) / relative).read_bytes(), data)

    def test_storage_statistics_use_background_and_include_saved_project(self):
        from ui_v2.session_storage_dialog import SessionStorageDialog
        controller, project = self.mobile()
        self.save_ui()
        dialog = SessionStorageDialog(controller, 'mobile_chain', self.win)
        dialog.show()
        self.wait(lambda: bool(dialog.rows))
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertTrue(any(path == project.saved_path for path, info, usage in dialog.rows))
        self.assertIn('当前工作区', dialog.summary.text())
        dialog.close()

    def test_turntable_parameters_only_save_and_restore(self):
        controller = self.bridge.projects
        self.win.set_mode('turntable', [])
        self.bridge._current_mode = 'turntable'
        ws = self.win.workspace_turntable()
        calibration = dict(axis=[0, 0, 1], center=[10, 20, 30], angle_deg=30., step_count=12)
        self.assertTrue(ws.apply_loaded_calibration(calibration))
        project = controller.projects['turntable']
        project.save_root = Path(self.temp.name) / 'sessions'
        project.save(controller.describe('turntable', False), include_raw=False)
        path = project.saved_path
        controller.new('turntable', '新转台任务')
        controller.open(path, 'turntable')
        self.wait(lambda: '已载入会话' in self.win._st_hint.text())
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertTrue(ws.session.is_calibrated())
        np.testing.assert_allclose(ws.session.calib.center, [10, 20, 30])
        self.assertEqual(ws.session.current_step, 0)
        self.assertFalse((path / 'data').exists())

    def test_close_save_covers_dirty_projects_in_inactive_workspaces(self):
        controller, mobile = self.mobile()
        multi = controller.projects['multi_cam']
        multi.name = '另一个工作区'
        multi.save_root = mobile.save_root
        multi.dirty = True
        accepting = [True]
        def accept_options():
            dialog = QApplication.activeModalWidget()
            if dialog and dialog.windowTitle() == '保存会话':
                dialog.accept()
            if accepting[0]:
                QTimer.singleShot(2, accept_options)
        with patch('ui_v2.session_projects.QMessageBox.warning', return_value=QMessageBox.Save):
            QTimer.singleShot(0, accept_options)
            self.assertTrue(controller.request_close())
        accepting[0] = False
        self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
        self.assertTrue((multi.saved_path / 'session.json').exists())
        self.assertTrue((mobile.saved_path / 'session.json').exists())
        self.assertFalse(multi.dirty or mobile.dirty)

    def test_management_deletes_selected_legacy_directory_but_protects_open_snapshot(self):
        from ui_v2.session_storage_dialog import SessionStorageDialog
        controller, project = self.mobile()
        self.save_ui()
        fake_root = Path(self.temp.name) / 'old_project'
        legacy = fake_root / 'offline_data' / 'session_old'
        legacy.mkdir(parents=True)
        (legacy / 'meta.json').write_text('{}')
        with patch('ui_v2.session_storage_dialog.PROJECT_ROOT', fake_root):
            dialog = SessionStorageDialog(controller, 'mobile_chain', self.win)
            dialog.show()
            self.wait(lambda: len(dialog.rows) == 2)
            self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            saved_index = next(i for i, row in enumerate(dialog.rows) if row[0] == project.saved_path)
            dialog.table.selectRow(saved_index)
            with patch('ui_v2.session_storage_dialog.QMessageBox.information') as message:
                dialog.delete()
                message.assert_called_once()
            index = next(i for i, row in enumerate(dialog.rows) if row[0] == legacy)
            dialog.table.clearSelection()
            dialog.table.selectRow(index)
            with patch('ui_v2.session_storage_dialog.QMessageBox.question', return_value=QMessageBox.Yes):
                dialog.delete()
                self.wait(lambda: not legacy.exists())
                self.wait(lambda: not any(w.isRunning() for w in self.bridge._workers))
            self.assertTrue(project.saved_path.exists())
            dialog.close()


if __name__ == '__main__':
    unittest.main()
