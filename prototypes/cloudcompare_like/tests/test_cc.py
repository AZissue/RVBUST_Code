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
import tempfile
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

# app 层（结果标签/局部极小口径）在无显示环境下也要可导入：先钉 offscreen 再导入 Qt。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from prototypes.cloudcompare_like.app.cc_workspace import (
        judge_icp_result, avg_point_spacing, rotation_angle_deg)
    _HAS_APP = True
    _APP_IMPORT_ERR = ""
except Exception as _e:  # PySide6/open3d-GUI 缺失时跳过该组，配准本体仍由 core 断言覆盖
    _HAS_APP = False
    _APP_IMPORT_ERR = repr(_e)


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
        """`point_to_point` **冷启动**：宽松式（§10.2）——姿态 <5°、平移 <30mm、后残差 <4mm。

        该组实测就是 ptp 的真实局部极小（rmse 1.651e-3 / maxdiff 1.690e-2 / 姿态差 1.13°），
        局部极小非缺陷，故不许用严格式判它；严格式见 `test_icp_init_transform_honored`
        与 `test_icp_point_to_plane_keeps_target_untouched`。
        """
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
        """`point_to_point` 给真值初值：严格式（§10.2）——rmse ≤1e-3、矩阵最大元素差 ≤1e-6。"""
        ok, msg, res = self.wf.icp_register(self.src_id, self.tgt_id,
                                            init_transform=self.T_true.copy())
        self.assertTrue(ok, msg)
        self.assertIsNotNone(res)
        self.assertLessEqual(res.inlier_rmse, 1e-3, f"inlier_rmse={res.inlier_rmse:.3e} 超严格式上限")
        maxdiff = float(np.abs(res.transformation - self.T_true).max())
        self.assertLessEqual(maxdiff, 1e-6, f"矩阵最大元素差 {maxdiff:.3e} 超严格式上限")
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

    def test_icp_point_to_plane_keeps_target_untouched(self):
        """D2：point_to_plane 不得给目标节点就地加法线。

        open3d 的 `estimate_normals()` 就地改写目标节点，而节点自身没有可撤销的历史：
        就地写入会让目标节点凭空多出法线属性（UI 着色/法线显示随之变化），且 undo 撤不掉。
        口径：目标法线只在本轮配准的临时副本上估计。
        """
        self.assertFalse(self.wf.get_node(self.tgt_id).pcd.has_normals(),
                         "前置条件：目标节点初始无法线")
        ok, msg, res = self.wf.icp_register(self.src_id, self.tgt_id,
                                            estimation_method="point_to_plane")
        self.assertTrue(ok, msg)
        self.assertIsNotNone(res)
        # 严格式（§10.2）：point_to_plane 冷启动不接受"大概对齐了"
        self.assertLessEqual(res.inlier_rmse, 1e-3, f"inlier_rmse={res.inlier_rmse:.3e} 超严格式上限")
        maxdiff = float(np.abs(res.transformation - self.T_true).max())
        self.assertLessEqual(maxdiff, 1e-6, f"矩阵最大元素差 {maxdiff:.3e} 超严格式上限")
        # 临时副本不得把配准跑空：残差仍须回到点距量级
        post = _nn_mean_dist(np.asarray(self.wf.get_node(self.src_id).pcd.points),
                             self.wf.get_node(self.tgt_id).pcd)
        self.assertLess(post, 4e-3, f"point_to_plane 对齐后残差 {post*1000:.2f}mm")
        self.assertFalse(self.wf.get_node(self.tgt_id).pcd.has_normals(),
                         "目标节点被就地加了法线 → 凭空多出未入历史的属性")
        ok, msg = self.wf.undo()
        self.assertTrue(ok, msg)
        self.assertFalse(self.wf.get_node(self.tgt_id).pcd.has_normals(),
                         "ICP 撤销后目标节点残留法线")

    def _fresh_pair(self, tgt_normals):
        """同几何的一对新 workflow/节点（ICP 会改写源节点，两组对照必须各起一套）。"""
        wf = CloudCompareWorkflow()
        src_pcd = o3d.geometry.PointCloud()
        src_pcd.points = o3d.utility.Vector3dVector(self.pts_src)
        tgt_pcd = o3d.geometry.PointCloud()
        tgt_pcd.points = o3d.utility.Vector3dVector(self.pts_src.copy())
        tgt_pcd.transform(self.T_true)
        if tgt_normals is not None:
            tgt_pcd.normals = o3d.utility.Vector3dVector(tgt_normals)
        return wf, wf.add_cloud("src", src_pcd), wf.add_cloud("tgt", tgt_pcd)

    def test_icp_point_to_plane_uses_existing_target_normals(self):
        """目标已带法线：原样使用（不重估、不改写），且这些法线必须真的进入求解。

        判据用**哨兵法线**：目标法线人为设成常数方向 (0,0,1)——真实曲面法线不可能恒为
        同一方向，故"有没有被重估"可由数值直接判别。另一组对照组不给法线（走内部重估）。
        若把目标法线无声重估（修过头），哨兵会被覆写成真实法线且两组解完全相同 → 两条
        断言同时变红。注：不能用"法线取反"当哨兵——点对面代价是残差平方，正负号无差别。
        """
        n = len(self.pts_src)
        sentinel = np.tile(np.array([0.0, 0.0, 1.0]), (n, 1))

        wf_s, src_s, tgt_s = self._fresh_pair(sentinel)
        ok, msg, res_s = wf_s.icp_register(src_s, tgt_s, estimation_method="point_to_plane")
        self.assertTrue(ok, msg)
        np.testing.assert_allclose(np.asarray(wf_s.get_node(tgt_s).pcd.normals), sentinel,
                                   atol=1e-12, err_msg="目标已有法线被重估/覆写")

        wf_a, src_a, tgt_a = self._fresh_pair(None)
        ok, msg, res_a = wf_a.icp_register(src_a, tgt_a, estimation_method="point_to_plane")
        self.assertTrue(ok, msg)
        self.assertFalse(wf_a.get_node(tgt_a).pcd.has_normals(),
                         "对照组：内部重估也不得写回目标节点")

        diff = float(np.abs(res_s.transformation - res_a.transformation).max())
        self.assertGreater(diff, 1e-3,
                           f"哨兵法线与内部重估法线得到同一解（最大差 {diff:.2e}）"
                           f" → 目标已存法线被忽略、配准偷偷重估了")


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

    def test_merge_sources_untouched(self):
        """S3b：合并 = 新增节点，源节点点序/属性逐点不变、不入撤销历史。

        merge_pointclouds 会对缺色/缺法线的输入就地补默认属性（pcd_utils.py:18-37），
        workflow 若传 node.pcd 本体，源节点会被不可逆改写（无色 → 0.85 灰、
        无法线 → 零法线），export_cloud 导出的也是被污染的数据。
        """
        a = self._cloud(300, color=(1.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0))
        b = self._cloud(200)
        a_pts, a_cols, a_nrm = (np.asarray(a.points).copy(),
                                np.asarray(a.colors).copy(),
                                np.asarray(a.normals).copy())
        b_pts = np.asarray(b.points).copy()
        ida = self.wf.add_cloud("a", a)
        idb = self.wf.add_cloud("b", b)

        ok, msg, new_id = self.wf.merge_clouds([ida, idb], "ab")
        self.assertTrue(ok, msg)
        self.assertIsNotNone(new_id)

        src_a, src_b = self.wf.get_node(ida).pcd, self.wf.get_node(idb).pcd
        self.assertTrue(np.array_equal(np.asarray(src_a.points), a_pts), "源 a 点序被改写")
        self.assertTrue(np.array_equal(np.asarray(src_a.colors), a_cols), "源 a 颜色被改写")
        self.assertTrue(np.array_equal(np.asarray(src_a.normals), a_nrm), "源 a 法线被改写")
        self.assertTrue(np.array_equal(np.asarray(src_b.points), b_pts), "源 b 点序被改写")
        self.assertFalse(src_b.has_colors(), "缺色源节点被就地填了 0.85 灰")
        self.assertFalse(src_b.has_normals(), "缺法线源节点被就地填了零法线")
        self.assertFalse(self.wf.can_undo(), "合并不应进入撤销历史")


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


