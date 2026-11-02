"""New-round action resets acquisition without discarding calibration or DB."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent/'src'))
from PySide6.QtWidgets import QApplication, QMessageBox
from ui_v2.workspaces.turntable_workspace import TurntableWorkspace

class NewRoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_restart_preserves_calibration_and_enables_capture(self):
        w=TurntableWorkspace()
        w._is_connected=lambda: True
        w.session.apply_calibration([0,0,1], [0,0,0], 90, 4)
        calibration=w.session.calib
        frame=Mock()
        w.session.sequence=[frame]
        w.session.sequence_pcds=[None]
        w.session.current_step=w.session.total_steps_needed()
        w._update_online_ui()
        self.assertFalse(w.btn_capture_step.isEnabled())
        with patch('ui_v2.workspaces.turntable_workspace.QMessageBox.question', return_value=QMessageBox.Yes):
            w._on_clear_sequence_data()
        self.assertIs(w.session.calib,calibration)
        self.assertEqual(w.session.current_step,0)
        self.assertEqual(w.session.sequence,[])
        self.assertTrue(w.btn_capture_step.isEnabled())
        frame.release.assert_called_once()
        w.close()

    def test_cancel_leaves_round_unchanged(self):
        w=TurntableWorkspace()
        frame=Mock();w.session.sequence=[frame];w.session.current_step=4
        with patch('ui_v2.workspaces.turntable_workspace.QMessageBox.question', return_value=QMessageBox.No):
            w._on_clear_sequence_data()
        self.assertEqual(w.session.current_step,4)
        frame.release.assert_not_called()
        w.close()

if __name__=='__main__':unittest.main()
