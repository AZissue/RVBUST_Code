"""Actual launcher widgets with simulated read-only discovery."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).parent/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtCore import Qt
from ui_v2 import LauncherDialog
from ui_v2.widgets.device_table import DeviceTable, DeviceInfo
from ui_v2.theme import STATUS_OK, STATUS_ERR, STATUS_WARN, TEXT_MUTED


class TableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self): self.table=DeviceTable()
    def tearDown(self): self.table.close();self.table.deleteLater();self.app.processEvents()
    def test_columns_text_color_detail_and_order(self):
        self.table.set_devices([DeviceInfo('M','busy','192.168.1.3',status='busy',status_detail='occupied',backend_ref=0),
            DeviceInfo('M','idle','192.168.1.2',status='idle',backend_ref=1),
            DeviceInfo('M','net','192.168.2.3',status='subnet_mismatch',backend_ref=2),
            DeviceInfo('USB','unknown',status='unknown',backend_ref=3)])
        self.assertEqual(self.table.COLS,('','型号','序列号','设备状态','IP 地址'))
        self.assertEqual([d.serial for d in self.table.devices()],['idle','busy','net','unknown'])
        for row,label,color in [(0,'空闲',STATUS_OK),(1,'被占用',STATUS_ERR),(2,'IP不在同一网段',STATUS_WARN),(3,'状态未知',TEXT_MUTED)]:
            item=self.table.item(row,3);self.assertEqual(item.text(),label);self.assertEqual(item.foreground().color().name(),color.lower())
        self.assertEqual(self.table.item(1,3).toolTip(),'occupied')
        self.assertFalse(self.table.isColumnHidden(3));self.assertFalse(self.table.isColumnHidden(4))
    def test_usb_and_offline_status_always_visible(self):
        self.table.set_devices([DeviceInfo('USB','sn',status='idle',backend_ref=0)])
        self.assertTrue(self.table.isColumnHidden(4));self.assertFalse(self.table.isColumnHidden(3))
        self.table.set_device_online('sn',False);self.assertEqual(self.table.item(0,3).text(),'离线')
        self.table.set_device_online('sn',True);self.assertEqual(self.table.item(0,3).text(),'状态未知')
    def test_checks_by_sn_filter_and_row_click(self):
        self.table.set_devices([DeviceInfo('A','a',backend_ref=0),DeviceInfo('B','b',backend_ref=1)])
        self.table._on_row_clicked(self.table.item(1,2))
        self.table.set_devices([DeviceInfo('B','b',backend_ref=0),DeviceInfo('A','a',backend_ref=1)])
        self.assertEqual([(d.serial,d.backend_ref) for d in self.table.checked_devices()],[('b',0)])
        self.table.apply_filter('a');self.assertTrue(self.table.isRowHidden(0));self.assertFalse(self.table.isRowHidden(1))
        self.table.clear_checks();self.assertEqual(self.table.checked_devices(),[])
    def test_launcher_refresh_test_devices_and_selection(self):
        dlg=LauncherDialog()
        try:
            dlg.set_devices([DeviceInfo('RVC','real',backend_ref=2,status='busy',checked=True)])
            spy=QSignalSpy(dlg.refresh_requested);dlg._btn_refresh.click();self.assertEqual(spy.count(),1)
            dlg._on_add_test_devices()
            tests=[d for d in dlg._table.devices() if d.backend_ref is None]
            self.assertEqual(len(tests),4);self.assertTrue(all(d.status=='idle' and '测试' in d.status_detail for d in tests))
            dlg.set_devices([DeviceInfo('RVC','real',backend_ref=0,status='idle')])
            self.assertEqual(dlg.selected_devices()[0].backend_ref,0)
        finally:
            dlg.close();dlg.deleteLater();self.app.processEvents()


class BridgeTests(unittest.TestCase):
    def test_poll_rows_mapped_without_losing_identity(self):
        from ui_v2.backend_bridge import BackendBridge
        from core.device_status import DeviceStatus
        bridge=NS(_ensure_sdk=Mock(return_value=True),can_change_workspace=Mock(return_value=True),
                  camera_manager=NS(poll_device_statuses=Mock(return_value=[DeviceStatus('RVC','SN','1.2.3.4','busy','Device is busy',True,7)])))
        for _ in range(2):
            rows=BackendBridge.enumerate_devices(bridge)
            self.assertEqual((rows[0].serial,rows[0].backend_ref,rows[0].status),('SN',7,'busy'))
        self.assertEqual(bridge.camera_manager.poll_device_statuses.call_count,2)
        test=DeviceInfo('TEST','test',status='idle')
        self.assertEqual(BackendBridge.get_ordered_devices([test,rows[0]]),[rows[0],test])
    def test_busy_gate_does_not_poll(self):
        from ui_v2.backend_bridge import BackendBridge
        bridge=NS(_ensure_sdk=Mock(return_value=True),can_change_workspace=Mock(return_value=False),shell=NS(log=Mock()),
                  camera_manager=NS(poll_device_statuses=Mock(side_effect=AssertionError('poll while busy'))))
        self.assertEqual(BackendBridge.enumerate_devices(bridge),[])
        bridge.camera_manager.poll_device_statuses.assert_not_called()

if __name__=='__main__': unittest.main()
