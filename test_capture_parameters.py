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
                        {'exposure_time_2d': 11.5}, {'projector_brightness': 256}):
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


class PageTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    wait = fixture.FrameBrowserTests.wait

    def page(self):
        return self.win._stack.currentWidget()._industrial.frame_browser.properties.capture

    def test_all_modes_have_shared_offline_page_and_no_sdk_access(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.win.set_mode(mode, [])
            page = self.page()
            page.refresh()
            properties = self.win._stack.currentWidget()._industrial.frame_browser.properties
            self.assertEqual(properties.tabs.tabText(2), '拍摄参数')
            self.assertFalse(page.read_button.isEnabled())
            self.assertFalse(page.apply_button.isEnabled())

    def test_read_apply_fail_disconnect_and_busy_without_db_side_effects(self):
        camera = fake_camera()
        camera.camera.LoadCaptureOptionParameters.side_effect = lambda: (True, SimpleNamespace(
            exposure_time_2d=11, exposure_time_3d=20, gain_2d=0.1234567,
            gain_3d=1.5, projector_brightness=240, hdr_exposure_times=2, custom_filter=42))
        self.bridge.camera_manager._cameras['cam0'] = camera
        page = self.page()
        page.refresh()
        self.assertFalse(page.apply_button.isEnabled())
        with patch.object(self.bridge.projects, 'prepare', side_effect=AssertionError('project mutated')), \
                patch.object(self.bridge.frame_db, 'restore', side_effect=AssertionError('DB restored')), \
                patch.object(self.bridge.frame_db, 'archive_context', side_effect=AssertionError('DB archived')), \
                patch.object(self.bridge.frame_db, 'synchronize', side_effect=AssertionError('DB synchronized')):
            page.read_button.click()
            self.wait(lambda: not page._pending and not self.bridge._workers)
            page.refresh()
            self.assertEqual(page.controls['exposure_time_2d'].value(), 11)
            self.assertTrue(page.apply_button.isEnabled())
            self.assertIn('HDR', page.status.text())
            page.controls['exposure_time_2d'].setValue(25)
            page.apply_button.click()
            self.wait(lambda: not page._pending and not self.bridge._workers)
            self.assertEqual(camera.current_options.exposure_time_2d, 25)
            self.assertEqual(camera.current_options.gain_2d, 0.1234567)
            camera.camera.SaveCaptureOptionParameters.return_value = False
            page.refresh()
            page.apply_button.click()
            self.wait(lambda: not page._pending and not self.bridge._workers)
            self.assertIn('拒绝', page.status.text())
            self.assertEqual(camera.current_options.exposure_time_2d, 25)
        with patch.object(self.bridge, 'can_change_workspace', return_value=False):
            page.refresh()
            self.assertFalse(page.apply_button.isEnabled())
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
        self.wait(lambda: not page._pending and not self.bridge._workers)
        page.camera.setCurrentText('cam1')
        self.assertIsNone(page._loaded)
        self.assertFalse(page.apply_button.isEnabled())
        manager._cameras['cam1'].camera.LoadCaptureOptionParameters.side_effect = RuntimeError('read failed')
        page.refresh()
        page.read_button.click()
        self.wait(lambda: not page._pending and not self.bridge._workers)
        page.refresh()
        self.assertIn('read failed', page.status.text())
        self.assertTrue(page.read_button.isEnabled())
        self.assertFalse(page.apply_button.isEnabled())
        manager._cameras['cam1'].camera.SaveCaptureOptionParameters.assert_not_called()
        manager._cameras.clear()


if __name__ == '__main__':
    unittest.main()
