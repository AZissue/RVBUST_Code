"""Integrated validation UI, data isolation and lifecycle regression; no SDK."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import test_ui_frame_database as fixture
from core.camera_manager import CameraManager
from ui_v2.experiments import ExperimentHub, clone_project, open_validation, FEATURES
from core.session_project import SessionProject

class ExperimentTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source
    def test_copy_live_database_and_save_isolation(self):
        uid = self.db.ingest(self.source())
        original = (self.db.directory/'frames'/uid/'pointmap.ply').read_bytes()
        source = self.bridge.projects.projects['multi_cam']
        saved, name = source.saved_path, source.name
        copy = clone_project(source)
        try:
            self.assertNotEqual(copy.uid, source.uid)
            self.assertIsNone(copy.saved_path)
            self.assertIn(uid, copy.database.records)
            copy.database.remove([uid])
            self.assertIn(uid, self.db.records)
            self.assertEqual((self.db.directory/'frames'/uid/'pointmap.ply').read_bytes(),original)
            with tempfile.TemporaryDirectory() as folder:
                copy.save_root = Path(folder)
                path = copy.save({})
                loaded, _ = SessionProject.load(path, 'multi_cam')
                loaded.dispose()
            self.assertEqual(source.saved_path, saved)
            self.assertEqual(source.name, name)
        finally:
            copy.dispose()

    def test_all_features_use_formal_workspace_without_sdk(self):
        for feature, _, mode in FEATURES:
            mode = mode or 'multi_cam'
            project = clone_project(self.bridge.projects.projects[mode])
            workflow = self.bridge.projects.describe(mode, True)
            with patch.object(CameraManager, 'initialize', side_effect=AssertionError('SDK forbidden')), \
                    patch('ui_v2.postprocess.window.PostprocessWindow.open_circle_match') as circle_entry:
                shell = open_validation(self.bridge, project, workflow, feature, [])
                self.bridge._validation_shell = shell
                self.app.processEvents()
                child = shell._backend_bridge
                if feature == 'circle_triangle':
                    circle_entry.assert_called_once()
                self.assertEqual(shell.current_mode(), mode)
                self.assertTrue(child.offline_preview)
                self.assertFalse(child.recognition.enabled)
                self.assertIsNone(project.saved_path)
                self.assertEqual(project.save_root.name, 'experiments')
                shell.open_device_manager()
                self.assertFalse(child._sdk_initialized)
                editor = getattr(child, '_postprocess_window', None)
                if editor:
                    self.assertEqual(editor.COLOR_VALIDATION, feature == 'color')
                    editor.close()
                child.projects.closed = True
                shell.close()
                self.app.processEvents()
                self.assertIsNone(self.bridge._validation_shell)

    def test_integrated_color_result_save_and_reopen_gate(self):
        import numpy as np
        from test_postprocess import cloud
        from test_color_correction import scene
        uid = self.db.ingest(self.source())
        xyz, _, rgb = scene()
        result = self.db.publish_result(cloud(xyz, rgb), [uid])
        original = set(self.db.records)
        project = clone_project(self.bridge.projects.projects['multi_cam'])
        shell = open_validation(self.bridge, project,
            self.bridge.projects.describe('multi_cam', True), 'color', [result])
        self.bridge._validation_shell = shell
        child = shell._backend_bridge
        editor = child._postprocess_window
        self.wait(lambda: editor._worker is None)
        editor._color_state.update(aligned=True, strength=1., max_gain=2., scale=15.)
        editor.correct_colors()
        self.wait(lambda: editor._worker is None)
        self.assertGreater(len(project.database.records),len(original))
        self.assertEqual(set(self.db.records),original)
        self.assertNotEqual(editor._display_ids,[result])
        output = editor._display_ids[0]
        np.testing.assert_array_equal(editor._clouds[output].points, xyz)
        with tempfile.TemporaryDirectory() as folder:
            project.save_root = Path(folder)
            saved = project.save(child.projects.describe('multi_cam', True))
            loaded, workflow = SessionProject.load(saved, 'multi_cam')
            try:
                # Opening even an existing saved project cannot target its source.
                old = child.projects.projects['multi_cam']
                child.projects.install('multi_cam', loaded)
                self.assertIsNone(loaded.saved_path)
                self.assertNotEqual(loaded.uid, project.uid)
                self.assertEqual(loaded.save_root.name,'experiments')
                child.projects.install('multi_cam',old)
            finally:
                loaded.dispose()
        editor.close()
        reopened = child.open_postprocess()
        self.assertTrue(reopened.COLOR_VALIDATION)
        reopened.close()
        child.projects.closed = True
        shell.close()
        self.app.processEvents()

    def test_cancel_close_and_failed_copy_recover_without_touching_source(self):
        from ui_v2.dialogs import ChineseMessageBox as QMessageBox
        project = clone_project(self.bridge.projects.projects['multi_cam'])
        shell = open_validation(self.bridge, project,
            self.bridge.projects.describe('multi_cam', True), 'multi_cam', [])
        self.bridge._validation_shell = shell
        shell.set_dirty(True)
        with patch.object(QMessageBox, 'warning', return_value=QMessageBox.Cancel):
            self.assertFalse(shell.close())
        self.assertIs(self.bridge._validation_shell, shell)
        with patch.object(QMessageBox, 'warning', return_value=QMessageBox.Discard):
            self.assertTrue(shell.close())
        self.app.processEvents()
        self.assertIsNone(self.bridge._validation_shell)
        self.assertFalse(project.directory.exists())
        hub = self.bridge.open_experiments()
        with patch('ui_v2.experiments.clone_project', side_effect=OSError('copy failed')):
            hub.launch('geometry')
            self.wait(lambda: not hub._preparing)
        self.assertIn('copy failed', hub.status.text())
        self.assertTrue(all(button.isEnabled() for button in hub.buttons.values()))
        self.assertIsNone(self.bridge.projects.projects['multi_cam'].saved_path)
        hub.close()

    def test_production_entry_and_background_launch(self):
        uid = self.db.ingest(self.source())
        button = self.win._industrial_ribbon.experiment_button
        button.click()
        hub = self.bridge._experiment_hub
        self.assertTrue(hub.isVisible())
        folder = Path('outputs/experiment_preview')
        folder.mkdir(parents=True, exist_ok=True)
        self.win.resize(1440,900)
        self.app.processEvents()
        self.win.grab().save(str(folder/'main.png'))
        hub.grab().save(str(folder/'hub.png'))
        hub.buttons['color'].click()
        self.wait(lambda: getattr(self.bridge,'_validation_shell',None) is not None)
        shell = self.bridge._validation_shell
        shell.resize(1440,900)
        self.app.processEvents()
        shell.grab().save(str(folder/'validation.png'))
        self.assertIn(uid,shell._backend_bridge.frame_db.databases['multi_cam'].records)
        shell._backend_bridge._postprocess_window.close()
        shell._backend_bridge.projects.closed = True
        shell.close()
        self.app.processEvents()
        hub.close()

if __name__ == '__main__':
    unittest.main()
