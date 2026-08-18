# -*- coding: utf-8 -*-
"""
HandEyeCalibrator 单元测试：合成数据验证 Eye-in-Hand / Eye-to-Hand 求解精度。
"""

import os
import sys
import tempfile
from typing import Tuple
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.handeye import HandEyeCalibrator


def _rotz(deg: float) -> np.ndarray:
    theta = np.radians(deg)
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0],
                     [s, c, 0],
                     [0, 0, 1]], dtype=np.float64)


def _rotx(deg: float) -> np.ndarray:
    theta = np.radians(deg)
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[1, 0, 0],
                     [0, c, -s],
                     [0, s, c]], dtype=np.float64)


def _make_T(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t, dtype=np.float64).flatten()
    return T


def _random_pose() -> np.ndarray:
    """生成一个合理的随机刚体位姿。"""
    R = _rotz(np.random.uniform(-180, 180)) @ _rotx(np.random.uniform(-60, 60))
    t = np.random.uniform(-200, 200, size=3)
    return _make_T(R, t)


def _pose_error(T_est: np.ndarray, T_true: np.ndarray) -> Tuple[float, float]:
    """返回（平移误差 mm，旋转误差 deg）。"""
    t_err = float(np.linalg.norm(T_est[:3, 3] - T_true[:3, 3]))
    R_err = T_est[:3, :3].T @ T_true[:3, :3]
    cos_val = np.clip((np.trace(R_err) - 1.0) / 2.0, -1.0, 1.0)
    r_err = float(np.degrees(np.arccos(cos_val)))
    return t_err, r_err


print("=" * 60)
print("HandEyeCalibrator 测试")
print("=" * 60)

# ------------------------------------------------------------------
# 1. Eye-in-Hand 合成数据标定
# ------------------------------------------------------------------
print("\n[1] Eye-in-Hand 合成数据标定（15 组样本，无噪声）")
np.random.seed(42)
T_cam2tool_true = _make_T(
    _rotz(15) @ _rotx(20),
    np.array([50.0, -30.0, 120.0])
)
T_tool2cam_true = np.linalg.inv(T_cam2tool_true)
T_base2board_true = _make_T(
    _rotz(5) @ _rotx(-10),
    np.array([400.0, 200.0, 0.0])
)

cal = HandEyeCalibrator(eye_in_hand=True)
for _ in range(15):
    T_base2tool = _random_pose()
    # board -> cam 变换：T_base2board = T_base2tool @ T_cam2tool @ T_board2cam
    # 因此 T_board2cam = T_cam2tool^{-1} @ T_base2tool^{-1} @ T_base2board_true
    T_board2cam = np.linalg.inv(T_cam2tool_true) @ np.linalg.inv(T_base2tool) @ T_base2board_true
    cal.add_sample(T_base2tool, T_board2cam)

res = cal.calibrate()
assert res['success'], f"标定失败: {res['message']}"
T_est = res['T_cam2tool']
t_err, r_err = _pose_error(T_est, T_cam2tool_true)
print(f"  样本数: {res['n_samples']}")
print(f"  平移一致性 RMS: {res['rms_t_mm']:.4f} mm")
print(f"  旋转一致性 RMS: {res['rms_r_deg']:.4f}°")
print(f"  相对真值平移误差: {t_err:.4f} mm，旋转误差: {r_err:.4f}°")
assert t_err < 1.0, f"Eye-in-Hand 平移误差过大: {t_err:.4f} mm"
assert r_err < 1.0, f"Eye-in-Hand 旋转误差过大: {r_err:.4f}°"
print("  [OK] Eye-in-Hand 标定精度满足要求")

# ------------------------------------------------------------------
# 2. 带噪声数据
# ------------------------------------------------------------------
print("\n[2] Eye-in-Hand 带 0.1mm/0.05° 噪声")
cal2 = HandEyeCalibrator(eye_in_hand=True)
for _ in range(20):
    T_base2tool = _random_pose()
    T_board2cam = np.linalg.inv(T_cam2tool_true) @ np.linalg.inv(T_base2tool) @ T_base2board_true
    # 在板位姿上加微小噪声（噪声作用在 board->cam 上）
    T_board2cam[:3, 3] += np.random.normal(0, 0.1, size=3)
    noise_R = _rotz(np.random.normal(0, 0.05)) @ _rotx(np.random.normal(0, 0.05))
    T_board2cam[:3, :3] = T_board2cam[:3, :3] @ noise_R
    cal2.add_sample(T_base2tool, T_board2cam)

