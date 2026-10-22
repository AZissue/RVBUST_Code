"""Component checks remain independent of preview, deletion and DB persistence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication
from core.frame_database import FrameDatabase, FrameRecord
from ui_v2.frame_database import FrameBrowser
from ui_v2 import GLOBAL_QSS


class ComponentCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(GLOBAL_QSS)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.browser = None

    def tearDown(self):
        if self.browser:
            self.browser.close()
            self.browser.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def database(self, mode='multi_cam'):
        db = FrameDatabase(mode, self.temp.name)
        sid = db.begin_session('测试会话')
        for uid, number, kind in [('raw', 1, 'raw'), ('result', 2, 'result')]:
            db.records[uid] = FrameRecord(uid, sid, 'cam0', number, 'calib', uid,
                '2026-10-22T12:00:00', 100, [10, 10], kind=kind)
        return db

    def show_browser(self, db):
        self.browser = FrameBrowser(db)
        self.browser.resize(410, 650)
        self.browser.show()
        self.app.processEvents()
        return self.browser

    def test_all_modes_offer_independent_components_without_loading_or_mutating_data(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            with self.subTest(mode=mode):
                db = self.database(mode)
                browser = self.show_browser(db)
                before = db.snapshot()
                changed = QSignalSpy(browser.checked_components_changed)
                with patch.object(db, 'load_frame', side_effect=AssertionError('no geometry IO')):
                    self.assertEqual(browser.checked_components(), [])
                    browser.set_component_checked('raw', 'image')
                    browser.set_component_checked('result', 'cloud')
                    self.assertEqual(browser.checked_components(), [('raw', 'image'), ('result', 'cloud')])
                    self.assertEqual(browser.checked_components('cloud'), [('result', 'cloud')])
                    self.assertEqual(browser.checked_components('image'), [('raw', 'image')])
                    self.assertEqual(changed.count(), 2)
                    browser.set_component_checked('raw', 'image')
                    self.assertEqual(changed.count(), 2)
                    self.assertNotIn(('result', 'image'), browser._component_items)
                    self.assertEqual(db.snapshot(), before)
                browser.close(); browser.deleteLater(); self.app.processEvents()
                self.browser = None

    def test_checks_survive_refresh_but_removed_components_and_replaced_databases_reset(self):
        db = self.database()
        browser = self.show_browser(db)
        browser.set_component_checked('raw', 'cloud')
        changed = QSignalSpy(browser.checked_components_changed)
        browser.refresh()
        self.assertEqual(browser.checked_components(), [('raw', 'cloud')])
        self.assertEqual(changed.count(), 0)
        removed = db.records.pop('raw')
        browser.refresh()
        self.assertEqual(browser.checked_components(), [])
        self.assertEqual(changed.count(), 1)
        db.records['raw'] = removed
        browser.refresh()
        self.assertEqual(browser.checked_components(), [])
        browser.set_component_checked('raw', 'image')
        browser.database = self.database()
        self.assertEqual(browser.checked_components(), [])
        browser.refresh()
        self.assertEqual(browser.checked_components(), [])
        self.assertEqual(changed.at(changed.count() - 1)[0], [])

    def test_mouse_check_keeps_preview_and_highlight_selection_unchanged(self):
        browser = self.show_browser(self.database())
        tree = browser.tree
        tree.setCurrentItem(browser._items['result'])
        before = browser.selected_ids()
        frames, components = QSignalSpy(browser.frame_selected), QSignalSpy(browser.component_selected)
        changed = QSignalSpy(browser.checked_components_changed)
        item = browser._component_items['raw', 'cloud']
        tree.scrollToItem(item)
        self.app.processEvents()
        index = tree.indexFromItem(item)
        rect = browser._check_delegate.check_rect(index)
        self.assertFalse(rect.isEmpty())
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(browser.checked_components(), [('raw', 'cloud')])
        self.assertEqual(browser.selected_ids(), before)
        self.assertEqual(frames.count() + components.count(), 0)
        self.assertEqual(changed.count(), 1)
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(browser.checked_components(), [])
        # Clicking the text still previews the component, while Space checks it.
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(rect.right() + 30, rect.center().y()))
        self.assertEqual(components.count(), 1)
        QTest.keyClick(tree, Qt.Key_Space)
        self.assertEqual(browser.checked_components(), [('raw', 'cloud')])
        self.assertEqual(components.count(), 1)
        self.assertEqual(browser.selected_ids(), ['raw'])

    def test_blank_click_clears_current_cell_and_selection_but_keeps_checks(self):
        browser = self.show_browser(self.database())
        tree = browser.tree
        browser.set_component_checked('raw', 'cloud')
        browser.set_component_checked('raw', 'image')
        tree.setCurrentItem(browser._component_items['raw', 'cloud'])
        browser._items['result'].setSelected(True)
        frames, components = QSignalSpy(browser.frame_selected), QSignalSpy(browser.component_selected)
        checks = QSignalSpy(browser.checked_components_changed)
        QTest.mouseClick(tree.viewport(), Qt.LeftButton,
                         pos=QPoint(15, tree.viewport().height()-10))
        self.app.processEvents()
        self.assertEqual(tree.selectedItems(), [])
        self.assertIsNone(tree.currentItem())
        self.assertFalse(tree.currentIndex().isValid())
        self.assertEqual(browser.checked_components(), [('raw', 'cloud'), ('raw', 'image')])
        self.assertEqual(frames.count()+components.count()+checks.count(), 0)
        self.assertIn('提示', browser.properties.values)
        tree.setCurrentItem(browser._items['raw'])
        tree.clearSelection()
        self.assertIsNone(tree.currentItem())


if __name__ == '__main__':
    unittest.main()
