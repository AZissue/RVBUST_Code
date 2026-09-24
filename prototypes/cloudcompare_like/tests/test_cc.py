# -*- coding: utf-8 -*-
"""
CloudCompare-Like 原型单元测试（无 UI 依赖）。

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    python prototypes/cloudcompare_like/tests/test_cc.py
"""

from __future__ import annotations

import os
import sys
import unittest
import numpy as np

# 包路径导入：prototypes 无 __init__.py，依赖命名空间包（PEP 420）。
# 项目根目录需在 sys.path 上（直接运行本脚本时自动满足：sys.path[0] 为 tests/ 的父链
# 不可依赖，这里显式插入项目根），src/ 也在 path 上供原型引用 core.utils 等主源码模块。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import open3d as o3d
from prototypes.cloudcompare_like.core.cc_workflow import CloudCompareWorkflow, CCNode, ScalarField
from prototypes.cloudcompare_like.core.cc_scalar_field import compute_scalar_field, apply_colormap
from prototypes.cloudcompare_like.core.cc_geometry import detect_shape
from prototypes.cloudcompare_like.core.cc_octree_lod import PointCloudOctree, MultiCloudLODManager


class TestCCWorkflow(unittest.TestCase):
    """测试工作流核心。"""

    def setUp(self):
        self.wf = CloudCompareWorkflow()
        # 创建测试点云（单位立方体 1000 点）
        pts = np.random.rand(1000, 3).astype(np.float64)
        self.pcd = o3d.geometry.PointCloud()
        self.pcd.points = o3d.utility.Vector3dVector(pts)

    def test_add_cloud(self):
        nid = self.wf.add_cloud("test", self.pcd)
        self.assertIsNotNone(nid)
        node = self.wf.get_node(nid)
        self.assertEqual(node.name, "test")
        self.assertEqual(node.point_count, 1000)

    def test_undo_redo(self):
        nid = self.wf.add_cloud("test", self.pcd)
        before = np.asarray(self.wf.get_node(nid).pcd.points).copy()
        # 执行后处理（下采样）
        self.wf.processor.enable_voxel_downsample = True
        self.wf.processor.voxel_size = 0.5
        ok, _, _ = self.wf.apply_process(nid)
        self.assertTrue(ok)
        after_count = self.wf.get_node(nid).point_count
        # 撤销
        ok, msg = self.wf.undo()
        self.assertTrue(ok)
        self.assertEqual(self.wf.get_node(nid).point_count, 1000)
        # 重做
        ok, msg = self.wf.redo()
        self.assertTrue(ok)
        self.assertEqual(self.wf.get_node(nid).point_count, after_count)

    def test_scalar_field(self):
        nid = self.wf.add_cloud("test", self.pcd)
        values = np.random.rand(1000)
        ok = self.wf.add_scalar_field(nid, "random", values, "jet")
        self.assertTrue(ok)
        node = self.wf.get_node(nid)
        self.assertIn("random", node.scalar_fields)
        ok = self.wf.set_active_scalar(nid, "random")
        self.assertTrue(ok)
        self.assertEqual(node.active_scalar, "random")

    def test_estimate_normals(self):
        nid = self.wf.add_cloud("test", self.pcd)
        ok, msg = self.wf.estimate_normals(nid)
        self.assertTrue(ok)
        self.assertTrue(self.wf.get_node(nid).pcd.has_normals())

    def test_detect_plane(self):
        # 创建平面点云
        xx, yy = np.meshgrid(np.linspace(-1, 1, 50), np.linspace(-1, 1, 50))
        zz = np.zeros_like(xx)
        pts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        nid = self.wf.add_cloud("plane", pcd)
        ok, msg, result = self.wf.detect_geometry(nid, "plane")
        self.assertTrue(ok)
        self.assertIn("fitness", result)
        self.assertGreater(result["fitness"], 0.9)


class TestScalarField(unittest.TestCase):
    """测试标量场。"""

    def test_height_field(self):
        pts = np.random.rand(100, 3)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        vals = compute_scalar_field(pcd, "z")
        self.assertIsNotNone(vals)
        self.assertEqual(len(vals), 100)

    def test_density_field(self):
        pts = np.random.rand(200, 3)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        vals = compute_scalar_field(pcd, "density", radius=0.5)
        self.assertIsNotNone(vals)
        self.assertEqual(len(vals), 200)
        self.assertTrue(np.all(vals >= 1))

    def test_colormap(self):
        t = np.linspace(0, 1, 100)
        colors = apply_colormap(t, "jet")
        self.assertEqual(colors.shape, (100, 3))
        self.assertTrue(np.all(colors >= 0) and np.all(colors <= 1))


