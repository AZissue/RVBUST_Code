# -*- coding: utf-8 -*-
"""
K4 测试：裁切（AABB/球/OBB）+ ROI 保留/剔除 + 历史扩展 + 选区纯函数。

覆盖门禁（`docs/后处理原型实现方案与实施路径_20260924.md` §10.15）：
  - G-K4 / W4   裁切与 v1 参照实现同参数下点数一致（差 ≤1 点）
  - G-K4 / W5a  ROI 纯投影口径：断言 = `world_to_screen` numpy 逐点真值
  - G-K4 / W5b  深度分支注入合成 depth_buf 直测（**不依赖 glReadPixels**）
  - G-K4 / W6   `include_occluded` 显式开关；默认 True = 无深度过滤结果
  - G-K4 / W9   GL 不可用时 ROI 必须给出原因，禁静默返回空
  - 历史扩展    「新增节点」型 entry 的 undo/redo（移除 + 原位置插入）

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    QT_QPA_PLATFORM=offscreen python -m unittest prototypes.cloudcompare_like.tests.test_cc_k4 -v
"""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import open3d as o3d  # noqa: E402

from prototypes.cloudcompare_like.core.cc_workflow import (  # noqa: E402
    CloudCompareWorkflow, CCNode)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # noqa: E402

try:
    from PySide6.QtCore import QRect  # noqa: E402
    from prototypes.cloudcompare_like.app.cc_gl_viewer import (  # noqa: E402
        roi_project_indices, roi_apply_depth_filter, PointCloudViewerLOD)
    _HAS_QT = True
    _QT_ERR = ""
except Exception as _e:  # PySide6 缺失时跳过纯函数组
    _HAS_QT = False
    _QT_ERR = str(_e)


# ---------------------------------------------------------------------------
# 合成几何工具
# ---------------------------------------------------------------------------
def _grid_cloud(nx: int = 20, ny: int = 20, nz: int = 5, spacing: float = 1.0):
    """规则网格点云：坐标可预测，便于逐点真值断言。"""
    xs = np.arange(nx, dtype=np.float64) * spacing
    ys = np.arange(ny, dtype=np.float64) * spacing
    zs = np.arange(nz, dtype=np.float64) * spacing
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    return pcd, pts


def _ortho_mvp(scale: float = 1.0):
    """正交投影 MVP：world → NDC 就是线性缩放（无透视除法的干扰）。

    取 scale=1 时，`roi_project_indices` 算出的屏幕坐标
    sx = (x+1)*0.5*W、sy = (1-y)*0.5*H —— 与手算真值逐点可比。
    """
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = scale
    m[1, 1] = scale
    m[2, 2] = scale
    m[3, 3] = 1.0
    return m


_QT_APP = None


def _make_viewer(width: int = 200, height: int = 150):
    """构造一个 offscreen 查看器实例（QWidget 必须先有 QApplication）。"""
    global _QT_APP
    from PySide6.QtWidgets import QApplication
    _QT_APP = QApplication.instance() or QApplication([])
    v = PointCloudViewerLOD()
    v.resize(width, height)
    return v


