# -*- coding: utf-8 -*-
"""
CloudCompare-Like 原型单元测试。

运行方式：
    cd prototypes/cloudcompare_like
    pytest tests/test_cc.py -v
"""

import numpy as np
import pytest


def _make_sphere_cloud(n=5000, radius=1.0):
    """生成测试用球面点云。"""
    phi = np.random.uniform(0, 2*np.pi, n)
    theta = np.random.uniform(0, np.pi, n)
    x = radius * np.sin(theta) * np.cos(phi)
    y = radius * np.sin(theta) * np.sin(phi)
    z = radius * np.cos(theta)
    return np.stack([x, y, z], axis=1).astype(np.float32)


class TestGeometry:
    """测试几何工具模块。"""

    def test_estimate_normals_shape(self):
        from core.cc_geometry import estimate_normals
        pts = _make_sphere_cloud(1000)
        normals = estimate_normals(pts, k=10)
        assert normals.shape == (1000, 3)
        # 归一化检查
        norms = np.linalg.norm(normals, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)

    def test_voxel_downsample(self):
        from core.cc_geometry import voxel_downsample
        pts = _make_sphere_cloud(10000)
        ds, _, _ = voxel_downsample(pts, voxel_size=0.2)
        assert len(ds) < len(pts)
        assert ds.dtype == np.float32

    def test_bounding_box(self):
        from core.cc_geometry import bounding_box
        pts = _make_sphere_cloud(100)
        mn, mx = bounding_box(pts)
        assert np.all(mn <= mx)
        assert mn.shape == (3,)
        assert mx.shape == (3,)


class TestOctreeLOD:
    """测试 Octree + LOD 模块。"""

    def test_build_and_query(self):
        from core.cc_octree_lod import OctreeLOD
        pts = _make_sphere_cloud(5000)
        lod = OctreeLOD(pts)
        lod.build_async()
        lod.wait_ready(timeout=10.0)
        assert lod.is_ready()

        # 球体查询
        center = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        indices = lod.query_sphere(center, 0.5)
        assert len(indices) > 0
        assert len(indices) <= len(pts)

    def test_visible_collection(self):
        from core.cc_octree_lod import OctreeLOD
        pts = _make_sphere_cloud(5000)
        lod = OctreeLOD(pts)
        lod.build_async()
        lod.wait_ready(timeout=10.0)

        cam_pos = np.array([3.0, 3.0, 3.0], dtype=np.float32)
        cam_dir = np.array([-1.0, -1.0, -1.0], dtype=np.float32)
        visible = lod.collect_visible_points(cam_pos, cam_dir, fov=60.0, screen_height=1080)
        assert visible is not None
        assert len(visible) > 0
        assert len(visible) <= len(pts)


class TestScalarField:
    """测试标量场模块。"""

    def test_color_maps(self):
        from core.cc_scalar_field import get_color_map
        for name in ["viridis", "jet", "hot", "coolwarm"]:
            cmap = get_color_map(name)
            assert cmap.shape == (256, 4)
            assert cmap.dtype == np.float32
            assert np.all(cmap >= 0) and np.all(cmap <= 1)

    def test_scalar_field_rgba(self):
        from core.cc_scalar_field import ScalarField
        values = np.random.rand(1000).astype(np.float32)
        sf = ScalarField("test", values)
        rgba = sf.to_rgba()
        assert rgba.shape == (1000, 4)
        assert rgba.dtype == np.float32

    def test_scalar_field_manager(self):
        from core.cc_scalar_field import ScalarField, ScalarFieldManager
        mgr = ScalarFieldManager()
        mgr.add(ScalarField("a", np.random.rand(100).astype(np.float32)))
        mgr.add(ScalarField("b", np.random.rand(100).astype(np.float32)))
        assert len(mgr.list_names()) == 2
        assert mgr.active_field() is not None
        mgr.remove("a")
        assert "a" not in mgr.list_names()


class TestWorkflow:
    """测试后处理管线模块。"""

    def test_default_pipeline(self):
        from core.cc_workflow import PointCloudData, create_default_pipeline
        pts = _make_sphere_cloud(2000)
        data = PointCloudData(points=pts)
        pipeline = create_default_pipeline()
        result = pipeline.run(data)
        assert result.n_points > 0
        assert result.n_points <= data.n_points  # 下采样会减少

    def test_plane_segmentation(self):
        from core.cc_workflow import PointCloudData, create_segmentation_pipeline
        # 创建平面点云
        x = np.random.uniform(-1, 1, 1000)
        y = np.random.uniform(-1, 1, 1000)
        z = np.zeros_like(x)
        pts = np.stack([x, y, z], axis=1).astype(np.float32)
        data = PointCloudData(points=pts)
        pipeline = create_segmentation_pipeline()
        result = pipeline.run(data)
        assert result.labels is not None
        assert "plane_id" in result.scalar_fields

    def test_undo(self):
        from core.cc_workflow import PointCloudData, Pipeline
        from core.cc_workflow import VoxelDownsampleNode
        pts = _make_sphere_cloud(5000)
        data = PointCloudData(points=pts)
        p = Pipeline()
        p.add(VoxelDownsampleNode(voxel_size=0.2))
        result = p.run(data)
        assert result.n_points < pts.shape[0]
        undone = p.undo()
        assert undone is not None
        assert undone.n_points == pts.shape[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