class TestProcessNoOpHistory(unittest.TestCase):
    """D1：`apply_process` 不产生变化时不得压入空操作历史。

    全算子禁用且点云无 NaN/零点时，`PointCloudProcessor.process()` 原样返回入参对象，
    旧写法把它当 after 记入历史（before 与 after 同一引用）→ `undo` 占一个槽位却什么
    都没变，`can_undo()` 也从 False 变 True（UI 撤销按钮随之点亮）。
    """

    def _wf_with(self, pts: np.ndarray):
        wf = CloudCompareWorkflow()
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        return wf, wf.add_cloud("n", pcd)

    def test_all_operators_disabled_pushes_no_history(self):
        wf, nid = self._wf_with(_asym_blob(500))
        ref = wf.get_node(nid).pcd
        self.assertFalse(wf.can_undo(), "前置条件：新点云无可撤销操作")

        ok, msg, stats = wf.apply_process(nid)

        self.assertFalse(ok, f"未启用任何算子却报成功：{msg}")
        self.assertIsNone(stats)
        self.assertFalse(wf.can_undo(),
                         "全算子禁用路径压入了空操作历史 → 撤销变成 no-op")
        self.assertIs(wf.get_node(nid).pcd, ref, "无变化路径不应替换节点点云对象")
        self.assertEqual(wf.get_node(nid).point_count, 500)

    def test_nan_removal_still_enters_history(self):
        """口径边界：剔除无效点是真实变化，即便算子全禁用也必须入历史且可撤销。"""
        pts = _asym_blob(500)
        pts[:20] = np.nan
        wf, nid = self._wf_with(pts)

        ok, msg, stats = wf.apply_process(nid)

        self.assertTrue(ok, msg)
        self.assertEqual(stats.get("invalid_removed"), 20)
        self.assertEqual(wf.get_node(nid).point_count, 480)
        self.assertTrue(wf.can_undo(), "剔除了 20 个无效点却未入历史")
        ok, msg = wf.undo()
        self.assertTrue(ok, msg)
        self.assertEqual(wf.get_node(nid).point_count, 500,
                         "撤销后未回到含 NaN 的原始点云")