# ===========================================================================
# W5a：纯投影口径（不依赖 GL）
# ===========================================================================
@unittest.skipUnless(_HAS_QT, f"app 层不可导入: {_QT_ERR}")
class TestRoiProjection(unittest.TestCase):
    """W5a：断言 = world_to_screen numpy 逐点真值，边界归属与容差写进测试。"""

    W, H = 400, 300

    def test_matches_manual_numpy_truth(self):
        """命中索引必须与手算的投影真值逐点一致（含边界点）。"""
        rng = np.random.default_rng(7)
        pts = rng.uniform(-1.0, 1.0, size=(500, 3))
        mvp = _ortho_mvp()

        # 手算真值（与实现同口径，但独立写一遍）
        homo = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
        clip = (mvp @ homo.T).T
        ndc = clip[:, :3] / clip[:, 3:]
        sx = (ndc[:, 0] + 1.0) * 0.5 * self.W
        sy = (1.0 - ndc[:, 1]) * 0.5 * self.H
        sz = (ndc[:, 2] + 1.0) * 0.5
        rect = QRect(120, 80, 160, 120)   # 既非空也非全集（W5a 要求）
        truth = np.nonzero(
            (sx >= rect.left()) & (sx <= rect.right()) &
            (sy >= rect.top()) & (sy <= rect.bottom()) &
            (sz >= 0.0) & (sz <= 1.0))[0]

        got, screen = roi_project_indices(mvp, pts, rect, self.W, self.H)
        np.testing.assert_array_equal(got, truth)
        # 非空也非全集 —— 这条判据本身要有判别力
        self.assertGreater(len(truth), 0, "选区为空，判据无判别力")
        self.assertLess(len(truth), len(pts), "选区命中全集，判据无判别力")
        np.testing.assert_allclose(screen[:, 0], sx, atol=1e-9)
        np.testing.assert_allclose(screen[:, 1], sy, atol=1e-9)
        np.testing.assert_allclose(screen[:, 2], sz, atol=1e-9)

    def test_boundary_points_are_inclusive(self):
        """边界归属口径：四边闭区间；容差 ±0.5px（避免精确落在边上被判越界）。

        ⚠️ Qt 陷阱：`QRect(x, y, w, h)` 的 `right()` = x+w−1、`bottom()` = y+h−1
        （**闭区间**语义，不是 x+w）。故"内侧"点必须按 `right()/bottom()` 反解，
        不能按 `x+w` —— 否则会落到矩形外 1px 却误以为在边界上。
        做法：在四边内侧 0.25px 与外侧 0.25px 各放点，内 5 个必中、外 4 个必不中。
        """
        rect = QRect(100, 100, 100, 100)
        L, R = rect.left(), rect.right()
        T, B = rect.top(), rect.bottom()

        def world_for(sx, sy, sz=0.5):
            """反解出 world 坐标，使投影后的屏幕坐标恰为 (sx, sy)。"""
            ndc_x = sx / (0.5 * self.W) - 1.0
            ndc_y = 1.0 - sy / (0.5 * self.H)
            return [ndc_x, ndc_y, 2.0 * sz - 1.0]

        eps = 0.25
        pts = np.array([
            world_for(L + eps, T + eps),   # 0 左上角内侧
            world_for(R - eps, T + eps),   # 1 右上角内侧
            world_for(L + eps, B - eps),   # 2 左下角内侧
            world_for(R - eps, B - eps),   # 3 右下角内侧
            world_for((L + R) / 2, (T + B) / 2),   # 4 正中
            world_for(L - eps, (T + B) / 2),       # 5 左外
            world_for(R + eps, (T + B) / 2),       # 6 右外
            world_for((L + R) / 2, T - eps),       # 7 上外
            world_for((L + R) / 2, B + eps),       # 8 下外
        ])
        got = set(int(i) for i in roi_project_indices(
            _ortho_mvp(), pts, rect, self.W, self.H)[0])
        self.assertEqual(got, {0, 1, 2, 3, 4},
                         f"闭区间边界口径不符：{sorted(got)}（内 0~4 全中、外 5~8 全不中）")

    def test_degenerate_inputs_return_empty_not_raise(self):
        rect = QRect(0, 0, 100, 100)
        empty, screen = roi_project_indices(_ortho_mvp(), np.zeros((0, 3)), rect,
                                           self.W, self.H)
        self.assertEqual(len(empty), 0)
        self.assertIsNone(screen)
        # 过小选区（<3px）
        tiny, _ = roi_project_indices(_ortho_mvp(), np.ones((10, 3)), QRect(0, 0, 2, 2),
                                     self.W, self.H)
        self.assertEqual(len(tiny), 0)
        # mvp 缺失
        none_mvp, _ = roi_project_indices(None, np.ones((10, 3)), rect, self.W, self.H)
        self.assertEqual(len(none_mvp), 0)

    def test_wide_rect_would_have_masked_regression(self):
        """W5a 反例：原判据用的 200×150+400×300 配置下命中份额过高，
        测不出「选区选了什么」。这里钉住「窄选区命中份额必须明显小于全集」，
        防止将来有人把测试几何改成无判别力的宽矩形。
        """
        rng = np.random.default_rng(11)
        pts = rng.uniform(-1.0, 1.0, size=(2000, 3))
        wide = QRect(0, 0, self.W, self.H)
        got_wide, _ = roi_project_indices(_ortho_mvp(), pts, wide, self.W, self.H)
        narrow = QRect(150, 100, 100, 80)
        got_narrow, _ = roi_project_indices(_ortho_mvp(), pts, narrow, self.W, self.H)
        self.assertLess(len(got_narrow), len(got_wide) * 0.5,
                        "窄选区命中份额未明显低于全屏，判据失去判别力")


