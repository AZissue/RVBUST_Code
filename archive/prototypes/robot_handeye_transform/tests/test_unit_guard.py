# -*- coding: utf-8 -*-
"""
A2 单位守卫测试（test_unit_guard）。

跑法（Git Bash，勿用 pytest）：
  cd D:\\RVC_SRC\\Python\\MultiCameraCalibration
  unset PYTHONPATH && export QT_QPA_PLATFORM=offscreen
  "D:\\Program Files\\Anaconda\\envs\\rvc\\python.exe" \
    prototypes/robot_handeye_transform/tests/test_unit_guard.py
判 pass/fail 看进程退出码。

覆盖：
  [1] to_mm/to_unit 换算 + 非法单位抛 UnitError（无 auto，D4）
  [2] 同一矩阵 mm↔m 往返差 < 1e-6 mm（必须用同一矩阵往返，@qa）
  [3] 平移范数窗口——眼在手上 6 档合法全过 + ÷1000/×1000 误读全拦
  [4] 平移范数窗口——眼在手外 6 档合法全过（@scribe 回归：2500/4000/8000
      旧单窗口会误拦）+ ÷1000 误读全拦（|t|=8000mm 误读 8mm 旧窗口漏放）
  [5] 分档设计规则：下界 > 上界 / 1000
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import unit_guard
from unit_guard import normalize_unit

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def T_with_norm(norm_mm: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = [norm_mm, 0.0, 0.0]
    return T


def main():
    print("=" * 70)
    print("[1] to_mm / to_unit / 非法单位")
    T_mm = T_with_norm(113.8)
    T_m = unit_guard.to_unit(T_mm, "m")
    check(abs(T_m[0, 3] - 0.1138) < 1e-12, "to_unit mm->m", f"t={T_m[0, 3]}")
    T_back = unit_guard.to_mm(T_m, "m")
    diff = float(np.max(np.abs(T_back - T_mm)))
    check(diff < 1e-6, "同一矩阵 mm->m->mm 往返 < 1e-6 mm", f"diff={diff:.3e}")
    check(abs(T_mm[0, 3] - 113.8) < 1e-12, "to_unit 不修改入参", f"t={T_mm[0, 3]}")
    check(normalize_unit("M") == "m" and normalize_unit("mM") == "mm",
          "单位大小写归一（M->m, mM->mm，无语义风险）")
    for bad in ("auto", "", "毫米", " meters", None):
        try:
            unit_guard.to_mm(T_mm, bad)
            check(False, f"非法单位 {bad!r} 必须抛 UnitError")
        except unit_guard.UnitError:
            check(True, f"非法单位 {bad!r} 抛 UnitError")

    print("=" * 70)
    print("[2] 眼在手上窗口 [5, 2000] mm")
    legal_eih = [30.0, 55.0, 113.8, 600.0, 1500.0, 2000.0]
    for n in legal_eih:
        ok, msg = unit_guard.check_translation_norm(T_with_norm(n), True)
        check(ok, f"合法眼在手上 ‖t‖={n} mm", msg)
    for n in [0.03, 0.055, 0.1138, 0.6, 1.5, 2.0]:  # ÷1000：米制当毫米
        ok, msg = unit_guard.check_translation_norm(T_with_norm(n), True)
        check(not ok, f"拦 ÷1000 误读 ‖t‖={n} mm", msg)
    for n in [30000.0, 55000.0, 113800.0]:  # ×1000：毫米当米
        ok, msg = unit_guard.check_translation_norm(T_with_norm(n), True)
        check(not ok, f"拦 ×1000 误读 ‖t‖={n} mm", msg)

    print("=" * 70)
    print("[3] 眼在手外窗口 [50, 20000] mm（@scribe/@qa 两档回归）")
    legal_eth = [600.0, 1500.0, 2500.0, 4000.0, 8000.0, 20000.0]
    for n in legal_eth:
        ok, msg = unit_guard.check_translation_norm(T_with_norm(n), False)
        check(ok, f"合法眼在手外 ‖t‖={n} mm", msg)
    for n in [0.6, 1.5, 2.5, 4.0, 8.0, 20.0]:  # ÷1000：8mm 在旧单窗口内会漏放
        ok, msg = unit_guard.check_translation_norm(T_with_norm(n), False)
        check(not ok, f"拦 ÷1000 误读 ‖t‖={n} mm", msg)
    for n in [600000.0, 8e6]:  # ×1000
        ok, msg = unit_guard.check_translation_norm(T_with_norm(n), False)
        check(not ok, f"拦 ×1000 误读 ‖t‖={n:g} mm", msg)

    print("=" * 70)
    print("[4] 分档设计规则：下界 > 上界/1000")
    for eih, (lo, hi) in unit_guard.TRANSLATION_NORM_WINDOW_MM.items():
        check(lo > hi / 1000.0, f"{'眼在手上' if eih else '眼在手外'} [{lo}, {hi}] "
                                 f"下界>上界/1000")

    print("=" * 70)
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("[ALL OK] test_unit_guard")
    sys.exit(0)


if __name__ == "__main__":
    main()
