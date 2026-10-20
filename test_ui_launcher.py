"""Production entrance contracts; no backend construction or SDK access."""
import os
import sys
from pathlib import Path
import unittest
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy
from ui_v2 import GLOBAL_QSS, LauncherDialog
from ui_v2.widgets.device_table import DeviceInfo


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(GLOBAL_QSS)

    def setUp(self):
        self._had_camera_module = 'core.camera_manager' in sys.modules
        self.dialog = LauncherDialog()
        self.dialog.set_devices([
            DeviceInfo(model='M2600R', serial='SN1', ip='192.168.1.10', backend_ref=0),
            DeviceInfo(model='M2600R', serial='SN2', ip='192.168.1.11', backend_ref=1),
        ])

    def tearDown(self):
        self.dialog.set_busy(False)
        self.dialog.set_auto_ip_busy(False)
        self.dialog.hide_connection_overlay()
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def select_two(self):
        for checkbox in self.dialog._table._check_widgets:
            checkbox.setChecked(True)

    def test_selection_never_moves_cards_and_modes_keep_rules(self):
        dlg = self.dialog
        dlg.show(); self.app.processEvents()
        before = {key: card.geometry() for key,card in dlg._cards.items()}
        self.assertEqual({r.height() for r in before.values()}, {100})
        self.select_two()
        self.assertTrue(dlg._btn_connect.isEnabled())
        for mode in (dlg.MODE_MOBILE_CHAIN, dlg.MODE_TURNTABLE, dlg.MODE_MULTI_CAM):
            dlg._set_mode(mode); self.app.processEvents()
            self.assertEqual(before, {key: card.geometry() for key,card in dlg._cards.items()})
            self.assertEqual(dlg.selected_devices(), [])
            self.assertFalse(dlg._btn_connect.isEnabled())
            if mode != dlg.MODE_MULTI_CAM:
                dlg._table._check_widgets[0].setChecked(True)
                self.assertTrue(dlg._btn_connect.isEnabled())

    def test_existing_backend_ports_receive_exact_devices(self):
        dlg = self.dialog
        refresh = QSignalSpy(dlg.refresh_requested)
        auto_ip = QSignalSpy(dlg.auto_ip_requested)
        connect = QSignalSpy(dlg.connect_requested)
        dlg._btn_refresh.click()
        self.assertEqual(refresh.count(), 1)
        self.select_two()
        chosen = dlg.selected_devices()
        dlg._btn_auto_ip.click()
        self.assertEqual(auto_ip.at(0)[0], chosen)
        dlg._btn_connect.click()
        self.assertEqual(connect.at(0), [dlg.MODE_MULTI_CAM, chosen])
        self.assertEqual(dlg.result(), 0)  # Only the backend may accept after success.

    def test_busy_selection_and_close_are_locked_then_restored(self):
        dlg = self.dialog
        self.select_two()
        dlg.show_connection_overlay('正在连接测试')
        dlg._set_mode(dlg.MODE_TURNTABLE)
        self.assertEqual(dlg.selected_mode(), dlg.MODE_MULTI_CAM)
        self.assertFalse(dlg._btn_connect.isEnabled())
        self.assertFalse(dlg._table.isEnabled())
        self.assertFalse(dlg.close())
        # An independent busy operation must not be cleared by hiding the overlay.
        dlg.set_auto_ip_busy(True)
        dlg.hide_connection_overlay()
        self.assertFalse(dlg._btn_connect.isEnabled())
        dlg.set_auto_ip_busy(False)
        self.assertTrue(dlg._btn_connect.isEnabled())
        self.assertTrue(dlg._table.isEnabled())
        dlg.set_busy(True)
        dlg.set_devices(dlg._table.devices())
        self.assertFalse(dlg._btn_connect.isEnabled())
        dlg.set_busy(False)
        self.assertTrue(dlg._btn_connect.isEnabled())

    def test_empty_message_filter_and_reopen_state(self):
        dlg = self.dialog
        dlg.set_devices([])
        self.assertIn('未检测到相机', dlg._device_hint.text())
        self.assertIn('2D', dlg._rule_hint.text())
        device = DeviceInfo(model='X1', serial='RESTORED', ip='192.168.1.12',
                            backend_ref=3, checked=True)
        dlg.restore_state(dlg.MODE_TURNTABLE, [device])
        self.assertEqual(dlg.selected_devices(), [device])
        self.assertTrue(dlg._btn_connect.isEnabled())
        dlg._search_edit.setText('missing')
        self.assertTrue(dlg._table.isRowHidden(0))
        dlg._search_edit.clear()
        self.assertFalse(dlg._table.isRowHidden(0))
        self.assertEqual('core.camera_manager' in sys.modules, self._had_camera_module)

    def test_test_devices_auto_ip_warns_without_calling_backend(self):
        dlg = self.dialog
        dlg.set_devices([])
        dlg._on_add_test_devices()
        auto_ip = QSignalSpy(dlg.auto_ip_requested)
        for choose in (False, True):
            dlg._table._check_widgets[0].setChecked(choose)
            dlg._btn_auto_ip.click()
            self.app.processEvents()
            self.assertEqual(auto_ip.count(), 0)
            self.assertEqual(dlg.log_summary.level, 'warn')
            self.assertIn('测试设备不支持', dlg.log_summary.full_text)
            self.assertFalse(dlg._is_busy())

    def test_background_log_and_summary_lifetime(self):
        from core.utils import logger
        dlg = self.dialog
        dlg.show(); self.app.processEvents()
        summary = dlg.log_summary
        worker = threading.Thread(target=lambda: logger.warning('未找到 GigE 设备'))
        worker.start(); worker.join()
        self.app.processEvents()
        self.assertEqual(summary.level, 'warn')
        self.assertIn('未找到 GigE 设备', summary.full_text)
        logger.info('success metadata', extra={'activity_owned':True, 'ui_level':'success'})
        self.app.processEvents()
        self.assertEqual(summary.level, 'success')
        dlg.reject()
        before = summary.full_text
        logger.warning('after close')
        self.app.processEvents()
        self.assertEqual(summary.full_text, before)
        dlg.show(); self.app.processEvents()
        logger.error('reopened')
        self.app.processEvents()
        self.assertEqual(summary.level, 'error')
        self.assertIn('reopened', summary.full_text)

    def test_auto_ip_outcomes_and_older_queued_logs(self):
        from core.utils import logger
        dlg = self.dialog
        logger.info('older queued operation')
        dlg.report_auto_ip_result([(-1,False,'未找到 GigE 设备')])
        self.app.processEvents()
        self.assertEqual(dlg.log_summary.level, 'warn')
        self.assertIn('未找到 GigE', dlg.log_summary.full_text)
        dlg.report_auto_ip_result([], RuntimeError('network failure'))
        self.assertEqual(dlg.log_summary.level, 'error')
        dlg.report_auto_ip_result([])
        self.assertEqual(dlg.log_summary.level, 'warn')
        dlg.report_auto_ip_result([(0,True,'OK'),(1,False,'失败原因')])
        self.assertIn('1 台成功', dlg.log_summary.full_text)
        self.assertIn('失败原因', dlg.log_summary.full_text)
        self.assertEqual(dlg.log_summary.level, 'warn')
        dlg.report_auto_ip_result([(0,True,'OK')])
        self.assertEqual(dlg.log_summary.level, 'success')
        long_text = '<b>plain text</b> ' + '长消息' * 300 + '\n下一行'
        dlg.log_summary.append(long_text, 'warn')
        dlg.show(); self.app.processEvents()
        self.assertNotIn('\n', dlg.log_summary.message.text())
        self.assertIn('plain text', dlg.log_summary.toolTip())
        self.assertLess(len(dlg.log_summary.message.text()), len(dlg.log_summary.full_text))


if __name__ == '__main__':
    unittest.main(verbosity=2)