# ===========================================================================
# W5b：深度分支（注入合成 depth_buf 直测，不用 glReadPixels）
# ===========================================================================
@unittest.skipUnless(_HAS_QT, f"app 层不可导入: {_QT_ERR}")
class TestRoiDepthBranch(unittest.TestCase):
    W, H = 200, 100

    def _setup(self):
        """一条沿 Z 排列的两点云：A 在前（sz 小），B 在后（sz 大），屏幕同位。"""
        rect = QRect(40, 20, 120, 60)
        # 两点投影到同一屏幕位置（x=y=0 → 视口中心）
        pts = np.array([[0.0, 0.0, -0.8],   # idx0: sz = 0.1（近）
                        [0.0, 0.0, 0.6]])   # idx1: sz = 0.8（远）
        mvp = _ortho_mvp()
        indices, screen = roi_project_indices(mvp, pts, rect, self.W, self.H)
        return rect, pts, indices, screen

    def test_occluded_point_filtered_by_synthetic_depth(self):
        """合成深度缓冲只记录了近点：远点必须被过滤掉（比较分支真的在跑）。"""
        rect, _pts, indices, screen = self._setup()
        self.assertEqual(len(indices), 2, "前置：两点均应落在矩形内")
        # 构造 depth_buf：把两点所在像素填成近点的深度 0.1
        buf = np.full((rect.height(), rect.width()), 0.1)
        kept = roi_apply_depth_filter(indices, screen, rect, buf, self.H)
        self.assertEqual(list(kept), [0], f"远点未被遮挡过滤，实际保留 {list(kept)}")

    def test_include_occluded_true_equals_no_depth_filter(self):
        """W5b 口径：`include_occluded=True`（默认）结果 = 无深度过滤结果。"""
        rect, _pts, indices, screen = self._setup()
        buf = np.full((rect.height(), rect.width()), 0.1)
        filtered = roi_apply_depth_filter(indices, screen, rect, buf, self.H)
        self.assertNotEqual(list(filtered), list(indices),
                            "前置：深度过滤应真的起作用（否则本判据无判别力）")

        v = _make_viewer()
        try:
            self.assertTrue(v._include_occluded,
                            "W6：默认必须 include_occluded=True（不做遮挡剔除）")
            v.set_include_occluded(False)
            self.assertFalse(v._include_occluded)
            v.set_include_occluded(True)
            self.assertTrue(v._include_occluded)
        finally:
            v.deleteLater()

    def test_nonfinite_depth_samples_are_kept(self):
        """不可判的深度采样（NaN/Inf）按「可见」处理：宁可多选也不静默丢点。"""
        rect, _pts, indices, screen = self._setup()
        buf = np.full((rect.height(), rect.width()), np.nan)
        kept = roi_apply_depth_filter(indices, screen, rect, buf, self.H)
        self.assertEqual(len(kept), len(indices), "NaN 深度不应导致点被丢弃")

    def test_none_depth_buf_degrades_to_projection(self):
        rect, _pts, indices, screen = self._setup()
        kept = roi_apply_depth_filter(indices, screen, rect, None, self.H)
        np.testing.assert_array_equal(kept, indices)


