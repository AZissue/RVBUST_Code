import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QStyle, QStyleOptionFocusRect

import main
from src.ui.project_cards import PREVIEW_ROLE


class ProjectStartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_primary_controls_have_icons_in_both_windows(self):
        with TemporaryDirectory() as directory:
            start = main.create_start_window(Path(directory))
            self.addCleanup(start.close)
            for name in ("sessionFilesNav", "settingsNav", "newProject", "openProject"):
                self.assertFalse(start.findChild(QPushButton, name).icon().isNull(), name)
            start.open_project(None)
            workbench = start.workbench
            for name in ("backToProjects", "stagePreparation", "toggleSample", "resetView", "nextStage"):
                self.assertFalse(workbench.findChild(QPushButton, name).icon().isNull(), name)
            workbench.close()

    def test_application_style_suppresses_native_button_focus_rect(self):
        self.assertTrue(hasattr(main, "configure_ui"))
        main.configure_ui(self.app)
        button = QPushButton("Test")
        button.setCheckable(True)
        button.setChecked(True)
        before = QImage(80, 30, QImage.Format.Format_ARGB32)
        before.fill(0)
        image = before.copy()
        option = QStyleOptionFocusRect()
        option.initFrom(button)
        option.rect = image.rect()
        option.state |= QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_KeyboardFocusChange
        with QPainter(image) as painter:
            button.style().drawPrimitive(QStyle.PrimitiveElement.PE_FrameFocusRect, option, painter, button)
        self.assertEqual(image, before)

    def test_new_dialogs_use_dark_background_and_readable_text(self):
        main.configure_ui(self.app)
        dialog = QDialog()
        palette = dialog.palette()
        self.assertLess(palette.color(QPalette.ColorRole.Window).lightness(), 64)
        self.assertGreater(palette.color(QPalette.ColorRole.WindowText).lightness(), 192)

    def test_project_tree_preserves_expansion_and_model_visibility(self):
        with TemporaryDirectory() as directory:
            start = main.create_start_window(Path(directory))
            self.addCleanup(start.close)
            demo, = start.library.list_projects()
            start.open_project(demo)
            workbench = start.workbench
            reference = workbench.tree.topLevelItem(0)
            self.assertGreater(reference.font(0).weight(), reference.child(0).font(0).weight())
            workbench.tree.collapseItem(reference)
            self.assertFalse(reference.isExpanded())
            workbench.tree.expandItem(reference)
            self.assertTrue(reference.isExpanded())
            reference.child(0).setCheckState(0, Qt.CheckState.Unchecked)
            self.assertFalse(workbench.viewport.sample_visible)
            workbench.close()

    def test_sidebar_switches_between_session_files_and_settings(self):
        with TemporaryDirectory() as directory:
            start = main.create_start_window(Path(directory))
            self.addCleanup(start.close)
            project = start.library.create("轴套检测")
            start.refresh_projects()
            start.show()

            files = start.findChild(QPushButton, "sessionFilesNav")
            settings = start.findChild(QPushButton, "settingsNav")
            self.assertIsNotNone(files)
            self.assertIsNotNone(settings)
            self.assertTrue(files.isChecked())
            self.assertTrue(start.project_list.isVisible())
            self.assertGreater(settings.y(), files.y())

            settings.click()
            location = start.findChild(QLineEdit, "projectDirectory")
            self.assertTrue(settings.isChecked())
            self.assertTrue(location.isVisible())
            self.assertEqual(Path(location.text()), Path(directory))
            self.assertFalse(start.project_list.isVisible())

            files.click()
            self.assertTrue(start.project_list.isVisible())
            item, = start.project_list.findItems(project.name, Qt.MatchFlag.MatchExactly)
            start.project_list.setCurrentItem(item)
            start.findChild(QPushButton, "openSelectedProject").click()
            self.assertEqual(start.workbench.project, project)
            start.workbench.close()

    def test_startup_and_project_round_trip(self):
        with TemporaryDirectory() as directory:
            self.assertTrue(hasattr(main, "create_start_window"))
            start = main.create_start_window(Path(directory))
            self.addCleanup(start.close)
            start.show()
            self.assertTrue(start.isVisible())
            self.assertIsNone(start.workbench)

            project = start.library.create("轴套检测")
            start.open_project(project)
            workbench = start.workbench
            self.assertFalse(start.isVisible())
            self.assertIn("轴套检测", workbench.windowTitle())
            self.assertFalse(workbench.viewport.sample_visible)
            workbench.findChild(QPushButton, "backToProjects").click()
            self.assertTrue(start.isVisible())
            self.assertIn(project, start.library.list_projects())
            item, = start.project_list.findItems(project.name, Qt.MatchFlag.MatchExactly)
            start.project_list.itemActivated.emit(item)
            self.assertEqual(start.workbench.project, project)
            start.workbench.close()

    def test_demo_is_installed_and_opens_from_its_preview_card(self):
        with TemporaryDirectory() as directory:
            self.assertTrue(hasattr(main, "create_start_window"))
            start = main.create_start_window(Path(directory))
            self.addCleanup(start.close)
            start.show()
            self.assertIsNone(start.findChild(QPushButton, "openDemo"))
            demo, = start.library.list_projects()
            self.assertTrue(demo.path.is_file())
            self.assertEqual(demo.path.parent, Path(directory))
            card, = start.project_list.findItems(demo.name, Qt.MatchFlag.MatchExactly)
            self.assertFalse(card.data(PREVIEW_ROLE).isNull())
            start.project_list.itemActivated.emit(card)
            workbench = start.workbench
            self.assertEqual(workbench.project, demo)
            self.assertTrue(workbench.viewport.sample_visible)
            workbench.next_stage.click()
            self.assertEqual(workbench.stage_index, 1)
            workbench.close()
            reopened = main.create_start_window(Path(directory))
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.library.list_projects(), [demo])