class TestOctreeLOD(unittest.TestCase):
    """测试 LOD 八叉树。"""

    def test_build_octree(self):
        pts = np.random.rand(10000, 3).astype(np.float32)
        octree = PointCloudOctree(pts)
        self.assertIsNotNone(octree.root)
        self.assertGreater(len(octree._lod_levels), 0)

    def test_query(self):
        pts = np.random.rand(100000, 3).astype(np.float32)
        octree = PointCloudOctree(pts)
        camera_pos = np.array([0.5, 0.5, 2.0])
        qpts, qcols = octree.query(camera_pos, target_count=5000)
        self.assertLessEqual(len(qpts), 5000)
        self.assertEqual(qpts.shape[1], 3)

    def test_multi_cloud_manager(self):
        mgr = MultiCloudLODManager(budget_per_cloud=1000)
        pts1 = np.random.rand(5000, 3).astype(np.float32)
        pts2 = np.random.rand(5000, 3).astype(np.float32)
        mgr.add_cloud("c1", pts1)
        mgr.add_cloud("c2", pts2)
        result = mgr.query_all(np.array([0.5, 0.5, 2.0]))
        self.assertIn("c1", result)
        self.assertIn("c2", result)


class TestGeometry(unittest.TestCase):
    """测试几何检测。"""

    def test_plane_detection(self):
        xx, yy = np.meshgrid(np.linspace(-1, 1, 50), np.linspace(-1, 1, 50))
        zz = np.zeros_like(xx)
        pts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        result = detect_shape(pcd, "plane")
        self.assertIsNotNone(result)
        self.assertGreater(result["fitness"], 0.9)


def _rot_xyz_deg(rx: float, ry: float, rz: float) -> np.ndarray:
    """XYZ 欧拉角（度）→ 3x3 旋转矩阵（Rz @ Ry @ Rx）。"""
    cx, cy, cz = np.cos(np.radians([rx, ry, rz]))
    sx, sy, sz = np.sin(np.radians([rx, ry, rz]))
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _make_T(rx, ry, rz, t) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = _rot_xyz_deg(rx, ry, rz)
    T[:3, 3] = np.asarray(t, dtype=np.float64)
    return T


def _asym_blob(n: int, seed: int = 7) -> np.ndarray:
    """非立方体盒内的均匀随机点（100×60×30mm）。

    必须用非对称形体：球面等旋转对称形体本身旋转后与自身近似重合，ICP 会在
    「点都对齐了但姿态转错」处收敛，姿态真值断言会假失败。
    """
    rng = np.random.default_rng(seed)
    ext = np.array([0.10, 0.06, 0.03])
    return rng.random((n, 3)) * ext - ext / 2.0


def _nn_mean_dist(src_pts: np.ndarray, ref_pcd) -> float:
    """src_pts 每点到 ref_pcd 的最近邻距离均值（米）。"""
    tree = o3d.geometry.KDTreeFlann(ref_pcd)
    ds = []
    for p in src_pts:
        _, _, d2 = tree.search_knn_vector_3d(p, 1)
        ds.append(np.sqrt(d2[0]))
    return float(np.mean(ds))