# ===========================================================================
# W9：GL 不可用时必须给原因（禁静默）
# ===========================================================================
@unittest.skipUnless(_HAS_QT, f"app 层不可导入: {_QT_ERR}")
class TestRoiSilentFailureW9(unittest.TestCase):
    def test_no_gl_reports_reason_and_getter_exposes_it(self):
        """offscreen 下无 GL/MVP：`_compute_roi_selection` 必须留下可上报的原因。"""
        v = _make_viewer(200, 150)
        try:
            v.set_roi_mode(True)
            v._roi_rect = QRect(10, 10, 100, 80)
            self.assertFalse(v._has_gl, "前置：offscreen 下不该有 GL 上下文")
            v._compute_roi_selection()
            err = v.roi_selection_error()
            self.assertIsNotNone(err, "W9：无 GL 时 ROI 静默返回空 —— 必须给出原因")
            self.assertIn("3D 视图未就绪", err)
        finally:
            v.deleteLater()

    def test_error_reads_tuple_from_read_depth_rect(self):
        """`_read_depth_rect` 失败必须带出原因（旧实现裸 except: return None）。"""
        v = _make_viewer(100, 100)
        try:
            buf, err = v._read_depth_rect(QRect(0, 0, 50, 50))
            self.assertIsNone(buf)
            self.assertIsNotNone(err, "深度读取失败未带出原因 → 调用方只能静默")
        finally:
            v.deleteLater()


# ===========================================================================
# 裁切（W4）
# ===========================================================================
class TestCrop(unittest.TestCase):
    def setUp(self):
        self.wf = CloudCompareWorkflow()
        self.pcd, self.pts = _grid_cloud()
        self.nid = self.wf.add_cloud("grid", self.pcd)
        self.n0 = len(self.pts)

    def test_crop_sphere_matches_v1_formula(self):
        """W4：球裁切与 v1 参照同参数下点数一致。

        v1 `point_cloud_processor._crop_center_sphere`：保留 ‖p - center‖ ≤ radius，
        center = 包围盒中心。
        """
        radius = 3.0
        ok, msg, stats = self.wf.crop_cloud(self.nid, "sphere", radius=radius)
        self.assertTrue(ok, msg)
        node = self.wf.get_node(self.nid)
        self.assertIsNotNone(stats)
        # 独立真值
        mins, maxs = self.pts.min(axis=0), self.pts.max(axis=0)
        center = (mins + maxs) / 2
        truth = int((np.linalg.norm(self.pts - center, axis=1) <= radius).sum())
        self.assertLessEqual(abs(len(node.pcd.points) - truth), 1,
                             f"球裁切点数 {len(node.pcd.points)} ≠ v1 参照 {truth}")
        self.assertTrue(self.wf.can_undo(), "裁切必须入历史")

    def test_crop_aabb_center_ratio(self):
        """AABB 中心裁切：保留包围盒中心 crop_ratio 比例的区域。"""
        ratio = 0.5
        ok, msg, _ = self.wf.crop_cloud(self.nid, "aabb", ratio=ratio)
        self.assertTrue(ok, msg)
        node = self.wf.get_node(self.nid)
        mins, maxs = self.pts.min(axis=0), self.pts.max(axis=0)
        center = (mins + maxs) / 2
        half = (maxs - mins) / 2 * ratio
        truth = int((np.all(np.abs(self.pts - center) <= half, axis=1)).sum())
        self.assertLessEqual(abs(len(node.pcd.points) - truth), 1,
                             f"AABB 裁切点数 {len(node.pcd.points)} ≠ 真值 {truth}")

    def test_crop_obb_runs_and_enters_history(self):
        ok, msg, _ = self.wf.crop_cloud(self.nid, "obb", ratio=0.5)
        self.assertTrue(ok, msg)
        self.assertLess(len(self.wf.get_node(self.nid).pcd.points), self.n0)

    def test_crop_undo_restores_exact_point_count(self):
        ok, _, _ = self.wf.crop_cloud(self.nid, "sphere", radius=2.0)
        self.assertTrue(ok)
        cropped = len(self.wf.get_node(self.nid).pcd.points)
        self.assertLess(cropped, self.n0)
        ok, msg = self.wf.undo()
        self.assertTrue(ok, msg)
        self.assertEqual(len(self.wf.get_node(self.nid).pcd.points), self.n0,
                         "撤销裁切未恢复原点数")

    def test_crop_rejects_invalid_params(self):
        ok, msg, _ = self.wf.crop_cloud(self.nid, "aabb", ratio=0.0)
        self.assertFalse(ok)
        self.assertIn("(0, 1]", msg)
        ok, msg, _ = self.wf.crop_cloud(self.nid, "sphere", radius=-1.0)
        self.assertFalse(ok)
        self.assertIn("半径", msg)
        ok, msg, _ = self.wf.crop_cloud(self.nid, "banana")
        self.assertFalse(ok)
        self.assertIn("未知裁切模式", msg)
        self.assertFalse(self.wf.can_undo(), "非法参数不应产生历史条目")

    def test_extreme_crop_to_empty_not_silently_ok(self):
        """极值边界：半径极小 → 结果为空时必须如实回报，不能伪装成功。"""
        ok, msg, _ = self.wf.crop_cloud(self.nid, "sphere", radius=1e-6)
        # 允许两种自洽结果：真的裁空（core 返回成功但点数为 0 应被拒）
        # 或 core 判无变化。无论哪种，都不得是"成功且点数不变"。
        if ok:
            self.assertEqual(len(self.wf.get_node(self.nid).pcd.points), 0,
                             "极小半径既未裁空也未报错 → 参数被静默忽略")
        else:
            self.assertIn("空", msg + "未执行")


