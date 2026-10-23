"""Single-node DB export routing, gates and read-only overlay behavior."""
import unittest
from pathlib import Path
from unittest.mock import patch
import test_ui_frame_database as fixture
from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from core.frame_database import STALE_RESULT


class DbExportTests(unittest.TestCase):
    setUpClass = classmethod(fixture.FrameBrowserTests.setUpClass.__func__)
    setUp = fixture.FrameBrowserTests.setUp
    tearDown = fixture.FrameBrowserTests.tearDown
    source = fixture.FrameBrowserTests.source
    wait = fixture.FrameBrowserTests.wait

    def highlight(self, uid, component='cloud'):
        with QSignalBlocker(self.browser.tree):
            item = self.browser._items[uid] if component is None else self.browser._component_items[uid, component]
            self.browser.tree.setCurrentItem(item)
        self.browser._selection_changed()

    def test_toolbar_exports_selected_raw_instead_of_latest_result(self):
        uid = self.db.ingest(self.source())
        _, cloud = self.db.load_frame(uid, 'cloud')
        self.db.publish_result(cloud, [uid])
        self.highlight(uid)
        command = self.win._industrial_ribbon.commands['multi_cam', 'export']
        self.assertTrue(command.isEnabled())
        output = Path(self.temp.name)/'raw export'
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=(str(output), '')), \
                patch.object(self.db, 'load_frame', side_effect=AssertionError('export must copy the stored file')):
            command.click()
            self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
        self.assertEqual(output.with_suffix('.ply').read_bytes(), fixture.PLY)

    def test_checked_cloud_exports_without_clearing_overlay(self):
        uid = self.db.ingest(self.source())
        self.browser.set_component_checked(uid, 'cloud')
        panel = self.win.workspace_multi().viewer()
        self.wait(lambda: bool(panel._database_clouds))
        self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
        original = dict(panel._database_clouds)
        self.highlight(uid, 'image')
        output = Path(self.temp.name)/'checked.ply'
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=(str(output), '')):
            self.win._industrial_ribbon.commands['multi_cam', 'export'].click()
            self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
        self.assertEqual(output.read_bytes(), fixture.PLY)
        self.assertEqual(panel._database_clouds, original)
        self.assertEqual(self.browser.checked_components('cloud'), [(uid, 'cloud')])

    def test_multiple_image_and_stale_selections_do_not_fall_back(self):
        uid = self.db.ingest(self.source())
        other = self.db.ingest(self.source(2))
        _, cloud = self.db.load_frame(uid, 'cloud')
        result = self.db.publish_result(cloud, [uid])
        self.highlight(uid)
        self.browser._items[other].setSelected(True)
        self.assertIsNone(self.browser.export_uid())
        self.highlight(uid, 'image')
        self.assertIsNone(self.browser.export_uid())
        self.db.records[result].status = STALE_RESULT
        self.highlight(result)
        self.assertFalse(self.win._industrial_ribbon.commands['multi_cam', 'export'].isEnabled())
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName') as dialog:
            self.bridge.stitching.export()
            dialog.assert_not_called()

    def test_right_click_exports_raw_without_loading_preview(self):
        first = self.db.ingest(self.source())
        source = self.source(2)
        data = Path(source.offline_pointmap_path).read_bytes().replace(b'format ascii 1.0\n', b'format ascii 1.0\ncomment second frame\n')
        Path(source.offline_pointmap_path).write_bytes(data)
        uid = self.db.ingest(source)
        self.highlight(first)
        self.browser._component_items[uid, 'cloud'].setSelected(True)
        self.assertIsNone(self.browser.export_uid())
        item = self.browser._component_items[uid, 'cloud']
        position = self.browser.tree.visualItemRect(item).center()
        output = Path(self.temp.name)/'context.ply'
        def activate():
            menu = self.app.activePopupWidget()
            try:
                next(action for action in menu.actions() if action.text().startswith('导出此点云')).trigger()
            finally:
                menu.close()
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=(str(output), '')), \
                patch.object(self.db, 'load_frame', side_effect=AssertionError('no preview IO')):
            QTimer.singleShot(0, activate)
            self.browser._context_menu(position)
            self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
        self.assertEqual(output.read_bytes(), data)

    def test_cancel_and_write_failure_leave_db_unchanged(self):
        uid = self.db.ingest(self.source())
        self.highlight(uid)
        before = self.db.snapshot()
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=('', '')), \
                patch.object(self.db, 'export_cloud') as export:
            self.bridge.stitching.export()
            export.assert_not_called()
        output = Path(self.temp.name)/'failure.ply'
        with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=(str(output), '')), \
                patch.object(self.db, 'export_cloud', side_effect=IOError('disk full')):
            self.bridge.stitching.export()
            self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
        self.assertEqual(before, self.db.snapshot())
        self.assertFalse(output.exists())

    def test_raw_and_derived_nodes_export_in_all_three_modes(self):
        for mode in ('multi_cam', 'mobile_chain', 'turntable'):
            self.bridge._current_mode = mode
            self.win.set_mode(mode, [])
            self.win.set_presentation('industrial')
            self.db = self.bridge.frame_db.databases[mode]
            self.browser = self.win._stack.currentWidget()._industrial.frame_browser
            uid = self.db.ingest(self.source())
            self.db.records[uid].kind = 'postprocessed'
            self.db.records[uid].logical_name = '后处理分支'
            self.browser.refresh()
            self.highlight(uid)
            output = Path(self.temp.name)/(mode+'.ply')
            with patch('ui_v2.explicit_stitching.QFileDialog.getSaveFileName', return_value=(str(output), '')):
                self.win._industrial_ribbon.commands[mode, 'export'].click()
                self.wait(lambda: not any(worker.isRunning() for worker in self.bridge._workers))
            self.assertEqual(output.read_bytes(), fixture.PLY)
