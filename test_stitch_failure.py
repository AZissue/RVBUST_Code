import unittest
from unittest.mock import patch
import test_explicit_stitching as fixture
from ui_v2.stitch_failure import show_stitch_failure, advice
from core import frame_recognition

class FailureTests(unittest.TestCase):
    setUpClass = classmethod(fixture.ExplicitStitchingTests.setUpClass.__func__)
    setUp = fixture.ExplicitStitchingTests.setUp
    tearDown = fixture.ExplicitStitchingTests.tearDown
    source = fixture.ExplicitStitchingTests.source
    wait = fixture.ExplicitStitchingTests.wait
    mobile = fixture.ExplicitStitchingTests.mobile
    execute = fixture.ExplicitStitchingTests.execute

    def test_explicit_failure_shows_reason_and_settings_action_without_new_result(self):
        self.mobile()
        before = set(self.db.records)
        with patch('core.chain_stitcher.ChainStitcher.add_frame', return_value=(False, '未检测到标记物', None)):
            self.execute()
        box = self.win._stitch_failure_dialog
        self.assertTrue(box.isVisible())
        self.assertIn('未检测到标记物', box.text())
        self.assertIn('非对称圆标定板', box.informativeText())
        self.assertEqual(set(self.db.records), before)
        show_stitch_failure(self.bridge, 'mobile_chain', '共有标记不足')
        self.assertIs(self.win._stitch_failure_dialog, box)
        next(b for b in box.buttons() if b.text() == '打开识别参数').click()
        props = self.bridge.frame_db.browsers['mobile_chain'].properties
        self.assertIs(props.tabs.currentWidget(), props.recognition)
        self.app.processEvents()
        self.assertIsNone(self.win._stitch_failure_dialog)

    def test_cached_recognition_error_is_reported_before_stitch_worker(self):
        self.mobile()
        recognition = self.bridge.recognition
        recognition.enabled = True
        key = frame_recognition.fingerprint(recognition.config('mobile_chain'))
        for row in self.db.records.values():
            row.recognition = dict(key=key, state='error', error='board detect failed')
        self.execute()
        self.assertIn('board detect failed', self.win._stitch_failure_dialog.text())
        self.win._stitch_failure_dialog.close()
        recognition.enabled = False

    def test_failed_waiter_reports_once_and_cleans_error_handler(self):
        self.mobile()
        recognition = self.bridge.recognition
        recognition.enabled = True
        config = recognition.config('mobile_chain')
        key = frame_recognition.fingerprint(config)
        inputs = tuple((r.uid, r.revision) for r in self.db.records.values())
        token = ('mobile_chain', self.db.directory, inputs, key)
        for row in self.db.records.values():
            row.recognition = dict(key=key, state='error', error='SDK recognition failed')
        recognition.waiters.append((token, lambda: self.fail('must not stitch')))
        recognition.waiter_errors[token] = lambda error: show_stitch_failure(self.bridge, 'mobile_chain', error)
        recognition.tick()
        self.assertIn('SDK recognition failed', self.win._stitch_failure_dialog.text())
        self.assertFalse(recognition.waiters)
        self.assertFalse(recognition.waiter_errors)
        self.win._stitch_failure_dialog.close()
        recognition.tick()
        self.assertIsNone(self.win._stitch_failure_dialog)
        recognition.enabled = False

    def test_advice_distinguishes_calibration_geometry_and_unknown_errors(self):
        self.assertIn('外参', advice('请先完成标定', 'coded_circle'))
        self.assertIn('有效深度', advice('没有有效3D点', 'coded_circle'))
        self.assertIn('磁盘空间', advice('disk full', 'coded_circle'))

if __name__ == '__main__': unittest.main()
