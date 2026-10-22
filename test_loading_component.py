"""Shared loading behavior, animation lifecycle and production entrance wiring."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
import shiboken6
from ui_common.appearance import LoadingAppearance
from ui_common.loading import LoadingSpinner, LoadingCard, LoadingOverlay


class LoadingComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def host(self, width=720, height=460):
        parent = QWidget()
        parent.resize(width, height)
        parent.show()
        self.addCleanup(parent.close)
        self.app.processEvents()
        return parent

    def test_common_widgets_import_without_application_package(self):
        code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ui_common.loading import LoadingSpinner, LoadingCard, LoadingOverlay
assert not any(k == 'ui_v2' or k.startswith('ui_v2.') for k in sys.modules)
'''
        result = subprocess.run([sys.executable, '-I', '-c', code,
                                 str(Path(__file__).parent / 'src')], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_visible_ring_animates_and_parent_hide_close_destroy_stop_it(self):
        parent = self.host()
        card = LoadingCard(parent)
        card.resize(380, 100)
        card.show()
        self.app.processEvents()
        spinner = card.spinner
        self.assertEqual(card.grab().toImage().pixelColor(15, 15).name(), '#27272b')
        first = spinner.grab().toImage()
        QTest.qWait(100)
        self.assertNotEqual(first, spinner.grab().toImage())
        self.assertTrue(spinner._timer.isActive())
        parent.hide()
        self.assertFalse(spinner._timer.isActive())
        parent.show()
        self.app.processEvents()
        self.assertTrue(spinner._timer.isActive())
        card.close()
        self.assertFalse(spinner._timer.isActive())
        card.show()
        timer = spinner._timer
        card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(shiboken6.isValid(timer))

    def test_messages_are_plain_text_update_keeps_phase_and_no_elapsed_label(self):
        parent = self.host()
        overlay = LoadingOverlay(parent)
        overlay.show_message('正在执行拼接；原始帧保持独立...')
        self.assertEqual(overlay.card.title_label.text(), '正在执行拼接')
        self.assertEqual(overlay.card.detail_label.text(), '原始帧保持独立')
        QTest.qWait(90)
        elapsed = overlay.card.spinner._clock.elapsed()
        overlay.update_message('<b>正在保存</b>', detail='请稍候')
        self.assertGreaterEqual(overlay.card.spinner._clock.elapsed(), elapsed)
        self.assertEqual(overlay.card.title_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(overlay.card.title_label.text(), '<b>正在保存</b>')
        self.assertEqual(len(overlay.findChildren(QLabel)), 2)
        overlay.hide_overlay()
        self.assertFalse(overlay.card.spinner._timer.isActive())

    def test_overlay_follows_parent_and_accepts_appearance_and_input_policy(self):
        parent = self.host()
        overlay = LoadingOverlay(parent, appearance=LoadingAppearance(accent='#00ff00', card_width=320))
        blocking = LoadingOverlay(parent, block_input=True)
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertFalse(blocking.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        overlay.show_message('加载；' + '长消息' * 12)
        parent.resize(250, 460)
        self.app.processEvents()
        self.assertEqual(overlay.geometry(), parent.rect())
        self.assertLessEqual(overlay.card.width(), 218)
        self.assertTrue(overlay.rect().contains(overlay.card.geometry()))
        overlay.hide_overlay()
        parent.setStyleSheet('background:white;')
        blocking.show_message('连接中')
        self.assertLess(parent.grab().toImage().pixelColor(2, 2).red(), 80)
        blocking.hide_overlay()

    def test_launcher_and_all_modes_reuse_component_and_existing_progress_gates(self):
        from ui_v2 import LauncherDialog, MainWindowShell
        from ui_v2.widgets.loading_overlay import LoadingOverlay as CompatibilityOverlay
        self.assertIs(CompatibilityOverlay, LoadingOverlay)
        launcher = LauncherDialog()
        self.addCleanup(launcher.close)
        launcher.show()
        launcher.show_connection_overlay('正在连接设备')
        self.assertIsInstance(launcher._connection_overlay, LoadingOverlay)
        self.assertTrue(launcher._is_busy())
        self.assertTrue(launcher._connection_overlay.card.spinner._timer.isActive())
        launcher.hide_connection_overlay()
        self.assertFalse(launcher._is_busy())
        self.assertFalse(launcher._connection_overlay.card.spinner._timer.isActive())
        win = MainWindowShell()
        self.addCleanup(win.close)
        win.show()
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            win.set_mode(mode, [])
            win.show_loading('处理中')
            self.assertIsInstance(win._overlay, LoadingOverlay)
            self.assertTrue(win._task_progress.isVisible())
            self.assertTrue(win._overlay.card.spinner._timer.isActive())
            win.hide_loading()
            self.assertFalse(win._task_progress.isVisible())
            self.assertFalse(win._overlay.card.spinner._timer.isActive())


if __name__ == '__main__':
    unittest.main(verbosity=2)
