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


if __name__ == "__main__":
    unittest.main(verbosity=2)
