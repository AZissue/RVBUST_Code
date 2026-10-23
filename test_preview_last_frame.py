"""Stopping mobile preview freezes its image; reset and camera changes still clear it."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication
from ui_v2 import MainWindowShell
from ui_v2.backend_bridge import BackendBridge
from ui_v2.widgets.device_table import DeviceInfo


class PreviewThread(QObject):
    frame_ready = Signal(object)

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.start = Mock()
        self.stop = Mock()


class LastFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindowShell()
        self.bridge = BackendBridge(self.window)
        self.bridge.wire_all()
        self.devices = [DeviceInfo(serial='ONE', backend_ref=0)]
        self.window.set_mode('mobile_chain', self.devices)
        self.window.set_presentation('industrial')
        self.ws = self.window.workspace_mobile()
        self.button = self.window._industrial_ribbon.commands['mobile_chain', 'preview']
        self.bridge.camera_manager.get_connected_ids = Mock(return_value=['cam0'])
        self.patcher = patch('ui_v2.backend_bridge.PreviewCaptureThread', PreviewThread)
        self.patcher.start()

    def tearDown(self):
        self.bridge.cleanup()
        self.patcher.stop()
        self.window._dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def start_frame(self, color='red'):
        self.button.click()
        thread = self.bridge._preview_thread
        pixmap = QPixmap(64, 48)
        pixmap.fill(QColor(color))
        thread.frame_ready.emit(pixmap)
        return thread, pixmap

    def test_stop_retains_last_frame_and_rejects_old_thread_frames_after_restart(self):
        old, pixmap = self.start_frame()
        self.button.click()
        old.stop.assert_called_once()
        self.assertIsNone(self.bridge._preview_thread)
        self.assertFalse(self.button.isChecked())
        self.assertEqual(self.ws.live_view()._current_pixmap.cacheKey(), pixmap.cacheKey())
        image = self.ws._industrial.inspector.image_view.image
        self.assertEqual(image.pixelColor(0, 0), QColor('red'))
        late = QPixmap(64, 48)
        late.fill(QColor('blue'))
        old.frame_ready.emit(late)
        self.assertEqual(self.ws.live_view()._current_pixmap.cacheKey(), pixmap.cacheKey())
        current, green = self.start_frame('green')
        old.frame_ready.emit(late)
        self.assertEqual(self.ws.live_view()._current_pixmap.cacheKey(), green.cacheKey())

    def test_capture_pause_retains_image_and_explicit_clear_still_clears(self):
        _, pixmap = self.start_frame()
        camera = self.bridge._pause_2d_preview()
        self.assertEqual(camera, 'cam0')
        self.assertEqual(self.ws.live_view()._current_pixmap.cacheKey(), pixmap.cacheKey())
        self.bridge._stop_preview_thread()
        self.assertIsNone(self.ws.live_view()._current_pixmap)
        self.assertTrue(self.ws._industrial.inspector.image_view.image.isNull())

    def test_new_session_and_device_change_clear_retained_image(self):
        self.start_frame()
        self.button.click()
        self.bridge.projects.reset_workflow('mobile_chain')
        self.assertIsNone(self.ws.live_view()._current_pixmap)
        self.start_frame()
        with patch.object(self.bridge, '_ensure_sdk', return_value=True), \
                patch.object(self.bridge, '_run_background'):
            self.bridge._on_device_manager_reopened('mobile_chain', self.devices, show_loading=False)
        self.assertIsNone(self.ws.live_view()._current_pixmap)


if __name__ == '__main__':
    unittest.main()