class TestICPRegister(unittest.TestCase):
    """ICP 配准（真值断言口径）。

    变换方向约定（@verify 首版探针曾把真值取成 inv(T) 报出假缺陷，这里写死）：
    - 真值构造 target = T_true @ source（open3d `pcd.transform(T)` 即 p' = R p + t）；
    - `icp_register(source, target)` 内部执行 `src_node.pcd = src.transform(result.transformation)`，
      故 `result.transformation` 的物理含义就是「源点云 → 目标点云」，应与 T_true 直接比较，**不取逆**。
    - fitness 只是「有对应点的源点占比」，可轻易为 1.0 而姿态仍有度级偏差，不能单独作为成败判据。
    """

    def setUp(self):
        self.wf = CloudCompareWorkflow()
        self.pts_src = _asym_blob(8000)
        self.T_true = _make_T(8.0, -5.0, 12.0, (0.03, -0.02, 0.05))

        src_pcd = o3d.geometry.PointCloud()
        src_pcd.points = o3d.utility.Vector3dVector(self.pts_src)
        tgt_pcd = o3d.geometry.PointCloud()
        tgt_pcd.points = o3d.utility.Vector3dVector(self.pts_src.copy())
        tgt_pcd.transform(self.T_true)

        self.src_id = self.wf.add_cloud("src", src_pcd)
        self.tgt_id = self.wf.add_cloud("tgt", tgt_pcd)

    def test_icp_truth_convergence(self):
        """合成已知变换：对齐后最近邻残差 + 变换真值误差双断言。"""
        pre = _nn_mean_dist(self.pts_src, self.wf.get_node(self.tgt_id).pcd)

        ok, msg, res = self.wf.icp_register(self.src_id, self.tgt_id)
        self.assertTrue(ok, msg)
        self.assertIsNotNone(res)

        aligned_pts = np.asarray(self.wf.get_node(self.src_id).pcd.points)
        post = _nn_mean_dist(aligned_pts, self.wf.get_node(self.tgt_id).pcd)

        # 点位精度：8000 点 / 100×60×30mm 体 → 平均点距 ≈ 2.8mm，对齐残差应与点距同量级
        self.assertLess(post, 4e-3,
                        f"对齐后最近邻残差 {post*1000:.2f}mm 超阈值；ICP 前 {pre*1000:.2f}mm")
        # 前置残差必须显著大于对齐后（防"ICP 实际没动/返回单位阵也算通过"）
        self.assertGreater(pre, 10.0 * post,
                           f"ICP 前 {pre*1000:.2f}mm 非对齐后 {post*1000:.2f}mm 的 10 倍，疑似未发生配准")

        # 变换真值误差（方向见类 docstring）
        T_est = res.transformation
        R_err = T_est[:3, :3] @ self.T_true[:3, :3].T
        angle_err = np.degrees(np.arccos(np.clip((np.trace(R_err) - 1.0) / 2.0, -1.0, 1.0)))
        t_err = float(np.linalg.norm(T_est[:3, 3] - self.T_true[:3, 3]))
        self.assertLess(angle_err, 5.0, f"姿态角误差 {angle_err:.2f}°")
        self.assertLess(t_err, 0.03, f"平移误差 {t_err*1000:.2f}mm")

        # fitness 可按点距轻易到 1.0，此时姿态仍有度级偏差 → 只能作辅助指标
        if res.fitness >= 0.999:
            self.assertLess(angle_err, 5.0,
                            f"fitness={res.fitness:.4f} 但姿态角误差 {angle_err:.2f}°，不得仅凭 fitness 判成败")

    def test_icp_writes_source_and_history(self):
        """ICP 就地改写源节点，且可 undo 还原。"""
        before = np.asarray(self.wf.get_node(self.src_id).pcd.points).copy()
        ok, _, _ = self.wf.icp_register(self.src_id, self.tgt_id)
        self.assertTrue(ok)
        after = np.asarray(self.wf.get_node(self.src_id).pcd.points)
        self.assertFalse(np.allclose(before, after), "ICP 未改写源点云")
        self.assertTrue(self.wf.can_undo())
        ok, msg = self.wf.undo()
        self.assertTrue(ok, msg)
        np.testing.assert_allclose(np.asarray(self.wf.get_node(self.src_id).pcd.points),
                                   before, atol=1e-9)

    def test_icp_init_transform_honored(self):
        """init_transform=T_true 时残差保持在同一量级（初值被真正使用）。"""
        ok, msg, res = self.wf.icp_register(self.src_id, self.tgt_id,
                                            init_transform=self.T_true.copy())
        self.assertTrue(ok, msg)
        post = _nn_mean_dist(np.asarray(self.wf.get_node(self.src_id).pcd.points),
                             self.wf.get_node(self.tgt_id).pcd)
        self.assertLess(post, 4e-3, f"给定真值初值后残差 {post*1000:.2f}mm")

    def test_icp_error_paths(self):
        ok, msg, res = self.wf.icp_register("cc_999", self.tgt_id)
        self.assertFalse(ok)
        self.assertIn("不存在", msg)
        self.assertIsNone(res)

        file_id = self.wf.add_file_node("f.ply")
        ok, msg, res = self.wf.icp_register(file_id, self.tgt_id)
        self.assertFalse(ok)
        self.assertIn("不是点云节点", msg)
        self.assertIsNone(res)