class TestICPResultReport(unittest.TestCase):
    """ICP 结果的**展示口径**（§10.2 连带要求）——判据是"人看得见的那两行"。

    背景：`_asym_blob(8000)` 上实测 12 组 fitness 全部 1.000000（含姿态差 1.13° 的局部
    极小那组），只报 fitness 会把局部极小当成功。故：① 结果必须同时给 fitness /
    inlier_rmse / 姿态角误差 / 平移误差；② 残差没落到点距以下时要提示"疑落入局部极小，
    建议给初值"。此处直接调 app 层纯函数，不依赖窗口显示。
    """

    def setUp(self):
        if not _HAS_APP:
            self.skipTest(f"app 层不可导入: {_APP_IMPORT_ERR}")
        self.pts_src = _asym_blob(8000)
        self.T_true = _make_T(8.0, -5.0, 12.0, (0.03, -0.02, 0.05))

    def _run(self, method: str, init=None):
        """同一对真值点云、指定估计方法与初值跑一次 ICP，返回 (result, 点距)。"""
        wf = CloudCompareWorkflow()
        src = o3d.geometry.PointCloud()
        src.points = o3d.utility.Vector3dVector(self.pts_src)
        tgt = o3d.geometry.PointCloud()
        tgt.points = o3d.utility.Vector3dVector(self.pts_src.copy())
        tgt.transform(self.T_true)
        sid = wf.add_cloud("src", src)
        tid = wf.add_cloud("tgt", tgt)
        spacing = avg_point_spacing(wf.get_node(sid).pcd)
        ok, msg, res = wf.icp_register(sid, tid, init_transform=init,
                                       estimation_method=method)
        self.assertTrue(ok, msg)
        self.assertIsNotNone(res)
        return res, spacing

    def test_label_carries_all_four_metrics(self):
        """三组都要四项齐全：fitness / inlier_rmse / 姿态角误差 / 平移误差（+ 4x4 矩阵）。"""
        cases = [("point_to_point", None), ("point_to_point", self.T_true.copy()),
                 ("point_to_plane", None)]
        for method, init in cases:
            res, spacing = self._run(method, init)
            panel, _, log = judge_icp_result(res, point_spacing=spacing)
            tag = f"{method}{'+真值初值' if init is not None else '冷启动'}"
            for field in ("fitness=", "inlier_rmse=", "姿态角误差=", "平移误差="):
                self.assertIn(field, panel, f"{tag}: 结果标签缺 {field}")
            self.assertEqual(panel.count("\n") - 4, 1 + (1 if "⚠" in panel else 0),
                             f"{tag}: 标签行数异常\n{panel}")
            matrix_rows = [ln for ln in panel.split("\n") if len(ln.split()) == 4]
            self.assertEqual(len(matrix_rows), 4, f"{tag}: 标签应含 4 行矩阵\n{panel}")
            # 长度量单位随点云，角度是度：必须标注，否则 0.0601 会被读成 mm
            self.assertIn("点云单位", panel, f"{tag}: 平移量未标单位")
            self.assertIn("°", panel, f"{tag}: 角度未带度符号")
            for field in ("fitness=", "inlier_rmse=", "姿态角误差=", "平移误差="):
                self.assertIn(field, log, f"{tag}: 日志缺 {field}")

    def test_local_minimum_flag_discriminates(self):
        """局部极小提示只看"残差有没有落到点距以下"，且判定不得退回 fitness。

        实测三组 fitness 全为 1.000000、点距中位 1.542mm：ptp 冷启动 rmse 1.651e-3
        （=1.07×点距）→ 必须提示；ptp 真值初值与 p2pl 冷启动 rmse ≤1e-10 → 必须不提示。
        """
        strict = [("point_to_point", self.T_true.copy()), ("point_to_plane", None)]
        loose = [("point_to_point", None)]

        for method, init in loose:
            res, spacing = self._run(method, init)
            panel, warn, log = judge_icp_result(res, point_spacing=spacing)
            self.assertGreaterEqual(res.fitness, 0.999,
                                    "该组 fitness 不是 1.0 级，判别前提变了，需重核阈值")
            self.assertTrue(warn, f"ptp 冷启动 rmse={res.inlier_rmse:.3e} 未提示局部极小")
            self.assertIn("疑落入局部极小，建议给初值", log)
            self.assertIn("疑落入局部极小", panel)  # 面板上也要看得见（不是只写日志）

        for method, init in strict:
            res, spacing = self._run(method, init)
            _, warn, log = judge_icp_result(res, point_spacing=spacing)
            self.assertGreaterEqual(res.fitness, 0.999)
            self.assertFalse(warn, f"{method} rmse={res.inlier_rmse:.3e} 被误判为局部极小")
            self.assertNotIn("疑落入局部极小", log)

    def test_zero_correspondence_not_read_as_perfect(self):
        """fitness=0（一个对应点都没有）时 inlier_rmse 恒为 0，必须标成"不可用"。

        否则面板上"inlier_rmse=0"会被读成完美对齐——这是 S1 报告里 fitness 陷阱的镜像版本。
        """
        wf = CloudCompareWorkflow()
        src = o3d.geometry.PointCloud()
        src.points = o3d.utility.Vector3dVector(self.pts_src)
        tgt = o3d.geometry.PointCloud()
        tgt.points = o3d.utility.Vector3dVector(self.pts_src + np.array([1.0, 0.0, 0.0]))
        sid = wf.add_cloud("src", src)
        tid = wf.add_cloud("tgt", tgt)

        ok, msg, res = wf.icp_register(sid, tid, max_distance=1e-3)
        self.assertTrue(ok, msg)
        self.assertEqual(res.fitness, 0.0, "前置条件：两朵点云相距 1m 应无任何对应点")
        self.assertEqual(res.inlier_rmse, 0.0, "前置条件：open3d 无对应时 inlier_rmse 为 0")

        panel, warn, log = judge_icp_result(res, point_spacing=avg_point_spacing(wf.get_node(sid).pcd))
        self.assertTrue(warn, "零对应却未告警 → fitness=0 / rmse=0 会被读成完美配准")
        self.assertIn("不可用", panel)
        self.assertIn("无有效对应点", log)
        self.assertNotIn("疑落入局部极小", log, "零对应与局部极小是两回事，提示不得混用")

    def test_pose_error_is_relative_to_initial_guess(self):
        """姿态/平移误差口径 = 相对初值（未给初值即原始位姿），与 core 真值比对同式。"""
        res, _ = self._run("point_to_point", self.T_true.copy())
        panel, _, _ = judge_icp_result(res, point_spacing=None, init_transform=self.T_true)
        self.assertIn("姿态角误差=0.000°", panel)
        self.assertIn("平移误差=0.0000", panel)

        res0, _ = self._run("point_to_point", None)
        panel0, _, _ = judge_icp_result(res0, point_spacing=None)
        _, _, log0 = judge_icp_result(res0, point_spacing=None, init_transform=np.eye(4))
        # 冷启动那组相对单位阵 ≈ 真值位姿本身（姿态角 8/-5/12° 的等效轴角 ≈15°）
        self.assertGreater(rotation_angle_deg(res0.transformation[:3, :3]), 10.0)
        self.assertIn("姿态角误差=", panel0)
        self.assertIn("相对初值", log0)

    def test_panel_to_handler_wiring_offscreen(self):
        """接线闭环：属性面板按钮 → icp_requested → workspace._on_icp → 结果上标签/日志。

        这一段正是 S2 要接的"UI 零接线"，纯函数测不到，故在 offscreen 下真点一次按钮：
        源 = 当前选中点云，目标由下拉提供，结果标签须含四项指标。
        """
        from PySide6.QtWidgets import QApplication
        from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace

        app = QApplication.instance() or QApplication([])  # noqa: F841
        ws = CloudCompareWorkspace()
        src = o3d.geometry.PointCloud()
        src.points = o3d.utility.Vector3dVector(self.pts_src)
        tgt = o3d.geometry.PointCloud()
        tgt.points = o3d.utility.Vector3dVector(self.pts_src.copy())
        tgt.transform(self.T_true)
        sid = ws._workflow.add_cloud("src", src)
        tid = ws._workflow.add_cloud("tgt", tgt)

        ws._current_node_id = sid
        ws._props.set_icp_targets([(tid, "tgt")])
        ws._props._combo_icp_method.setCurrentIndex(
            ws._props._combo_icp_method.findData("point_to_point"))
        logged = []
        ws.log_message.connect(lambda msg, level: logged.append((msg, level)))

        ws._props._btn_icp.click()

        label = ws._props._lbl_icp_result.text()
        self.assertIn("fitness=", label)
        self.assertIn("inlier_rmse=", label)
        self.assertIn("姿态角误差=", label)
        self.assertIn("平移误差=", label)
        self.assertTrue(logged, "点按钮后 log_message 未发出任何日志")
        text = "\n".join(m for m, _ in logged)
        self.assertIn("变换矩阵 (源→目标)", text)
        self.assertTrue(any(lv == "warn" and "疑落入局部极小" in m for m, lv in logged),
                        f"ptp 冷启动未给出局部极小告警，日志={logged!r}")
        # 源点云已被就地改写并可撤销（接线没把 workflow 的历史/状态绕过去）
        self.assertTrue(ws._workflow.can_undo())


