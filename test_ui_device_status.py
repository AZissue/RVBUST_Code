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
from PySide6.QtGui import QFontMetrics
from ui_v2 import LauncherDialog
from ui_v2.widgets.device_table import (
    DeviceTable, DeviceInfo, ModernCheckBox, DATA_FONT_PX, ROW_HEIGHT,
    SERIAL_MIN_WIDTH, SERIAL_MAX_WIDTH, STATUS_MIN_WIDTH, IP_MIN_WIDTH,
)
from ui_v2.theme import STATUS_OK, STATUS_ERR, STATUS_WARN, TEXT_MUTED


class TableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self): self.table=DeviceTable()
    def tearDown(self): self.table.close();self.table.deleteLater();self.app.processEvents()
    def test_columns_text_color_detail_and_order(self):
        self.table.set_devices([DeviceInfo('M','busy','192.168.1.3',status='busy',status_detail='Camera is occupied!',backend_ref=0),
            DeviceInfo('M','idle','192.168.1.2',status='idle',status_detail='X2 打开成功，探测句柄已关闭',backend_ref=1),
            DeviceInfo('M','net','192.168.2.3',status='subnet_mismatch',status_detail='相机 192.168.2.3/24；主机 192.168.1.2/24',backend_ref=2),
            DeviceInfo('USB','unknown',status='unknown',status_detail='查询超时',backend_ref=3)])
        self.assertEqual(self.table.COLS,('','型号','序列号','设备状态','IP 地址'))
        self.assertEqual([d.serial for d in self.table.devices()],['idle','busy','net','unknown'])
        for row,label,color in [(0,'空闲',STATUS_OK),(1,'占用',STATUS_ERR),(2,'跨网段',STATUS_WARN),(3,'未知',TEXT_MUTED)]:
            item=self.table.item(row,3);self.assertEqual(item.text(),label);self.assertEqual(item.foreground().color().name(),color.lower())
        # 短标签不回退语义：tooltip 必须同时保留完整描述与识别依据/错误详情
        self.assertIn('被占用',self.table.item(1,3).toolTip())
        self.assertIn('Camera is occupied!',self.table.item(1,3).toolTip())
        self.assertIn('空闲',self.table.item(0,3).toolTip())
        self.assertIn('X2 打开成功',self.table.item(0,3).toolTip())
        self.assertIn('IP不在同一网段',self.table.item(2,3).toolTip())
        self.assertIn('192.168.2.3/24',self.table.item(2,3).toolTip())
        self.assertIn('状态未知',self.table.item(3,3).toolTip())
        self.assertIn('查询超时',self.table.item(3,3).toolTip())
        self.assertFalse(self.table.isColumnHidden(3));self.assertFalse(self.table.isColumnHidden(4))
    def test_usb_and_offline_status_always_visible(self):
        self.table.set_devices([DeviceInfo('USB','sn',status='idle',backend_ref=0)])
        self.assertTrue(self.table.isColumnHidden(4));self.assertFalse(self.table.isColumnHidden(3))
        self.assertEqual(self.table.item(0,3).text(),'空闲')
        self.table.set_device_online('sn',False);self.assertEqual(self.table.item(0,3).text(),'离线')
        self.assertIn('设备已离线',self.table.item(0,3).toolTip())
        self.table.set_device_online('sn',True);self.assertEqual(self.table.item(0,3).text(),'未知')
        self.assertIn('重新上线',self.table.item(0,3).toolTip())
    def test_connected_status_label_color_and_detail(self):
        self.table.set_devices([DeviceInfo('RVC','own','192.168.1.9',status='connected',
            status_detail='本程序已连接（识别依据：索引 0）；不重复打开探测',backend_ref=0)])
        item=self.table.item(0,3)
        self.assertEqual(item.text(),'已连接')
        self.assertEqual(item.foreground().color().name(),'#64b5f6')
        self.assertEqual(item.toolTip(),'本程序已连接（识别依据：索引 0）；不重复打开探测')
    def test_test_device_short_label_keeps_detail(self):
        self.table.set_devices([DeviceInfo('TEST-A',status='idle',serial='SN_TEST_A',
            status_detail='测试设备，不查询SDK')])
        item=self.table.item(0,3)
        self.assertEqual(item.text(),'测试')
        self.assertEqual(item.foreground().color().name(),STATUS_OK.lower())
        self.assertIn('测试设备',item.toolTip());self.assertIn('不查询SDK',item.toolTip())
    def test_compact_layout_and_long_text_geometry(self):
        """1062×652 / 1440×900 下长型号、长 SN、五类状态不挤掉状态列、不横向溢出。"""
        long_model='Tina-RVC-P5330-Industrial-Ultra-Long-Model-Name'
        long_serial='P2GM353W002-LONG-SERIAL-ABCDEFGHIJKLMNOP'
        devices=[DeviceInfo(long_model,long_serial,'192.168.1.10',backend_ref=0,status='idle',status_detail='X2 打开成功'),
            DeviceInfo('RVC-X2-Industrial-LongModelName','X2GM001-LONG-SERIAL-00000001','192.168.1.13',backend_ref=1,status='connected',status_detail='本程序已连接（识别依据：SN）'),
            DeviceInfo('RVC-G52000','G2GM250BA21','192.168.1.11',backend_ref=2,status='busy',status_detail='Camera is occupied!'),
            DeviceInfo('RVC-M51000C','M3GM150W005','192.168.2.12',backend_ref=3,status='subnet_mismatch',status_detail='相机 192.168.2.12/24'),
            DeviceInfo('RVC-I2120','I1GM112B652','',backend_ref=4,status='unknown',status_detail='查询超时')]
        dlg=LauncherDialog()
        try:
            for width,height in ((1062,652),(1440,900)):
                dlg.resize(width,height);dlg.show();self.app.processEvents()
                dlg.set_devices([DeviceInfo(d.model,d.serial,d.ip,backend_ref=d.backend_ref,
                    status=d.status,status_detail=d.status_detail) for d in devices])
                self.app.processEvents()
                table=dlg._table
                self.assertEqual(table.textElideMode(),Qt.ElideMiddle)
                self.assertFalse(table.wordWrap())
                self.assertEqual(table.verticalHeader().defaultSectionSize(),ROW_HEIGHT)
                self.assertEqual(table.rowHeight(0),ROW_HEIGHT)
                self.assertLessEqual(table.font().pixelSize(),DATA_FONT_PX)
                self.assertGreaterEqual(table.columnWidth(2),SERIAL_MIN_WIDTH)
                self.assertLessEqual(table.columnWidth(2),SERIAL_MAX_WIDTH)
                self.assertGreaterEqual(table.columnWidth(3),STATUS_MIN_WIDTH)
                self.assertGreater(table.columnWidth(1),0)
                self.assertEqual(table.columnViewportPosition(3),
                    table.columnViewportPosition(2)+table.columnWidth(2))
                self.assertEqual(table.columnViewportPosition(4),
                    table.columnViewportPosition(3)+table.columnWidth(3))
                self.assertEqual(table.horizontalScrollBar().maximum(),0)
                self.assertFalse(table.isColumnHidden(3))
                fm=QFontMetrics(table.font())
                rows={table.item(r,2).text():r for r in range(table.rowCount())}
                for serial,row in rows.items():
                    self.assertLessEqual(fm.horizontalAdvance(table.item(row,3).text()),
                                         table.columnWidth(3)-8)
                first=rows[long_serial]
                if width==1062:
                    # 小窗口下长型号必须触发省略，而不是把状态列挤出视口
                    self.assertGreater(fm.horizontalAdvance(long_model),table.columnWidth(1))
                self.assertEqual(table.item(first,1).toolTip(),long_model)
                self.assertEqual(table.item(first,2).toolTip(),long_serial)
                self.assertEqual(table.item(first,3).text(),'空闲')
                self.assertGreaterEqual(table.columnWidth(4),IP_MIN_WIDTH)
                checkbox=table.cellWidget(first,0).findChild(ModernCheckBox)
                self.assertIsNotNone(checkbox);self.assertEqual(checkbox.width(),18)
        finally:
            dlg.close();dlg.deleteLater();self.app.processEvents()
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
            row=[r for r in range(dlg._table.rowCount()) if dlg._table.item(r,2).text()=='SN_TEST_A'][0]
            self.assertEqual(dlg._table.item(row,3).text(),'测试')
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
