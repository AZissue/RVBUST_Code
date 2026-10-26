# -*- coding: utf-8 -*-
"""
单位守卫（unit_guard）—— A2 单位不静默错。

口径（方案 v2 §1 A2 + @qa 两档窗口实测，待 arch 落 v3）：
  - 单位**显式必选**（"mm" / "m"），无 auto、无默认（D4）。
  - 平移范数物理窗口按 eye_in_hand 分档（毫米域）：
      眼在手上 [5, 2000] mm   —— ‖t‖ = 相机→法兰距离（受相机本体 73.5mm + 支架限制）
      眼在手外 [50, 20000] mm —— ‖t‖ = 相机→基座原点安装距离，可达米级（@scribe 实测
                               单窗口会把合法的 2500/4000/8000mm 误拦）
  - 分档设计规则：窗口下界必须 > 上界 / 1000（@qa 实测），否则 ÷1000 误读
    落在窗内漏放、×1000 误读落在窗外，两边都靠不住。
  - 已弃用：范数比值启发式 r_c/‖t_base2tool‖（@feas R1 实测 18 场景只拦 6/18
    且误拦正确矩阵，无判别力）。

内部统一毫米（mm），与 src/core/frame_data.py:219 一致；换算只在
矩阵加载处与机器人位姿录入处两个入口做。
"""

from __future__ import annotations

import numpy as np

UNITS = ("mm", "m")

# 平移范数物理窗口（毫米域），键 = eye_in_hand
TRANSLATION_NORM_WINDOW_MM = {
    True: (5.0, 2000.0),     # 眼在手上
    False: (50.0, 20000.0),  # 眼在手外
}

# 分档设计规则自检：下界 > 上界 / 1000（@qa）
for _lo, _hi in TRANSLATION_NORM_WINDOW_MM.values():
    assert _lo > _hi / 1000.0, f"窗口 [{_lo}, {_hi}] 违反 下界>上界/1000 规则"


class UnitError(ValueError):
    """单位参数非法（非 mm/m）。"""


def normalize_unit(unit: str) -> str:
    """校验并归一单位字符串，非法时抛 UnitError。"""
    if not isinstance(unit, str) or unit.strip().lower() not in UNITS:
        raise UnitError(
            f"单位必须显式选择 'mm' 或 'm'（收到 {unit!r}）；"
            f"矩阵单位由产出者决定且 JSON 无 unit 字段，不允许 auto/默认（D4）")
    return unit.strip().lower()


def to_mm(T: np.ndarray, unit: str) -> np.ndarray:
    """把齐次矩阵的平移列归一到毫米。仅缩放平移列，旋转块不动。

    Args:
        T: 4×4 齐次矩阵（unit 域）。
        unit: "mm" | "m"（显式必选，无 auto）。

    Returns:
        新的 4×4 矩阵（毫米域），不修改入参。
    """
    unit = normalize_unit(unit)
    T = np.asarray(T, dtype=np.float64).copy()
    if unit == "m":
        T[:3, 3] *= 1000.0
    return T


def to_unit(T_mm: np.ndarray, unit: str) -> np.ndarray:
    """毫米域矩阵换算到目标单位（to_mm 的逆，供往返测试与导出）。"""
    unit = normalize_unit(unit)
    T = np.asarray(T_mm, dtype=np.float64).copy()
    if unit == "m":
        T[:3, 3] /= 1000.0
    return T


def translation_norm_mm(T_handeye_mm: np.ndarray) -> float:
    """手眼矩阵平移范数（毫米域）。"""
    return float(np.linalg.norm(np.asarray(T_handeye_mm, dtype=np.float64)[:3, 3]))


def check_translation_norm(T_handeye_mm: np.ndarray,
                           eye_in_hand: bool) -> tuple[bool, str]:
    """A2 平移范数物理窗口检查（毫米域）。

    Returns:
        (ok, message)。ok=False 时 message 给出可读的改法提示。
    """
    norm = translation_norm_mm(T_handeye_mm)
    lo, hi = TRANSLATION_NORM_WINDOW_MM[bool(eye_in_hand)]
    kind = "眼在手上（相机→法兰距离）" if eye_in_hand else "眼在手外（相机→基座原点安装距离）"
    # ⚠️ 必须写成 `not (lo <= n <= hi)`：写成 `n < lo or n > hi` 时 NaN 两次比较
    #    均为 False → 静默放行（@qa 实测 NaN 位姿透传成 [nan 40. 520.] 的机制）
    if not (lo <= norm <= hi):
        if not np.isfinite(norm):
            return False, (f"‖t‖={norm} 非有限值（NaN/Inf 矩阵）：拒绝，"
                           f"请检查标定结果与单位设置")
        if norm < lo:
            return False, (
                f"‖t‖={norm:.3f} mm 低于物理下限 {lo:.0f} mm（{kind}）："
                f"疑似米制矩阵被当毫米读入，请把单位改为 m")
        return False, (
            f"‖t‖={norm:.3f} mm 高于物理上限 {hi:.0f} mm（{kind}）："
            f"疑似毫米被当米读入，请把单位改为 mm")
    return True, f"‖t‖={norm:.3f} mm 在物理窗口 [{lo:.0f}, {hi:.0f}] mm 内（{kind}）"


# ======================================================================
# 共用校验层（批 1.5）—— handeye_result（矩阵侧）与 pose_source（位姿侧）共用，
# 禁止两份实现：转台原型已实证 K4 型副本漂移会漂出 bug（方案 §4.2）
# ======================================================================

