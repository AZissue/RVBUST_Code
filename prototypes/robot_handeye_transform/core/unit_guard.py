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
    if norm < lo:
        return False, (
            f"‖t‖={norm:.3f} mm 低于物理下限 {lo:.0f} mm（{kind}）："
            f"疑似米制矩阵被当毫米读入，请把单位改为 m")
    if norm > hi:
        return False, (
            f"‖t‖={norm:.3f} mm 高于物理上限 {hi:.0f} mm（{kind}）："
            f"疑似毫米被当米读入，请把单位改为 mm")
    return True, f"‖t‖={norm:.3f} mm 在物理窗口 [{lo:.0f}, {hi:.0f}] mm 内（{kind}）"
