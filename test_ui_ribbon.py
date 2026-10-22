"""Industrial ribbon delegates once, mirrors gates and keeps classic layout."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QPushButton
from ui_v2 import MainWindowShell
from ui_v2.industrial_ribbon import CommandButton
from ui_v2.widgets.device_table import DeviceInfo


class RibbonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def setUp(self):
        self.win = MainWindowShell()
        self.ribbon = self.win._industrial_ribbon

    def tearDown(self):
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def enter(self, mode):
        self.win.set_mode(mode, [DeviceInfo(serial='A', backend_ref=0)])
        self.win.set_presentation('industrial')
        return self.win._stack.currentWidget()

    def test_mode_groups_and_classic_restoration_have_no_duplicate_toolbar(self):
        for _ in range(2):
            for mode in ('multi_cam', 'mobile_chain', 'turntable'):
                ws = self.enter(mode)
                self.assertTrue(self.win._toolbar.isHidden())
                self.assertFalse(self.ribbon.isHidden())
                self.assertEqual(self.ribbon.pages.currentWidget(), self.ribbon._pages[mode])
                self.assertIn((mode, 'fit'), self.ribbon.commands)
                self.win.set_presentation('classic')
                self.assertTrue(self.ribbon.isHidden())
                self.assertFalse(self.win._toolbar.isHidden())
                if mode == 'mobile_chain':
                    self.assertFalse(ws._btn_capture.isHidden())
                    self.assertFalse(ws._btn_capture.parentWidget().isHidden())

    def test_multicam_gate_updates_without_rebinding_and_locked_text_follows(self):
        ws = self.enter('multi_cam')
        detect = self.ribbon.commands[('multi_cam', 'detect')]
        capture = self.ribbon.commands[('multi_cam', 'capture')]
        spy = QSignalSpy(ws.detect_requested)
        self.assertFalse(detect.isEnabled())
        detect.click()
        self.assertEqual(spy.count(), 0)
        ws.set_state('captured')
        self.assertTrue(detect.isEnabled())
        detect.click()
        self.assertEqual(spy.count(), 1)
        ws.on_calibrate_done([], 90, True)
        ws.set_state('locked')
        self.assertEqual(capture.text(), '重新标定')
        self.assertTrue(self.ribbon.commands[('multi_cam', 'scan')].isEnabled())
        ws.offline_preview = True
        ws.set_state('locked')
        self.assertFalse(capture.isEnabled())
        self.assertFalse(self.ribbon.commands[('multi_cam', 'scan')].isEnabled())

    def test_mobile_open_and_edit_commands_use_existing_business_routes(self):
        ws = self.enter('mobile_chain')
        load = QSignalSpy(self.win.open_session_requested)
        undo = QSignalSpy(ws.undo_requested)
        self.ribbon.commands[('mobile_chain', 'open')].click()
        self.assertEqual(load.count(), 1)
        button = self.ribbon.commands[('mobile_chain', 'undo')]
        self.assertFalse(button.isEnabled())
        ws.on_evaluation_done(8, .9, .2, 'ok', '继续', backend_ref='station_1')
        button.click()
        self.assertEqual(undo.count(), 1)
        self.assertTrue(ws._btn_capture.isHidden())

    def test_session_actions_move_to_ribbon_once_and_restore_current_mode(self):
        manage = Mock()
        self.win._backend_bridge = SimpleNamespace(projects=SimpleNamespace(manage=manage))
        try:
            for mode in ('multi_cam', 'mobile_chain', 'turntable'):
                # Create presentations without backend setup; the production
                # bindings are covered by the frame-database integration tests.
                self.win._backend_bridge = None
                ws = self.enter(mode)
                self.win.set_presentation('classic')
                self.win.set_presentation('industrial')
                self.win._backend_bridge = SimpleNamespace(projects=SimpleNamespace(manage=manage))
                browser = ws._industrial.frame_browser
                self.assertTrue(browser.footer.isHidden())
                restore = QSignalSpy(browser.restore_requested)
                opened = QSignalSpy(self.win.open_session_requested)
                self.ribbon.commands[(mode, 'restore')].click()
                self.assertEqual(restore.count(), 1)
                self.ribbon.commands[(mode, 'open')].click()
                self.assertEqual(opened.count(), 1)
                manage.reset_mock()
                self.ribbon.commands[(mode, 'manage')].click()
                manage.assert_called_once_with()
        finally:
            self.win._backend_bridge = None

    def test_turntable_save_uses_workspace_gate_and_shell_signal_once(self):
        ws = self.enter('turntable')
        button = self.ribbon.commands[('turntable', 'save')]
        spy = QSignalSpy(self.win.save_session_requested)
        self.assertFalse(button.isEnabled())
        ws.btn_save_session.setEnabled(True)
        button.click()
        self.assertEqual(spy.count(), 1)
        self.assertTrue(ws.btn_save_session.isHidden())

    def test_checkable_proxy_mirrors_source_and_invokes_once(self):
        source = QPushButton()
        source.setCheckable(True)
        callback = Mock()
        source.toggled.connect(callback)
        proxy = CommandButton(source, '自动采集', 'loop')
        proxy.click()
        callback.assert_called_once_with(True)
        self.assertTrue(source.isChecked())
        self.assertTrue(proxy.isChecked())
        source.setChecked(False)
        self.assertFalse(proxy.isChecked())
        source.setEnabled(False)
        self.assertFalse(proxy.isEnabled())
        proxy.deleteLater()
        source.deleteLater()

    def test_controls_stay_at_top_and_turntable_uses_sidebar_height(self):
        self.win.resize(1280, 800)
        for mode in ('mobile_chain', 'turntable'):
            ws = self.enter(mode)
            self.win.show()
            self.app.processEvents()
            last = self.ribbon.commands[(mode, 'screenshot')]
            self.assertLess(last.mapTo(self.ribbon, last.rect().topRight()).x(), self.ribbon.width())
            presentation = ws._industrial
            widget = ws._live_view if mode == 'mobile_chain' else ws._left_panel
            self.assertLess(widget.y(), 20)
            if mode == 'turntable':
                self.assertGreater(widget.height(), presentation.sidebar.viewport().height() * .8)

    def test_fit_tracks_current_view_and_log_header_uses_bottom_dock(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.enter(mode)
            viewer = self.ribbon._viewer()
            with patch.object(viewer, 'reset_view') as fit:
                self.ribbon.commands[(mode, 'fit')].click()
                fit.assert_called_once_with()
        self.ribbon.log_button.click()
        self.assertTrue(self.win._btn_log.isChecked())
        self.assertIs(self.win._log_panel.parentWidget(), self.win._content_split)
        self.win._btn_log.setChecked(False)
        self.assertFalse(self.ribbon.log_button.isChecked())

    def test_screenshot_saves_actual_view_and_cancel_does_not_write(self):
        self.enter('mobile_chain')
        self.win.show()
        self.app.processEvents()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'view.png')
            with patch('ui_v2.industrial_ribbon.QFileDialog.getSaveFileName', return_value=(path, '')):
                self.ribbon.screenshot()
            self.assertTrue(Path(path).is_file())
            self.assertGreater(Path(path).stat().st_size, 100)
            with patch('ui_v2.industrial_ribbon.QFileDialog.getSaveFileName', return_value=('', '')):
                self.ribbon.screenshot()
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
