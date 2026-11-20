import _bootstrap
import unittest
from PySide6.QtWidgets import QApplication, QWidget


class FailureTests(unittest.TestCase):
    def test_actionable_nonblocking_dialog_and_automatic_suppression(self):
        from ui_v2.operation_failure import show_operation_failure, failure_advice
        app = QApplication.instance() or QApplication([])
        owner = QWidget()
        logs = []
        self.assertIsNone(show_operation_failure(owner, '加载失败', ValueError('文件损坏'),
            log=lambda *args: logs.append(args), automatic=True))
        self.assertFalse(hasattr(owner, '_operation_failure_dialog'))
        box = show_operation_failure(owner, '导出失败', OSError('disk full'))
        self.assertTrue(box.isVisible())
        self.assertIn('disk full', box.text())
        self.assertIn('磁盘', box.informativeText())
        self.assertIs(show_operation_failure(owner, '处理失败', '重叠不足'), box)
        self.assertIn('重叠', failure_advice('重叠不足'))
        self.assertEqual(len(logs), 1)
        self.assertIn('普通圆点', failure_advice('识别失败', 'unencoded_circle'))
        self.assertIn('2D特征', failure_advice('识别失败', 'feature'))
        box.close()
        owner.close()
        app.processEvents()