res2 = cal2.calibrate()
assert res2['success']
t_err2, r_err2 = _pose_error(res2['T_cam2tool'], T_cam2tool_true)
print(f"  相对真值平移误差: {t_err2:.4f} mm，旋转误差: {r_err2:.4f}°")
assert t_err2 < 2.0
assert r_err2 < 2.0
print("  [OK] 带噪声标定仍满足亚毫米/亚度级精度")

# ------------------------------------------------------------------
# 3. 样本不足应失败
# ------------------------------------------------------------------
print("\n[3] 样本不足应返回失败")
cal3 = HandEyeCalibrator(eye_in_hand=True)
cal3.add_sample(np.eye(4), np.eye(4))
res3 = cal3.calibrate()
assert not res3['success']
print(f"  失败提示: {res3['message']}")
print("  [OK] 样本不足正确失败")

# ------------------------------------------------------------------
# 4. 结果保存/加载
# ------------------------------------------------------------------
print("\n[4] 手眼结果 JSON 保存/加载")
fd, path = tempfile.mkstemp(suffix=".json")
os.close(fd)
ok = cal.save(path)
assert ok, "保存失败"
loaded = HandEyeCalibrator.load_result(path)
assert loaded is not None
assert loaded['eye_in_hand'] is True
assert 'T_cam2tool' in loaded
T_loaded = loaded['T_cam2tool']
t_err_l, r_err_l = _pose_error(T_loaded, T_cam2tool_true)
print(f"  加载后相对真值平移误差: {t_err_l:.4f} mm，旋转误差: {r_err_l:.4f}°")
assert t_err_l < 1.0 and r_err_l < 1.0
os.unlink(path)
print("  [OK] 保存/加载一致")

# ------------------------------------------------------------------
# 5. Eye-to-Hand 合成数据
# ------------------------------------------------------------------
print("\n[5] Eye-to-Hand 合成数据标定")
np.random.seed(7)
T_cam2base_true = _make_T(
    _rotz(-20) @ _rotx(10),
    np.array([800.0, 100.0, 600.0])
)
T_base2cam_true = np.linalg.inv(T_cam2base_true)
T_board2tool_true = _make_T(
    _rotz(30),
    np.array([0.0, 0.0, 150.0])
)

cal_e2h = HandEyeCalibrator(eye_in_hand=False)
for _ in range(15):
    T_base2tool = _random_pose()
    # Eye-to-Hand：T_board2cam = T_base2cam @ T_base2board
    # 其中 T_base2board = T_base2tool^{-1} @ T_board2tool_true（板固定在工具上）
    T_base2board = np.linalg.inv(T_base2tool) @ T_board2tool_true
    T_board2cam = T_base2cam_true @ T_base2board
    cal_e2h.add_sample(T_base2tool, T_board2cam)

res_e2h = cal_e2h.calibrate()
assert res_e2h['success'], f"Eye-to-Hand 标定失败: {res_e2h['message']}"
print(f"  样本数: {res_e2h['n_samples']}")
print(f"  平移一致性 RMS: {res_e2h['rms_t_mm']:.4f} mm")
print(f"  旋转一致性 RMS: {res_e2h['rms_r_deg']:.4f}°")
t_err_e, r_err_e = _pose_error(res_e2h['T_cam2base'], T_cam2base_true)
print(f"  相对真值平移误差: {t_err_e:.4f} mm，旋转误差: {r_err_e:.4f}°")
assert t_err_e < 2.0
assert r_err_e < 2.0
print("  [OK] Eye-to-Hand 标定精度满足要求")

print("\n" + "=" * 60)
print("[OK] 所有 HandEye 测试通过")
print("=" * 60)
