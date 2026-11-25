from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.app_state import AppState
from core.data_model import make_demo_project
from core.project import ProjectRepository


class DataModelTests(unittest.TestCase):
    def test_demo_tree_contains_all_workflow_groups(self):
        root = make_demo_project()
        project = root.children[0]
        self.assertEqual(7, len(project.children))
        self.assertEqual("Original_PointCloud", project.children[2].children[0].name)
        self.assertTrue(project.children[2].children[0].locked)

    def test_project_repository_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ProjectRepository()
            path = repository.create(Path(directory) / "project", "测量项目", "A17")
            self.assertEqual("测量项目", repository.load(path)["name"])
            self.assertTrue((path.parent / "database").is_dir())

    def test_app_state_emits_only_real_changes(self):
        state = AppState()
        modules = []
        state.module_changed.connect(modules.append)
        state.set_module("CAD 对比")
        state.set_module("CAD 对比")
        state.set_module("不存在的模块")
        self.assertEqual(["CAD 对比"], modules)


if __name__ == "__main__":
    unittest.main()
