"""DB metadata, context operations and shared display-control integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QPushButton, QFormLayout
from core.frame_database import FrameDatabase, FrameRecord
from ui_v2.frame_database import FrameBrowser
from ui_v2 import MainWindowShell, GLOBAL_QSS


class PropertiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(GLOBAL_QSS)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = FrameDatabase('multi_cam', self.temp.name)
        sid = self.db.begin_session('测试会话')
        self.db.records['raw'] = FrameRecord('raw', sid, 'cam0', 1, 'calib', '测试原始帧',
            '2026-10-22T12:00:00', 100, [10, 10], markers=[{'id': 1}])
        self.db.records['result'] = FrameRecord('result', sid, 'merged', 2, '扫描', '测试拼接结果',
            '2026-10-22T12:01:00', 80, [0, 0], kind='result', source_ids=['raw'])
        self.browser = FrameBrowser(self.db)
        self.browser.resize(330, 620)
        self.browser.show()
        self.app.processEvents()

    def tearDown(self):
        self.browser.close()
        self.browser.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_metadata_for_cloud_image_result_group_and_clear_without_io(self):
        properties = self.browser.properties
        with patch.object(self.db, 'load_frame', side_effect=AssertionError('metadata must not read geometry')):
            self.browser.tree.setCurrentItem(self.browser._component_items['raw', 'cloud'])
            self.assertEqual(properties.values['文件点槽位'], '100')
            self.app.processEvents()
            for index in range(properties.form.rowCount()):
                label = properties.form.itemAt(index, QFormLayout.ItemRole.FieldRole).widget()
                self.assertGreaterEqual(label.height(), label.fontMetrics().height())
            self.assertGreater(properties.data_scroll.verticalScrollBar().maximum(), 0)
            self.assertIn('无效占位点', properties.values['点数说明'])
            self.assertNotIn('图像分辨率', properties.values)
            self.browser.tree.setCurrentItem(self.browser._component_items['raw', 'image'])
            self.assertEqual(properties.values['图像分辨率'], '10 × 10 px')
            self.assertTrue({'创建时间', '数据版本', '数据路径', '操作'}.isdisjoint(properties.values))
            self.assertNotIn('文件点槽位', properties.values)
            self.browser.tree.setCurrentItem(self.browser._items['result'])
            self.assertEqual(properties.values['有效点数'], '80')
            self.assertEqual(properties.values['来源帧数'], 1)
            self.browser.tree.setCurrentItem(self.browser.tree.topLevelItem(0))
            self.assertEqual(properties.values['关联帧 / 结果'], 2)
            self.browser.tree.clearSelection()
            self.assertIn('提示', properties.values)

    def test_right_click_updates_properties_and_delete_uses_existing_signal(self):
        self.assertNotIn('删除', [button.text() for button in self.browser.findChildren(QPushButton)])
        preview = QSignalSpy(self.browser.component_selected)
        deleted = QSignalSpy(self.browser.delete_requested)
        target = self.browser._component_items['raw', 'image']
        position = self.browser.tree.visualItemRect(target).center()
        def choose_delete():
            menu = self.app.activePopupWidget()
            next(action for action in menu.actions() if action.text() == '删除选中数据').trigger()
            menu.close()
        QTimer.singleShot(0, choose_delete)
        self.browser._context_menu(position)
        self.assertEqual(preview.count(), 0)
        self.assertEqual(deleted.at(0), [['raw']])
        self.assertEqual(self.browser.properties.values['类型'], '2D 图像')

    def test_multiselect_refresh_and_removal_do_not_show_stale_values(self):
        self.browser.tree.setCurrentItem(self.browser._items['raw'])
        self.browser._items['result'].setSelected(True)
        self.assertEqual(self.browser.properties.values['关联帧 / 结果'], 2)
        self.assertNotIn('操作', self.browser.properties.values)
        self.browser.refresh()
        self.assertEqual(self.browser.properties.values['选中项'], 2)
        self.db.records.clear()
        self.browser.refresh()
        self.assertEqual(self.browser.properties.values, {'提示': '请选择 DB 树中的数据'})


class DisplayPropertiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(GLOBAL_QSS)

    def setUp(self):
        self.win = MainWindowShell()
        self.win.resize(1600, 960)
        self.win.show()

    def tearDown(self):
        self.win._dirty = False
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def test_controls_follow_live_renderer_in_all_modes_and_after_switch(self):
        for mode, workspace in [('multi_cam', self.win.workspace_multi()),
                ('mobile_chain', self.win.workspace_mobile()), ('turntable', self.win.workspace_turntable())]:
            self.win.set_mode(mode, [])
            self.win.set_presentation('industrial')
            presentation = workspace._industrial
            panel = workspace.viewer if mode == 'turntable' else workspace._viewer
            properties = presentation.frame_browser.properties
            renderer = panel.viewer()
            self.assertIs(properties._renderer, renderer)
            self.assertTrue(renderer.toolbar.isHidden())
            properties.quality.setCurrentText('流畅')
            properties.color_mode.setCurrentText('高度着色')
            properties.point_size.setValue(5)
            properties.options['grid'].setChecked(False)
            self.assertEqual(renderer.quality.currentText(), '流畅')
            self.assertEqual(renderer.canvas.color_mode, '高度着色')
            self.assertEqual(renderer.canvas.point_size, 5)
            self.assertFalse(renderer.canvas.grid)
            renderer.point_size_control.setValue(3)
            self.assertEqual(properties.point_size.value(), 3)
            panel.set_point_size(4)
            panel.set_view_preset('top')
            self.assertEqual(properties.point_size.value(), 4)
            self.assertEqual(properties.view_preset.currentText(), '顶视')
            old_canvas = renderer.canvas
            with patch.object(old_canvas, 'render_failed', object(), create=True):
                renderer._fallback('测试兼容画布切换')
            self.assertIsNot(renderer.canvas, old_canvas)
            self.assertEqual(renderer.canvas.color_mode, '高度着色')
            self.assertEqual(renderer.canvas.point_size, 4)
            self.assertFalse(renderer.canvas.grid)
            properties.point_size.setValue(7)
            self.assertEqual(renderer.canvas.point_size, 7)
            self.win.set_presentation('classic')
            self.assertIsNone(properties._renderer)
            self.win.set_presentation('industrial')
            self.assertIs(properties._renderer, panel.viewer())
            self.assertIsNot(properties._renderer, renderer)
            properties.point_size.setValue(6)
            self.assertEqual(panel.viewer().canvas.point_size, 6)

    def test_maximize_can_restore_with_escape_when_sidebar_is_hidden(self):
        self.win.set_mode('multi_cam', [])
        self.win.set_presentation('industrial')
        presentation = self.win.workspace_multi()._industrial
        properties = presentation.frame_browser.properties
        properties.max_button.click()
        self.app.processEvents()
        self.assertTrue(presentation.side_column.isHidden())
        self.win.activateWindow()
        self.app.processEvents()
        QTest.keyClick(self.win, Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(presentation.side_column.isHidden())
        self.assertFalse(properties.max_button.isChecked())
