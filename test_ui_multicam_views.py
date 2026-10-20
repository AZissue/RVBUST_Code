"""Adaptive 2D layouts retain frame objects/action ports; dialogs use Chinese."""
import os
import sys
from pathlib import Path
import unittest
import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from ui_v2 import MainWindowShell
from ui_v2.widgets.device_table import DeviceInfo
from ui_v2.dialogs import ChineseMessageBox, localize_buttons
from core.frame_data import FrameData


class MulticamViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindowShell()
        self.win.resize(1600, 950)
        self.win.set_mode('multi_cam', [DeviceInfo(serial=str(i), backend_ref=i) for i in range(2)])
        self.win.set_presentation('industrial')
        self.ws = self.win.workspace_multi()
        self.presentation = self.ws._industrial
        self.grid = self.ws.camera_grid()
        self.win.show()
        self.flush()
        for cid in self.grid.camera_ids():
            self.grid.set_frame(cid, FrameData(1, cid, image_np=np.zeros((204, 244, 3), np.uint8)))
        self.flush()

    def flush(self):
        for _ in range(5):
            self.app.processEvents()

    def tearDown(self):
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def test_joint_stacks_two_cameras_and_uses_height_with_readable_controls(self):
        self.assertEqual(self.presentation._multi_view, 'joint')
        self.assertEqual(self.grid._last_cols, 1)
        cards = list(self.grid._cards.values())
        self.assertGreater(cards[1].y(), cards[0].y())
        bottom = cards[-1].y()+cards[-1].height()
        self.assertLess(abs(bottom-self.grid.viewport().height()), 16)
        self.assertGreater(self.ws.viewer().width(), self.grid.width())
        for card in cards:
            self.assertLess(card._marker_badge.y(), card._btn_capture.y())
            for button in (card._btn_preview, card._btn_capture, card._btn_detect):
                self.assertGreaterEqual(button.width(), 48)

    def test_view_modes_and_double_click_focus_keep_exact_frames_and_actions(self):
        original = {cid: card.current_frame() for cid, card in self.grid._cards.items()}
        capture = QSignalSpy(self.ws.card_capture_requested)
        # The production grid cards continue using their existing signal ports.
        for _ in range(2):
            self.presentation.view_buttons['2d'].click()
            self.flush()
            self.assertTrue(self.ws.viewer().isHidden())
            self.assertGreaterEqual(self.grid._last_cols, 2)
            self.presentation.view_buttons['3d'].click()
            self.assertTrue(self.grid.isHidden())
            self.assertFalse(self.ws.viewer().isHidden())
            self.presentation.view_buttons['joint'].click()
            self.flush()
        card = self.grid.card('cam0')
        spy = QSignalSpy(card.capture_requested)
        QTest.mouseDClick(card._thumb, Qt.LeftButton)
        self.flush()
        self.assertEqual(self.grid._focused_id, 'cam0')
        self.assertEqual(self.presentation._multi_view, '2d')
        self.assertTrue(self.grid.card('cam1').isHidden())
        self.presentation.all_cameras_button.click()
        self.flush()
        self.assertEqual(self.presentation._multi_view, 'joint')
        self.assertFalse(self.grid.card('cam1').isHidden())
        card.set_controls_enabled(True)
        card._btn_capture.click()
        self.assertEqual(spy.count(), 1)
        self.assertEqual(capture.count(), 1)
        for cid, frame in original.items():
            self.assertIs(self.grid.card(cid).current_frame(), frame)

    def test_many_cameras_scroll_and_classic_restore_without_stale_cards(self):
        self.grid.set_cameras([f'cam{i}' for i in range(6)])
        self.presentation.view_buttons['2d'].click()
        self.flush()
        self.assertEqual(len(self.grid._cards), 6)
        self.assertGreaterEqual(self.grid._last_cols, 2)
        for card in self.grid._cards.values():
            self.assertFalse(card.isHidden())
            self.assertGreaterEqual(card.height(), 210)
        self.presentation.set_multi_view('2d')
        self.win.set_presentation('classic')
        self.flush()
        for card in self.grid._cards.values():
            self.assertFalse(hasattr(card, '_overview_original'))
            self.assertEqual(card.minimumWidth(), 300)
        self.win.set_presentation('industrial')
        self.flush()
        self.assertEqual(self.presentation._multi_view, '2d')
        self.presentation.maximize(True)
        self.assertFalse(self.ws.viewer().isHidden())
        self.presentation.maximize(False)
        self.assertTrue(self.ws.viewer().isHidden())

    def test_save_dialog_labels_and_standard_result_flags_are_chinese(self):
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        localize_buttons(box)
        self.assertEqual(box.button(QDialogButtonBox.Save).text(), '保存')
        self.assertEqual(box.button(QDialogButtonBox.Cancel).text(), '取消')
        observed = []
        def cancel():
            dialog = self.app.activeModalWidget()
            observed.append([dialog.button(flag).text() for flag in (QMessageBox.Save, QMessageBox.Discard, QMessageBox.Cancel)])
            dialog.button(QMessageBox.Cancel).click()
        QTimer.singleShot(0, cancel)
        result = ChineseMessageBox.warning(self.win, '会话未保存', '保存或放弃修改？',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        self.assertEqual(result, QMessageBox.Cancel)
        self.assertEqual(observed, [['保存', '放弃修改', '取消']])


if __name__ == '__main__':
    unittest.main()
