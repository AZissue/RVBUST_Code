# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
转台标定器合成数据测试（无相机、无 GUI）。

覆盖 `src/core/turntable_calibrator.py`：角度/轴/中心估计精度、
序列生成不得原地修改（逐点位移判据）、完整 360° 拼接完整性。

由 `src/core/turntable_calibrator.py` 内嵌 demo `test_synthetic()` 抽离
（第七轮审查 D8），并补断言与序列独立性检查。

运行：
    "D:\\Program Files\\Anaconda\\envs\\rvc\\python.exe" test_turntable.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from core.turntable_calibrator import (  # noqa: E402
    SyntheticTurntableData,
    TurntableCalibrator,
)


def test_rotation_accuracy():
    """[1] 多角度下旋转参数估计精度与 360° 步数估算。"""
    print("\n[1] 旋转参数估计精度")
    for angle_deg in [15, 30, 45, 60, 90]:
        synth = SyntheticTurntableData(angle_deg=angle_deg, noise_mm=0.1)
        _, markers = synth.generate_sequence(n_steps=1)
        calib = TurntableCalibrator()
        ok, msg, info = calib.calibrate_from_markers(markers[0], markers[1])
        assert ok, msg

        est_axis = np.array(info["axis"])
        est_center = np.array(info["center"])
        angle_err = abs(info["angle_deg"] - angle_deg)
        axis_err = np.linalg.norm(est_axis - synth.axis)
        center_offset = est_center - synth.center
        center_perp_err = np.linalg.norm(
            center_offset - np.dot(center_offset, synth.axis) * synth.axis)
        expected_count = int(round(360 / angle_deg))

        print(f"  真实 {angle_deg:3.0f}° -> 估计 {info['angle_deg']:6.2f}° "
              f"(误差 {angle_err:5.2f}°), 轴误差 {axis_err:.4f}, "
              f"中心垂距误差 {center_perp_err:2.2f} mm, "
              f"360°步数 {info['step_count']}/{expected_count}")
        assert angle_err < 0.5, f"角度估计误差过大: {angle_err}"
        assert center_perp_err < 2.0, f"中心垂距误差过大: {center_perp_err}"
        assert info["step_count"] == expected_count, \
            f"步数估算错误: {info['step_count']} != {expected_count}"
    print("  [PASS]")


def test_sequence_not_inplace():
    """[2] 序列每帧独立对象，且逐点位移显著（防"原地 transform"回归）。

    判据必须用逐点平均位移而非质心位移：合成场景整体平移到转轴附近，
    质心到轴垂距仅 ~0.16mm，绕轴旋转时质心几乎不动，质心判据会误报。
    """
    print("\n[2] 序列独立性（非原地修改）")
    synth = SyntheticTurntableData(angle_deg=30.0, noise_mm=0.3)
    pcds, _ = synth.generate_sequence(n_steps=11)
    assert len(pcds) == 12, f"帧数错误: {len(pcds)}"
    p0 = np.asarray(pcds[0].points)
    for i in range(1, len(pcds)):
        assert pcds[i] is not pcds[0], f"第 {i} 帧与第 0 帧是同一对象（原地修改 bug）"
        pi = np.asarray(pcds[i].points)
        mean_disp = np.linalg.norm(pi - p0, axis=1).mean()
        assert mean_disp > 1.0, f"第 {i} 帧逐点平均位移过小: {mean_disp:.4f} mm"
    print(f"  第 11 帧相对第 0 帧逐点平均位移 "
          f"{np.linalg.norm(np.asarray(pcds[11].points) - p0, axis=1).mean():.2f} mm")
    print("  [PASS]")


