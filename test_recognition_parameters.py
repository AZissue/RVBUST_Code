"""Recognition settings wiring, offline use, gates and background invalidation."""
import copy
import threading
import unittest
from unittest.mock import patch
import test_ui_frame_database as fixture
from core import frame_recognition


class RecognitionPageTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait
    source = fixture.FrameBrowserTests.source

    def page(self):
        props = self.win._stack.currentWidget()._industrial.frame_browser.properties
        props.tabs.setCurrentWidget(props.recognition)
        self.app.processEvents()
        return props.recognition

    def test_offline_types_specs_and_legacy_controls_stay_in_sync_in_all_modes(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.bridge._current_mode = mode
            self.win.set_mode(mode, [])
            page = self.page()
            self.assertTrue(page.marker_type.isEnabled())
            self.assertEqual(page.board_spec.count(), 4)
            self.assertIn('N = 8', page.circle_values.text())
            page.marker_type.setCurrentIndex(page.marker_type.findData('asymmetric_grid'))
            page.board_spec.setCurrentIndex(2)
            page.gamma.set_value(1.75)
            page.apply_button.click()
            config = self.bridge.recognition.config(mode)
            self.assertEqual(config['marker_type'], 'asymmetric_grid')
            self.assertEqual([(s['rows'], s['cols']) for s in config['boards']], [(7, 11)])
            self.assertEqual(config['gamma'], 1.75)
            if mode == 'multi_cam':
                self.assertEqual(self.win.workspace_multi().current_detect_method(), 'calib_board')
            if mode == 'turntable':
                self.assertEqual(self.win.workspace_turntable().combo_marker_type.currentData(), 'asymmetric_grid')
            page.board_spec.setCurrentIndex(0)
            page.marker_type.setCurrentIndex(0)
            page.apply_button.click()
            self.assertEqual(len(self.bridge.recognition.config(mode)['boards']), 3)
            self.assertEqual(self.bridge.recognition.config(mode)['marker_type'], 'coded_circle')
        self.assertFalse(self.bridge.camera_manager.get_connected_ids())

    def test_busy_invalid_and_external_changes_do_not_apply_stale_parameters(self):
        service = self.bridge.recognition
        before = copy.deepcopy(service.config('multi_cam'))
        page = self.page()
        page.marker_type.setCurrentIndex(1)
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            page.refresh()
            self.assertFalse(page.apply_button.isEnabled())
            page._apply()
            self.assertEqual(service.config('multi_cam'), before)
        with self.assertRaises(ValueError):
            service.configure('multi_cam', 'asymmetric_grid', [], 2.5)
        self.assertEqual(service.config('multi_cam'), before)
        self.bridge._detect_lock.acquire()
        try:
            with self.assertRaises(ValueError):
                service.configure('multi_cam', 'asymmetric_grid', before['boards'], 2.5)
        finally:
            self.bridge._detect_lock.release()
        self.win.workspace_multi()._detect_combo.setCurrentIndex(1)
        page._apply()
        self.assertIn('其他入口变化', page.status.text())
        self.assertEqual(page.marker_type.currentData(), 'asymmetric_grid')
        self.assertEqual(service.config('multi_cam')['boards'], before['boards'])

    def test_new_settings_discard_inflight_result_and_recompute_with_selected_spec(self):
        service = self.bridge.recognition
        service.timer.stop()
        service.enabled = True
        uid = self.db.ingest(self.source())
        started, release = threading.Event(), threading.Event()
        calls = []
        def detect(frame, config):
            calls.append(copy.deepcopy(config))
            if len(calls) == 1:
                started.set()
                release.wait(5)
            return dict(state='done', key=frame_recognition.fingerprint(config),
                        marker_type=config['marker_type'], markers=[dict(code=len(calls))])
        with patch('core.frame_recognition.detect', side_effect=detect):
            try:
                service.tick()
                self.assertTrue(started.wait(2))
                page = self.page()
                page.marker_type.setCurrentIndex(1)
                page.board_spec.setCurrentIndex(3)
                page.apply_button.click()
                expected = frame_recognition.fingerprint(service.config('multi_cam'))
            finally:
                release.set()
            def ready():
                service.tick()
                return not service.jobs and self.db.records[uid].recognition.get('key') == expected
            self.wait(ready)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['marker_type'], 'coded_circle')
        self.assertEqual(calls[1]['boards'][0]['name'], '4x5')
        self.assertEqual(self.db.records[uid].markers, [dict(code=2)])
        self.assertEqual(self.db.records[uid].revision, 0)


if __name__ == '__main__':
    unittest.main()
