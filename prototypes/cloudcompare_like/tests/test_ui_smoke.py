# -*- coding: utf-8 -*-
"""
K3 UI 冒烟测试（G-K3，offscreen，不涉 ROI）。

链路：载入 → DB 树 → 可见性切换 → 后处理应用 → 导出端到端。
导出判据 = 触发后文件落地（@lead 裁定：不用"连接数 ≥1"）。

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    QT_QPA_PLATFORM=offscreen python -m unittest prototypes.cloudcompare_like.tests.test_ui_smoke -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

# 包路径导入：与 tests/test_cc.py 同口径（项目根 + src/ 上 path）。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import open3d as o3d  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace
    _HAS_APP = True
    _APP_IMPORT_ERR = ""
except Exception as _e:  # PySide6/open3d-GUI 缺失时整组跳过
    _HAS_APP = False
    _APP_IMPORT_ERR = str(_e)


@unittest.skipUnless(_HAS_APP, f"app 层不可导入: {_APP_IMPORT_ERR}")
class TestUiSmokeExport(unittest.TestCase):
    """G-K3：导出端到端 + 取消/边界/覆盖/不污染撤销栈。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self._ws = CloudCompareWorkspace()
        self._logs: list[tuple[str, str]] = []
        self._ws.log_message.connect(lambda m, lvl: self._logs.append((lvl, m)))
        # 写出失败弹窗在 offscreen 下会阻塞，统一打桩为记录器（判据看记录内容）
        self._errors: list[tuple[str, str]] = []
        self._ws._notify_error = lambda title, msg: self._errors.append((title, msg))

    # ------------------------------------------------------------------ 工具
    def _load_one(self, directory: str, name: str = "a.ply", n: int = 200,
                  seed: int = 5, with_color: bool = True,
                  with_normals: bool = True) -> str:
        rng = np.random.default_rng(seed)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(rng.normal(size=(n, 3)))
        if with_color:
            pcd.colors = o3d.utility.Vector3dVector(rng.random((n, 3)))
        if with_normals:
            pcd.normals = o3d.utility.Vector3dVector(
                rng.normal(size=(n, 3)))
        path = os.path.join(directory, name)
        assert o3d.io.write_point_cloud(path, pcd)
        self._ws._load_files([path])
        return self._ws._workflow.list_cloud_nodes()[-1].node_id

    def _trigger_menu_export(self, node_id: str):
        """复刻用户右键 → 点「导出点云」（菜单动作真实触发，信号走真实接线）。"""
        item = self._ws._db_tree._node_items[node_id]
        menu = self._ws._db_tree._build_context_menu(item)
        acts = {a.text(): a for a in menu.actions()}
        self.assertIn("导出点云", acts)
        acts["导出点云"].trigger()

    def _save_dialog(self, path: str):
        """mock getSaveFileName：注入路径，绕过对话框。"""
        return mock.patch(
            "prototypes.cloudcompare_like.app.cc_workspace.QFileDialog.getSaveFileName",
            return_value=(path, "PLY 文件 (*.ply)"))

    # ------------------------------------------------------------ 端到端主链
    def test_export_end_to_end(self):
        """载入 → DB 树 → 可见性 → 后处理(法线估计) → 右键导出：文件落地+读回一致。"""
        from PySide6.QtCore import Qt
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d, n=200)
            out = os.path.join(d, "out.ply")

            # DB 树：文件/点云两级节点就位
            self.assertEqual(len(self._ws._workflow.list_cloud_nodes()), 1)
            self.assertIn(cid, self._ws._db_tree._node_items)

            # 可见性切换（取消勾选 → 视图移除 → 再勾回）
            self._ws._db_tree._node_items[cid].setCheckState(0, Qt.Unchecked)
            self.assertNotIn(cid, self._ws._viewer._clouds)
            self._ws._db_tree._node_items[cid].setCheckState(0, Qt.Checked)
            self.assertIn(cid, self._ws._viewer._clouds)

            # 后处理应用：法线估计（零法线 → 非零）
            node = self._ws._workflow.get_node(cid)
            node.pcd.normals = o3d.utility.Vector3dVector(
                np.zeros((200, 3)))
            ok, _ = self._ws._workflow.estimate_normals(cid)
            self.assertTrue(ok)
            norms = np.asarray(node.pcd.normals)
            self.assertGreater(np.abs(norms).sum(), 0, "法线估计应产生非零法线")
            colors_before = np.asarray(node.pcd.colors).copy()
            norms_before = norms.copy()

            # 不污染撤销栈：历史栈深+游标快照相等（K3-D1'：布尔对在有前置
            # 历史时恒真无判别力，栈深可捕获"导出误入历史"变异）
            hist_before = (len(self._ws._workflow._history),
                           self._ws._workflow._history_index)
            with self._save_dialog(out):
                self._trigger_menu_export(cid)

            # --- G-K3 判据：触发后文件落地 ---
            self.assertTrue(os.path.isfile(out), "导出后文件必须落地")
            with open(out, "rb") as f:
                self.assertEqual(f.read(4), b"ply\n", "PLY 头必须合法")
            back = o3d.io.read_point_cloud(out)
            self.assertEqual(len(back.points), 200, "读回点数须与节点一致")
            self.assertEqual(len(back.colors), 200, "颜色必须随节点写出")
            self.assertTrue(np.allclose(np.asarray(back.colors),
                                        colors_before, atol=2 / 255),
                            "读回颜色应与节点颜色一致（PLY uchar 量化容差）")
            self.assertEqual(len(back.normals), 200, "法线应随节点写出")
            # S1 口径：写出不得改变节点内数据
            self.assertTrue(np.allclose(np.asarray(node.pcd.normals),
                                        norms_before))
            # 不污染撤销栈
            self.assertEqual((len(self._ws._workflow._history),
                              self._ws._workflow._history_index), hist_before)
            # 成功日志可见（非静默）
            self.assertTrue(any(lvl == "success" and "已导出" in m
                                for lvl, m in self._logs))
            self.assertFalse(self._errors, "成功路径不应触发错误对话框")

    # ------------------------------------------------------------------ 取消
    def test_export_cancel_no_side_effect(self):
        """取消路径：无文件、无异常、无成功/错误日志。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            out = os.path.join(d, "cancelled.ply")
            with self._save_dialog(""):
                self._trigger_menu_export(cid)
            self.assertFalse(os.path.exists(out), "取消后不得产生文件")
            self.assertFalse(self._errors)
            self.assertFalse([1 for lvl, _ in self._logs if lvl in ("success", "error")],
                             "取消不得留下成功/错误日志")

    # ------------------------------------------------------------ 非法后缀兜底
    def test_export_bad_suffix_falls_back_to_ply(self):
        """G-K3：非法后缀兜底补 .ply + 日志明示（W9/W11 不静默替换口径）。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            bad = os.path.join(d, "out.txt")
            fixed = os.path.join(d, "out.ply")
            with self._save_dialog(bad):
                self._trigger_menu_export(cid)
            self.assertFalse(os.path.exists(bad))
            self.assertTrue(os.path.isfile(fixed), "兜底后 .ply 必须落地")
            self.assertTrue(any(lvl == "warn" and "已按 PLY 导出" in m
                                for lvl, m in self._logs),
                            "兜底替换必须在日志明示")

    # ------------------------------------------------------------ 写出失败明示
    def test_export_write_failure_notifies(self):
        """G-K3：写出失败 → 日志 + 对话框明示，禁吞异常。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            # 指向不存在目录下的文件 → open3d 写出失败
            bad_path = os.path.join(d, "no_such_dir", "out.ply")
            with self._save_dialog(bad_path):
                self._trigger_menu_export(cid)
            self.assertFalse(os.path.exists(bad_path))
            self.assertTrue(any(lvl == "error" for lvl, _ in self._logs),
                            "写出失败必须有 error 日志")
            self.assertEqual(len(self._errors), 1, "写出失败必须弹错误对话框")
            self.assertEqual(self._errors[0][0], "导出失败")

    # ------------------------------------------------------------ 覆盖 / 可重复
    def test_export_overwrite_same_path(self):
        """同一目标连导两次：直接覆盖，内容确实更新（非仅文件存在）。"""
        with tempfile.TemporaryDirectory() as d:
            cid_a = self._load_one(d, "a.ply", n=150, seed=6)
            out = os.path.join(d, "same.ply")
            with self._save_dialog(out):
                self._trigger_menu_export(cid_a)
            back = o3d.io.read_point_cloud(out)
            self.assertEqual(len(back.points), 150)

            cid_b = self._load_one(d, "b.ply", n=400, seed=7)
            with self._save_dialog(out):
                self._trigger_menu_export(cid_b)
            back2 = o3d.io.read_point_cloud(out)
            self.assertEqual(len(back2.points), 400,
                             "覆盖导出后读回应是第二次的内容")

    # ------------------------------------------------------------ file 节点边界
    def test_export_file_node_rejected(self):
        """file 节点走导出入口 → 明示拒绝（warn 日志），不产生文件。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            file_id = self._ws._workflow.get_node(cid).parent_id
            self.assertIsNotNone(file_id)
            with self._save_dialog(os.path.join(d, "x.ply")):
                self._ws._on_export_node(file_id)
            self.assertTrue(any(lvl == "warn" for lvl, _ in self._logs),
                            "file 节点导出必须 warn 明示")
            self.assertFalse([f for f in os.listdir(d) if f == "x.ply"])


if __name__ == "__main__":
    unittest.main()
