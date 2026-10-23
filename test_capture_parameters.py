"""SDK-free parameter I/O and industrial page regression."""
import copy
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.camera_manager import CameraManager, SingleCameraController
from core.capture_parameters import FIELDS
import test_ui_frame_database as fixture
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_ui_setting_wheel import wheel


def rich_camera(kind='X1'):
    from core.camera_manager import RVC
    controller = fake_camera(kind)
    controller.device_info = SimpleNamespace(support_capture_mode=63, support_color=15)
    controller.camera.GetGammaRange.return_value = (True, .1, 4.)
    def load():
        values = dict(exposure_time_2d=11, exposure_time_3d=20, gain_2d=.25, gain_3d=1.5,
                      gamma_2d=1., gamma_3d=1.2, scan_times=2, projector_brightness=240,
                      use_projector_capturing_2d_image=True, hdr_exposure_times=0,
                      capture_mode=RVC.CaptureMode_Normal, custom_filter=42)
        if kind == 'X2':
            values.update(projector_color=RVC.ProjectorColor_Blue, correspond2d=True)
        return True, SimpleNamespace(**values)
    controller.camera.LoadCaptureOptionParameters.side_effect = load
    return controller


def fake_camera(kind='X1'):
    controller = SingleCameraController('cam0')
    controller.camera_type = kind
    controller.is_connected = True
    options = SimpleNamespace(exposure_time_2d=11, exposure_time_3d=20,
                              gain_2d=0.25, gain_3d=1.5, projector_brightness=240,
                              hdr_exposure_times=2, custom_filter=42)
    controller.current_options = copy.deepcopy(options)
    controller.camera = Mock()
    controller.camera.LoadCaptureOptionParameters.side_effect = lambda: (True, copy.deepcopy(options))
    controller.camera.GetExposureTimeRange.return_value = (True, 3, 100)
    controller.camera.GetGainRange.return_value = (True, 0., 12.)
    controller.camera.SaveCaptureOptionParameters.return_value = True
    return controller


