"""Recognition settings wiring, offline use, gates and background invalidation."""
import copy
import threading
import unittest
from unittest.mock import patch
import test_ui_frame_database as fixture
from core import frame_recognition
from core.marker_detector import MarkerDetector
from PySide6.QtCore import QPoint


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

    def applied(self, page):
        self.wait(lambda: not page.apply_timer.isActive() and not page._edited)

    def test_offline_types_specs_and_legacy_controls_stay_in_sync_in_all_modes(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable', 'robot_stitch'):
            self.bridge._current_mode = mode
            self.win.set_mode(mode, [])
            page = self.page()
            self.assertTrue(page.marker_type.isEnabled())
            self.assertEqual(page.board_spec.count(), 4)
            self.assertEqual(page.circle_n.value(), 8)
            page.marker_type.setCurrentIndex(page.marker_type.findData('asymmetric_grid'))
            page.board_spec.setCurrentIndex(2)
            page.gamma.set_value(1.75)
            self.applied(page)
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
            self.applied(page)
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
            self.assertFalse(page.circle_n.isEnabled())
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
                self.applied(page)
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

    def test_board_configuration_stays_readable_and_applies_in_narrow_panel(self):
        page = self.page()
        page.marker_type.setCurrentIndex(1)
        page.resize(300, 290)
        self.app.processEvents()
        self.assertIn('自动尝试 3 种规格', page.board_details.text())
        self.assertLessEqual(page.gamma.minimumSizeHint().width(), 260)
        self.assertFalse(hasattr(page, 'apply_button'))
        page.board_spec.setCurrentIndex(2)
        page.gamma.set_value(1.8)
        self.applied(page)
        self.assertIn('已自动应用', page.status.text())
        self.assertEqual(self.bridge.recognition.config('multi_cam')['gamma'], 1.8)

    def test_circle_edits_debounce_once_invalidate_cache_and_keep_board_settings(self):
        service = self.bridge.recognition
        before = copy.deepcopy(service.config('multi_cam'))
        page = self.page()
        with patch.object(service, 'configure', wraps=service.configure) as configure:
            page.circle_n.setValue(10)
            page.circle_r1.setValue(3)
            page.circle_r2.setValue(5)
            self.applied(page)
            self.assertEqual(configure.call_count, 1)
        after = service.config('multi_cam')
        self.assertEqual(after['circle'], [10, 3., 5.])
        self.assertNotEqual(frame_recognition.fingerprint(before), frame_recognition.fingerprint(after))
        self.assertEqual(before['boards'], after['boards'])
        page.marker_type.setCurrentIndex(1)
        self.applied(page)
        page.gamma.set_value(1.2)
        self.applied(page)
        self.assertEqual(service.config('multi_cam')['circle'], after['circle'])
        page.marker_type.setCurrentIndex(0)
        self.applied(page)
        self.assertEqual(page.circle_n.value(), 10)

    def test_invalid_circle_is_atomic_and_busy_or_conflicting_edits_do_not_overwrite(self):
        service = self.bridge.recognition
        before = copy.deepcopy(service.config('multi_cam'))
        for circle in ([0, 2, 3], [33, 2, 3], [2.5, 2, 3], [True, 2, 3],
                       [8, float('nan'), 3], [8, 2, float('inf')], [8, 0, 3], [8, 3, 2]):
            with self.assertRaises(ValueError):
                service.configure('multi_cam', 'asymmetric_grid', before['boards'], 1., circle=circle)
            self.assertEqual(service.config('multi_cam'), before)
        page = self.page()
        page.circle_r1.setValue(4)
        page._apply()
        self.assertIn('大于', page.status.text())
        self.assertEqual(service.config('multi_cam'), before)
        page.circle_r2.setValue(6)
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            page._apply()
            self.assertIn('任务进行中', page.status.text())
            self.assertEqual(service.config('multi_cam'), before)
        self.bridge.marker_detector.set_params(12, 2., 4.)
        page._apply()
        self.assertIn('其他入口变化', page.status.text())
        self.assertEqual(service.config('multi_cam')['circle'], [12, 2., 4.])

    def search_frame(self):
        uid = self.db.ingest(self.source())
        frame, _ = self.db.load_frame(uid, 'image')
        self.bridge.frame_db.display_frame('multi_cam', uid, frame, None, 'image')
        return uid

    def test_auto_search_applies_integer_result_and_no_detection_keeps_parameters(self):
        page = self.page()
        page.auto_button.click()
        self.assertIn('没有原始图像', page.status.text())
        self.search_frame()
        outcome = dict(circle=[10, 3, 5], stable_count=3, evaluated=21)
        with patch.object(MarkerDetector, 'search_params', return_value=outcome):
            page.auto_button.click()
            self.wait(lambda: self.bridge.recognition.config('multi_cam')['circle'] == [10, 3., 5.])
            self.wait(lambda: not self.bridge._workers)
        self.assertEqual(page.circle_n.value(), 10)
        before = copy.deepcopy(self.bridge.recognition.config('multi_cam'))
        with patch.object(MarkerDetector, 'search_params', side_effect=ValueError('未稳定检出编码圆')):
            page.auto_button.click()
            self.wait(lambda: not self.bridge._workers)
        self.assertIn('未稳定检出', page.status.text())
        self.assertEqual(self.bridge.recognition.config('multi_cam'), before)

    def test_cancel_or_deleted_source_drops_late_search_results(self):
        page = self.page()
        uid = self.search_frame()
        before = copy.deepcopy(self.bridge.recognition.config('multi_cam'))
        for cancel in (True, False):
            started, release = threading.Event(), threading.Event()
            def search(*args, **kwargs):
                started.set()
                release.wait(3)
                return dict(circle=[16, 3, 5], stable_count=4, evaluated=21)
            with patch.object(MarkerDetector, 'search_params', side_effect=search):
                try:
                    page.auto_button.click()
                    self.assertTrue(started.wait(2))
                    if cancel:
                        page.auto_button.click()
                    else:
                        self.db.remove([uid])
                finally:
                    release.set()
                self.wait(lambda: not self.bridge._workers)
            self.assertEqual(self.bridge.recognition.config('multi_cam'), before)
        self.assertIn('原始帧', page.status.text())

    def test_external_change_during_search_is_not_overwritten(self):
        page = self.page()
        self.search_frame()
        started, release = threading.Event(), threading.Event()
        def search(*args, **kwargs):
            started.set()
            release.wait(3)
            return dict(circle=[16, 3, 5], stable_count=4, evaluated=21)
        with patch.object(MarkerDetector, 'search_params', side_effect=search):
            try:
                page.auto_button.click()
                self.assertTrue(started.wait(2))
                self.bridge.marker_detector.set_params(12, 2., 4.)
            finally:
                release.set()
            self.wait(lambda: not self.bridge._workers)
        self.assertEqual(self.bridge.recognition.config('multi_cam')['circle'], [12, 2., 4.])
        self.assertIn('已变化', page.status.text())

    def test_business_search_uses_displayed_image_instead_of_latest_frame(self):
        self.bridge._current_mode = 'mobile_chain'
        self.win.set_mode('mobile_chain', [])
        first, second = self.source(1), self.source(2)
        presentation = self.win.workspace_mobile()._industrial
        presentation.set_marker_image(first.image_np, [])
        with patch.object(self.bridge.frame_db, '_frames', return_value=[first, second]):
            frame, _ = self.bridge.recognition._search_source('mobile_chain')
        self.assertIs(frame, first)

    def test_hidden_pending_edits_are_discarded_and_narrow_controls_scroll_into_view(self):
        page = self.page()
        page.circle_n.setValue(16)
        props = self.win.workspace_multi()._industrial.frame_browser.properties
        props.tabs.setCurrentIndex(0)
        # Hide explicitly to exercise cancellation without depending on tab order.
        page.hide()
        props.tabs.setCurrentWidget(page)
        page.show()
        self.app.processEvents()
        self.assertEqual(page.circle_n.value(), 8)
        page.resize(280, 140)
        page.scroll.ensureWidgetVisible(page.auto_button)
        self.app.processEvents()
        point = page.auto_button.mapTo(page.scroll.viewport(), QPoint(5, 5))
        self.assertTrue(page.scroll.viewport().rect().contains(point))


if __name__ == '__main__':
    unittest.main()
