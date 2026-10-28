"""Real CameraManager wiring for the launcher refresh path (no SDK, no hardware).

Previous rounds only used ``SimpleNamespace(camera_manager=...)`` doubles, which
silently supplied ``poll_device_statuses`` even though the real ``CameraManager``
class never defined it.  These tests construct the real class, drive the real
``BackendBridge.enumerate_devices`` and the same call as ``main.py on_refresh``;
only the SDK module reference and the bridge's SDK/workspace gates are replaced.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import core.camera_manager as camera_manager_module
from core.camera_manager import CameraManager, SingleCameraController
from ui_v2.backend_bridge import BackendBridge


class FakeDevice:
    """Read-only device double: no capture, no network write."""

    def __init__(self, sn, model='RVC', port='USB', ip='', mask='255.255.255.0',
                 open_ok=True):
        self.info = NS(name=model, sn=sn, port=port)
        self.ip, self.mask, self.open_ok = ip, mask, open_ok
        self.GetNetworkConfig = Mock(
            return_value=(0, ip.encode(), mask.encode(), b'0.0.0.0', 0))
        self.IsFirmwareMatch = Mock(return_value=True)
        self.AutoConfigureNetwork = Mock(
            side_effect=AssertionError('network write forbidden'))

    def GetDeviceInfo(self):
        return True, self.info


def fake_sdk(devices, error='Camera is occupied!'):
    """Minimal PyRVC surface used by device_status.poll_devices/probe."""
    events = []

    def make_create(kind):
        def create(device, *args):
            camera = Mock()
            camera.IsValid.return_value = True
            camera.Open.side_effect = lambda: events.append(kind + '.Open') or device.open_ok
            camera.IsOpen.return_value = device.open_ok
            camera.Close.side_effect = lambda: events.append(kind + '.Close')
            return camera
        return create

    sdk = NS(
        SystemListDeviceTypeEnum=NS(All=0),
        PortType=NS(PortType_GIGE='GigE'),
        NetworkDevice=NS(NetworkDevice_LightMachine=0),
        CameraID_Left=0,
        GetLastErrorMessage=Mock(return_value=error),
        SystemListDevices=Mock(return_value=(0, list(devices))),
    )
    for kind in ('X2', 'X1'):
        setattr(sdk, kind, NS(Create=Mock(side_effect=make_create(kind)),
                              Destroy=Mock(return_value=None)))
    return sdk, events


def make_bridge(manager, sdk_ready=True):
    """Real BackendBridge.enumerate_devices; only SDK/workspace gates replaced."""
    bridge = BackendBridge.__new__(BackendBridge)
    bridge.camera_manager = manager
    bridge.shell = NS(log=Mock())
    bridge._ensure_sdk = Mock(return_value=sdk_ready)
    bridge.can_change_workspace = Mock(return_value=True)
    return bridge


class CameraManagerOwnershipTests(unittest.TestCase):
    def test_manager_owns_poll_and_controller_has_no_duplicate(self):
        """Fails before the fix: the method lived on SingleCameraController."""
        self.assertIn('poll_device_statuses', CameraManager.__dict__)
        self.assertNotIn('poll_device_statuses', SingleCameraController.__dict__)
        self.assertTrue(callable(getattr(CameraManager(), 'poll_device_statuses')))

    def test_real_manager_without_sdk_returns_empty_without_init(self):
        manager = CameraManager()
        before = CameraManager._sys_init_count
        with patch.object(camera_manager_module, 'RVC', None), \
                patch.object(CameraManager, 'initialize',
                             side_effect=AssertionError('SDK init forbidden')):
            self.assertEqual(manager.poll_device_statuses(), [])
        self.assertEqual(CameraManager._sys_init_count, before)


class RealManagerEnumerateTests(unittest.TestCase):
    def test_enumerate_devices_real_manager_and_real_poll(self):
        manager = CameraManager()
        devices = [
            FakeDevice('SN-USB', model='RVC-P5330'),
            FakeDevice('SN-BUSY', model='RVC-G52000', open_ok=False),
            FakeDevice('SN-NET', model='RVC-M51000C', port='GigE',
                       ip='192.168.2.10'),
        ]
        sdk, events = fake_sdk(devices)
        bridge = make_bridge(manager)
        with patch.object(camera_manager_module, 'RVC', sdk), \
                patch('core.device_status.host_interfaces',
                      return_value=[('192.168.1.2', '24')]):
            rows = BackendBridge.enumerate_devices(bridge)

        self.assertEqual([r.serial for r in rows], ['SN-USB', 'SN-BUSY', 'SN-NET'])
        self.assertEqual([r.status for r in rows], ['idle', 'busy', 'subnet_mismatch'])
        self.assertEqual([r.backend_ref for r in rows], [0, 1, 2])
        self.assertEqual(rows[2].ip, '192.168.2.10')
        self.assertIn('Camera is occupied!', rows[1].status_detail)
        devices[0].GetNetworkConfig.assert_not_called()
        devices[1].GetNetworkConfig.assert_not_called()
        devices[2].GetNetworkConfig.assert_called_once()
        for device in devices:
            device.AutoConfigureNetwork.assert_not_called()
        self.assertTrue(rows[0].online)
        self.assertEqual(events, [
            'X2.Open', 'X2.Close', 'X2.Open', 'X2.Close', 'X1.Open', 'X1.Close'])

    def test_enumerate_devices_without_sdk_returns_empty(self):
        manager = CameraManager()
        bridge = make_bridge(manager)
        with patch.object(camera_manager_module, 'RVC', None):
            self.assertEqual(BackendBridge.enumerate_devices(bridge), [])


class LauncherRefreshChainTests(unittest.TestCase):
    """Same call as main.py on_refresh: launcher.set_devices(bridge.enumerate_devices())."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui_v2 import LauncherDialog
        self.dlg = LauncherDialog()

    def tearDown(self):
        self.dlg.close()
        self.dlg.deleteLater()
        self.app.processEvents()

    def _own_connected_manager(self):
        manager = CameraManager()
        manager.add_camera('cam0')
        own = manager._cameras['cam0']
        own.is_connected, own.sn, own.device_index = True, 'SN-OWN', 1
        return manager

    def test_on_refresh_with_devices_keeps_rows_status_and_serial_selection(self):
        manager = self._own_connected_manager()
        devices = [
            FakeDevice('SN-USB', model='RVC-P5330'),
            FakeDevice('SN-OWN', model='RVC-G52000', port='GigE',
                       ip='192.168.1.11'),
            FakeDevice('SN-NET', model='RVC-M51000C', port='GigE',
                       ip='192.168.2.12'),
            FakeDevice('SN-BUSY', model='RVC-I2120', open_ok=False),
        ]
        sdk, events = fake_sdk(devices)
        bridge = make_bridge(manager)
        with patch.object(camera_manager_module, 'RVC', sdk), \
                patch('core.device_status.host_interfaces',
                      return_value=[('192.168.1.2', '24')]):
            self.dlg.set_devices(bridge.enumerate_devices())
            table = self.dlg._table
            self.assertEqual(table.COLS, ('', '型号', '序列号', '设备状态', 'IP 地址'))
            rows = {table.item(r, 2).text(): r for r in range(table.rowCount())}
            self.assertEqual(set(rows), {'SN-USB', 'SN-OWN', 'SN-NET', 'SN-BUSY'})
            self.assertEqual(table.item(rows['SN-USB'], 3).text(), '空闲')
            self.assertEqual(table.item(rows['SN-OWN'], 3).text(), '已连接')
            self.assertEqual(table.item(rows['SN-NET'], 3).text(), '跨网段')
            self.assertEqual(table.item(rows['SN-BUSY'], 3).text(), '占用')
            self.assertIn('本程序已连接', table.item(rows['SN-OWN'], 3).toolTip())
            self.assertIn('Camera is occupied!',
                          table.item(rows['SN-BUSY'], 3).toolTip())
            self.assertFalse(table.isColumnHidden(3))
            self.assertNotEqual(table.item(rows['SN-BUSY'], 3).text(), '空闲')
            self.assertEqual(table.item(rows['SN-NET'], 4).text(), '192.168.2.12')
            self.assertEqual(
                {d.serial: d.backend_ref for d in table.devices()},
                {'SN-USB': 0, 'SN-OWN': 1, 'SN-NET': 2, 'SN-BUSY': 3})

            # 勾选按 SN 在刷新后保留（main.py 的刷新不丢用户选择）。
            table._on_row_clicked(table.item(rows['SN-USB'], 2))
            self.assertEqual([d.serial for d in self.dlg.selected_devices()],
                             ['SN-USB'])
            self.dlg.set_devices(bridge.enumerate_devices())
            self.assertEqual([d.serial for d in self.dlg.selected_devices()],
                             ['SN-USB'])
            # 两次刷新都重新逐台探测：空闲 + 占用各 Open 一次；自有相机不重复打开。
            self.assertEqual(events.count('X2.Open'), 4)
            # 直接调用真实管理器的轮询方法仍返回同一组行。
            polled = manager.poll_device_statuses()
            self.assertEqual([r.serial for r in polled],
                             ['SN-USB', 'SN-OWN', 'SN-NET', 'SN-BUSY'])
            self.assertEqual(polled[1].status, 'connected')
            self.assertEqual(events.count('X2.Open'), 6)
            self.assertEqual(events.count('X1.Open'), 3)
            devices[1].GetNetworkConfig.assert_called()
            for device in devices:
                device.AutoConfigureNetwork.assert_not_called()

        # 无设备结果同样走 on_refresh 链路，正常清空表格。
        with patch.object(camera_manager_module, 'RVC', None):
            self.dlg.set_devices(bridge.enumerate_devices())
        self.assertEqual(self.dlg._table.rowCount(), 0)


if __name__ == '__main__':
    unittest.main()
