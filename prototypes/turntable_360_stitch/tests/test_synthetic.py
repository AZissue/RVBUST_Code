# -*- coding: utf-8 -*-
"""
转台拼接算法单元测试：纯合成数据，无 UI，验证标定精度与拼接完整性。

运行方式：
    cd D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\turntable_360_stitch\tests
    "D:\Program Files\Anaconda\envs\rvc\python.exe" test_synthetic.py
"""

import sys
import os

# 引入核心模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import numpy as np
import open3d as o3d

from turntable_calibrator import (
    SyntheticTurntableData,
    TurntableCalibrator,
    kabsch_rigid_transform,
)


def test_rotation_estimation():
    """测试从两帧标记点估计的旋转参数是否接近真值。"""
    print("\n[TEST] 旋转参数估计精度")
    for angle_deg in [15, 30, 45, 60, 90]:
        synth = SyntheticTurntableData(angle_deg=angle_deg, noise_mm=0.1)
        _, markers = synth.generate_sequence(n_steps=1)
        calib = TurntableCalibrator()
        ok, msg, info = calib.calibrate_from_markers(markers[0], markers[1])
        assert ok, msg

        est_axis = np.array(info["axis"])
        est_center = np.array(info["center"])
        est_angle = info["angle_deg"]
        est_count = info["step_count"]

        axis_err = np.linalg.norm(est_axis - synth.axis)
        # 旋转中心在轴向上有任意性，只检查"到真实轴线的垂直距离"
        center_offset = est_center - synth.center
        center_perp_err = np.linalg.norm(
            center_offset - np.dot(center_offset, synth.axis) * synth.axis)
        angle_err = abs(est_angle - angle_deg)
        expected_count = int(round(360 / angle_deg))

        print(
            f"  真实 {angle_deg:3.0f}° -> 估计 {est_angle:6.2f}° "
            f"(误差 {angle_err:5.2f}°), 轴误差 {axis_err:.4f}, "
            f"中心垂距误差 {center_perp_err:2.2f} mm, 360°步数 {est_count}/{expected_count}"
        )
        assert angle_err < 0.5, f"角度估计误差过大: {angle_err}"
        assert center_perp_err < 2.0, f"中心垂距误差过大: {center_perp_err}"
        assert est_count == expected_count, f"步数估算错误: {est_count} != {expected_count}"
    print("  [PASS]")


def test_full_360_stitch():
    """测试完整 360° 多帧拼接。"""
    print("\n[TEST] 完整 360° 拼接")
    angle_deg = 30.0
    synth = SyntheticTurntableData(angle_deg=angle_deg, noise_mm=0.3)
    pcds, markers = synth.generate_sequence(n_steps=11)  # 0~330°

    calib = TurntableCalibrator()
    ok, msg, info = calib.calibrate_from_markers(markers[0], markers[1])
    assert ok, msg
    print(f"  {msg}")

    merged, msg = calib.stitch_pointclouds(pcds, downsample_voxel=1.0)
    assert merged is not None, msg
    print(f"  {msg}")

    # 拼接后点云应大致覆盖原场景，且 AABB 与原始场景同量级
    pts = np.asarray(merged.points)
    extent = pts.max(axis=0) - pts.min(axis=0)
    print(f"  合并 AABB 范围: {extent.round(1)}")
    assert extent[0] > 100 and extent[1] > 100, "合并结果 XY 范围异常，可能拼接失败"
    print("  [PASS]")


def test_kabsch_noise_robustness():
    """测试 Kabsch 对噪声的鲁棒性。"""
    print("\n[TEST] Kabsch 噪声鲁棒性")
    synth = SyntheticTurntableData(angle_deg=30.0, noise_mm=2.0)
    _, markers = synth.generate_sequence(n_steps=1)
    calib = TurntableCalibrator()
    ok, msg, info = calib.calibrate_from_markers(markers[0], markers[1])
    assert ok, msg
    angle_err = abs(info["angle_deg"] - 30.0)
    est_center = np.array(info["center"])
    center_offset = est_center - synth.center
    center_perp_err = np.linalg.norm(
        center_offset - np.dot(center_offset, synth.axis) * synth.axis)
    print(f"  2mm 噪声下角度误差: {angle_err:.2f}°, 中心垂距误差: {center_perp_err:.2f} mm")
    assert angle_err < 2.0, f"噪声下角度估计失败: {angle_err}"
    assert center_perp_err < 5.0, f"噪声下中心估计失败: {center_perp_err}"
    print("  [PASS]")


def main():
    print("=" * 60)
    print("转台拼接合成数据测试")
    print("=" * 60)
    test_rotation_estimation()
    test_full_360_stitch()
    test_kabsch_noise_robustness()
    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
