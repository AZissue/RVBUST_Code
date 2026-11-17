# -*- coding: utf-8 -*-
"""
K4 UI 级验证（G-S5-lite 续）：裁切 / ROI 保留剔除 / 门禁 / 工具栏灰显。

口径（`docs/后处理原型实现方案与实施路径_20260924.md` §10.15）：
  - ROI 保留 / 剔除产出**新节点**，源节点几何/属性不被改写，且**入历史**。
  - 裁切三档（AABB/球/OBB）走 UI 入口 → workflow，且可撤销。
  - 工具栏 `set_undo_enabled`/`set_redo_enabled` **落实现**（K3 遗留①）。
  - 导出默认名清洗（K3 遗留②）。
  - W9：ROI 降级原因必须经 `_log(warning)` 上报 + 面板可见，禁静默。

**ROI 选区在 offscreen 下无 GL**，无法靠真实拖框产生选区；本文件按 K4 口径
用「注入 viewer 选区状态」的方式测**选区之后的全部接线**（掩码构造 → 派生 →
历史 → 树/视图同步），投影与深度分支本身由 `test_cc_k4.py` 的纯函数组覆盖。

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    QT_QPA_PLATFORM=offscreen python -m unittest prototypes.cloudcompare_like.tests.test_ui_k4 -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

import numpy as np

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
except Exception as _e:
    _HAS_APP = False
    _APP_IMPORT_ERR = str(_e)


@unittest.skipUnless(_HAS_APP, f"app 层不可导入: {_APP_IMPORT_ERR}")
class _K4UiBase(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self._ws = CloudCompareWorkspace()
        self._logs: list[tuple[str, str]] = []
        self._ws.log_message.connect(lambda m, lvl: self._logs.append((lvl, m)))
        self._ws._notify_error = lambda title, msg: self._logs.append(("dialog", msg))
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _load(self, name: str = "a.ply", n: int = 400, seed: int = 3) -> str:
        rng = np.random.default_rng(seed)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(rng.normal(size=(n, 3)) * 10.0)
        pcd.colors = o3d.utility.Vector3dVector(rng.random((n, 3)))
        path = os.path.join(self._tmp.name, name)
        assert o3d.io.write_point_cloud(path, pcd)
        self._ws._load_files([path])
        return self._ws._workflow.list_cloud_nodes()[-1].node_id

    def _inject_roi(self, node_id: str, indices):
        """注入 viewer 的 ROI 选区（等价于用户框选后 _compute_roi_selection 的结果）。"""
        self._ws._viewer._roi_selected_indices = {
            node_id: np.asarray(indices, dtype=np.int64)}
        self._ws._viewer._roi_last_error = None

    def _has_log(self, level: str, needle: str) -> bool:
        return any(lvl == level and needle in m for lvl, m in self._logs)


# ===========================================================================
# 裁切（UI 入口 → workflow）
# ===========================================================================
class TestCropWiring(_K4UiBase):
    def test_crop_via_ui_enters_history_and_can_undo(self):
        nid = self._load(n=400)
        n0 = len(self._ws._workflow.get_node(nid).pcd.points)
        params = self._ws._props.get_process_params()
        params.update({"crop_mode": "sphere", "crop_radius": 5.0})
        self._ws._on_apply_process(params)
        n1 = len(self._ws._workflow.get_node(nid).pcd.points)
        self.assertLess(n1, n0, "球裁切未生效")
        self.assertTrue(self._ws._workflow.can_undo(), "裁切必须进撤销历史")
        self.assertTrue(self._ws._toolbar.is_undo_enabled(),
                        "工具栏撤销键未随历史解锁（K3 遗留①）")
        self._ws._on_undo()
        self.assertEqual(len(self._ws._workflow.get_node(nid).pcd.points), n0,
                         "撤销未恢复原点数")

    def test_aabb_and_obb_reach_workflow(self):
        nid = self._load(n=300)
        n0 = len(self._ws._workflow.get_node(nid).pcd.points)
        for mode in ("aabb", "obb"):
            params = self._ws._props.get_process_params()
            params.update({"crop_mode": mode, "crop_ratio": 0.4})
            self._ws._on_apply_process(params)
            cur = len(self._ws._workflow.get_node(nid).pcd.points)
            self.assertLess(cur, n0, f"{mode} 裁切未生效")
            self._ws._on_undo()
            n0 = len(self._ws._workflow.get_node(nid).pcd.points)

    def test_invalid_crop_param_rejected_with_readable_log(self):
        nid = self._load(n=200)
        params = self._ws._props.get_process_params()
        params.update({"crop_mode": "aabb", "crop_ratio": 0.0})
        self._ws._on_apply_process(params)
        self.assertTrue(self._has_log("warn", "裁切比例"), self._logs)
        self.assertFalse(self._ws._workflow.can_undo(),
                         "非法参数不应进历史")

    def test_no_selection_apply_warns(self):
        self._load(n=100)
        self._ws._current_node_id = None
        self._ws._on_apply_process(self._ws._props.get_process_params())
        self.assertTrue(self._has_log("warn", "请先选择点云"), self._logs)


# ===========================================================================
# P0-B：参数可见且默认不剔点
# ===========================================================================
class TestProcessParamsVisible(_K4UiBase):
    def test_panel_defaults_to_outlier_removal_off(self):
        """P0-B：面板复选框默认不勾，且与 workflow.processor 一致。"""
        self._load(n=300)
        self.assertFalse(self._ws._props._chk_outlier.isChecked(),
                         "P0-B：离群点去除必须默认关闭（守 D1 契约）")
        self.assertFalse(self._ws._workflow.processor.enable_outlier_removal)

    def test_ui_shows_actual_processor_values(self):
        """面板显示值 = workflow.processor 真实值（单一真相源，不许漂移）。"""
        self._load(n=300)
        self._ws._workflow.processor.enable_outlier_removal = True
        self._ws._workflow.processor.outlier_nb_neighbors = 33
        self._ws._workflow.processor.outlier_std_ratio = 1.25
        self._ws._update_properties()
        self.assertTrue(self._ws._props._chk_outlier.isChecked())
        self.assertEqual(self._ws._props._spin_outlier_nb.value(), 33)
        self.assertAlmostEqual(self._ws._props._spin_outlier_std.value(), 1.25, places=6)

    def test_disabled_operators_leave_cloud_unchanged(self):
        """D1 回归（P0-B 触点）：未启用任何算子 → 点数逐点不变 + 不入历史。"""
        nid = self._load(n=500)
        before = np.asarray(self._ws._workflow.get_node(nid).pcd.points).copy()
        params = self._ws._props.get_process_params()
        self.assertEqual(params["crop_mode"], "none")
        self.assertFalse(params["enable_outlier_removal"])
        self._ws._on_apply_process(params)
        after = np.asarray(self._ws._workflow.get_node(nid).pcd.points)
        self.assertEqual(len(after), len(before),
                         "未启用算子却改了点云（P0-B 回归）")
        np.testing.assert_array_equal(after, before)
        self.assertFalse(self._ws._workflow.can_undo(),
                         "无操作却压了历史（D1 回归）")


# ===========================================================================
# ROI 保留 / 剔除
# ===========================================================================
class TestRoiWiring(_K4UiBase):
    def test_keep_creates_new_node_source_untouched(self):
        nid = self._load(n=400)
        src_before = np.asarray(self._ws._workflow.get_node(nid).pcd.points).copy()
        self._inject_roi(nid, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        self._ws._on_roi_keep()

        nodes = self._ws._workflow.list_cloud_nodes()
        self.assertEqual(len(nodes), 2, "保留未产出新节点")
        new_id = next(n.node_id for n in nodes if n.node_id != nid)
        self.assertEqual(len(self._ws._workflow.get_node(new_id).pcd.points), 10)
        # 源节点逐点不变
        np.testing.assert_array_equal(
            np.asarray(self._ws._workflow.get_node(nid).pcd.points), src_before)
        # 树同步
        self.assertIn(new_id, self._ws._db_tree._node_items)
        self.assertEqual(self._ws._current_node_id, new_id, "未选中新节点")
        self.assertTrue(self._has_log("success", "ROI 保留"), self._logs)

    def test_remove_keeps_complement(self):
        nid = self._load(n=400)
        self._inject_roi(nid, list(range(40)))
        self._ws._on_roi_remove()
        nodes = self._ws._workflow.list_cloud_nodes()
        new_id = next(n.node_id for n in nodes if n.node_id != nid)
        self.assertEqual(len(self._ws._workflow.get_node(new_id).pcd.points), 360)

    def test_roi_operation_enters_history_with_new_node_kind(self):
        nid = self._load(n=200)
        self._inject_roi(nid, [0, 1, 2])
        self._ws._on_roi_keep()
        hist = self._ws._workflow._history
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["kind"], "create",
                         "ROI 派生必须登记 create 型历史（否则撤销无处落脚）")

    def test_undo_removes_new_node_from_tree_and_view(self):
        nid = self._load(n=200)
        self._inject_roi(nid, [0, 1, 2, 3])
        self._ws._on_roi_keep()
        new_id = [n.node_id for n in self._ws._workflow.list_cloud_nodes()
                  if n.node_id != nid][0]
        self.assertIn(new_id, self._ws._db_tree._node_items)
        self._ws._on_undo()
        self.assertIsNone(self._ws._workflow.get_node(new_id))
        self.assertNotIn(new_id, self._ws._db_tree._node_items,
                         "撤销后树里残留幽灵节点（W12）")
        self.assertNotIn(new_id, self._ws._viewer._clouds,
                         "撤销后 3D 视图仍渲染被撤销的节点")
        self.assertEqual(self._ws._current_node_id, nid)

    def test_redo_restores_new_node_in_tree(self):
        nid = self._load(n=200)
        self._inject_roi(nid, [0, 1, 2, 3])
        self._ws._on_roi_keep()
        new_id = [n.node_id for n in self._ws._workflow.list_cloud_nodes()
                  if n.node_id != nid][0]
        self._ws._on_undo()
        self._ws._on_redo()
        self.assertIsNotNone(self._ws._workflow.get_node(new_id))
        self.assertIn(new_id, self._ws._db_tree._node_items, "重做未补回树节点")
        self.assertIn(new_id, self._ws._viewer._clouds, "重做未回到 3D 视图")

    def test_roi_without_selection_warns_not_silent(self):
        self._load(n=200)
        self._ws._viewer._roi_selected_indices = {}
        self._ws._on_roi_keep()
        self.assertTrue(self._has_log("warn", "未框选"), self._logs)
        self.assertEqual(len(self._ws._workflow.list_cloud_nodes()), 1)

    def test_roi_out_of_range_indices_rejected(self):
        nid = self._load(n=100)
        self._inject_roi(nid, [0, 1, 99_999])
        self._ws._on_roi_keep()
        self.assertTrue(self._has_log("warn", "越界"), self._logs)
        self.assertEqual(len(self._ws._workflow.list_cloud_nodes()), 1,
                         "越界选区不得派生新节点")

    def test_roi_selection_cleared_after_apply(self):
        """选区被消费后必须清高亮，避免残留红点让人误以为选区还在。"""
        nid = self._load(n=200)
        self._inject_roi(nid, [0, 1, 2])
        self._ws._on_roi_keep()
        self.assertEqual(self._ws._viewer.get_roi_selection(), {},
                         "应用后选区未清除")
        self.assertTrue(self._has_log("info", "ROI 高亮已清除"), self._logs)

    def test_roi_buttons_disabled_without_selection(self):
        self._load(n=100)
        self._ws._props.set_roi_state(0)
        self.assertFalse(self._ws._props._btn_roi_keep.isEnabled())
        self.assertFalse(self._ws._props._btn_roi_remove.isEnabled())
        self._ws._props.set_roi_state(42)
        self.assertTrue(self._ws._props._btn_roi_keep.isEnabled())
        self.assertTrue(self._ws._props._btn_roi_remove.isEnabled())


# ===========================================================================
# W9：ROI 降级必须可见
# ===========================================================================
class TestRoiDegradationVisible(_K4UiBase):
    def test_check_roi_reports_reason_from_viewer(self):
        """viewer 报降级原因 → workspace 必须落 warn 日志 + 面板显示。"""
        self._load(n=200)
        self._ws._viewer._roi_last_error = "深度缓冲不可读（模拟）"
        self._ws._check_roi()
        self.assertTrue(self._has_log("warn", "ROI 提示"), self._logs)
        self.assertIn("模拟", self._ws._props._lbl_roi.text(),
                      "W9：降级原因未在面板可见")

    def test_check_roi_reports_each_reason_once(self):
        """同一原因不重复刷屏；原因变化时重新上报。"""
        self._load(n=100)
        self._ws._viewer._roi_last_error = "原因A"
        self._ws._check_roi()
        self._ws._check_roi()
        self.assertEqual(sum(1 for lvl, m in self._logs if lvl == "warn"), 1)
        self._ws._viewer._roi_last_error = "原因B"
        self._ws._check_roi()
        self.assertEqual(sum(1 for lvl, m in self._logs if lvl == "warn"), 2)
        # 恢复正常后应清掉告警态
        self._ws._viewer._roi_last_error = None
        self._ws._check_roi()
        self.assertNotIn("原因B", self._ws._props._lbl_roi.text())


# ===========================================================================
# K3 遗留：工具栏灰显 + 导出默认名清洗
# ===========================================================================
class TestToolbarAndExportName(_K4UiBase):
    def test_undo_redo_buttons_track_history(self):
        nid = self._load(n=300)
        self.assertFalse(self._ws._toolbar.is_undo_enabled(),
                         "初始无历史，撤销键应为灰")
        self.assertFalse(self._ws._toolbar.is_redo_enabled())
        params = self._ws._props.get_process_params()
        params.update({"crop_mode": "sphere", "crop_radius": 8.0})
        self._ws._on_apply_process(params)
        self.assertTrue(self._ws._toolbar.is_undo_enabled(), "有历史后撤销键应解锁")
        self.assertFalse(self._ws._toolbar.is_redo_enabled())
        self._ws._on_undo()
        self.assertFalse(self._ws._toolbar.is_undo_enabled(), "退到底后应回到灰")
        self.assertTrue(self._ws._toolbar.is_redo_enabled(), "可重做时应解锁")

    def test_export_default_name_is_sanitized(self):
        """K3 遗留②：节点名含路径分隔符/非法字符时，默认文件名必须清洗。"""
        self.assertEqual(
            self._ws._safe_export_default_name("a/b"), "a_b.ply")
        self.assertEqual(
            self._ws._safe_export_default_name("a\\b"), "a_b.ply")
        self.assertEqual(
            self._ws._safe_export_default_name('x:*?"<>|y'), "x_______y.ply")
        self.assertEqual(
            self._ws._safe_export_default_name("normal.ply"), "normal.ply")
        # 退化输入不留空名
        self.assertEqual(self._ws._safe_export_default_name("..."), "cloud.ply")
        self.assertEqual(self._ws._safe_export_default_name(""), "cloud.ply")

    def test_export_uses_sanitized_default_name(self):
        nid = self._load(n=100)
        self._ws._workflow.rename_node(nid, "a/b")
        captured = {}

        def fake_dialog(parent, title, default, filters):
            captured["default"] = default
            return "", ""

        import prototypes.cloudcompare_like.app.cc_workspace as ws_mod
        orig = ws_mod.QFileDialog.getSaveFileName
        ws_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog)
        try:
            self._ws._export_node(nid)
        finally:
            ws_mod.QFileDialog.getSaveFileName = orig
        self.assertEqual(captured["default"], "a_b.ply",
                         "导出对话框默认名未清洗（K3 遗留②）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
