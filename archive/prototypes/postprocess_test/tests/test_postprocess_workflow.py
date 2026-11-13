# -*- coding: utf-8 -*-
"""
PostprocessWorkflow 单元测试（无 UI、无相机、无 SDK）。

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/postprocess_test/tests/test_postprocess_workflow.py
"""

import os
import sys
import tempfile

import numpy as np
import open3d as o3d

# 加入项目 src 和本原型 core 路径
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TESTS_DIR)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(os.path.dirname(_TESTS_DIR), "core"))

from postprocess_workflow import PostprocessWorkflow


def make_sphere_pcd(n=1000, radius=10.0, center=None):
    """生成测试用球形点云。"""
    rng = np.random.default_rng(42)
    pts = rng.normal(size=(n, 3))
    pts = pts / np.linalg.norm(pts, axis=1, keepdims=True) * radius
    if center is not None:
        pts = pts + np.asarray(center)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    return pcd


def make_plane_pcd(n=1000, size=20.0, z=0.0):
    """生成测试用平面点云。"""
    rng = np.random.default_rng(42)
    x = rng.uniform(-size / 2, size / 2, n)
    y = rng.uniform(-size / 2, size / 2, n)
    z = np.full(n, z) + rng.normal(0, 0.1, n)
    pts = np.column_stack([x, y, z])
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    return pcd


def test_add_and_remove_cloud():
    print("[TEST] 添加/删除点云")
    wf = PostprocessWorkflow()
    pcd = make_sphere_pcd(500)
    nid = wf.add_cloud("test_sphere", pcd)
    assert nid in [n.node_id for n in wf.list_nodes()]
    assert wf.get_state() == "loaded"
    assert wf.selected_id() == nid
    assert wf.get_cloud(nid) is not None

    ok = wf.remove_cloud(nid)
    assert ok
    assert wf.get_cloud(nid) is None
    assert wf.get_state() == "idle"
    print("  [PASS]")


def test_process_downsample():
    print("[TEST] 体素下采样")
    wf = PostprocessWorkflow()
    pcd = make_sphere_pcd(5000)
    nid = wf.add_cloud("sphere", pcd)
    original_count = len(pcd.points)

    wf.processor.enable_voxel_downsample = True
    wf.processor.voxel_size = 1.0
    ok, msg, stats = wf.apply_process(nid)
    assert ok, msg
    assert len(wf.get_cloud(nid).points) < original_count
    print(f"  {original_count} -> {len(wf.get_cloud(nid).points)} 点")
    print("  [PASS]")


def test_process_crop_aabb():
    print("[TEST] AABB 中心裁切")
    wf = PostprocessWorkflow()
    # 平面点云：XY 各 ±20，中心区域密度高
    pcd = make_plane_pcd(2000, size=20.0, z=0.0)
    nid = wf.add_cloud("plane", pcd)

    wf.processor.crop_mode = "aabb"
    wf.processor.crop_ratio = 0.5
    ok, msg, stats = wf.apply_process(nid)
    assert ok, msg
    after = len(wf.get_cloud(nid).points)
    assert 0 < after < 2000, f"裁切后点数异常: {after}"
    print(f"  2000 -> {after} 点")
    print("  [PASS]")


def test_undo_redo():
    print("[TEST] 撤销 / 重做")
    wf = PostprocessWorkflow()
    pcd = make_sphere_pcd(1000)
    nid = wf.add_cloud("sphere", pcd)
    original = len(wf.get_cloud(nid).points)

    wf.processor.enable_voxel_downsample = True
    wf.processor.voxel_size = 2.0
    ok, msg, _ = wf.apply_process(nid)
    assert ok
    after_process = len(wf.get_cloud(nid).points)
    assert after_process < original

    ok, msg = wf.undo()
    assert ok
    assert len(wf.get_cloud(nid).points) == original

    ok, msg = wf.redo()
    assert ok
    assert len(wf.get_cloud(nid).points) == after_process
    print("  [PASS]")


def test_icp_register():
    print("[TEST] ICP 点云配准")
    wf = PostprocessWorkflow()
    target = make_sphere_pcd(1000, radius=10.0)
    # 源点云 = 目标点云 + 平移
    source = o3d.geometry.PointCloud(target)
    source.points = o3d.utility.Vector3dVector(
        np.asarray(source.points) + np.array([2.0, 1.0, 0.5]))

    tgt_id = wf.add_cloud("target", target)
    src_id = wf.add_cloud("source", source)

    ok, msg, result = wf.icp_register(src_id, tgt_id)
    assert ok, msg
    assert result is not None
    assert result.fitness > 0.5, f"fitness 过低: {result.fitness}"
    # 配准后源点云质心应接近目标点云质心
    src_center = np.asarray(wf.get_cloud(src_id).points).mean(axis=0)
    tgt_center = np.asarray(wf.get_cloud(tgt_id).points).mean(axis=0)
    dist = np.linalg.norm(src_center - tgt_center)
    assert dist < 2.0, f"配准后质心距离过大: {dist}"
    print(f"  fitness={result.fitness:.4f}, rmse={result.inlier_rmse:.4f}, 质心距离={dist:.3f}")
    print("  [PASS]")


def test_merge_clouds():
    print("[TEST] 点云合并")
    wf = PostprocessWorkflow()
    pcd1 = make_sphere_pcd(500, radius=10.0, center=[0, 0, 0])
    pcd2 = make_sphere_pcd(500, radius=10.0, center=[20, 0, 0])
    id1 = wf.add_cloud("pcd1", pcd1)
    id2 = wf.add_cloud("pcd2", pcd2)

    ok, msg, merged_id = wf.merge_clouds([id1, id2])
    assert ok, msg
    merged = wf.get_cloud(merged_id)
    assert merged is not None
    assert len(merged.points) == 1000
    print("  [PASS]")


def test_export_cloud():
    print("[TEST] 导出点云")
    wf = PostprocessWorkflow()
    pcd = make_sphere_pcd(500)
    nid = wf.add_cloud("sphere", pcd)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_export.ply")
        ok, msg = wf.export_cloud(nid, path)
        assert ok, msg
        assert os.path.isfile(path)
        # 重新加载验证点数
        reloaded = o3d.io.read_point_cloud(path)
        assert len(reloaded.points) == len(pcd.points)
    print("  [PASS]")


def test_auto_tune():
    print("[TEST] 自动参数估计")
    wf = PostprocessWorkflow()
    pcd = make_sphere_pcd(10000, radius=10.0)
    nid = wf.add_cloud("sphere", pcd)

    ok, msg, params = wf.auto_tune(nid, target_points=2000)
    assert ok, msg
    assert params is not None
    assert "voxel_size" in params
    assert "crop_mode" in params
    print(f"  单位={params['unit']}, 体素={params['voxel_size']:.3f}, 裁切={params['crop_mode']}")
    print("  [PASS]")


def main():
    print("=" * 60)
    print("PostprocessWorkflow 单元测试")
    print("=" * 60)
    test_add_and_remove_cloud()
    test_process_downsample()
    test_process_crop_aabb()
    test_undo_redo()
    test_icp_register()
    test_merge_clouds()
    test_export_cloud()
    test_auto_tune()
    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