class TestMergeWiring(unittest.TestCase):
    """S3 合并接线（G-S3）：DB 树多选 → 面板按钮 → workflow.merge_clouds → 回树。

    树为唯一真值：选中集由工作区从树读，测试在 offscreen 下对树 item 设选中态后
    真点一次按钮，走完整 UI 数据路径（与 S2 的 ICP 接线测试同法）。
    """

    def setUp(self):
        if not _HAS_APP:
            self.skipTest(f"app 层不可导入: {_APP_IMPORT_ERR}")
        from PySide6.QtWidgets import QApplication
        from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace
        self._QApplication = QApplication
        self._Workspace = CloudCompareWorkspace

    def _make_workspace_with(self, specs):
        """specs = [(name, n, color, normal)] → (ws, [node_id,...])。树/工作区同步建。"""
        ws = self._Workspace()
        ids = []
        for name, n, color, normal in specs:
            pcd = TestMergeClouds._cloud(n, color=color, normal=normal)
            nid = ws._workflow.add_cloud(name, pcd)
            ws._add_node_to_ui(ws._workflow.get_node(nid))
            ids.append(nid)
        return ws, ids

    def test_merge_wiring_offscreen(self):
        """接线闭环 + 属性并集经 UI 路径（混合属性输入）+ 历史口径（G-S3-a/b/c）。"""
        app = self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws, (ida, idb) = self._make_workspace_with([
            ("a", 300, (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),  # 有色有法线
            ("b", 200, None, None),                          # 无色无法线
        ])

        # G-S3-b 前置：合并 = 新增节点不入历史，前后 undo/redo 状态必须不变
        undo_before, redo_before = ws._workflow.can_undo(), ws._workflow.can_redo()

        ws._db_tree._node_items[ida].setSelected(True)
        ws._db_tree._node_items[idb].setSelected(True)
        self.assertTrue(ws._props._btn_merge.isEnabled(), "选中 2 朵后合并按钮应启用")

        logged = []
        ws.log_message.connect(lambda msg, level: logged.append((msg, level)))
        ws._props._btn_merge.click()

        # G-S3-c：新节点入 workflow + 入树（顶层，与 v1 一致），源节点保留
        clouds = ws._workflow.list_cloud_nodes()
        self.assertEqual(len(clouds), 3, "合并应新增 1 节点且源节点保留")
        merged_id = next(n.node_id for n in clouds if n.node_id not in (ida, idb))
        merged_item = ws._db_tree._node_items.get(merged_id)
        self.assertIsNotNone(merged_item, "合并结果未入树")
        self.assertIsNone(merged_item.parent(), "合并结果应为顶层节点（与 v1 一致）")
        self.assertIsNotNone(ws._db_tree._node_items.get(ida), "源节点 a 应保留")
        self.assertIsNotNone(ws._db_tree._node_items.get(idb), "源节点 b 应保留")

        merged = ws._workflow.get_node(merged_id).pcd
        self.assertEqual(len(merged.points), 500)

        # G-S3-a 经 UI 路径（W2a′ 硬要求：断言属性槽长度，不只点数）：
        # 颜色逐点并集，无色一侧按 pcd_utils 口径填 0.85 灰
        self.assertTrue(merged.has_colors())
        cols = np.asarray(merged.colors)
        self.assertEqual(len(cols), 500, "属性槽长度必须 = 总点数（变异判别点）")
        self.assertTrue(np.allclose(cols[:300], [1.0, 0.0, 0.0]), "前半段颜色丢失")
        self.assertTrue(np.allclose(cols[300:], 0.85), "无色一侧应为 0.85 灰（并集填充）")
        # 法线逐点并集，无法线一侧零填充（全零段不可用）
        self.assertTrue(merged.has_normals())
        nrm = np.asarray(merged.normals)
        self.assertEqual(len(nrm), 500)
        self.assertTrue(np.allclose(nrm[:300], [0.0, 0.0, 1.0]))
        self.assertTrue(np.allclose(nrm[300:], 0.0))

        # G-S3-c：日志一行 + 状态回落 loaded
        self.assertTrue(any("合并完成" in m and lv == "success" for m, lv in logged),
                        f"缺合并成功日志: {logged!r}")
        self.assertEqual(ws._state, "loaded")

        # G-S3-b：合并前后 undo/redo 状态不变；对合并结果做一次处理后可 undo 复原
        self.assertEqual(ws._workflow.can_undo(), undo_before)
        self.assertEqual(ws._workflow.can_redo(), redo_before)
        ok, msg = ws._workflow.estimate_normals(merged_id)
        self.assertTrue(ok, msg)
        self.assertTrue(ws._workflow.can_undo(), "处理合并结果后应可撤销")
        self.assertFalse(np.allclose(np.asarray(ws._workflow.get_node(merged_id).pcd.normals)[300:], 0.0),
                         "前置：法线估计后零填充段应被改写")
        ok, msg = ws._workflow.undo()
        self.assertTrue(ok, msg)
        self.assertTrue(np.allclose(np.asarray(ws._workflow.get_node(merged_id).pcd.normals)[300:], 0.0),
                        "undo 后合并结果应复原为合并当场的零填充状态")

    def test_merge_order_follows_tree_display(self):
        """W2b/W2d：合并输入顺序 = 树显示序（非点击序）；混合选中只收 cloud 节点。"""
        app = self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        wf, tree = ws._workflow, ws._db_tree
        # 走真实 UI 建树路径：云节点顶层入树（文件节点在 S3 无必经路径，略）
        ida = wf.add_cloud("a", TestMergeClouds._cloud(300, color=(1.0, 0.0, 0.0)))
        idb = wf.add_cloud("b", TestMergeClouds._cloud(200, color=(0.0, 1.0, 0.0)))
        idc = wf.add_cloud("c", TestMergeClouds._cloud(100, color=(0.0, 0.0, 1.0)))
        ws._add_node_to_ui(wf.get_node(ida))
        ws._add_node_to_ui(wf.get_node(idb))
        ws._add_node_to_ui(wf.get_node(idc))
        # 给 a 挂一个标量场节点（混合选中项的一部分）
        a_item = tree._node_items[ida]
        tree.add_scalar_node(ida, "curvature", ida)

        # 反点击序选：先 c、再 b、最后 a（外加 a 的标量节点）
        tree._node_items[idc].setSelected(True)
        tree._node_items[idb].setSelected(True)
        tree._node_items[f"{ida}_scalar_curvature"].setSelected(True)
        a_item.setSelected(True)

        # W2d：标量节点被过滤，ids 只含 cloud；W2b：顺序 = 树显示序（a→b→c）
        self.assertEqual(tree.selected_cloud_ids(), [ida, idb, idc])

        logged = []
        ws.log_message.connect(lambda msg, level: logged.append((msg, level)))
        ws._props._btn_merge.click()

        clouds = wf.list_cloud_nodes()
        merged_id = next(n.node_id for n in clouds
                         if n.node_id not in (ida, idb, idc))
        cols = np.asarray(wf.get_node(merged_id).pcd.colors)
        # 树显示序 a→b→c：前 300 红、中 200 绿、后 100 蓝（与点击顺序无关）
        self.assertTrue(np.allclose(cols[:300], [1.0, 0.0, 0.0]), "a 段颜色/顺序错")
        self.assertTrue(np.allclose(cols[300:500], [0.0, 1.0, 0.0]), "b 段颜色/顺序错")
        self.assertTrue(np.allclose(cols[500:], [0.0, 0.0, 1.0]), "c 段颜色/顺序错")

    def test_merge_button_enabled_state(self):
        """合并按钮 enabled 随选中数变化：<2 禁用，≥2 启用。"""
        app = self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws, (ida, idb) = self._make_workspace_with([("a", 10, None, None),
                                                    ("b", 10, None, None)])
        self.assertFalse(ws._props._btn_merge.isEnabled())
        self.assertIn("需 ≥2", ws._props._lbl_merge.text())

        ws._db_tree._node_items[ida].setSelected(True)
        ws._on_tree_selection(ida)
        self.assertFalse(ws._props._btn_merge.isEnabled(), "仅选 1 朵应禁用")
        self.assertIn("已选 1 朵", ws._props._lbl_merge.text())

        ws._db_tree._node_items[idb].setSelected(True)
        ws._on_tree_selection(idb)
        self.assertTrue(ws._props._btn_merge.isEnabled(), "选 2 朵应启用")
        self.assertIn("已选 2 朵", ws._props._lbl_merge.text())

    def test_judge_icp_result_low_fitness_warns(self):
        """G-S3-d：0 < fitness < 0.90 必须告警且文案含 fitness 值（不依赖点距）。"""
        from types import SimpleNamespace
        from prototypes.cloudcompare_like.app.cc_workspace import (
            ICP_LOCAL_MIN_FITNESS, judge_icp_result)

        result = SimpleNamespace(
            transformation=np.eye(4), fitness=0.42, inlier_rmse=1.0e-3)
        panel, warn, log = judge_icp_result(result, point_spacing=None)
        self.assertTrue(warn, "低 fitness 未告警")
        self.assertIn("0.420000", log, "告警文案必须含 fitness 值")
        self.assertIn(f"低于 {ICP_LOCAL_MIN_FITNESS:g}", log)
        self.assertIn("对应点过少", panel, "面板上也要看得见")

        # 边界：fitness=0 仍走"无有效对应点"分支，不得被新分支吞掉
        result0 = SimpleNamespace(
            transformation=np.eye(4), fitness=0.0, inlier_rmse=0.0)
        _, warn0, log0 = judge_icp_result(result0, point_spacing=None)
        self.assertTrue(warn0)
        self.assertIn("无有效对应点", log0)
        self.assertNotIn("对应点过少", log0)


class TestLoadFilesWiring(unittest.TestCase):
    """G-S3.5-c 载入闭环：多文件 / 失败不静默（W11）/ 拖拽同路径（W14）/ 四处同步。"""

    def setUp(self):
        if not _HAS_APP:
            self.skipTest(f"app 层不可导入: {_APP_IMPORT_ERR}")
        from PySide6.QtWidgets import QApplication
        from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace
        self._QApplication = QApplication
        self._Workspace = CloudCompareWorkspace

    @staticmethod
    def _write_ply(directory, name, n=200, seed=0):
        rng = np.random.default_rng(seed)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(rng.normal(size=(n, 3)))
        path = os.path.join(directory, name)
        assert o3d.io.write_point_cloud(path, pcd), f"写测试点云失败: {path}"
        return path

    def test_multi_file_load_tree_and_sync(self):
        """多文件载入：file→cloud 层级入树，状态/视图/ICP 下拉同步。"""
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            pa = self._write_ply(d, "a.ply", 1200, 1)
            pb = self._write_ply(d, "b.pcd", 2300, 2)
            ws._load_files([pa, pb])

        tree = ws._db_tree
        self.assertEqual(tree._tree.topLevelItemCount(), 2, "每文件一个顶层文件节点")
        for i in range(tree._tree.topLevelItemCount()):
            item = tree._tree.topLevelItem(i)
            self.assertEqual(item.text(1), "文件")
            self.assertEqual(item.childCount(), 1, "文件节点下应挂 1 朵点云")
            cloud_item = item.child(0)
            self.assertEqual(cloud_item.text(1), "点云")
            self.assertIn(",", cloud_item.text(2), "点数列应显示千分位计数")
        self.assertEqual(ws._state, "loaded")
        self.assertEqual(len(ws._workflow.list_cloud_nodes()), 2)
        # 视图同步：viewer 持有全部可见点云
        self.assertEqual(set(ws._viewer._clouds.keys()),
                         {n.node_id for n in ws._workflow.list_cloud_nodes()})
        # ICP 目标下拉同步：当前选中云之外的全部点云
        self.assertEqual(ws._props._combo_icp_target.count(), 1)

    def test_load_failure_not_silent_from_loaded(self):
        """W11：已载入状态下吃坏文件 → error 日志 + 树不新增 + 状态不变。"""
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            good = self._write_ply(d, "good.ply", 100, 3)
            ws._load_files([good])
            self.assertEqual(ws._state, "loaded")

            bad = os.path.join(d, "bad.ply")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("this is not a point cloud")
            junk = os.path.join(d, "notes.txt")
            with open(junk, "w", encoding="utf-8") as f:
                f.write("x")

            logged = []
            ws.log_message.connect(lambda m, lv: logged.append((m, lv)))
            nodes_before = len(ws._db_tree._node_items)
            clouds_before = len(ws._workflow.list_cloud_nodes())
            ws._load_files([bad, junk])

        self.assertEqual(len(ws._db_tree._node_items), nodes_before, "树不得新增节点")
        self.assertEqual(len(ws._workflow.list_cloud_nodes()), clouds_before)
        self.assertEqual(ws._state, "loaded", "已载入状态下失败批次不得改状态")
        errors = [m for m, lv in logged if lv == "error"]
        self.assertEqual(len(errors), 2, f"坏文件与不支持的类型都应有 error 日志: {logged!r}")
        self.assertTrue(any("bad.ply" in m for m in errors))
        self.assertTrue(any("notes.txt" in m for m in errors))

    def test_load_failed_state_from_idle(self):
        """裁定 B：idle 吃真坏文件 → failed（S4 状态色的真实分支，非改标签伪造）。"""
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "broken.ply")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("ply\nbroken header\n")
            ws._load_files([bad])
        self.assertEqual(ws._state, "failed")

    def test_mixed_batch_loaded_state_and_error_log(self):
        """混合批次（1 成功 + 1 失败）：状态点落 loaded 且 error 日志同现，二者缺一即缺陷。"""
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            good = self._write_ply(d, "good.ply", 100, 8)
            bad = os.path.join(d, "bad.ply")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("not a point cloud")
            logged = []
            ws.log_message.connect(lambda m, lv: logged.append((m, lv)))
            ws._load_files([good, bad])
        self.assertEqual(ws._state, "loaded", "有成功必须落 loaded")
        self.assertTrue(any(lv == "error" and "bad.ply" in m for m, lv in logged),
                        f"失败文件必须同现 error 日志: {logged!r}")

    def test_drag_drop_same_load_path(self):
        """W14：合成 QMimeData 投递，走与对话框完全相同的 _load_files 实参元组。"""
        from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
        from PySide6.QtGui import QDropEvent

        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            pa = self._write_ply(d, "a.ply", 120, 4)
            recorded = []
            ws._load_files = lambda paths: recorded.append(tuple(paths))

            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(pa)])
            drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime,
                              Qt.LeftButton, Qt.NoModifier)
            ws.dropEvent(drop)
            self.assertTrue(drop.isAccepted())
            # QUrl 规一化分隔符后必须与对话框入口的实参一致
            self.assertEqual(tuple(os.path.normpath(p) for p in recorded[0]),
                             (os.path.normpath(pa),),
                             "拖拽应与对话框产出相同实参元组")

            # 空 mime（无 urls）→ 不触发载入
            empty = QMimeData()
            drop2 = QDropEvent(QPointF(10, 10), Qt.CopyAction, empty,
                               Qt.LeftButton, Qt.NoModifier)
            ws.dropEvent(drop2)
            self.assertFalse(drop2.isAccepted())
            self.assertEqual(len(recorded), 1, "空 mime 不得触发载入")


