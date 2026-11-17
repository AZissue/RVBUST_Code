# -*- coding: utf-8 -*-
"""
退化门禁测试（test_validation_degenerate）—— 批 3 / A3 / A9 / R2 / R3。

跑法：conda rvc python 直跑，看退出码，勿用 pytest。

覆盖：
  [1] 正确矩阵 + 离面姿态 → PASS（err_mean ≈ 0）
  [2] 退化矩阵（平移错 110 mm，对应 @qa/@feas 复现的单轴退化场景）→ **必须 FAIL**
      ——A3 核心回归：success=True/rms_t=0.000 的退化矩阵，内符合指标全绿，
      只有戳点绝对度量能判死
  [3] 样本不足（n<3）→ FAIL（fail-closed）
  [4] 姿态离面：纯平移验证 / 全共轴旋转 → FAIL（沿公共轴平移误差不可辨）
  [5] A9 判别下限：≥3 mm 级偏差必判 FAIL；0.2 mm 不可判（判 PASS，
      证明门禁下限 ≈1 mm 量级、不是亚毫米保证）；1.0 mm 在本合成几何/姿态集下
      err_mean=0.326 判 PASS——检出率依赖几何与姿态集，与方案 A9 的实证口径
      （对方真实场景 1.0 mm 检出 100%）不矛盾，禁把 0.7 mm 门限当普遍保证
  [6] err_max 仅诊断：8 姿态中 1 个 2.4 mm 粗差 → warning 在、verdict 仍 PASS
  [7] 输入守卫：姿态内多点拒收 / NaN 针尖拒收 / 坏位姿拒收
  [8] TwoFrameOverlapChecker：同一云复制 → median 0；整体平移 1 mm → median ≈1 mm；
      ≥30° 旋转前提；轴向盲区提示恒在
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np

import pose_source
import transform_chain
import validation
from validation import TipTouchValidator, TwoFrameOverlapChecker

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def _rotz(deg):
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def _rotx(deg):
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def _roty(deg):
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)


def mkT(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = np.asarray(t, float)
    return M


# 真值链：眼在手上，T_cam2tool 真值 + 固定针尖（基座系）
T_cam2tool_true = mkT(_rotz(15) @ _rotx(20), [50.0, -30.0, 120.0])
P_TIP_BASE = np.array([400.0, 100.0, 420.0])

# 4 个离面姿态（旋转轴互不相同：Z / X / Y / 组合）
POSES_SPREAD = [
    mkT(_rotz(0),  [400.0, 100.0, 420.0]),
    mkT(_rotz(25), [420.0, 110.0, 430.0]),
    mkT(_rotx(30), [410.0, 120.0, 425.0]),
    mkT(_roty(35) @ _rotz(-20), [390.0, 105.0, 435.0]),
]


def tip_in_cam(T_base2tool, T_cam2tool):
    """真值链反推：基座系针尖 → 相机系观测（用**真值**矩阵，模拟相机看到针尖）。"""
    T_cam2base = transform_chain.compute_cam2base(True, T_cam2tool, T_base2tool)
    return np.linalg.inv(T_cam2base) @ np.append(P_TIP_BASE, 1.0)


print("=" * 70)
print("[1] 正确矩阵 + 离面姿态 → PASS")
v = TipTouchValidator(True, T_cam2tool_true)
for Tp in POSES_SPREAD:
    ok, msg = v.add_sample(Tp, tip_in_cam(Tp, T_cam2tool_true)[:3])
    check(ok, f"add_sample 接受 | {msg}")
rep = v.check()
check(rep["verdict"] == "PASS", "verdict == PASS", f"err_mean={rep['err_mean_mm']:.6f}")
check(rep["err_mean_mm"] < 1e-6, "err_mean ≈ 0（真值链闭环）",
      f"err_mean={rep['err_mean_mm']:.6f} mm")
check(rep["spread_ok"], "姿态离面满足", rep["spread_message"])
check(rep["n"] == 4, "样本数=4", f"n={rep['n']}")

print("=" * 70)
print("[2] 退化矩阵（平移错 110 mm，@qa/@feas 场景）→ 必须 FAIL")
T_bad = T_cam2tool_true.copy()
T_bad[:3, 3] += np.array([110.0, 0.0, 0.0])   # 退化标定的典型残留误差
v2 = TipTouchValidator(True, T_bad)
for Tp in POSES_SPREAD:
    ok, _ = v2.add_sample(Tp, tip_in_cam(Tp, T_cam2tool_true)[:3])
    check(ok, f"add_sample 接受（位姿本身合法）")
rep2 = v2.check()
check(rep2["verdict"] == "FAIL", "退化矩阵必须判 FAIL（A3 核心）",
      f"err_mean={rep2['err_mean_mm']:.3f} mm")
check(rep2["err_mean_mm"] > 0.7, "err_mean 超 0.7 mm 硬门禁",
      f"err_mean={rep2['err_mean_mm']:.3f}")
check(len(rep2["reasons"]) > 0, "FAIL 给出可读原因", "; ".join(rep2["reasons"])[:60])

print("=" * 70)
print("[3] 样本不足（n=2）→ FAIL（fail-closed）")
v3 = TipTouchValidator(True, T_cam2tool_true)
for Tp in POSES_SPREAD[:2]:
    v3.add_sample(Tp, tip_in_cam(Tp, T_cam2tool_true)[:3])
rep3 = v3.check()
check(rep3["verdict"] == "FAIL", "n=2 必须 FAIL", f"n={rep3['n']}")
check(any("样本不足" in r for r in rep3["reasons"]), "原因含『样本不足』",
      "; ".join(rep3["reasons"])[:60])

print("=" * 70)
print("[4] 姿态离面：纯平移 / 全共轴旋转 → FAIL")
poses_translate = [mkT(np.eye(3), [400 + 30 * i, 100, 420]) for i in range(3)]
v4 = TipTouchValidator(True, T_cam2tool_true)
for Tp in poses_translate:
    v4.add_sample(Tp, tip_in_cam(Tp, T_cam2tool_true)[:3])
rep4 = v4.check()
check(rep4["verdict"] == "FAIL" and not rep4["spread_ok"],
      "纯平移验证无判别力 → FAIL", rep4["spread_message"][:60])

poses_coplanar = [mkT(_rotz(d), [400, 100, 420]) for d in (0, 15, 30, 45)]
v4b = TipTouchValidator(True, T_cam2tool_true)
for Tp in poses_coplanar:
    v4b.add_sample(Tp, tip_in_cam(Tp, T_cam2tool_true)[:3])
rep4b = v4b.check()
check(not rep4b["spread_ok"], "全共轴（绕 Z）旋转 → 离面不满足",
      rep4b["spread_message"][:60])

print("=" * 70)
print("[5] A9 判别下限：≥3 mm 必判 FAIL；0.2 mm 不可判；1.0 mm 本姿态集不保证检出")


def biased_report(bias_mm):
    T_b = T_cam2tool_true.copy()
    T_b[:3, 3] += np.array([bias_mm, 0.0, 0.0])
    vb = TipTouchValidator(True, T_b)
    for Tp in POSES_SPREAD:
        vb.add_sample(Tp, tip_in_cam(Tp, T_cam2tool_true)[:3])
    return vb.check()


rep5a = biased_report(3.0)
check(rep5a["verdict"] == "FAIL", "3.0 mm 偏差检出（FAIL）",
      f"err_mean={rep5a['err_mean_mm']:.3f} mm")
rep5b = biased_report(0.2)
check(rep5b["verdict"] == "PASS", "0.2 mm 不可判（PASS，A9：非亚毫米保证）",
      f"err_mean={rep5b['err_mean_mm']:.3f} mm")
rep5c = biased_report(2.38)   # ≈ 1.0° 旋转等效平移（A9 表）
check(rep5c["verdict"] == "FAIL", "≈1.0° 旋转等效偏差（2.38 mm）检出（FAIL）",
      f"err_mean={rep5c['err_mean_mm']:.3f} mm")
rep5d = biased_report(1.0)
print(f"  [info] 1.0 mm 偏差在本合成几何/姿态集：err_mean={rep5d['err_mean_mm']:.3f} "
      f"→ {rep5d['verdict']}（检出率依赖几何与姿态集；方案 A9 的『1.0 mm 检出 100%』"
      f"是对方真实场景实证，本测试不冒用该口径）")

print("=" * 70)
print("[6] err_max 仅诊断：8 姿态中 1 个 2.4 mm 粗差 → warning 在、verdict 仍 PASS")
POSES_EIGHT = [
    mkT(_rotz(a) @ _rotx(b), [400 + 5 * i, 100 + 3 * i, 420 + 2 * i])
    for i, (a, b) in enumerate([(0, 0), (25, 10), (-30, 20), (40, -25),
                                (10, 40), (-20, -35), (55, 5), (-45, 15)])
]
v6 = TipTouchValidator(True, T_cam2tool_true)
for i, Tp in enumerate(POSES_EIGHT):
    pt = tip_in_cam(Tp, T_cam2tool_true)[:3]
    if i == 3:
        pt = pt + np.array([2.4, 0.0, 0.0])   # 该姿态针尖观测粗差 2.4 mm
    v6.add_sample(Tp, pt)
rep6 = v6.check()
check(len(rep6["warnings"]) > 0 and any("err_max" in w for w in rep6["warnings"]),
      "err_max>2.0 出 warning", "; ".join(rep6["warnings"])[:70])
check(rep6["verdict"] == "PASS", "warning 不进硬门禁，verdict 仍 PASS（R3）",
      f"err_mean={rep6['err_mean_mm']:.3f} err_max={rep6['err_max_mm']:.3f}")

print("=" * 70)
print("[7] 输入守卫：多点 / NaN 针尖 / 坏位姿 拒收")
v7 = TipTouchValidator(True, T_cam2tool_true)
ok7, msg7 = v7.add_sample(POSES_SPREAD[0],
                          np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))
check(not ok7, "姿态内多点拒收（门限可复现，§4.2）", msg7[:60])
ok7b, msg7b = v7.add_sample(POSES_SPREAD[0], [np.nan, 0.0, 500.0])
check(not ok7b, "NaN 针尖拒收", msg7b[:50])
bad_pose = POSES_SPREAD[0].copy()
bad_pose[:3, :3] *= 2.0
ok7c, msg7c = v7.add_sample(bad_pose, [0.0, 0.0, 500.0])
check(not ok7c, "坏位姿（缩放）拒收", msg7c[:50])
check(len(v7) == 0, "拒收的样本不入序列", f"n={len(v7)}")
ok7d, _ = v7.add_sample(POSES_SPREAD[0].tolist(),
                        tip_in_cam(POSES_SPREAD[0], T_cam2tool_true)[:3].tolist())
check(ok7d, "list 形态的位姿/针尖也收（宽松入参）", f"n={len(v7)}")

print("=" * 70)
print("[8] TwoFrameOverlapChecker：统计 / 30° 前提 / 盲区提示")
rng = np.random.default_rng(3)
obj = rng.uniform([350, 150, 60], [450, 250, 140], (2000, 3))
Ta = mkT(_rotz(10), [400, 100, 420])
Tb_far = mkT(_rotz(60) @ _rotx(30), [430, 120, 430])     # 旋转差 ≫ 30°
Tb_near = mkT(_rotz(20), [405, 105, 422])                 # 旋转差 < 30°


def cloud_of(T_base2tool):
    T_cb = transform_chain.compute_cam2base(True, T_cam2tool_true, T_base2tool)
    hom = np.concatenate([obj, np.ones((len(obj), 1))], axis=1)
    return (np.linalg.inv(T_cb) @ hom.T).T[:, :3]


rep8 = TwoFrameOverlapChecker.check(cloud_of(Ta), cloud_of(Ta).copy(), Ta, Ta)
check(abs(rep8["median_mm"]) < 1e-9, "同一云复制 → median = 0",
      f"median={rep8['median_mm']:.6f} p95={rep8['p95_mm']:.6f}")
shifted = cloud_of(Ta) + np.array([1.0, 0.0, 0.0])
rep8s = TwoFrameOverlapChecker.check(cloud_of(Ta), shifted, Ta, Ta)
check(abs(rep8s["median_mm"] - 1.0) < 1e-6, "整体平移 1 mm → median ≈ 1 mm（度量正确性）",
      f"median={rep8s['median_mm']:.6f}")
rep8r = TwoFrameOverlapChecker.check(cloud_of(Ta), cloud_of(Tb_far), Ta, Tb_far)
check(rep8r["rotation_deg"] >= 30.0 and rep8r["verdict"] == "OK",
      "旋转差 ≥30° → 前提满足（数值此时只是参考）",
      f"rot={rep8r['rotation_deg']:.1f}° median={rep8r['median_mm']:.3f}")
check("轴向盲区" in rep8r["hint"], "盲区提示恒在（R2）", rep8r["hint"][:40])

rep8b = TwoFrameOverlapChecker.check(cloud_of(Ta), cloud_of(Tb_near), Ta, Tb_near)
check(rep8b["verdict"] == "PRECONDITION_FAILED", "旋转差 <30° → 前提不满足（仅供参考）",
      f"rot={rep8b['rotation_deg']:.1f}°")

rep8c = TwoFrameOverlapChecker.check(cloud_of(Ta), cloud_of(Tb_far))  # 不给位姿
check(rep8c["verdict"] == "OK" and rep8c["rotation_deg"] is None,
      "不给位姿则不查前提（责任在调用方，README 写明）", "")

try:
    TwoFrameOverlapChecker.check(cloud_of(Ta),
                                 np.full((10, 3), np.nan))
    check(False, "NaN 点云拒收", "")
except validation.ValidationError as e:
    check(True, "NaN 点云拒收", str(e)[:40])

print("=" * 70)
if FAILURES:
    print(f"[FAILED] {len(FAILURES)} 项失败:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("[ALL OK] test_validation_degenerate")
sys.exit(0)
