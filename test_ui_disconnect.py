"""Shared ribbon disconnect lifecycle, retained data and no SDK initialization."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_ui_frame_database as fixture
from PySide6.QtCore import QThread, Signal, QSignalBlocker
from PySide6.QtGui import QPixmap, QColor
from ui_v2.widgets.device_table import DeviceInfo


class Camera:
    def __init__(self, serial, calls):
        self.sn = serial
        self.device_info = SimpleNamespace(name='TEST', sn=serial)
        self.is_connected = True
        self.calls = calls

    def disconnect(self):
        self.calls.append(threading.get_ident())
        self.is_connected = False


class Preview(QThread):
    frame_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.entered = threading.Event()
        self.request_stop = Mock()

    def run(self):
        self.entered.set()
        self.release.wait(5)


class DisconnectTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    source = fixture.FrameBrowserTests.source
    wait = fixture.FrameBrowserTests.wait

    def connect_fake(self, count=1):
        self.calls = []
        self.bridge._current_mode = self.win.current_mode()
        self.bridge.camera_manager._cameras = {
            f'cam{i}': Camera(f'MOCK{i}', self.calls) for i in range(count)}
        devices = [DeviceInfo(serial=f'MOCK{i}', backend_ref=i) for i in range(count)]
        self.win.set_mode(self.win.current_mode(), devices)
        self.win._industrial_ribbon.update_status()

    def finish(self):
        self.wait(lambda: not self.bridge._disconnecting and not any(w.isRunning() for w in self.bridge._workers))

    def test_ribbon_devices_disconnect_and_postprocess_are_commands_in_all_modes(self):
        ribbon = self.win._industrial_ribbon
        self.assertFalse(hasattr(ribbon, 'postprocess_button'))
        for mode in ribbon._pages:
            self.assertEqual(ribbon.commands[mode, 'disconnect'].text(), '断开连接')
            self.assertEqual(ribbon.commands[mode, 'postprocess'].text(), '点云后处理')
            self.assertFalse(ribbon.commands[mode, 'postprocess'].property('headerAction'))
            with patch.object(self.bridge, 'open_postprocess') as opened:
                ribbon.commands[mode, 'postprocess'].click()
                opened.assert_called_once()
            self.assertFalse(ribbon.commands[mode, 'disconnect'].isEnabled())

    def test_disconnect_from_toolbar_runs_off_ui_and_preserves_db_views_and_workflows(self):
        self.connect_fake(2)
        uid = self.db.ingest(self.source())
        before = (self.db.directory/'index.json').read_bytes()
        geometry = self.db.directory/'frames'/uid/'pointmap.ply'
        raw = geometry.read_bytes()
        self.win.workspace_multi().set_state('captured')
        states = [self.win.workspace_multi().current_state(), self.win.workspace_mobile().current_state()]
        turn = self.win.workspace_turntable()
        turn.current_frame0 = self.source(5)
        previous_turn = turn.current_frame0
        node = self.source(6)
        self.bridge.fixed_workflow.frames_calib['cam0'] = node
        # Disconnect is a device-only background task, never a project/DB edit.
        with patch.object(self.bridge.projects, 'prepare', side_effect=AssertionError('no prepare')), \
             patch.object(self.bridge.frame_db, 'restore', side_effect=AssertionError('no restore')), \
             patch.object(self.bridge.frame_db, 'synchronize', side_effect=AssertionError('no sync')):
            self.win._industrial_ribbon.commands['multi_cam','disconnect'].click()
            self.finish()
        self.assertEqual(self.bridge.camera_manager.get_connected_ids(), [])
        self.assertEqual(len(self.calls),2)
        self.assertTrue(all(tid != threading.get_ident() for tid in self.calls))
        self.assertEqual((self.db.directory/'index.json').read_bytes(), before)
        self.assertEqual(geometry.read_bytes(), raw)
        self.assertIs(self.bridge.fixed_workflow.frames_calib['cam0'], node)
        self.assertIs(turn.current_frame0, previous_turn)
        self.assertEqual(self.win.workspace_multi().current_state(), states[0])
        self.assertFalse(self.win.workspace_multi()._btn_capture.isEnabled())
        self.assertFalse(self.win._devices)
        self.assertIn('0/0', self.win._st_devices.text())
        self.assertFalse(self.win._industrial_ribbon.commands['multi_cam','disconnect'].isEnabled())
        self.assertTrue(self.win._industrial_ribbon.commands['multi_cam','postprocess'].isEnabled())
        self.bridge.fixed_workflow.frames_calib.clear()

    def test_inflight_preview_waits_without_blocking_gui_and_late_frames_are_ignored(self):
        self.win.set_mode('mobile_chain', [])
        self.connect_fake()
        preview = Preview()
        preview.start()
        self.assertTrue(preview.entered.wait(2))
        self.bridge._preview_thread = preview
        self.bridge._preview_camera_id = 'cam0'
        with QSignalBlocker(self.win.workspace_mobile()._btn_preview):
            self.win.workspace_mobile().set_preview_enabled(True)
        pixmap = QPixmap(16,16);pixmap.fill(QColor('red'))
        self.win.workspace_mobile().live_view().set_frame(pixmap)
        try:
            self.assertTrue(self.bridge.disconnect_devices())
            preview.request_stop.assert_called_once()
            self.app.processEvents()
            self.assertFalse(self.calls)
            self.assertTrue(self.bridge._disconnecting)
            self.assertIsNone(self.bridge._preview_thread)
            late = QPixmap(16,16);late.fill(QColor('blue'))
            self.bridge._on_preview_frame(late,source=preview)
            self.assertEqual(self.win.workspace_mobile().live_view()._current_pixmap.cacheKey(), pixmap.cacheKey())
            self.assertFalse(self.bridge.disconnect_devices())
            self.assertFalse(self.win._industrial_ribbon.commands['mobile_chain','disconnect'].isEnabled())
        finally:
            preview.release.set()
        self.finish()
        self.assertEqual(len(self.calls),1)
        self.assertFalse(self.win.workspace_mobile().is_preview_enabled())

    def test_busy_and_offline_requests_do_not_disconnect_or_initialize_sdk(self):
        with patch.object(self.bridge.camera_manager, 'disconnect_all') as disconnect, \
             patch.object(self.bridge, '_ensure_sdk', side_effect=AssertionError('no SDK')):
            self.assertFalse(self.bridge.disconnect_devices())
            self.connect_fake()
            with patch.object(self.bridge, 'can_change_workspace', return_value=False):
                self.assertFalse(self.bridge.disconnect_devices())
            self.win.workspace_turntable()._busy = True
            self.assertFalse(self.bridge.disconnect_devices())
            self.win.workspace_turntable()._busy = False
            disconnect.assert_not_called()

    def test_partial_failure_keeps_online_devices_retryable(self):
        self.connect_fake(2)
        def fail():
            self.bridge.camera_manager._cameras['cam0'].disconnect()
            raise OSError('close failed')
        with patch.object(self.bridge.camera_manager, 'disconnect_all', side_effect=fail):
            self.assertTrue(self.bridge.disconnect_devices())
            self.finish()
        self.assertEqual(self.bridge.camera_manager.get_connected_ids(), ['cam1'])
        self.assertEqual([d.serial for d in self.win._devices], ['MOCK1'])
        self.assertTrue(self.win._industrial_ribbon.commands['multi_cam','disconnect'].isEnabled())
        self.assertTrue(self.bridge.disconnect_devices())
        self.finish()
        self.assertFalse(self.bridge.camera_manager.get_connected_ids())

    def test_parameter_debug_uses_safe_disconnect_and_launches_only_after_release(self):
        self.connect_fake()
        with patch.object(self.bridge, '_launch_param_debug') as launch:
            self.bridge._on_param_debug()
            self.finish()
            launch.assert_called_once()
            self.assertFalse(self.bridge.camera_manager.get_connected_ids())
        self.connect_fake()
        with patch.object(self.bridge.camera_manager, 'disconnect_all', side_effect=OSError('failure')), \
             patch.object(self.bridge, '_launch_param_debug') as launch:
            self.bridge._on_param_debug();self.finish()
            launch.assert_not_called()

    def test_reconnect_attempt_is_rejected_during_disconnect_before_sdk_init(self):
        self.bridge._disconnecting = True
        try:
            with patch.object(self.bridge,'_ensure_sdk',side_effect=AssertionError('no SDK')):
                self.bridge.connect_devices('multi_cam',[])
        finally:
            self.bridge._disconnecting = False

    def test_multicamera_card_preview_stops_and_cards_are_retained(self):
        self.connect_fake(2)
        cards = dict(self.win.workspace_multi()._camera_grid._cards)
        self.bridge._on_card_preview_toggled('cam0', True)
        self.assertTrue(self.bridge._card_preview_timer.isActive())
        with patch.object(self.bridge.camera_manager, 'capture_2d_preview',
                          side_effect=AssertionError('preview after disconnect')):
            self.assertTrue(self.bridge.disconnect_devices())
            self.finish()
        self.assertFalse(self.bridge._card_preview_timer.isActive())
        self.assertFalse(self.bridge._card_preview_active)
        self.assertEqual(self.win.workspace_multi()._camera_grid._cards, cards)

    def test_robot_disconnect_retains_handeye_and_disables_capture(self):
        import numpy as np
        from core.robot_handeye import HandEyeResult
        self.win.set_mode('robot_stitch', [])
        self.connect_fake()
        robot = self.win.workspace_robot()
        matrix = np.eye(4)
        matrix[:3, 3] = [20, -10, 120]
        ok, message, handeye = HandEyeResult.from_matrix(matrix, 'mm', True)
        self.assertTrue(ok, message)
        self.assertTrue(robot.load_handeye(handeye))
        retained = robot.workflow.handeye
        self.assertTrue(robot._capture_available())
        self.assertTrue(self.bridge.disconnect_devices())
        self.finish()
        self.assertIs(robot.workflow.handeye, retained)
        self.assertFalse(robot._capture_available())


if __name__ == '__main__':
    unittest.main()