class TestDBTreeDisplay(unittest.TestCase):
    """G-S3.5-d DB 树显示：三列 / 层级 / 可见性同步 / 右键四项 / 双击适配。"""

    def setUp(self):
        if not _HAS_APP:
            self.skipTest(f"app 层不可导入: {_APP_IMPORT_ERR}")
        from PySide6.QtWidgets import QApplication
        from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace
        self._QApplication = QApplication
        self._Workspace = CloudCompareWorkspace

    def _load_one(self, ws, directory, name="a.ply", n=150, seed=5):
        rng = np.random.default_rng(seed)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(rng.normal(size=(n, 3)))
        path = os.path.join(directory, name)
        assert o3d.io.write_point_cloud(path, pcd)
        ws._load_files([path])
        return ws._workflow.list_cloud_nodes()[-1].node_id

    def test_three_columns_and_hierarchy(self):
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(ws, d, n=1500)
        tree = ws._db_tree
        self.assertFalse(tree._tree.isHeaderHidden(), "表头必须可见（三列）")
        header = tree._tree.headerItem()
        self.assertEqual([header.text(c) for c in range(3)], ["名称", "类型", "点数"])
        file_item = tree._tree.topLevelItem(0)
        cloud_item = file_item.child(0)
        self.assertEqual(cloud_item.text(2), "1,500")
        # 标量场节点层级：file → cloud → scalar
        scalar_item = tree.add_scalar_node(cid, "z", cid)
        self.assertIs(scalar_item.parent(), cloud_item)
        self.assertEqual(scalar_item.text(1), "标量场")
        self.assertEqual(scalar_item.text(2), "-")

    def test_visibility_syncs_viewer(self):
        from PySide6.QtCore import Qt
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            ida = self._load_one(ws, d, "a.ply", 100, 6)
            idb = self._load_one(ws, d, "b.ply", 100, 7)
        self.assertEqual(set(ws._viewer._clouds.keys()), {ida, idb})
        ws._db_tree._node_items[ida].setCheckState(0, Qt.Unchecked)
        self.assertNotIn(ida, ws._viewer._clouds, "取消勾选后视图应移除该点云")
        self.assertIn(idb, ws._viewer._clouds)
        node = ws._workflow.get_node(ida)
        self.assertFalse(node.visible, "workflow 侧可见性应同步")

    def test_context_menu_four_actions(self):
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(ws, d)
        item = ws._db_tree._node_items[cid]
        menu = ws._db_tree._build_context_menu(item)
        texts = [a.text() for a in menu.actions()]
        for expected in ("适配视角", "导出点云", "重命名", "删除"):
            self.assertIn(expected, texts, f"右键菜单缺「{expected}」: {texts}")

    def test_context_menu_export_state(self):
        """G-K3：cloud 节点导出项可用（端到端已接线）；file 节点禁用 + tooltip。"""
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(ws, d)
        cloud_item = ws._db_tree._node_items[cid]
        acts = {a.text(): a for a in ws._db_tree._build_context_menu(cloud_item).actions()}
        self.assertTrue(acts["导出点云"].isEnabled(),
                        "K3 起导出端到端已接线，cloud 节点菜单项必须可用")
        file_item = ws._db_tree._tree.topLevelItem(0)
        file_acts = {a.text(): a for a in ws._db_tree._build_context_menu(file_item).actions()}
        self.assertFalse(file_acts["导出点云"].isEnabled(),
                         "file 节点不可导出，菜单项必须禁用")
        self.assertTrue(file_acts["导出点云"].toolTip(), "禁用项必须有 tooltip 明示原因")

    def test_rename_syncs_workflow_and_props(self):
        """K2-D2/W12：重命名后树、workflow、属性面板三方同名（无状态漂移）。"""
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(ws, d)
        ws._on_tree_selection(cid)  # 让属性面板显示该节点
        item = ws._db_tree._node_items[cid]
        item.setText(0, "renamed_cloud")  # 复刻 _rename_item 的树侧动作
        ws._db_tree.rename_requested.emit(cid, "renamed_cloud")
        node = ws._workflow.get_node(cid)
        self.assertIsNotNone(node)
        self.assertEqual(node.name, "renamed_cloud")
        self.assertEqual(ws._props._lbl_name.text(), "renamed_cloud")
        self.assertEqual(item.text(0), "renamed_cloud")

    def test_double_click_fits_view(self):
        self._QApplication.instance() or self._QApplication([])  # noqa: F841
        ws = self._Workspace()
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(ws, d)
        fitted = []
        ws._viewer.fit_to_cloud = lambda cloud_id: fitted.append(cloud_id)
        item = ws._db_tree._node_items[cid]
        ws._db_tree._tree.itemDoubleClicked.emit(item, 0)
        self.assertEqual(fitted, [cid], "双击点云应触发适配视角")


