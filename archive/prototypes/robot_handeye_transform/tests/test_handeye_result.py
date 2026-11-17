# -*- coding: utf-8 -*-
"""
A7 手眼结果加载守卫测试（test_handeye_result）。

跑法同 test_unit_guard.py（conda rvc python 直跑，看退出码）。

覆盖：
  [1] A7 矩阵合法性：非有限 / 非正交 / det=-1 镜像 / 末行错 → 拒绝
  [2] K6 键名分支：眼在手上取 T_cam2tool，眼在手外取 T_cam2base
  [3] K7 _fail() 缺键守卫：success=False（含眼在手外缺 T_cam2base 键）→
      拒绝且可读，不 KeyError
  [4] 单位：unit 必填（auto/非法拒绝）；米制 JSON 用 unit="m" 读入与毫米真值一致
  [5] from_matrix：16 数行优先 / 4×4；validated 默认 False（UNVERIFIED）
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import handeye_result
from handeye_result import HandEyeResult
from unit_guard import normalize_unit

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def write_json(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json", prefix="mcc_he_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def base_T(t=(100.0, 20.0, 120.0)) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = list(t)
    return T


def T_with_t(t) -> np.ndarray:
    return base_T(t)


def good_json(eye_in_hand: bool = True, T=None, **extra) -> dict:
    T = np.asarray(T if T is not None else base_T(), dtype=np.float64)
    d = {
        "success": True,
        "eye_in_hand": eye_in_hand,
        "method": 0,
        "n_samples": 9,
        "rms_t_mm": 0.12,
        "rms_r_deg": 0.05,
    }
    if eye_in_hand:
        d["T_cam2tool"] = T.tolist()
        d["T_tool2cam"] = np.linalg.inv(T).tolist()
    else:
        d["T_cam2base"] = T.tolist()
        d["T_base2cam"] = np.linalg.inv(T).tolist()
    d.update(extra)
    return d


def main():
    print("=" * 70)
    print("[1] A7 矩阵合法性（from_matrix 路径）")
    cases = []
    bad = base_T(); bad[0, 3] = np.nan
    cases.append(("NaN", bad))
    bad = base_T(); bad[:3, :3] = np.diag([2.0, 1.0, 1.0])  # 含缩放，非正交
    cases.append(("缩放(非正交)", bad))
    bad = base_T(); bad[0, 0] = -1.0  # det=-1 镜像
    cases.append(("det=-1 镜像", bad))
    bad = base_T(); bad[3] = [0.0, 0.0, 1.0, 1.0]  # 末行错
    cases.append(("末行非[0,0,0,1]", bad))
    for name, T in cases:
        ok, msg, res = HandEyeResult.from_matrix(T, "mm", True)
        check(not ok and res is None, f"拒绝 {name}", msg)
    ok, msg, res = HandEyeResult.from_matrix(base_T(), "mm", True)
    check(ok and res is not None, "合法矩阵放行", msg)

    print("=" * 70)
    print("[2] K6 键名分支")
    p = write_json(good_json(True))
    ok, msg, res = HandEyeResult.load(p, "mm")
    check(ok and res is not None and res.eye_in_hand
          and np.allclose(res.T_handeye_mm, base_T()),
          "眼在手上 JSON 取 T_cam2tool", msg)
    os.unlink(p)

    p = write_json(good_json(False, T=T_with_t((1500.0, 0.0, 0.0))))
    ok, msg, res = HandEyeResult.load(p, "mm")
    check(ok and res is not None and not res.eye_in_hand
          and abs(res.T_handeye_mm[0, 3] - 1500.0) < 1e-9,
          "眼在手外 JSON 取 T_cam2base", msg)
    os.unlink(p)

    # 键缺失：眼在手上 JSON 里没有 T_cam2base，反装 must 拒绝而非误读
    p = write_json(good_json(True))
    ok, msg, res = HandEyeResult.load(p, "mm", eye_in_hand=False)
    check(not ok and res is None, "eye_in_hand 参数与 JSON 不一致 → 拒绝", msg)
    os.unlink(p)

    print("=" * 70)
    print("[3] K7 _fail() 缺键守卫")
    fail_dict = {  # 模拟 handeye.py:225 _fail() 实际输出（success=False 且缺眼在手外键）
        "success": False,
        "message": "手眼标定至少需要 3 组样本",
        "T_cam2tool": None, "T_tool2cam": None,
        "rms_t_mm": 0.0, "rms_r_deg": 0.0, "n_samples": 0,
    }
    p = write_json(fail_dict)
    ok, msg, res = HandEyeResult.load(p, "mm")
    check(not ok and res is None and "未成功" in msg,
          "success=False 拒绝且不 KeyError", msg)
    os.unlink(p)

    no_success = good_json(True)
    del no_success["success"]
    p = write_json(no_success)
    ok, msg, res = HandEyeResult.load(p, "mm")
    check(not ok, "缺 success 键 → 拒绝", msg)
    os.unlink(p)

    no_eih = good_json(True)
    del no_eih["eye_in_hand"]
    p = write_json(no_eih)
    ok, msg, res = HandEyeResult.load(p, "mm")
    check(not ok, "缺 eye_in_hand 键 → 拒绝（无法定键分支）", msg)
    os.unlink(p)

    print("=" * 70)
    print("[4] 单位（A2：显式必选，大小写归一）")
    check(normalize_unit("mM") == "mm", "unit='mM' 归一为 'mm'")
    for bad_unit in ("auto", "", "米"):
        p = write_json(good_json(True))
        ok, msg, res = HandEyeResult.load(p, bad_unit)
        check(not ok and res is None, f"unit={bad_unit!r} 拒绝（无 auto）", msg)
        os.unlink(p)

    T_m = base_T((0.1, 0.02, 0.12))  # 米制真值
    p = write_json(good_json(True, T=T_m))
    ok, msg, res = HandEyeResult.load(p, "m")
    check(ok and np.allclose(res.T_handeye_mm, base_T(), atol=1e-9),
          "米制 JSON + unit='m' → 与毫米真值一致", msg)
    os.unlink(p)
    p = write_json(good_json(True, T=T_m))
    ok, msg, res = HandEyeResult.load(p, "mm")  # 0.1mm 低于下界 → 拦（米制当毫米）
    check(not ok, "米制 JSON 误用 unit='mm' → 范数窗口拦", msg)
    os.unlink(p)

    print("=" * 70)
    print("[5] from_matrix 录入与 UNVERIFIED 语义")
    ok, msg, res = HandEyeResult.from_matrix(base_T().reshape(-1), "mm", True)
    check(ok and res is not None and abs(res.T_handeye_mm[0, 3] - 100.0) < 1e-9,
          "16 数行优先录入", msg)
    check(ok and res is not None and res.validated is False
          and res.source == "manual" and res.n_samples == 0,
          "validated 默认 False（UNVERIFIED，戳点 A3 前不许导出）")
    ok, msg, res = HandEyeResult.from_matrix(np.ones((3, 3)), "mm", True)
    check(not ok, "3×3 拒绝", msg)

    print("=" * 70)
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("[ALL OK] test_handeye_result")
    sys.exit(0)


if __name__ == "__main__":
    main()
