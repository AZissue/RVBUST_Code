"""Connection identity/rollback contracts without importing the camera SDK."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parents[1]/'src'), str(HERE.parent)]
from industrial_scan_ui.app.devices import DeviceService
from ui_v2.widgets.device_table import DeviceInfo


class ConnectionTests(unittest.TestCase):
    def service(self, *, success=True, identity=True):
        manager = Mock()
        manager.connect_all.return_value = success, 'connection failure'
        manager.find_by_sn.side_effect = lambda sn: 'cam1' if identity else None
        # A refresh changed the enumeration index from 9 to 0.
        device = Mock()
        device.GetDeviceInfo.return_value = True, SimpleNamespace(name='RVC',sn='A',ip='')
        manager.find_devices.return_value = [device]
        service = DeviceService()
        service.manager = manager
        return service, manager, DeviceInfo(model='RVC', serial='A', backend_ref=9)

    def test_stale_index_resolved_by_serial_and_cleanup(self):
        service, manager, selected = self.service()
        result = service.connect([selected])
        self.assertEqual(result[0].backend_ref, 0)
        manager.connect_all.assert_called_once_with({'cam1':0})
        service.connect([selected])
        manager.connect_all.assert_called_once()
        service.close()
        manager.shutdown.assert_called_once()
        self.assertEqual(service.connected, [])

    def test_failed_connect_and_identity_change_roll_back(self):
        for success, identity in [(False, True),(True, False)]:
            service, manager, selected = self.service(success=success, identity=identity)
            with self.assertRaises(RuntimeError):service.connect([selected])
            self.assertEqual(service.connected, [])
            self.assertEqual(manager.clear.call_count, 2)

    def test_disappeared_and_duplicate_devices_never_open(self):
        service, manager, selected = self.service()
        with self.assertRaises(ValueError):service.connect([selected,selected])
        selected.serial='missing'
        with self.assertRaises(RuntimeError):service.connect([selected])
        manager.connect_all.assert_not_called()
        manager.clear.assert_not_called()


if __name__ == '__main__':unittest.main(verbosity=2)