class ServiceTests(unittest.TestCase):
    def test_extended_fields_and_supported_choices_are_model_specific(self):
        from core.capture_parameters import read, apply
        from core.camera_manager import RVC
        for kind in ('X1', 'X2'):
            camera = rich_camera(kind)
            snapshot = read(camera)
            self.assertIn('gamma_2d', snapshot['values'])
            self.assertNotIn('scan_times', snapshot['values'])
            self.assertNotIn('gamma_3d', snapshot['values'])
            self.assertEqual('projector_color' in snapshot['choices'], kind == 'X2')
            values = dict(snapshot['values'], gamma_2d=2.5,
                          use_projector_capturing_2d_image=False,
                          capture_mode=int(RVC.CaptureMode_SwingLineScan))
            apply(camera, values)
            self.assertTrue(camera.line_scan_detected)
            self.assertEqual(camera.current_options.gamma_2d, 2.5)
            self.assertEqual(camera.current_options.gamma_3d, 1.2)
            self.assertEqual(camera.current_options.scan_times, 2)
            self.assertEqual(camera.current_options.custom_filter, 42)
            self.assertIs(camera.current_options.use_projector_capturing_2d_image, False)
            for changes in ({'gamma_2d': 5},
                            {'use_projector_capturing_2d_image': 1}, {'capture_mode': 64}):
                with self.assertRaises(ValueError):
                    apply(camera, dict(values, **changes))
            camera.camera.GetGammaRange.return_value = (False, 0, 0)
            self.assertNotIn('gamma_2d', read(camera)['values'])

    def test_installed_sdk_option_types_without_initializing_hardware(self):
        from core.camera_manager import RVC
        from core.capture_parameters import read, apply
        with patch.object(RVC, 'SystemInit', side_effect=AssertionError('hardware init forbidden')):
            for kind in ('X1', 'X2'):
                camera = rich_camera(kind)
                factory = getattr(RVC, kind + '_CaptureOptions')
                camera.camera.LoadCaptureOptionParameters.side_effect = lambda: (True, factory())
                snapshot = read(camera)
                original_scan_times = factory().scan_times
                original_gamma_3d = factory().gamma_3d
                apply(camera, dict(snapshot['values'], gamma_2d=1.125))
                self.assertIsInstance(camera.current_options, factory)
                self.assertEqual(camera.current_options.scan_times, original_scan_times)
                self.assertEqual(camera.current_options.gamma_3d, original_gamma_3d)
                self.assertEqual(camera.current_options.gamma_2d, 1.125)
    def test_disconnect_waits_for_parameter_sdk_operation(self):
        camera = fake_camera()
        entered, release = threading.Event(), threading.Event()
        original = camera.camera.LoadCaptureOptionParameters.side_effect
        def load():
            entered.set()
            release.wait(3)
            return original()
        camera.camera.LoadCaptureOptionParameters.side_effect = load
        from core.capture_parameters import read
        reader = threading.Thread(target=lambda: read(camera))
        closer = threading.Thread(target=camera.disconnect)
        with patch('core.camera_manager.RVC', Mock()):
            reader.start()
            try:
                self.assertTrue(entered.wait(2))
                closer.start()
                closer.join(.05)
                self.assertTrue(closer.is_alive())
                camera.camera.Close.assert_not_called()
            finally:
                release.set()
                reader.join(3)
                if closer.ident is not None:
                    closer.join(3)
        self.assertFalse(camera.is_connected)

    def test_x1_x2_preserve_other_settings_and_convert_types(self):
        for kind in ('X1', 'X2'):
            manager = CameraManager()
            camera = fake_camera(kind)
            manager._cameras['cam0'] = camera
            snapshot = manager.common_capture_parameters('cam0')
            self.assertEqual(snapshot['camera_type'], kind)
            self.assertEqual(set(snapshot['values']), set(FIELDS))
            values = dict(snapshot['values'], exposure_time_2d=25, gain_3d=2.125)
            result = manager.common_capture_parameters('cam0', values)
            saved = camera.camera.SaveCaptureOptionParameters.call_args.args[0]
            self.assertIs(type(saved.exposure_time_2d), int)
            self.assertIs(type(saved.gain_3d), float)
            self.assertEqual(saved.custom_filter, 42)
            self.assertEqual(saved.hdr_exposure_times, 2)
            self.assertEqual(result['values'], values)
            self.assertIs(camera.current_options, saved)

    def test_failure_does_not_mutate_cached_options(self):
        camera = fake_camera()
        from core.capture_parameters import read, apply
        values = read(camera)['values']
        original = camera.current_options
        camera.camera.SaveCaptureOptionParameters.return_value = False
        with self.assertRaisesRegex(RuntimeError, '拒绝'):
            apply(camera, dict(values, exposure_time_2d=30))
        self.assertIs(camera.current_options, original)
        self.assertEqual(original.exposure_time_2d, 11)

    def test_invalid_values_ranges_and_disconnected_never_write(self):
        camera = fake_camera()
        from core.capture_parameters import read, apply
        values = read(camera)['values']
        for changes in ({'gain_2d': float('nan')}, {'exposure_time_3d': 2},
                        {'exposure_time_2d': 11.5}, {'projector_brightness': 241}, {'projector_brightness': -1}):
            with self.assertRaises(ValueError):
                apply(camera, dict(values, **changes))
        camera.camera.GetGainRange.return_value = (False, 0, 0)
        with self.assertRaises(RuntimeError):
            read(camera)
        camera.is_connected = False
        with self.assertRaises(RuntimeError):
            apply(camera, values)
        camera.camera.SaveCaptureOptionParameters.assert_not_called()

    def test_sdk_exception_missing_camera_and_failed_read(self):
        manager = CameraManager()
        with self.assertRaises(RuntimeError):
            manager.common_capture_parameters('missing')
        camera = fake_camera()
        manager._cameras['cam0'] = camera
        camera.camera.LoadCaptureOptionParameters.return_value = (False, None)
        camera.camera.LoadCaptureOptionParameters.side_effect = None
        with self.assertRaisesRegex(RuntimeError, '读取'):
            manager.common_capture_parameters('cam0')
        camera.camera.LoadCaptureOptionParameters.side_effect = RuntimeError('SDK failure')
        with self.assertRaisesRegex(RuntimeError, 'SDK failure'):
            manager.common_capture_parameters('cam0')
        camera.camera.SaveCaptureOptionParameters.assert_not_called()

    def test_replaced_target_is_rejected_before_any_sdk_access(self):
        manager = CameraManager()
        manager._cameras['cam0'] = fake_camera()
        source = manager.capture_parameter_source('cam0')
        replacement = fake_camera()
        manager._cameras['cam0'] = replacement
        with self.assertRaisesRegex(RuntimeError, '更换'):
            manager.common_capture_parameters('cam0', expected_source=source)
        replacement.camera.LoadCaptureOptionParameters.assert_not_called()


class PageTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait

    def page(self):
        return self.win._stack.currentWidget()._industrial.frame_browser.properties.capture

    def open_page(self):
        self.win._stack.currentWidget()._industrial.frame_browser.properties.tabs.setCurrentIndex(2)
        self.page().refresh()

    def test_multicam_selected_target_reads_and_writes_independently(self):
        manager = self.bridge.camera_manager
        states, cameras = {}, {}
        for camera_id, exposure in (('cam0', 11), ('cam1', 33)):
            camera = rich_camera('X2')
            _, options = camera.camera.LoadCaptureOptionParameters()
            state = vars(options).copy()
            state['exposure_time_2d'] = exposure
            def save(options, state=state):
                state.update(vars(options))
                return True
            camera.camera.LoadCaptureOptionParameters.side_effect = lambda state=state: (True, SimpleNamespace(**state))
            camera.camera.SaveCaptureOptionParameters.side_effect = save
            states[camera_id], cameras[camera_id] = state, camera
            manager._cameras[camera_id] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        self.assertEqual(page.camera.count(), 2)
        self.assertTrue(page.camera.isEnabled())
        self.assertNotIn('gamma_3d', page.controls)
        self.assertNotIn('scan_times', page.controls)
        page.controls['exposure_time_2d'].setValue(21)
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(states['cam0']['exposure_time_2d'], 21)
        cameras['cam1'].camera.SaveCaptureOptionParameters.assert_not_called()
        page.camera.setCurrentText('cam1')
        page.refresh()
        self.wait(lambda: page._loaded == 'cam1' and not self.bridge._workers)
        self.assertEqual(page.controls['exposure_time_2d'].value(), 33)
        self.assertFalse(hasattr(page, 'apply_button'))
        page.controls['exposure_time_2d'].setValue(44)
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(states['cam1']['exposure_time_2d'], 44)
        self.assertEqual(states['cam0']['exposure_time_2d'], 21)
        self.assertEqual(cameras['cam0'].camera.SaveCaptureOptionParameters.call_count, 1)
        page.camera.setCurrentText('cam0')
        page.refresh()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        self.assertEqual(page.controls['exposure_time_2d'].value(), 21)
        manager._cameras.clear()

    def test_automatically_read_on_open_switch_and_reconnect_but_never_write(self):
        manager = self.bridge.camera_manager
        camera = rich_camera()
        manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        self.assertEqual(page.controls['exposure_time_2d'].value(), 11)
        self.assertEqual(page.controls['gamma_2d'].value(), 1.)
        self.assertTrue(page.rows['gamma_2d'][0].isRowVisible(page.rows['gamma_2d'][1]))
        self.assertFalse(page.rows['correspond2d'][0].isRowVisible(page.rows['correspond2d'][1]))
        page.controls['exposure_time_2d'].setValue(30)
        count = camera.camera.LoadCaptureOptionParameters.call_count
        page.refresh()
        self.assertEqual(camera.camera.LoadCaptureOptionParameters.call_count, count)
        self.assertEqual(page.controls['exposure_time_2d'].value(), 30)
        manager._cameras['cam1'] = rich_camera('X2')
        page.refresh()
        self.assertEqual(page.controls['exposure_time_2d'].value(), 30)
        page.camera.setCurrentText('cam1')
        page.refresh()
        self.wait(lambda: page._loaded == 'cam1' and not self.bridge._workers)
        self.assertTrue(page.rows['correspond2d'][0].isRowVisible(page.rows['correspond2d'][1]))
        replacement = rich_camera('X2')
        manager._cameras['cam1'] = replacement
        page.refresh()
        self.wait(lambda: page._loaded == 'cam1' and not self.bridge._workers)
        self.assertEqual(replacement.camera.LoadCaptureOptionParameters.call_count, 1)
        for controller in manager._cameras.values():
            controller.camera.SaveCaptureOptionParameters.assert_not_called()
        manager._cameras.clear()

    def test_auto_read_waits_for_idle_and_does_not_retry_failure_continuously(self):
        camera = rich_camera()
        self.bridge.camera_manager._cameras['cam0'] = camera
        camera.camera.LoadCaptureOptionParameters.side_effect = RuntimeError('failed')
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            self.open_page()
            self.assertTrue(self.page()._auto_needed)
            camera.camera.LoadCaptureOptionParameters.assert_not_called()
        self.page().refresh()
        self.wait(lambda: not self.page()._pending and not self.bridge._workers)
        self.page().refresh()
        self.page().refresh()
        self.assertEqual(camera.camera.LoadCaptureOptionParameters.call_count, 1)
        self.assertIn('failed', self.page().status.text())
        self.assertFalse(self.page().controls['exposure_time_2d'].isEnabled())
        self.bridge.camera_manager._cameras.clear()

    def test_sliders_exact_input_and_wheel_protection_do_not_write(self):
        camera = rich_camera()
        self.bridge.camera_manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        exposure = page.sliders['exposure_time_2d']
        exposure.slider.setValue(exposure.slider.maximum())
        self.assertEqual(exposure.spin.value(), 100)
        exposure.spin.setValue(11)
        expected = round((11-3)/97 * exposure.slider.maximum())
        self.assertEqual(exposure.slider.value(), expected)
        gamma = page.sliders['gamma_2d']
        gamma.spin.setValue(1.375)
        self.assertAlmostEqual(gamma.spin.value(), 1.375)
        QTest.keyClick(exposure.slider, Qt.Key_Right)
        self.assertEqual(exposure.spin.value(), 12)
        for control in (exposure.slider, exposure.spin, gamma.slider):
            before = exposure.spin.value(), gamma.spin.value()
            wheel(control)
            self.assertEqual((exposure.spin.value(), gamma.spin.value()), before)
        camera.camera.SaveCaptureOptionParameters.assert_not_called()
        self.bridge.camera_manager._cameras.clear()

    def test_stale_callback_is_discarded_and_status_stays_visible_when_scrolled(self):
        manager = self.bridge.camera_manager
        manager._cameras['cam0'] = rich_camera()
        replies = []
        def queued(camera_id, values, done):
            replies.append((manager.common_capture_parameters(camera_id), done))
        with patch.object(self.bridge, 'capture_parameters', side_effect=queued):
            self.open_page()
            page = self.page()
            self.assertEqual(len(replies), 1)
            manager._cameras['cam0'] = rich_camera('X2')
            page.refresh()
            snapshot, done = replies[0]
            done(snapshot, None)
            self.assertIsNone(page._loaded)
            page.refresh()
            self.assertEqual(len(replies), 2)
            snapshot, done = replies[1]
            done(snapshot, None)
            self.assertEqual(page._loaded, 'cam0')
            self.app.processEvents()
            self.assertGreater(page.scroll.verticalScrollBar().maximum(), 0)
            page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum())
            self.assertLessEqual(page.status.geometry().bottom(), page.height())
            self.assertTrue(page.status.isVisible())
        manager._cameras.clear()

    def test_all_modes_have_shared_offline_page_and_no_sdk_access(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.win.set_mode(mode, [])
            page = self.page()
            page.refresh()
            properties = self.win._stack.currentWidget()._industrial.frame_browser.properties
            self.assertEqual(properties.tabs.tabText(2), '拍摄参数')
            self.assertFalse(page.read_button.isEnabled())
            self.assertFalse(page.controls['exposure_time_2d'].isEnabled())
            self.assertFalse(page.camera.isEnabled())
            for group, _ in page.groups.values():
                self.assertFalse(group.isHidden())
            for key, (form, row) in page.rows.items():
                self.assertTrue(form.isRowVisible(row))
                self.assertFalse(row.isEnabled())
                if key in page.sliders:
                    self.assertEqual(page.controls[key].text(), '—')
                else:
                    self.assertEqual(page.controls[key].currentText(), '待读取')
        reply = Mock()
        self.bridge.capture_parameters('cam0', None, reply)
        self.assertIn('断开', reply.call_args.args[1])

    def test_disconnect_restores_visible_disabled_placeholders_and_reconnect_reads(self):
        manager = self.bridge.camera_manager
        camera = rich_camera('X2')
        manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        self.assertEqual(page.controls['exposure_time_2d'].text(), '11 ms')
        self.assertEqual(page.controls['use_projector_capturing_2d_image'].currentData(), True)
        manager._cameras.clear()
        page.refresh()
        for key, (form, row) in page.rows.items():
            self.assertTrue(form.isRowVisible(row))
            self.assertFalse(row.isEnabled())
        self.assertEqual(page.controls['exposure_time_2d'].text(), '—')
        self.assertFalse(page.camera.isEnabled())
        manager._cameras['cam0'] = camera
        page.refresh()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        self.assertEqual(page.controls['exposure_time_2d'].text(), '11 ms')
        self.assertEqual(page.controls['use_projector_capturing_2d_image'].currentData(), True)
        camera.camera.SaveCaptureOptionParameters.assert_not_called()
        manager._cameras.clear()

    def test_read_apply_fail_disconnect_and_busy_without_db_side_effects(self):
        camera = fake_camera()
        camera.camera.LoadCaptureOptionParameters.side_effect = lambda: (True, SimpleNamespace(
            exposure_time_2d=11, exposure_time_3d=20, gain_2d=0.1234567,
            gain_3d=1.5, projector_brightness=240, hdr_exposure_times=2, custom_filter=42))
        self.bridge.camera_manager._cameras['cam0'] = camera
        page = self.page()
        page.refresh()
        self.assertFalse(page.controls['exposure_time_2d'].isEnabled())
        with patch.object(self.bridge.projects, 'prepare', side_effect=AssertionError('project mutated')), \
                patch.object(self.bridge.frame_db, 'restore', side_effect=AssertionError('DB restored')), \
                patch.object(self.bridge.frame_db, 'archive_context', side_effect=AssertionError('DB archived')), \
                patch.object(self.bridge.frame_db, 'synchronize', side_effect=AssertionError('DB synchronized')):
            page.read_button.click()
            self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
            page.refresh()
            self.assertEqual(page.controls['exposure_time_2d'].value(), 11)
            self.assertTrue(page.controls['exposure_time_2d'].isEnabled())
            self.assertIn('HDR', page.status.text())
            page.controls['exposure_time_2d'].setValue(25)
            self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
            self.assertEqual(camera.current_options.exposure_time_2d, 25)
            self.assertEqual(camera.current_options.gain_2d, 0.1234567)
            camera.camera.SaveCaptureOptionParameters.return_value = False
            page.refresh()
            page.controls['exposure_time_2d'].setValue(26)
            self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
            self.assertIn('拒绝', page.status.text())
            self.assertEqual(camera.current_options.exposure_time_2d, 25)
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            page.refresh()
            self.assertFalse(page.controls['exposure_time_2d'].isEnabled())
            result = Mock()
            self.bridge.capture_parameters('cam0', None, result)
            self.assertIn('进行中', result.call_args.args[1])
        self.bridge.camera_manager._cameras.clear()
        page.refresh()
        self.assertIsNone(page._loaded)
        self.assertFalse(page.read_button.isEnabled())

    def test_camera_switch_requires_read_and_failed_read_restores_buttons(self):
        manager = self.bridge.camera_manager
        manager._cameras['cam0'] = fake_camera()
        manager._cameras['cam1'] = fake_camera('X2')
        page = self.page()
        page.refresh()
        page.read_button.click()
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        page.camera.setCurrentText('cam1')
        self.assertIsNone(page._loaded)
        self.assertFalse(page.controls['exposure_time_2d'].isEnabled())
        manager._cameras['cam1'].camera.LoadCaptureOptionParameters.side_effect = RuntimeError('read failed')
        page.refresh()
        page.read_button.click()
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        page.refresh()
        self.assertIn('read failed', page.status.text())
        self.assertTrue(page.read_button.isEnabled())
        self.assertFalse(page.controls['exposure_time_2d'].isEnabled())
        manager._cameras['cam1'].camera.SaveCaptureOptionParameters.assert_not_called()
        manager._cameras.clear()

    def test_auto_changes_coalesce_and_next_preview_uses_latest_options(self):
        camera = rich_camera()
        camera.camera.GetImage.return_value = fixture.np.zeros((2, 2, 3), fixture.np.uint8)
        self.bridge.camera_manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        for exposure in (20, 21, 22, 23):
            page.controls['exposure_time_2d'].setValue(exposure)
        self.assertFalse(hasattr(page, 'apply_button'))
        camera.camera.SaveCaptureOptionParameters.assert_not_called()
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(camera.camera.SaveCaptureOptionParameters.call_count, 1)
        _, message = camera.capture_2d()
        self.assertEqual(message, 'success')
        options = camera.camera.Capture2D.call_args.args[0]
        self.assertEqual(options.exposure_time_2d, 23)
        self.assertIn('实时生效', page.status.text())
        self.bridge.camera_manager._cameras.clear()

    def test_edits_during_inflight_write_keep_latest_values_and_follow_up_once(self):
        camera = rich_camera()
        self.bridge.camera_manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        replies = []
        def queued(camera_id, values, done):
            snapshot = dict(values=dict(values), ranges=dict(page._ranges), choices={}, hdr=0)
            replies.append((snapshot, done))
        with patch.object(self.bridge, 'capture_parameters', side_effect=queued):
            page.controls['exposure_time_2d'].setValue(20)
            self.wait(lambda: len(replies) == 1)
            self.assertTrue(page.controls['exposure_time_2d'].isEnabled())
            page.controls['exposure_time_2d'].setValue(31)
            page.controls['exposure_time_2d'].setValue(32)
            snapshot, done = replies[0]
            done(snapshot, None)
            self.assertEqual(page.controls['exposure_time_2d'].value(), 32)
            self.wait(lambda: len(replies) == 2)
            snapshot, done = replies[1]
            self.assertEqual(snapshot['values']['exposure_time_2d'], 32)
            done(snapshot, None)
            QTest.qWait(350)
            self.assertEqual(len(replies), 2)
            self.assertFalse(page._dirty)
        self.bridge.camera_manager._cameras.clear()

    def test_failed_auto_write_does_not_loop_and_new_edit_can_retry(self):
        camera = rich_camera()
        self.bridge.camera_manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        camera.camera.SaveCaptureOptionParameters.return_value = False
        page.controls['exposure_time_2d'].setValue(20)
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        QTest.qWait(650)
        self.assertEqual(camera.camera.SaveCaptureOptionParameters.call_count, 1)
        self.assertEqual(camera.current_options.exposure_time_2d, 11)
        camera.camera.SaveCaptureOptionParameters.return_value = True
        page.controls['exposure_time_2d'].setValue(21)
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(camera.current_options.exposure_time_2d, 21)
        self.bridge.camera_manager._cameras.clear()

    def test_pending_edit_is_cancelled_on_target_change_and_brightness_is_limited(self):
        manager = self.bridge.camera_manager
        first, second = rich_camera(), rich_camera('X2')
        manager._cameras.update(cam0=first, cam1=second)
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        page.controls['exposure_time_2d'].setValue(50)
        page.camera.setCurrentText('cam1')
        page.refresh()
        self.wait(lambda: page._loaded == 'cam1' and not self.bridge._workers)
        QTest.qWait(350)
        first.camera.SaveCaptureOptionParameters.assert_not_called()
        second.camera.SaveCaptureOptionParameters.assert_not_called()
        control = page.controls['projector_brightness']
        self.assertEqual((control.minimum(), control.maximum()), (0, 240))
        control.setValue(255)
        self.assertEqual(control.value(), 240)
        control.setValue(0)
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(second.current_options.projector_brightness, 0)
        manager._cameras.clear()

    def test_outdated_saved_brightness_is_corrected_on_next_edit_without_resending_255(self):
        camera = fake_camera()
        original = camera.camera.LoadCaptureOptionParameters.side_effect
        def load():
            ok, options = original()
            options.projector_brightness = 255
            return ok, options
        camera.camera.LoadCaptureOptionParameters.side_effect = load
        self.bridge.camera_manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        self.assertEqual(page.controls['projector_brightness'].value(), 240)
        camera.camera.SaveCaptureOptionParameters.assert_not_called()
        page.controls['exposure_time_2d'].setValue(20)
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(camera.current_options.projector_brightness, 240)
        self.bridge.camera_manager._cameras.clear()

    def test_fractional_sdk_bounds_are_rounded_inward_and_busy_edits_wait(self):
        camera = rich_camera()
        camera.camera.GetGainRange.return_value = (True, .123456, .987654)
        self.bridge.camera_manager._cameras['cam0'] = camera
        self.open_page()
        page = self.page()
        self.wait(lambda: page._loaded == 'cam0' and not self.bridge._workers)
        gain = page.controls['gain_2d']
        self.assertGreaterEqual(gain.minimum(), .123456)
        self.assertLessEqual(gain.maximum(), .987654)
        gain.setValue(gain.maximum())
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            QTest.qWait(600)
            camera.camera.SaveCaptureOptionParameters.assert_not_called()
        self.wait(lambda: not page._dirty and not page._pending and not self.bridge._workers)
        self.assertEqual(camera.current_options.gain_2d, .987)
        self.bridge.camera_manager._cameras.clear()


if __name__ == '__main__':
    unittest.main()
