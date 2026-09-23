# -*- coding: utf-8 -*-
"""
共用校验层测试（test_matrix_guard）—— 批 1.5 / 方案 v4 §4.2。

跑法同 test_unit_guard.py（conda rvc python 直跑，看退出码，勿用 pytest）。

覆盖：
  [1] check_rigid_4x4：有限性 / 正交 / det=+1 / 末行 —— 含 **det=+1 的 shear**
      用例（@qa 变异测试：把 ORTH_TOL 改成 1e9 时旧用例全绿未拦，因为旧的
      "非正交" 用例 diag([2,1,1]) 被 det 检查兜住了）
  [2] check_pose_norm：absolute [30, 20000] / delta [1, 500] 双窗口边界（双端闭区间）
  [3] NaN：范数窗口写成 `if n < lo or n > hi` 会静默放行 —— 必须拒绝
  [4] unit / pose_type 归一与非法拒绝（均无默认）
  [5] 判别力 assert：lo > v_max/1000 且 hi < 1000·v_min（含 [100, 100000] 反例）
  [6] 只有一份实现：改 unit_guard 的容差，矩阵侧 handeye_result.validate_matrix
      同步生效（委托证明；禁两份副本）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import handeye_result
import unit_guard
from unit_guard import (POSE_DOMAIN_MM, POSE_NORM_WINDOW_MM, PoseError,
                        check_pose_norm, check_rigid_4x4, check_translation_norm,
                        normalize_pose_type)

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def T(t=(100.0, 0.0, 0.0), R=None) -> np.ndarray:
    M = np.eye(4)
    if R is not None:
        M[:3, :3] = R
    M[:3, 3] = list(t)
    return M


SHEAR = np.array([[1.0, 0.5, 0.0],   # det=+1 但非正交：‖RᵀR−I‖∞ = 0.5
                  [0.0, 1.0, 0.0],
                  [0.0, 0.0, 1.0]])


def main():
    print("=" * 70)
    print("[1] check_rigid_4x4（A7 共用实现）")
    ok, msg = check_rigid_4x4(T())
    check(ok, "合法刚性矩阵放行", msg)
    ok, msg = check_rigid_4x4(np.ones((3, 3)))
    check(not ok and "4×4" in msg, "3×3 拒绝且报 shape", msg)
    bad = T(); bad[0, 3] = np.nan
    ok, msg = check_rigid_4x4(bad)
    check(not ok and "非有限" in msg, "NaN 拒绝", msg)
    bad = T(); bad[1, 1] = np.inf
    ok, msg = check_rigid_4x4(bad)
    check(not ok and "非有限" in msg, "Inf 拒绝", msg)
    ok, msg = check_rigid_4x4(T(R=np.diag([2.0, 1.0, 1.0])))
    check(not ok and "非正交" in msg, "缩放（非正交）拒绝", msg)
    ok, msg = check_rigid_4x4(T(R=SHEAR))
    check(not ok and "非正交" in msg,
          "det=+1 的 shear 拒绝（正交性检查单独有效，@qa 盲点）",
          f"det=+1, ‖RᵀR−I‖∞=0.5 → {msg}")
    bad = T(); bad[0, 0] = -1.0
    ok, msg = check_rigid_4x4(bad)
    check(not ok and "det(R)" in msg, "det=-1 镜像拒绝", msg)
    bad = T(); bad[3] = [0.0, 0.0, 1.0, 1.0]
    ok, msg = check_rigid_4x4(bad)
    check(not ok and "末行" in msg, "末行非 [0,0,0,1] 拒绝", msg)
    ok, msg = check_rigid_4x4([["a"] * 4] * 4)
    check(not ok and "无法解析" in msg, "非数值输入自家可读报错", msg)

    print("=" * 70)
    print("[2] check_pose_norm 双窗口边界（双端闭区间）")
    a_lo, a_hi = POSE_NORM_WINDOW_MM["absolute"]
    for norm, expect in ((a_lo - 0.1, False), (a_lo, True),
                         (a_hi, True), (a_hi + 1.0, False)):
        ok, msg = check_pose_norm(T((norm, 0.0, 0.0)), "absolute")
        check(ok is expect, f"absolute ‖t‖={norm:g} → {'放行' if expect else '拒绝'}", msg)
    d_lo, d_hi = POSE_NORM_WINDOW_MM["delta"]
    # 注意：delta 窗口是**预留值**（批 2~4 不可达）——`pose_source.admit_pose()` 已对
    # delta 做 fail-closed 拒绝（R11）。本段只锁窗口函数本身的判别力，不代表 delta 可用。
    for norm, expect in ((d_lo - 0.1, False), (d_lo, True),
                         (d_hi, True), (d_hi + 1.0, False)):
        ok, msg = check_pose_norm(T((norm, 0.0, 0.0)), "delta")
        check(ok is expect, f"delta ‖t‖={norm:g} → {'放行' if expect else '拒绝'}", msg)

    print("=" * 70)
    print("[3] NaN 必须拒绝（不是静默放行）")
    nan_T = T(); nan_T[0, 3] = np.nan
    ok, msg = check_pose_norm(nan_T, "absolute")
    check(not ok, "NaN 位姿 → 拒绝（`if n < lo or n > hi` 写法会漏）", msg)
    inf_T = T(); inf_T[0, 3] = np.inf
    ok, msg = check_pose_norm(inf_T, "absolute")
    check(not ok, "Inf 位姿 → 拒绝", msg)
    ok, msg = check_rigid_4x4(nan_T)
    check(not ok, "NaN 位姿在刚性校验即拒绝（更早一道）", msg)
    # 矩阵侧对称用例（@qa②：双保险里此前只有位姿侧被测试盯着）
    ok, msg = check_translation_norm(nan_T, True)
    check(not ok, "矩阵侧 check_translation_norm 遇 NaN 也拒绝（对称用例）", msg)
    ok, msg = check_translation_norm(inf_T, False)
    check(not ok, "矩阵侧 Inf 同样拒绝", msg)

    print("=" * 70)
    print("[4] unit / pose_type 无默认")
    for bad_pt in (None, "", "绝对", 0, "abs"):
        try:
            normalize_pose_type(bad_pt)
            check(False, f"pose_type={bad_pt!r} 必须拒绝")
        except PoseError as e:
            check("必须显式选择" in str(e), f"pose_type={bad_pt!r} 拒绝且可读", str(e)[:40])
    check(normalize_pose_type(" Absolute ") == "absolute",
          "pose_type 大小写/空格归一（同 unit 'mM'→'mm' 口径，不算非法）")
    ok, msg = check_pose_norm(T(), "auto")
    check(not ok, "pose_type='auto' 拒绝（无 auto，同 unit 口径）", msg[:40])
    # @arch 硬约束：禁止 POSE_NORM_WINDOW_MM.get(pt, 默认值) 兜底——非法 pose_type
    # 一旦有默认档位就会静默落进某窗口，"返回元组不抛异常"从礼貌变成漏洞
    import inspect
    fn_src = inspect.getsource(unit_guard.check_pose_norm)
    check(".get(" not in fn_src,
          "check_pose_norm 源码内无 .get() 兜底默认值（@arch 硬约束，源码级锁定）")
    mid = 100.0  # 同时落在 absolute [30,20000] 与 delta [1,500] 内的歧义值
    for bad_pt in (None, "", "abs", "both", "auto"):
        ok, msg = check_pose_norm(T((mid, 0.0, 0.0)), bad_pt)
        check(not ok, f"‖t‖={mid:g}（两档窗口皆合法）但 pose_type={bad_pt!r} → 仍拒绝",
              msg[:40])

    print("=" * 70)
    print("[5] 判别力规则：lo > v_max/1000 且 hi < 1000·v_min")

    def has_power(win, v):
        lo, hi = win
        return lo > v[1] / 1000.0 and hi < 1000.0 * v[0]

    v_abs = POSE_DOMAIN_MM["absolute"]
    check(has_power(POSE_NORM_WINDOW_MM["absolute"], v_abs),
          f"当前 absolute 窗口 {POSE_NORM_WINDOW_MM['absolute']} 有判别力",
          f"合法域={v_abs}")
    check(has_power(POSE_NORM_WINDOW_MM["delta"], POSE_DOMAIN_MM["delta"]),
          "当前 delta 窗口有判别力")
    check(not has_power((100.0, 100000.0), v_abs),
          "[100, 100000] 判无判别力（@arch 复算 @feas 表格）")
    ok, _ = check_pose_norm(T((60000.0, 0.0, 0.0)), "absolute")
    check(not ok, "60×1000=60000 的 ×1000 误读被当前窗口拦住（该放大窗口会漏）")
    check(has_power((5.0, 2000.0), v_abs),
          "[5, 2000] 判别力成立但会误拦长臂（R10，非判别力问题）")
    for n in (2700.0, 4500.0):
        check(not (5.0 <= n <= 2000.0) and (30.0 <= n <= 20000.0),
              f"长臂位姿 ‖t‖={n:g} mm 在 [5,2000] 被误拦、在当前窗口放行")

    print("=" * 70)
    print("[6] 单实现证明：改 unit_guard 容差，矩阵侧同步生效")
    keep = unit_guard.ORTH_TOL
    try:
        unit_guard.ORTH_TOL = 1e9
        ok_guard, _ = check_rigid_4x4(T(R=SHEAR))
        ok_he, _ = handeye_result.validate_matrix(T(R=SHEAR))
        check(ok_guard and ok_he,
              "容差改 1e9 后两侧同时放行 → 确认只有一份实现（委托）")
    finally:
        unit_guard.ORTH_TOL = keep
    ok, _ = handeye_result.validate_matrix(T(R=SHEAR))
    check(not ok, "容差复位后矩阵侧重新拒绝 shear")

    print("=" * 70)
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("[ALL OK] test_matrix_guard")
    sys.exit(0)


if __name__ == "__main__":
    main()
