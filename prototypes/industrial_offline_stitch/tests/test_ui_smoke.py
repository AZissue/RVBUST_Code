"""Offscreen industrial offline-stitch UI end-to-end test."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from ui_v2.theme import GLOBAL_QSS
from test_offline_workflow import make_dataset, StaticDetector
from app.window import OfflineStitchWindow


class OfflineStitchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        cls.app.setStyleSheet(GLOBAL_QSS)

    def wait(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail('UI operation timed out')
            time.sleep(.005)
        self.app.processEvents()

    def test_load_stitch_export_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            markers = make_dataset(folder)
            window = OfflineStitchWindow(detector=StaticDetector(markers))
            self.addCleanup(window.deleteLater)
            window.show()
            window.load_directory(folder)
            self.wait(lambda: len(window.pairs) == 2 and not window._busy)
            self.assertEqual(window.tree.topLevelItemCount(), 2)
            window.tree.setCurrentItem(window.tree.topLevelItem(0))
            try:
                self.wait(lambda: window.viewer._clouds.get('raw') is not None and not window._busy)
            except AssertionError:
                self.fail(window.status.text() + ' | ' + window.log_panel.toPlainText())
            first = window.start_stitch()
            second = window.start_stitch()
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.wait(lambda: window.workflow.last_result is not None and
                window.workflow.last_result.ok and not window._busy)
            self.assertTrue(window.btn_export.isEnabled())
            self.assertIsNotNone(window.viewer._merged)
            target = Path(folder) / 'ui_merged.ply'
            window.export_merged(str(target))
            self.wait(lambda: target.is_file() and not window._busy)
            window.clear_project()
            self.assertIsNone(window.workflow.last_result)
            self.assertEqual(window.viewer._clouds, {})
            self.assertIsNone(window.viewer._merged)
            window.close()

    def test_stool_workspace_and_compact_layout(self):
        window = OfflineStitchWindow()
        self.addCleanup(window.deleteLater)
        window.show()
        window.load_stool()
        self.wait(lambda: len(window.pairs) == 2 and not window._busy)
        window.start_stitch()
        self.wait(lambda: window.workflow.last_result is not None and
            window.workflow.last_result.ok and not window._busy)
        self.assertGreater(window.viewer.viewer().canvas.total_points, 0)
        output = ROOT / 'tmp_skill_logs' / 'industrial_offline_stitch'
        output.mkdir(parents=True, exist_ok=True)
        for width, height in ((1440, 900), (1050, 650)):
            window.resize(width, height)
            self.app.processEvents()
            self.assertTrue(window.tree.isVisible())
            self.assertTrue(window.viewer.isVisible())
            self.assertTrue(window.preview.isVisible())
            path = output / f'offline_{width}x{height}.png'
            self.assertTrue(window.grab().save(str(path)))
        window.close()

    def test_preview_failure_does_not_keep_previous_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            markers = make_dataset(folder)
            (Path(folder) / '2.ply').write_text('broken ply', encoding='utf-8')
            window = OfflineStitchWindow(detector=StaticDetector(markers))
            self.addCleanup(window.deleteLater)
            window.show()
            window.load_directory(folder)
            self.wait(lambda: len(window.pairs) == 2 and not window._busy)
            self.wait(lambda: window.viewer._clouds.get('raw') is not None and not window._busy)
            window.tree.setCurrentItem(window.tree.topLevelItem(1))
            self.wait(lambda: '2' in window.preview_info.text() and not window._busy)
            self.assertIsNone(window.viewer._clouds.get('raw'))
            self.assertIn('2', window.preview_info.text())
            window.close()

    def test_close_discards_queued_result_callbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            markers = make_dataset(folder)
            window = OfflineStitchWindow(detector=StaticDetector(markers))
            self.addCleanup(window.deleteLater)
            window.show()
            window.load_directory(folder)
            self.wait(lambda: len(window.pairs) == 2 and not window._busy)
            window.start_stitch()
            window.close()
            self.app.processEvents()
            self.assertTrue(window._closing)
            self.assertIsNone(window.viewer._merged)


if __name__ == '__main__':
    unittest.main()