def test_stitch_360():
    """[3] 12 帧（0~330°）完整拼接，结果 AABB 与场景同量级。"""
    print("\n[3] 完整 360° 拼接")
    synth = SyntheticTurntableData(angle_deg=30.0, noise_mm=0.3)
    pcds, markers = synth.generate_sequence(n_steps=11)

    calib = TurntableCalibrator()
    ok, msg, info = calib.calibrate_from_markers(markers[0], markers[1])
    assert ok, msg
    print(f"  {msg}")
    print(f"  真实角度 30.00°, 估计角度 {info['angle_deg']:.2f}°, "
          f"真实轴 {synth.axis.round(4)}, 估计轴 {np.array(info['axis']).round(4)}")
    print(f"  真实中心 {synth.center.round(2)}, 估计中心 {np.array(info['center']).round(2)}")

    merged, msg = calib.stitch_pointclouds(pcds, downsample_voxel=2.0)
    assert merged is not None, msg
    print(f"  {msg}")

    pts = np.asarray(merged.points)
    extent = pts.max(axis=0) - pts.min(axis=0)
    print(f"  合并 AABB 范围: {extent.round(1)}")
    assert extent[0] > 100 and extent[1] > 100, "合并结果 XY 范围异常，可能拼接失败"
    print("  [PASS]")


def test_icp_refine():
    """[4] ICP 精修：标定带小误差（实测 3 对标记场景为数度/数十 mm）时，
    精修后的帧间对齐显著优于纯标定变换。"""
    from scipy.spatial import cKDTree
    print("\n[4] ICP 精修校正标定残差")
    synth = SyntheticTurntableData(angle_deg=90.0, noise_mm=0.2)
    pcds, _ = synth.generate_sequence(n_steps=3)  # 4 帧：0/90/180/270°

    # 故意给有小误差的标定：角度偏 +0.8°，中心偏 ~1.5mm
    calib = TurntableCalibrator()
    wrong_center = synth.center + np.array([0.5, 1.0, 1.0])
    calib.set_calibration(synth.axis, wrong_center, angle_deg=90.8, step_count=3)

    merged_plain, msg = calib.stitch_pointclouds(pcds, icp_refine=False)
    assert merged_plain is not None, msg
    merged_refined, msg_r = calib.stitch_pointclouds(pcds, icp_refine=True)
    assert merged_refined is not None, msg_r
    print(f"  {msg_r}")

    n = len(pcds[0].points)

    def frame_nn(merged, i, sample=40000):
        """第 i 帧（变换后）到第 0 帧的最近邻平均距离（mm）。"""
        pts = np.asarray(merged.points)
        a = pts[i * n:(i + 1) * n]
        b = pts[0:n]
        rng = np.random.default_rng(0)
        a = a[rng.choice(len(a), min(sample, len(a)), replace=False)]
        b = b[rng.choice(len(b), min(sample, len(b)), replace=False)]
        return float(cKDTree(b).query(a, k=1)[0].mean())

    plain_d2, plain_d3 = frame_nn(merged_plain, 2), frame_nn(merged_plain, 3)
    ref_d2, ref_d3 = frame_nn(merged_refined, 2), frame_nn(merged_refined, 3)
    print(f"  帧2→帧0 NN: 纯标定 {plain_d2:.3f}mm / ICP 精修 {ref_d2:.3f}mm")
    print(f"  帧3→帧0 NN: 纯标定 {plain_d3:.3f}mm / ICP 精修 {ref_d3:.3f}mm")
    assert ref_d2 < plain_d2 * 0.5, f"帧2 精修无改善: {ref_d2:.3f} vs {plain_d2:.3f}"
    assert ref_d2 < 0.6, f"帧2 精修后 NN 仍过大: {ref_d2:.3f}mm"
    assert ref_d3 < plain_d3 * 0.5, f"帧3 精修无改善: {ref_d3:.3f} vs {plain_d3:.3f}"
    print("  [PASS]")


def main():
    print("=" * 60)
    print("转台标定器合成数据测试（src/core/turntable_calibrator.py）")
    print("=" * 60)
    test_rotation_accuracy()
    test_sequence_not_inplace()
    test_stitch_360()
    test_icp_refine()
    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
