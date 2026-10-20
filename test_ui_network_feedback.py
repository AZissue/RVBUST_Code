"""Backend network guard and completion feedback, with all SDK calls mocked."""
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0, str(Path(__file__).parent/'src'))
from PySide6.QtCore import QObject
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo


class NetworkFeedbackTests(unittest.TestCase):
    def bridge(self):
        bridge = BackendBridge.__new__(BackendBridge)
        QObject.__init__(bridge)
        bridge.shell = Mock()
        bridge.camera_manager = Mock()
        bridge.camera_manager.initialize.return_value = (True, 'mock SDK ready')
        bridge._run_background = Mock()
        return bridge

    def test_test_only_selection_never_configures_all_physical_devices(self):
        bridge = self.bridge()
        callback = Mock()
        bridge.auto_configure_network([DeviceInfo(model='TEST', serial='TEST')], callback)
        bridge._run_background.assert_not_called()
        bridge.camera_manager.auto_configure_network.assert_not_called()
        results, error = callback.call_args.args
        self.assertIsNone(error)
        self.assertFalse(results[0][1])
        self.assertIn('测试设备', results[0][2])
        self.assertEqual(bridge.shell.log.call_args.args[1], 'warn')

    def test_real_selection_and_no_selection_keep_original_targets_and_results(self):
        for devices, expected in [([], []), ([DeviceInfo(serial='REAL',backend_ref=7)], [7])]:
            bridge = self.bridge()
            results = [(-1,False,'未找到 GigE 设备')]
            bridge.camera_manager.auto_configure_network.return_value = results
            callback = Mock()
            bridge.auto_configure_network(devices, callback)
            work, done = bridge._run_background.call_args.args
            done(work(), None)
            bridge.camera_manager.auto_configure_network.assert_called_once_with(expected)
            callback.assert_called_once_with(results, None)
            self.assertEqual(bridge.shell.log.call_args.args[1], 'warn')


if __name__ == '__main__':unittest.main(verbosity=2)
