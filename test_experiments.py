"""Integrated validation UI, data isolation and lifecycle regression; no SDK."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import test_ui_frame_database as fixture
from core.camera_manager import CameraManager
from prototypes.offline_workspace import OfflineWorkspace, load_session
from prototypes.color_postprocess.editor import ColorValidationWindow
from prototypes.circle_geometry_match.editor import CircleMatchEditor
from ui_v2.postprocess.fpfh_editor import FPFHEditor
from ui_v2.postprocess.window import PostprocessWindow
from core.session_project import SessionProject

class ExperimentTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source
    def test_offline_entry_opens_file_pair_ui_without_devices(self):
        from PySide6.QtWidgets import QGroupBox, QPushButton
        with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK forbidden')):
            shell = self.win.open_offline_stitch()
            self.assertIsNotNone(shell)
            self.assertIsNone(getattr(shell._backend_bridge, 'validation_root', None))
            self.assertEqual(shell._frame_databases['mobile_chain'].records, {})
            self.assertEqual(shell.workspace_mobile()._industrial.frame_browser.database, shell._frame_databases['mobile_chain'])
            self.assertTrue(shell._btn_devices.isHidden())
            self.assertFalse(shell._industrial_ribbon.commands[('mobile_chain', 'stitch')].isEnabled())
            self.assertIs(self.win.open_offline_stitch(), shell)
            shell.close()
            self.assertIsNone(self.win._offline_stitch_window)

    def test_saved_session_is_loaded_as_a_private_copy(self):
        uid = self.db.ingest(self.source())
        source = self.bridge.projects.projects['multi_cam']
        with tempfile.TemporaryDirectory() as folder:
            source.save_root = Path(folder)
            saved = source.save(self.bridge.projects.describe('multi_cam', True))
            manifest = (saved / 'session.json').read_bytes()
            copy, workflow = load_session(saved, 'multi_cam')
            try:
                self.assertIn(uid, copy.database.records)
                self.assertIsNone(copy.saved_path)
                self.assertNotEqual(copy.uid, source.uid)
                copy.database.remove([uid])
                self.assertEqual((saved / 'session.json').read_bytes(), manifest)
                reloaded, _ = SessionProject.load(saved, 'multi_cam')
                try:
                    self.assertIn(uid, reloaded.database.records)
                finally:
                    reloaded.dispose()
                with self.assertRaises(ValueError):
                    load_session(saved, 'robot_stitch')
            finally:
                copy.dispose()

    def test_independent_editors_load_saved_session_and_close_without_sdk(self):
        uid = self.db.ingest(self.source())
        source = self.bridge.projects.projects['multi_cam']
        with tempfile.TemporaryDirectory() as folder:
            source.save_root = Path(folder)
            saved = source.save(self.bridge.projects.describe('multi_cam', True))
            for key, editor_type in (
                ('color_postprocess', ColorValidationWindow),
                ('fpfh_geometry_match', FPFHEditor),
                ('industrial_pointcloud_postprocess', PostprocessWindow),
                ('circle_geometry_match', CircleMatchEditor),
                ('fixed_multi_camera', None),
            ):
                with self.subTest(key=key), patch.object(
                    CameraManager, 'initialize', side_effect=AssertionError('SDK forbidden')
                ):
                    project, workflow = load_session(saved / 'session.json')
                    shell = OfflineWorkspace(project, workflow, key=key, title=key,
                                             editor_type=editor_type)
                    bridge = shell._backend_bridge
                    shell.show()
                    self.assertEqual(shell._presentation, 'industrial')
                    self.assertIn(uid, bridge.frame_db.databases['multi_cam'].records)
                    self.assertEqual(project.save_root.name, key)
                    self.assertFalse(bridge._ensure_sdk())
                    if editor_type is not None:
                        editor = bridge.open_postprocess()
                        self.assertIs(type(editor), editor_type)
                        editor.load_selected([uid])
                        self.wait(lambda: editor._worker is None)
                        self.assertIn(uid, editor._display_ids)
                    self.assertTrue(shell.close())
                    self.app.processEvents()
                    self.assertFalse(project.directory.exists())

    def test_robot_loads_offline_handeye_and_raw_frame(self):
        import numpy as np

        mode = 'robot_stitch'
        source = self.bridge.projects.projects[mode]
        uid = source.database.ingest(self.source())
        transform = np.eye(4)
        transform[:3, 3] = [100, 200, 300]
        ok, message = self.bridge.robot_workflow.set_handeye_result(False, transform)
        self.assertTrue(ok, message)
        with tempfile.TemporaryDirectory() as folder:
            source.save_root = Path(folder)
            saved = source.save(self.bridge.projects.describe(mode, True))
            project, workflow = load_session(saved, mode)
            with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK forbidden')):
                shell = OfflineWorkspace(project, workflow, key='robot_handeye_transform', title='Robot')
                bridge = shell._backend_bridge
                np.testing.assert_allclose(bridge.robot_workflow._T_handeye, transform)
                self.assertIn(uid, bridge.frame_db.databases[mode].records)
                self.assertEqual(bridge.projects._robot_offline_provider(project)().database_id, uid)
                self.assertTrue(shell.close())
                self.app.processEvents()

    def test_integrated_color_result_save_and_reopen(self):
        import numpy as np
        from test_postprocess import cloud
        from test_color_correction import scene

        uid = self.db.ingest(self.source())
        xyz, _, rgb = scene()
        result = self.db.publish_result(cloud(xyz, rgb), [uid])
        source = self.bridge.projects.projects['multi_cam']
        with tempfile.TemporaryDirectory() as folder:
            source.save_root = Path(folder) / 'source'
            saved = source.save(self.bridge.projects.describe('multi_cam', True))
            original = (saved / 'session.json').read_bytes()
            project, workflow = load_session(saved)
            shell = OfflineWorkspace(project, workflow, key='color_postprocess',
                                     title='Color', editor_type=ColorValidationWindow,
                                     output=Path(folder) / 'experiment')
            child = shell._backend_bridge
            shell.show()
            editor = child.open_postprocess()
            self.wait(lambda: editor._worker is None)
            editor._color_state.update(aligned=True, strength=1., max_gain=2., scale=15.)
            editor.correct_colors()
            self.wait(lambda: editor._worker is None)
            self.assertNotEqual(editor._display_ids, [result], editor.status.text())
            output = editor._display_ids[0]
            np.testing.assert_array_equal(editor._clouds[output].points, xyz)
            completed = []
            from PySide6.QtWidgets import QDialog
            with patch.object(QDialog, 'exec', return_value=QDialog.Accepted):
                child.projects.save('multi_cam', completed.append)
            self.wait(lambda: completed)
            self.assertEqual(completed, [True])
            output_path = project.saved_path
            self.assertEqual(output_path.parent, project.save_root)
            self.assertEqual((saved / 'session.json').read_bytes(), original)
            self.assertNotIn(output, self.db.records)
            copy, _ = SessionProject.load(output_path, 'multi_cam')
            try:
                self.assertIn(output, copy.database.records)
            finally:
                copy.dispose()
            editor.close()
            reopened = child.open_postprocess()
            self.assertIsInstance(reopened, ColorValidationWindow)
            self.wait(lambda: reopened._worker is None)
            self.assertTrue(shell.close())
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
