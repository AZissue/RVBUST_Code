# -*- coding: utf-8 -*-
"""
退化门禁与快检（validation）—— A3 / A9 / R2 / R3。

A3 唯一门禁：TipTouchValidator（戳点绝对位置度量）。
  背景（方案 v2 §1 三条硬门禁 / K8）：`rms_t_mm/rms_r_deg` 是"内符合"指标，
  单轴退化标定数据下恒为 0（@qa/@feas 独立复现：success=True、rms_t=0.000 mm，
  真值平移却错 110~121 mm），不能当可用性判据。矩阵加载后状态一律 UNVERIFIED，
  只有戳点门禁通过才允许导出（HandEyeResult.validated 置 True）。
  两帧重合度**不是**门禁（@feas 数学恒等：平移误差 δ ∥ 两位姿旋转轴时重合度
  误差恒为 0；@qa 实测同轴两位姿 median 0.263 mm 在 1.0 mm 阈值下判 PASS）——
  故 TwoFrameOverlapChecker 只出 warning/参考报告。

门禁口径（方案 §4.2，已钉死）：
  - err_i = 第 i 姿态下针尖在基座系位置与多姿态均值的距离（毫米）。
  - 特征点 = 相机系针尖 ROI 质心/球心，**每姿态单点**；"姿态内多点取 max"
    不允许（@feas：不钉死则门限不可复现）——add_sample 收到多点直接拒绝。
  - 硬门禁：n ≥ 3 且 err_mean ≤ 0.7 mm（@qa/@feas P99 口径一致，R3）。
  - err_max 仅诊断：> 2.0 mm 出 warning，不进硬门禁（两方 max P99 测值
    1.055 vs 1.25~1.41 mm 分歧，对姿态数与离群点敏感，R3）。
  - 可测性（姿态离面）：验证姿态集须含 ≥1 个与所有其他相对旋转轴夹角
    > 20° 的旋转（可程序判定）。姿态全共轴或纯平移时平移误差沿轴不可辨
    （歧义螺旋轴），门禁无判别力 → fail-closed 判 FAIL，不许放行。
  - A9 判别下限 ≈ 1.0 mm：1.0 mm 平移偏差检出 100%，0.5 mm 检出 0~30%，
    0.2 mm 不可判；旋转 0.5°→1.24 mm、1.0°→2.38 mm。禁止当亚毫米保证。

内部统一毫米（§4.1）。纯 numpy + scipy 实现，不依赖 src/ 与 open3d。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

try:
    from .unit_guard import check_rigid_4x4
    from .transform_chain import compute_cam2base
except ImportError:  # 测试以顶层模块方式引入时
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from unit_guard import check_rigid_4x4
    from transform_chain import compute_cam2base

# 硬门禁阈值（方案 §4.2 / R3，两方 P99 口径一致；勿与诊断阈值混用）
TIP_MEAN_GATE_MM = 0.7        # err_mean 硬门禁
TIP_MAX_WARN_MM = 2.0         # err_max 仅诊断 warning
MIN_SAMPLES = 3               # 硬门禁最少姿态数

# 姿态离面判据（可测性要求，方案 §4.2）
SPREAD_AXIS_ANGLE_DEG = 20.0      # 须存在与所有其他相对旋转轴夹角 > 此值的轴
_MIN_REL_ROTATION_DEG = 1.0       # 相对旋转小于此角视为"无旋转信息"，不计轴


class ValidationError(ValueError):
    """验证输入非法（位姿/针尖点）。"""


def _single_tip_point(p_tip_in_cam_mm) -> np.ndarray:
    """把针尖点规整成 3 向量；多点输入拒绝（姿态内多点取 max 不可复现，§4.2）。"""
    arr = np.asarray(p_tip_in_cam_mm, dtype=np.float64)
    if arr.shape == (3,):
        pt = arr
    elif arr.shape == (1, 3):
        pt = arr[0]
    elif arr.ndim == 2 and arr.shape[1] == 3 and arr.shape[0] > 1:
        raise ValidationError(
            f"每姿态只接受**单个**特征点（针尖 ROI 质心/球心），收到 {arr.shape[0]} 点；"
            f"\"姿态内多点取 max\"会使 err_max 门限不可复现（方案 §4.2），"
            f"请先自行聚合成每姿态一个点")
    else:
        raise ValidationError(
            f"针尖点必须是 3 分量（相机系，毫米），实际 shape={arr.shape}")
    if not np.all(np.isfinite(pt)):
        raise ValidationError("针尖点含 NaN/Inf 非有限值：拒绝")
    return pt


def _relative_rotation_axes(poses: Sequence[np.ndarray]) -> List[np.ndarray]:
    """所有姿态两两相对旋转（R_iᵀ R_j）的转轴单位向量（符号归一）。

    相对旋转角 < _MIN_REL_ROTATION_DEG 的对不计（无旋转信息）。
    返回的轴已做符号归一（最大绝对值分量取正），便于夹角比较。
    """
    axes: List[np.ndarray] = []
    n = len(poses)
    for i in range(n):
        for j in range(i + 1, n):
            R_rel = poses[i][:3, :3].T @ poses[j][:3, :3]
            cos_val = float(np.clip((np.trace(R_rel) - 1.0) / 2.0, -1.0, 1.0))
            angle = float(np.degrees(np.arccos(cos_val)))
            if angle < _MIN_REL_ROTATION_DEG:
                continue
            sin_val = np.sqrt(max(1.0 - cos_val * cos_val, 0.0))
            if sin_val < 1e-12:          # 180° 附近轴退化，跳过该对
                continue
            ax = np.array([R_rel[2, 1] - R_rel[1, 2],
                           R_rel[0, 2] - R_rel[2, 0],
                           R_rel[1, 0] - R_rel[0, 1]], dtype=np.float64)
            ax /= 2.0 * sin_val
            # 轴符号无物理意义（±a 同一转轴），归一后比较夹角
            k = int(np.argmax(np.abs(ax)))
            if ax[k] < 0:
                ax = -ax
            axes.append(ax)
    return axes


def rotation_spread_ok(poses: Sequence[np.ndarray]) -> tuple[bool, str]:
    """姿态离面可测性检查（方案 §4.2）。

    须存在至少一个相对旋转轴，与**所有其他**相对旋转轴的夹角 > 20°；
    全部共轴 / 纯平移（无相对旋转）→ 无判别力，判不通过。

    Returns:
        (ok, message)。
    """
    axes = _relative_rotation_axes(poses)
    if not axes:
        return False, (f"姿态集无有效相对旋转（相对旋转均 < {_MIN_REL_ROTATION_DEG:g}°）："
                       f"纯平移验证无法辨识沿轴平移误差（歧义螺旋轴），请增加旋转姿态")
    need = np.cos(np.radians(SPREAD_AXIS_ANGLE_DEG))
    for i, a in enumerate(axes):
        others = [b for k, b in enumerate(axes) if k != i]
        if all(float(np.dot(a, b)) < need for b in others):
            return True, (f"姿态离面满足：相对旋转轴 #{i + 1} 与所有其他轴夹角均 > "
                          f"{SPREAD_AXIS_ANGLE_DEG:g}°（共 {len(axes)} 个轴）")
    return False, (f"姿态离面不足：所有相对旋转轴两两夹角均 ≤ {SPREAD_AXIS_ANGLE_DEG:g}°"
                   f"（共 {len(axes)} 个轴，近乎共轴）——沿公共轴方向的平移误差不可辨，"
                   f"请增加离面旋转姿态")


class TipTouchValidator:
    """戳点验证器（A3 唯一门禁）：同一物理针尖点、多姿态，看基座系落点分散程度。

    用法：
        v = TipTouchValidator(eye_in_hand, T_handeye_mm)
        for T_base2tool, p_tip_cam in samples:   # 每姿态单点
            v.add_sample(T_base2tool, p_tip_cam)
        report = v.check()                       # verdict == "PASS" 才允许导出

    add_sample 收到的是**已通过 PoseSource 守卫的绝对位姿**（毫米）；本类只做
    刚性复核（防第三方绕过 PoseSource 直接喂坏矩阵，K8"core 不守、原型守"的
    原型侧收口），不重复范数窗口。
    """

    def __init__(self, eye_in_hand: bool, T_handeye_mm: np.ndarray,
                 mean_gate_mm: float = TIP_MEAN_GATE_MM,
                 max_warn_mm: float = TIP_MAX_WARN_MM):
        T = np.asarray(T_handeye_mm, dtype=np.float64)
        ok, msg = check_rigid_4x4(T)
        if not ok:
            raise ValidationError(f"手眼矩阵非法: {msg}")
        self.eye_in_hand = bool(eye_in_hand)
        self.T_handeye_mm = T
        self.mean_gate_mm = float(mean_gate_mm)
        self.max_warn_mm = float(max_warn_mm)
        self._poses: List[np.ndarray] = []
        self._tips_base: List[np.ndarray] = []

    def __len__(self) -> int:
        return len(self._poses)

    def add_sample(self, T_base2tool_mm: np.ndarray,
                   p_tip_in_cam_mm) -> tuple[bool, str]:
        """记录一个姿态下的针尖观测（同一物理点）。

        Args:
            T_base2tool_mm: 该姿态的基座→法兰位姿（绝对位姿，毫米，已过 PoseSource 守卫）。
            p_tip_in_cam_mm: 相机系针尖特征点（**单点**，毫米；ROI 质心/球心）。

        Returns:
            (ok, message)。失败（位姿刚性不过/针尖多点/NaN）时不入样本。
        """
        T = np.asarray(T_base2tool_mm, dtype=np.float64)
        ok, msg = check_rigid_4x4(T)
        if not ok:
            return False, f"位姿非法: {msg}"
        try:
            pt_cam = _single_tip_point(p_tip_in_cam_mm)
        except ValidationError as e:
            return False, str(e)
        T_cam2base = compute_cam2base(self.eye_in_hand, self.T_handeye_mm, T)
        hom = np.append(pt_cam, 1.0)
        pt_base = (T_cam2base @ hom)[:3]
        self._poses.append(T)
        self._tips_base.append(pt_base)
        return True, (f"戳点样本 #{len(self._poses)}：针尖基座系落点 "
                      f"{np.round(pt_base, 3).tolist()} mm")

    def check(self) -> dict:
        """跑门禁，返回报告字典（JSON 可序列化，可进会话 error_report.json）。

        verdict 取值："PASS" | "FAIL"（fail-closed：样本不足 / 离面不足 /
        err_mean 超门限，任一不满足即 FAIL）。
        """
        n = len(self._poses)
        warnings: List[str] = []
        reasons: List[str] = []

        spread_ok, spread_msg = (False, "无样本") if n == 0 else \
            rotation_spread_ok(self._poses)

        if n < MIN_SAMPLES:
            reasons.append(f"样本不足：{n} < {MIN_SAMPLES}（硬门禁最少姿态数）")
        if not spread_ok:
            reasons.append(f"姿态离面不满足：{spread_msg}")

        if n > 0:
            pts = np.asarray(self._tips_base, dtype=np.float64)
            mean = pts.mean(axis=0)
            errs = np.linalg.norm(pts - mean, axis=1)
            err_mean = float(errs.mean())
            err_max = float(errs.max())
            if err_mean > self.mean_gate_mm:
                reasons.append(
                    f"err_mean={err_mean:.3f} mm 超硬门禁 {self.mean_gate_mm:.1f} mm"
                    f"（戳点落点分散 → 手眼矩阵不可用）")
            if err_max > self.max_warn_mm:
                warnings.append(
                    f"err_max={err_max:.3f} mm > {self.max_warn_mm:.1f} mm"
                    f"（仅诊断不进硬门禁，R3：对姿态数与离群点敏感）")
        else:
            err_mean = float("nan")
            err_max = float("nan")

        verdict = "PASS" if (n >= MIN_SAMPLES and spread_ok
                             and not reasons) else "FAIL"
        if verdict == "PASS":
            spread_msg = f"姿态离面满足（{spread_msg}）"
        return {
            "validator": "TipTouchValidator",
            "n": n,
            "err_mean_mm": err_mean,
            "err_max_mm": err_max,
            "mean_gate_mm": self.mean_gate_mm,
            "max_warn_mm": self.max_warn_mm,
            "spread_ok": bool(spread_ok),
            "spread_message": spread_msg,
            "warnings": warnings,
            "reasons": reasons,
            "verdict": verdict,
        }


# ----------------------------------------------------------------------
# 两帧重合度快检 —— 降级为参考报告，**不是**门禁（R2，方案 v2 §1 硬条款）
# ----------------------------------------------------------------------
AXIAL_BLIND_ZONE_HINT = (
    "轴向盲区提示：当平移误差平行于两位姿旋转轴时，重合度误差恒为 0（数学恒等），"
    "本项不能判可用——可用性以戳点门禁（TipTouchValidator）为准。")


class TwoFrameOverlapChecker:
    """两帧重合度快检（warning 级）。使用前提：两位姿旋转差 ≥ 30°。"""

    PRECONDITION_DEG = 30.0     # 方案 §4.2：低于此旋转差，重合度报告无意义

    @staticmethod
    def _as_points(pcd_mm) -> np.ndarray:
        """N×3 数组或带 .points 的点云对象 → (N,3) 数组。"""
        pts = getattr(pcd_mm, "points", pcd_mm)
        arr = np.asarray(pts, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] != 3 or len(arr) == 0:
            raise ValidationError(
                f"点云必须是 N×3（毫米，非空），实际 shape={arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise ValidationError("点云含 NaN/Inf 非有限值：拒绝")
        return arr

    @classmethod
    def check(cls, pcd_a_mm, pcd_b_mm,
              T_base2tool_a: Optional[np.ndarray] = None,
              T_base2tool_b: Optional[np.ndarray] = None) -> dict:
        """B→A 最近邻距离统计（median / p95）。

        Args:
            pcd_a_mm / pcd_b_mm: N×3 数组或 open3d 点云（毫米）。
            T_base2tool_a / T_base2tool_b: 可选；给了就检查 ≥30° 旋转前提，
                不满足时 verdict="PRECONDITION_FAILED"（报告数值仅供参考）。

        Returns:
            {median_mm, p95_mm, n_a, n_b, rotation_deg, verdict, hint}
            verdict ∈ "OK" | "PRECONDITION_FAILED"。本方法**不设任何通过
            阈值**——重合度不能判可用（R2），只作参考。
        """
        a = cls._as_points(pcd_a_mm)
        b = cls._as_points(pcd_b_mm)
        from scipy.spatial import cKDTree
        dist, _ = cKDTree(a).query(b, k=1)
        median = float(np.median(dist))
        p95 = float(np.percentile(dist, 95))

        rotation_deg: Optional[float] = None
        verdict = "OK"
        if T_base2tool_a is not None and T_base2tool_b is not None:
            Ra = np.asarray(T_base2tool_a, dtype=np.float64)[:3, :3]
            Rb = np.asarray(T_base2tool_b, dtype=np.float64)[:3, :3]
            cos_val = float(np.clip((np.trace(Ra.T @ Rb) - 1.0) / 2.0, -1.0, 1.0))
            rotation_deg = float(np.degrees(np.arccos(cos_val)))
            if rotation_deg < cls.PRECONDITION_DEG:
                verdict = "PRECONDITION_FAILED"
        return {
            "checker": "TwoFrameOverlapChecker",
            "median_mm": median,
            "p95_mm": p95,
            "n_a": len(a),
            "n_b": len(b),
            "rotation_deg": rotation_deg,
            "verdict": verdict,
            "hint": AXIAL_BLIND_ZONE_HINT,
        }