ORTH_TOL = 1e-6      # 旋转块正交性容差（A7）
DET_TOL = 1e-6       # det(R)≈+1 容差（A7）
LAST_ROW_TOL = 1e-9  # 末行 [0,0,0,1] 容差（A7）

# 位姿（T_base2tool）平移范数窗口（毫米域），键 = pose_type（v4 §4.2 / R10 / R11）
POSE_NORM_WINDOW_MM = {
    "absolute": (30.0, 20000.0),  # 法兰到基座原点，长臂/龙门可达数米
    "delta": (1.0, 500.0),        # 增量位姿：单步运动量级
}

# 各来源声明的合法极值（毫米）—— 只用于判别力自检；absolute 的 [60, 4500] 属
# @feas R10 假设集，**待现场确认**
POSE_DOMAIN_MM = {
    "absolute": (60.0, 4500.0),
    "delta": (1.0, 500.0),
}

# 判别力自检：lo > v_max/1000 且 hi < 1000·v_min。
# 只写 lo > hi/1000 在窗口放大后会静默失效（[100, 100000] 会放行 60×1000=60000
# 的 ×1000 误读）；窗口=合法域时两种写法等价，故上面矩阵窗口的 lo>hi/1000 仍正确。
for _pt, (_lo, _hi) in POSE_NORM_WINDOW_MM.items():
    _vmin, _vmax = POSE_DOMAIN_MM[_pt]
    assert _lo > _vmax / 1000.0 and _hi < 1000.0 * _vmin, (
        f"位姿窗口 [{_lo}, {_hi}]（{_pt}）失去判别力：要求 lo > v_max/1000 且 "
        f"hi < 1000·v_min，实际 v=[{_vmin}, {_vmax}]")


class PoseError(ValueError):
    """位姿/矩阵参数非法（单位为位姿类型/欧拉顺序/刚性/范数窗口）。"""


def normalize_pose_type(pose_type: str) -> str:
    """校验并归一位姿类型，非法时抛 PoseError。无默认（R11）。"""
    if not isinstance(pose_type, str) or pose_type.strip().lower() \
            not in POSE_NORM_WINDOW_MM:
        raise PoseError(
            f"pose_type 必须显式选择 'absolute' 或 'delta'（收到 {pose_type!r}）；"
            f"两者窗口不同（{[f'{k}: [{v[0]:g}, {v[1]:g}]' for k, v in POSE_NORM_WINDOW_MM.items()]}），"
            f"数值无法推断，不允许默认（R11）")
    return pose_type.strip().lower()


def check_rigid_4x4(T) -> tuple[bool, str]:
    """刚性 4×4 校验：有限性 / 旋转块正交 / det(R)=+1 / 末行 [0,0,0,1]（A7）。

    矩阵侧（handeye_result）与位姿侧（pose_source）共用同一实现，禁两份。
    """
    try:
        arr = np.asarray(T, dtype=np.float64)
    except (TypeError, ValueError) as e:
        return False, f"无法解析为 4×4 数值矩阵：{e}"
    if arr.shape != (4, 4):
        return False, f"必须是 4×4 矩阵，实际 shape={arr.shape}"
    if not np.all(np.isfinite(arr)):
        return False, "含 NaN/Inf 非有限值"
    R = arr[:3, :3]
    orth = float(np.max(np.abs(R.T @ R - np.eye(3))))
    if not (orth < ORTH_TOL):        # NaN 时两次比较均 False → 必须用 not(...)
        return False, f"旋转块非正交 ‖RᵀR−I‖∞={orth:.3e}（≥{ORTH_TOL:g}）"
    det = float(np.linalg.det(R))
    if not (abs(det - 1.0) < DET_TOL):
        return False, f"det(R)={det:.6f} ≠ +1（含镜像/缩放）"
    if not np.allclose(arr[3], [0.0, 0.0, 0.0, 1.0], atol=LAST_ROW_TOL):
        return False, f"末行应为 [0,0,0,1]，实际 {arr[3].tolist()}"
    return True, "ok"


def check_pose_norm(T_base2tool_mm, pose_type: str) -> tuple[bool, str]:
    """机器人位姿平移范数窗口（A2 位姿侧 / R10 / R11）。

    Args:
        T_base2tool_mm: 毫米域 4×4 位姿。
        pose_type: "absolute" | "delta"，**必填无默认**。

    窗口与手眼矩阵**不共用**（物理量不同：一个是相机安装距离，一个是法兰位置）。
    """
    try:
        pt = normalize_pose_type(pose_type)
    except PoseError as e:      # 入口统一返回元组，不抛异常
        return False, str(e)
    norm = translation_norm_mm(T_base2tool_mm)
    lo, hi = POSE_NORM_WINDOW_MM[pt]
    kind = "绝对位姿（法兰→基座原点距离）" if pt == "absolute" else "增量位姿（单步运动量）"
    if not (lo <= norm <= hi):
        if not np.isfinite(norm):
            return False, f"‖t‖={norm} 非有限值（NaN/Inf 位姿）：拒绝"
        if norm < lo:
            return False, (
                f"‖t‖={norm:.3f} mm 低于位姿窗口下限 {lo:.0f} mm（{kind}，"
                f"pose_type={pt}）：疑似米制位姿被当毫米读入，请把 unit 改为 m")
        return False, (
            f"‖t‖={norm:.3f} mm 高于位姿窗口上限 {hi:.0f} mm（{kind}，"
            f"pose_type={pt}）：疑似毫米被当米读入，请把 unit 改为 mm")
    return True, f"‖t‖={norm:.3f} mm 在位姿窗口 [{lo:.0f}, {hi:.0f}] mm 内（{kind}）"