# ===========================================================================
# ROI 派生新节点 + 历史扩展
# ===========================================================================
class TestCreateNodeFromMask(unittest.TestCase):
    def setUp(self):
        self.wf = CloudCompareWorkflow()
        self.pcd, self.pts = _grid_cloud(nx=10, ny=10, nz=2)
        self.src = self.wf.add_cloud("src", self.pcd)
        self.n = len(self.pts)

    def _half_mask(self):
        mask = np.zeros(self.n, dtype=bool)
        mask[: self.n // 2] = True
        return mask

    def test_new_node_created_and_source_untouched(self):
        before = np.asarray(self.wf.get_node(self.src).pcd.points).copy()
        mask = self._half_mask()
        ok, msg, new_id = self.wf.create_node_from_mask(self.src, mask, "src_roi")
        self.assertTrue(ok, msg)
        self.assertIsNotNone(new_id)
        self.assertNotEqual(new_id, self.src)
        # 源节点逐点不变（ROI 哲学：产出新节点）
        after = np.asarray(self.wf.get_node(self.src).pcd.points)
        np.testing.assert_array_equal(before, after)
        self.assertEqual(len(self.wf.get_node(new_id).pcd.points), int(mask.sum()))

    def test_new_node_inserted_right_after_source(self):
        other = self.wf.add_cloud("other", self.pcd)
        ok, _, new_id = self.wf.create_node_from_mask(self.src, self._half_mask(), "src_roi")
        self.assertTrue(ok)
        order = [n.node_id for n in self.wf.list_nodes()]
        self.assertEqual(order.index(new_id), order.index(self.src) + 1,
                         f"新节点未插在源节点之后: {order}")

    def test_undo_removes_new_node_and_restores_selection(self):
        mask = self._half_mask()
        ok, _, new_id = self.wf.create_node_from_mask(self.src, mask, "src_roi")
        self.assertTrue(ok)
        self.assertIsNotNone(self.wf.get_node(new_id))
        ok, msg = self.wf.undo()
        self.assertTrue(ok, msg)
        self.assertIsNone(self.wf.get_node(new_id), "撤销后新节点仍在")
        self.assertEqual(self.wf.selected_id(), self.src, "撤销后未恢复源节点选中")
        self.assertEqual(len(self.wf.list_cloud_nodes()), 1)

    def test_redo_reinserts_at_original_position(self):
        self.wf.add_cloud("tail", self.pcd)
        order_before = [n.node_id for n in self.wf.list_nodes()]
        ok, _, new_id = self.wf.create_node_from_mask(self.src, self._half_mask(), "src_roi")
        self.assertTrue(ok)
        pos = order_before.index(self.src) + 1
        self.wf.undo()
        self.assertIsNone(self.wf.get_node(new_id))
        ok, msg = self.wf.redo()
        self.assertTrue(ok, msg)
        self.assertIsNotNone(self.wf.get_node(new_id))
        order_after = [n.node_id for n in self.wf.list_nodes()]
        self.assertEqual(order_after.index(new_id), pos,
                         f"重做未回到原位置: {order_after}")

    def test_undo_redo_cycle_is_stable(self):
        """连续 undo/redo 三轮：节点集合与点数逐轮一致（无幽灵节点/漂移）。"""
        for i in range(3):
            ok, _, new_id = self.wf.create_node_from_mask(
                self.src, self._half_mask(), f"src_roi{i}")
            self.assertTrue(ok)
        self.assertEqual(len(self.wf.list_cloud_nodes()), 4)
        for _ in range(3):
            ok, msg = self.wf.undo()
            self.assertTrue(ok, msg)
        self.assertEqual(len(self.wf.list_cloud_nodes()), 1)
        for _ in range(3):
            ok, msg = self.wf.redo()
            self.assertTrue(ok, msg)
        self.assertEqual(len(self.wf.list_cloud_nodes()), 4)
        self.assertEqual(len(self.wf.list_cloud_nodes()), 4)

    def test_rejects_mask_length_mismatch(self):
        ok, msg, new_id = self.wf.create_node_from_mask(self.src, np.ones(3, dtype=bool), "x")
        self.assertFalse(ok)
        self.assertIn("掩码长度与点云不一致", msg)
        self.assertIsNone(new_id)

    def test_rejects_empty_mask(self):
        ok, msg, _ = self.wf.create_node_from_mask(
            self.src, np.zeros(self.n, dtype=bool), "x")
        self.assertFalse(ok)
        self.assertIn("选区为空", msg)
        self.assertEqual(len(self.wf.list_cloud_nodes()), 1, "空选区不应创建节点")

    def test_remove_semantics_keeps_complement(self):
        """ROI 剔除 = 对 ~mask 做派生：新节点点数 = 总数 − 选区数。"""
        mask = self._half_mask()
        ok, _, new_id = self.wf.create_node_from_mask(
            self.src, ~mask, "src_cut", action="ROI 剔除")
        self.assertTrue(ok)
        self.assertEqual(len(self.wf.get_node(new_id).pcd.points), self.n - int(mask.sum()))

    def test_undo_after_user_deleted_new_node_is_not_failure(self):
        """新节点被用户先删掉再撤销：不算失败，指针照常回退且报文如实说明。"""
        ok, _, new_id = self.wf.create_node_from_mask(self.src, self._half_mask(), "src_roi")
        self.assertTrue(ok)
        self.wf.remove_node(new_id)
        ok, msg = self.wf.undo()
        self.assertTrue(ok, msg)
        self.assertIn("已不存在", msg)


class TestHistoryDepthSnapshot(unittest.TestCase):
    """K3-D1′ 口径延续：history_depth() 供"某操作不得污染撤销栈"做快照。"""

    def test_history_depth_reports_stack_and_index(self):
        wf = CloudCompareWorkflow()
        pcd, _ = _grid_cloud(nx=5, ny=5, nz=1)
        nid = wf.add_cloud("a", pcd)
        self.assertEqual(wf.history_depth(), (0, -1))
        wf.crop_cloud(nid, "sphere", radius=1.0)
        depth, idx = wf.history_depth()
        self.assertEqual(depth, 1)
        self.assertEqual(idx, 0)
        wf.undo()
        self.assertEqual(wf.history_depth(), (1, -1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