class TestMergeClouds(unittest.TestCase):
    """点云合并（属性对齐口径）。"""

    def setUp(self):
        self.wf = CloudCompareWorkflow()

    @staticmethod
    def _cloud(n: int, color=None, normal=None):
        pts = np.random.rand(n, 3)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        if color is not None:
            pcd.colors = o3d.utility.Vector3dVector(np.tile(np.asarray(color), (n, 1)))
        if normal is not None:
            pcd.normals = o3d.utility.Vector3dVector(np.tile(np.asarray(normal), (n, 1)))
        return pcd

    def test_merge_colors_preserved(self):
        a = self._cloud(300, color=(1.0, 0.0, 0.0))
        b = self._cloud(200, color=(0.0, 1.0, 0.0))
        ida = self.wf.add_cloud("a", a)
        idb = self.wf.add_cloud("b", b)
        ok, msg, new_id = self.wf.merge_clouds([ida, idb], "ab")
        self.assertTrue(ok, msg)
        merged = self.wf.get_node(new_id).pcd
        self.assertEqual(len(merged.points), 500)
        cols = np.asarray(merged.colors)
        self.assertTrue(np.allclose(cols[:300], [1.0, 0.0, 0.0]), "前半段颜色丢失")
        self.assertTrue(np.allclose(cols[300:], [0.0, 1.0, 0.0]), "后半段颜色丢失")

    def test_merge_normal_slot_zero_filled(self):
        """口径：一侧无法线时按 src/core/pcd_utils.py:31-36 零填充对齐，故 has_normals() 会为 True。

        零填充是防 open3d `+=` 清空颜色/法线的既定做法，不是本轮缺陷；此处钉死现状，
        调用方需自行判断法线是否可用（全零段不可用）。
        """
        a = self._cloud(300, normal=(0.0, 0.0, 1.0))
        b = self._cloud(200)
        ida = self.wf.add_cloud("a", a)
        idb = self.wf.add_cloud("b", b)
        ok, msg, new_id = self.wf.merge_clouds([ida, idb], "ab")
        self.assertTrue(ok, msg)
        merged = self.wf.get_node(new_id).pcd
        self.assertTrue(merged.has_normals(), "零填充后 has_normals() 应为 True（属性槽存在）")
        nrm = np.asarray(merged.normals)
        self.assertTrue(np.allclose(nrm[:300], [0.0, 0.0, 1.0]))
        self.assertTrue(np.allclose(nrm[300:], 0.0),
                        "无法线一侧应为零填充（全零段即不可用法线）")

    def test_merge_color_slot_filled_default(self):
        """口径：一侧无色时按 pcd_utils.py:21-26 填 0.85 灰，不零填充。"""
        a = self._cloud(300, color=(1.0, 0.0, 0.0))
        b = self._cloud(200)
        ida = self.wf.add_cloud("a", a)
        idb = self.wf.add_cloud("b", b)
        ok, msg, new_id = self.wf.merge_clouds([ida, idb], "ab")
        self.assertTrue(ok, msg)
        cols = np.asarray(self.wf.get_node(new_id).pcd.colors)
        self.assertTrue(np.allclose(cols[300:], 0.85))

    def test_merge_node_registered(self):
        ida = self.wf.add_cloud("a", self._cloud(10))
        idb = self.wf.add_cloud("b", self._cloud(10))
        ok, msg, new_id = self.wf.merge_clouds([ida, idb], "union")
        self.assertTrue(ok, msg)
        node = self.wf.get_node(new_id)
        self.assertIsNotNone(node)
        self.assertEqual(node.name, "union")
        self.assertEqual(node.point_count, 20)

    def test_merge_error_paths(self):
        ida = self.wf.add_cloud("a", self._cloud(10))
        ok, msg, new_id = self.wf.merge_clouds([ida])
        self.assertFalse(ok)
        self.assertIn("至少选择两朵", msg)
        self.assertIsNone(new_id)

        ok, msg, new_id = self.wf.merge_clouds([ida, "cc_999"])
        self.assertFalse(ok)
        self.assertIn("不存在或为空", msg)
        self.assertIsNone(new_id)


class TestHistoryReferenceSafety(unittest.TestCase):
    """撤销记录必须持有「操作前」的独立副本。

    open3d 的 `estimate_normals()` / `transform()` 都是就地改写，若 `_push_history` 的
    before 与节点当前对象是同一引用，撤销即变成空操作（ICP 配准曾因此完全不可撤销）。
    """

    def test_normals_undo_restores(self):
        wf = CloudCompareWorkflow()
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(_asym_blob(500))
        nid = wf.add_cloud("n", pcd)
        ok, msg = wf.estimate_normals(nid)
        self.assertTrue(ok, msg)
        self.assertTrue(wf.get_node(nid).pcd.has_normals())
        ok, msg = wf.undo()
        self.assertTrue(ok, msg)
        self.assertFalse(wf.get_node(nid).pcd.has_normals(),
                         "撤销法线估计后仍带法线 → before 与节点对象是同一引用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
