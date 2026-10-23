"""Device identity must survive SDK re-enumeration and launcher reopening."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtWidgets import QApplication, QDialog
from core.camera_manager import CameraManager
from ui_v2 import MainWindowShell, LauncherDialog
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo


class Device:
    def __init__(self, model, serial):
        self.info = SimpleNamespace(name=model, sn=serial, support_extra=False)

    def GetDeviceInfo(self):
        return True, self.info

    def IsFirmwareMatch(self):
        return True


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.m = Device('RVC-M2600C-V2', 'M3GM620B039')
        self.dg = Device('RVC-DG51600C-WL3', 'G3GM550W002')
        self.sdk_camera = Mock()
        self.sdk_camera.Open.return_value = True
        self.sdk_camera.IsOpen.return_value = True
        self.sdk_camera.LoadCaptureOptionParameters.return_value = (False, None)
        self.sdk = SimpleNamespace(CameraID_Left=0, CameraID_Extra=1,
            SystemListDeviceTypeEnum=SimpleNamespace(All=0),
            SystemListDevices=Mock(return_value=(True, [self.dg, self.m])),
            X2=SimpleNamespace(Create=Mock(return_value=self.sdk_camera), Destroy=Mock()))
        self.patcher = patch('core.camera_manager.RVC', self.sdk)
        self.patcher.start()
        self.manager = CameraManager()
        self.manager.add_camera('cam0')

    def tearDown(self):
        self.manager.clear()
        self.patcher.stop()

    def test_stale_index_zero_opens_selected_serial_at_new_index_one(self):
        ok, msg = self.manager.connect('cam0', 0, expected_sn=self.m.info.sn, expected_model=self.m.info.name)
        self.assertTrue(ok, msg)
        self.sdk.X2.Create.assert_called_once_with(self.m)
        self.assertEqual(self.manager._cameras['cam0'].device_index, 1)
        self.assertEqual(self.manager._cameras['cam0'].sn, self.m.info.sn)

    def test_missing_duplicate_or_missing_serial_never_falls_back_to_index(self):
        for serial, devices in ((self.m.info.sn, [self.dg]), ('', [self.dg]),
                                (self.m.info.sn, [self.m, self.m])):
            self.sdk.SystemListDevices.return_value = True, devices
            ok, msg = self.manager.connect('cam0', 0, expected_sn=serial)
            self.assertFalse(ok, msg)
        self.sdk.X2.Create.assert_not_called()

    def test_model_mismatch_is_rejected_before_open(self):
        ok, msg = self.manager.connect('cam0', 0, expected_sn=self.m.info.sn, expected_model='WRONG')
        self.assertFalse(ok, msg)
        self.sdk.X2.Create.assert_not_called()

    def test_sdk_enumeration_order_changes_between_listing_and_opening(self):
        self.sdk.SystemListDevices.side_effect = [(True, [self.m, self.dg]), (True, [self.dg, self.m])]
        listed = self.manager.find_devices()
        serial = listed[0].GetDeviceInfo()[1].sn
        ok, message = self.manager.connect('cam0', 0, expected_sn=serial)
        self.assertTrue(ok, message)
        self.sdk.X2.Create.assert_called_once_with(self.m)

    def test_identity_change_during_open_closes_handle_before_loading_parameters(self):
        serial = self.m.info.sn
        def change():
            self.m.info = self.dg.info
            return True
        self.sdk_camera.Open.side_effect = change
        ok, msg = self.manager.connect('cam0', 0, expected_sn=serial)
        self.assertFalse(ok, msg)
        self.assertFalse(self.manager.is_connected('cam0'))
        self.sdk_camera.Close.assert_called_once()
        self.sdk_camera.LoadCaptureOptionParameters.assert_not_called()

    def test_serial_deduplication_and_stale_indices_for_two_different_devices(self):
        self.assertTrue(self.manager.connect('cam0', 0, expected_sn=self.m.info.sn)[0])
        self.manager.add_camera('cam1')
        self.assertFalse(self.manager.connect('cam1', 1, expected_sn=self.m.info.sn)[0])
        # Old numeric index is occupied, but the selected serial is another device.
        self.assertTrue(self.manager.connect('cam1', 1, expected_sn=self.dg.info.sn)[0])
        self.assertEqual(self.manager._cameras['cam1'].sn, self.dg.info.sn)

    def test_manager_closes_an_unexpected_identity_returned_by_controller(self):
        controller = self.manager._cameras['cam0']
        controller.sn = self.dg.info.sn
        controller.device_info = self.dg.info
        with patch.object(controller, 'connect', return_value=(True, 'wrong')), \
                patch.object(controller, 'disconnect') as close:
            ok, msg = self.manager.connect('cam0', 0, expected_sn=self.m.info.sn)
            self.assertFalse(ok, msg)
            close.assert_called_once()

    def test_launcher_keeps_fresh_enumeration_and_restores_selection_by_serial(self):
        window = MainWindowShell()
        old = DeviceInfo(model=self.m.info.name, serial=self.m.info.sn, backend_ref=0)
        fresh = [DeviceInfo(model=self.dg.info.name, serial=self.dg.info.sn, backend_ref=0),
                 DeviceInfo(model=self.m.info.name, serial=self.m.info.sn, backend_ref=1)]
        self_check = self
        class Dialog(LauncherDialog):
            def exec(dialog):
                devices = dialog._table.devices()
                self_check.assertEqual([d.serial for d in devices], [self_check.dg.info.sn, self_check.m.info.sn])
                selected = dialog._table.checked_devices()
                self_check.assertEqual(len(selected), 1)
                self_check.assertEqual(selected[0].backend_ref, 1)
                return QDialog.Rejected
        try:
            window.set_mode('mobile_chain', [old])
            window._launcher_factory = Dialog
            window.set_backend_bridge(SimpleNamespace(can_change_workspace=lambda: True,
                                                      enumerate_devices=lambda: fresh))
            window.open_device_manager()
        finally:
            window._dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_bridge_passes_selected_serial_and_model_to_connection(self):
        window = MainWindowShell()
        bridge = BackendBridge(window)
        try:
            device = DeviceInfo(model=self.m.info.name, serial=self.m.info.sn, backend_ref=0)
            with patch.object(bridge, '_ensure_sdk', return_value=True), \
                    patch.object(bridge, '_run_background') as runner, \
                    patch.object(bridge.camera_manager, 'connect', return_value=(True, 'ok')) as connect:
                bridge._on_device_manager_reopened('mobile_chain', [device], show_loading=False)
                runner.call_args.args[0]()
                connect.assert_called_once_with('cam0', 0, expected_sn=device.serial, expected_model=device.model)
        finally:
            bridge.cleanup()
            window._dirty = False
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