class TestShellOffscreen(unittest.TestCase):
    """G-S3.5-a① 外壳四件 + W15 浮动日志不吞日志（offscreen 构造断言）。"""

    def setUp(self):
        if not _HAS_APP:
            self.skipTest(f"app 层不可导入: {_APP_IMPORT_ERR}")
        from PySide6.QtWidgets import QApplication, QScrollArea
        from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWindow
        self._QApplication = QApplication
        self._QScrollArea = QScrollArea
        self._Window = CloudCompareWindow

    def _make_window(self):
        app = self._QApplication.instance() or self._QApplication([])  # noqa: F841
        win = self._Window()
        win.show()
        app.processEvents()
        return win

    def test_shell_four_pieces(self):
        win = self._make_window()
        self.assertTrue(win._toolbar.isVisible(), "顶栏缺失")
        self.assertTrue(win._statusbar.isVisible(), "状态栏缺失")
        self.assertIsInstance(win.workspace._left_panel, self._QScrollArea,
                              "左面板必须是 QScrollArea")
        win.set_log_visible(True)
        self.assertTrue(win._log_panel.isVisible(), "浮动日志面板未显示")
        self.assertFalse(win._log_panel.isWindow(), "日志必须是叠加层而非独立窗")

    def test_floating_log_receives_workspace_log(self):
        """W15：LogPanel → 浮动后 _log 仍可达（blockCount 递增 + 状态栏提示同步）。

        QPlainTextEdit 首行写入空文档不产生新 block（blockCount 恒 1 起），
        故连续写两行、断言第二行带来递增。
        """
        win = self._make_window()
        win.set_log_visible(True)
        win.workspace._log("外壳接线自检 1", "info")
        app = self._QApplication.instance()
        app.processEvents()
        before = win._log_panel._text.document().blockCount()
        win.workspace._log("外壳接线自检 2", "info")
        app.processEvents()
        after = win._log_panel._text.document().blockCount()
        self.assertGreater(after, before, "浮动日志吞掉了工作区日志")
        self.assertIn("外壳接线自检 2", win._st_hint.text())

    def test_state_dot_follows_workspace(self):
        """四态：idle 吃真坏文件 → 状态点/文案落 failed（STATUS_ERR 分支真实可达）。"""
        win = self._make_window()
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "broken.ply")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("ply\nbroken header\n")
            win.workspace._load_files([bad])
        self.assertEqual(win.workspace._state, "failed")
        self.assertIn("载入失败", win._st_step.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
