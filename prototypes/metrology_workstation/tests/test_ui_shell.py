from __future__ import annotations

import tempfile
import unittest

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from app.application import create_application
from app.main_window import MainWindow
from core.data_model import make_demo_project
from ui.project_tree import ProjectTreeModel
from ui.property_panel import MODULE_INFO


class ProjectTreeModelTests(unittest.TestCase):
    def test_rename_visibility_lock_and_move(self):
        model = ProjectTreeModel(make_demo_project())
        project = model.root.children[0]
        cloud = project.children[2].children[1]
        index = model.index_for_node(cloud)
        self.assertTrue(model.setData(index, "Aligned_Cloud"))
        self.assertEqual("Aligned_Cloud", cloud.name)
        self.assertTrue(model.setData(index, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole))
        self.assertFalse(cloud.visible)
        model.set_locked(cloud, True)
        self.assertFalse(model.setData(index, "Blocked"))
        self.assertEqual("Aligned_Cloud", cloud.name)
        target = project.children[3]
        mime = model.mimeData([index])
        self.assertTrue(model.dropMimeData(mime, Qt.DropAction.MoveAction, -1, 0, model.index_for_node(target)))
        self.assertEqual(target, cloud.parent)


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or create_application([])
        cls.tempdir = tempfile.TemporaryDirectory()
        settings = QSettings(str(cls.tempdir.name) + "/settings.ini", QSettings.Format.IniFormat)
        cls.window = MainWindow(settings)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.state.mark_saved(True)
        cls.window.close()
        cls.app.processEvents()
        cls.tempdir.cleanup()

    def test_01_viewport_is_persistent_across_modules(self):
        viewport = self.window.viewport
        renderer = viewport.renderer
        for module in self.window.state.MODULES:
            self.window.state.set_module(module)
            self.app.processEvents()
            self.assertIs(viewport, self.window.viewport)
            self.assertIs(renderer, self.window.viewport.renderer)
            self.assertEqual(MODULE_INFO[module][0], self.window.property_panel.module_name.text())

    def test_02_project_selection_updates_properties_and_scene(self):
        project = self.window.project_tree.model.root.children[0]
        cloud = project.children[2].children[1]
        self.window.project_tree.select_node(cloud)
        self.app.processEvents()
        self.assertIs(cloud, self.window.property_panel.current_node)
        self.assertEqual(1, self.window.property_panel.stack.currentIndex())
        self.assertTrue(self.window.viewport.scene.actor("cloud_fused").GetVisibility())

    def test_03_tree_check_controls_scene_visibility(self):
        project = self.window.project_tree.model.root.children[0]
        cloud = project.children[2].children[1]
        index = self.window.project_tree.model.index_for_node(cloud)
        self.window.project_tree.model.setData(index, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
        self.assertFalse(self.window.viewport.scene.actor("cloud_fused").GetVisibility())
        self.window.project_tree.model.setData(index, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
        self.assertTrue(self.window.viewport.scene.actor("cloud_fused").GetVisibility())

    def test_04_engineer_mode_exposes_advanced_parameters(self):
        project = self.window.project_tree.model.root.children[0]
        cloud = project.children[2].children[1]
        self.window.property_panel.set_node(cloud)
        self.window.state.set_mode("工程师")
        self.assertTrue(self.window.property_panel.engineer_group.isVisibleTo(self.window.property_panel))
        self.window.state.set_mode("工作站")
        self.assertFalse(self.window.property_panel.engineer_group.isVisibleTo(self.window.property_panel))

    def test_05_docks_can_hide_and_restore(self):
        for dock in (self.window.project_dock, self.window.property_dock, self.window.task_dock):
            dock.hide()
            self.assertFalse(dock.isVisible())
            dock.show()
            self.app.processEvents()
            self.assertTrue(dock.isVisible())

    def test_06_window_can_resize(self):
        self.window.resize(1280, 760)
        self.app.processEvents()
        self.assertEqual(1280, self.window.width())
        self.assertGreaterEqual(self.window.viewport.width(), 500)


if __name__ == "__main__":
    unittest.main()
