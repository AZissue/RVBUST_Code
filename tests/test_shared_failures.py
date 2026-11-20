import _bootstrap
import unittest
import test_postprocess as fixture


class SharedFailureTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PostprocessTests.setUpClass.__func__)
    setUp = fixture.PostprocessTests.setUp
    tearDown = fixture.PostprocessTests.tearDown
    wait = fixture.PostprocessTests.wait
    source = fixture.PostprocessTests.source

    def test_robot_negative_result_uses_shared_failure_surface(self):
        workspace = self.win.workspace_robot()
        workspace._busy = True
        workspace._on_capture_done((False, '相机未取得图像', None), None)
        self.assertFalse(workspace._busy)
        box = self.win._operation_failure_dialog
        self.assertTrue(box.isVisible())
        self.assertIn('相机未取得图像', box.text())
        box.close()

    def test_explicit_postprocess_failure_has_advice_and_recovers_controls(self):
        before = set(self.db.records)
        def fail():
            raise ValueError('重叠不足，ICP失败')
        self.editor._run(fail, lambda value: self.fail('no result'))
        self.wait(lambda: self.editor._worker is None)
        box = self.editor._operation_failure_dialog
        self.assertTrue(box.isVisible())
        self.assertIn('重叠', box.informativeText())
        self.assertEqual(set(self.db.records), before)
        self.assertTrue(self.editor.source_browser.isEnabled())
        box.close()

    def test_automatic_load_failure_does_not_open_dialog(self):
        def fail():
            raise IOError('文件损坏')
        self.editor._run(fail, lambda value: self.fail('no result'), kind='load')
        self.wait(lambda: self.editor._worker is None)
        self.assertIsNone(getattr(self.editor, '_operation_failure_dialog', None))

    def test_explicit_inspection_is_not_treated_as_automatic_work(self):
        def fail():
            raise OSError('相机断开失败')
        self.bridge._run_background(fail, lambda *args: None,
                                   name='device_disconnect', must_finish=True)
        self.wait(lambda: not self.bridge._workers)
        box = self.win._operation_failure_dialog
        self.assertTrue(box.isVisible())
        self.assertIn('相机断开失败', box.text())
        box.close()
        self.app.processEvents()
        self.bridge._run_background(fail, lambda *args: None,
                                   name='capture_parameters', automatic=True)
        self.wait(lambda: not self.bridge._workers)
        self.assertIsNone(self.win._operation_failure_dialog)
