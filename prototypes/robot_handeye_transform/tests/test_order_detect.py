# -*- coding: utf-8 -*-
"""
A11-③ 欧拉顺序自动判定测试（test_order_detect）。

跑法（REGRESSION §0 第 4 条，conda rvc python 直跑，看退出码）：

    cd D:/RVC_SRC/Python/MultiCameraCalibration
    unset PYTHONPATH; export QT_QPA_PLATFORM=offscreen
    "D:/Program Files/Anaconda/envs/rvc/python.exe" \
        prototypes/robot_handeye_transform/tests/test_order_detect.py; echo exit=$?

覆盖：
  [0] 内核等价性：`order_detect._residual` 与 **@verify 原始实现**（tools/golden/
      full_handeye.py 的 `resid`）残差向量逐元素一致（1e-12），且用参照残差拟合
      真值分支得到同一结论 —— 参照实现**只 exec 源码、不复制内容**
  [1] A11-1 正例：12 个 Tait-Bryan 真值逐一注入 → 唯一挑出真值，其余候选全部超阈
  [2] A11-2 位数下限：n=2 拒 / n=3,4,5 唯一通过 / 空表 INVALID
  [3] A11-3 退化必报多解：纯单轴 → INSUFFICIENT + 只输出"补什么方向"；
      平移共线/共面 → INSUFFICIENT
  [4] A11-4 弱判据禁用：n=3 给 1 个候选（弱判据会给 6~24 个）+ 源码无弱判据定案分支
  [5] A11-5 稳定性（@lead v2.3-④ 口径）：边界只出"多解/激励不足"，不给答案；
      掩码不变量 —— 冠军变化必须伴随结论降级。**如实标注：不含"自然冠军翻转"用例**
  [6] A11-6 单位先行：同一批数据 mm/m 两种声明排名逐位一致；米制数值当 mm 被 A2 拒
  [7] R19/R25：候选基数公式 == 实际条数；PE 只作诊断；rad 走单位分支识别；
      平移散布按维数判（n=3 不被"共面"判死）
  [8] R24/verdict 枚举/A11-④：排名表字段两引擎共用（缺失填 null）；engine 参数化
      且 sdk 未接线时直接报错不静默退回；verdict ⊆ 冻结四值；输出口径唯一实现
"""

import math
import os
import re
import sys

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation as Rot

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, "..", "core"))
sys.path.insert(0, CORE)

import order_detect as od  # noqa: E402

# @verify 原始实现的存放位置（@lead v2.3-⑥ 指定 tools/golden/；挪档前只有 scratch 一份）
GOLDEN_DIRS = [
    os.path.normpath(os.path.join(HERE, "..", "tools", "golden")),
    r"C:\Users\jingz\AppData\Local\hermes\profiles\verify\cache\scratch",
]

FAILURES = []
VERDICT_SEEN = set()
VERDICT_ENUM = {"OK", "MULTI", "INSUFFICIENT", "INVALID"}   # v2.3-③ 冻结四值
RANK_ROW_KEYS = {"key", "order", "angle_unit", "resid", "pass", "n_kept",
                 "tme", "baseline_diff", "note"}


def fnum(v, fmt=".3e") -> str:
    """可选数值的安全格式化：`None`（未定案时 rms/gap 恒为 None）不炸测试。"""
    return format(v, fmt) if isinstance(v, (int, float)) else str(v)


def load_golden_head(name: str):
    """exec golden 目录里某脚本的**函数定义部分**（跳过顶层 sweep），返回命名空间。

    与 `load_golden_resid` 同一纪律：引用 golden、不复制内容；缺失即测试失败。
    """
    for d in GOLDEN_DIRS:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        ns = {}
        marker = re.search(r"^rng\s*=", src, flags=re.M)
        head = src[:marker.start()] if marker else src
        exec(compile(head, p, "exec"), ns)              # noqa: S102
        return ns, f"{p}（exec 函数定义，未复制内容）"
    return None, f"未找到 {name}（找过 {GOLDEN_DIRS}）"


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def note(res: dict):
    """收集实际出现过的 verdict（[8] 断言取值恰为冻结四值）。"""
    VERDICT_SEEN.add(res.get("verdict"))


# ----------------------------------------------------------------------
# 参照实现（@verify 原始 kernel）—— 只 exec 源码，不复制内容
# ----------------------------------------------------------------------
def load_golden_resid():
    """返回 (resid 函数, 出处说明)。找不到 → (None, 说明)。

    `full_handeye.py` 顶层自带一段 sweep 打印，直接 exec 会跑它：只 exec 到函数定义
    结束（首个顶层赋值之前）。切分失败则整体 exec 并把 stdout 吞掉（结论不变）。
    """
    for d in GOLDEN_DIRS:
        p = os.path.join(d, "full_handeye.py")
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        ns = {}
        marker = re.search(r"^rng\s*=", src, flags=re.M)
        head = src[:marker.start()] if marker else src
        try:
            if marker:
                exec(compile(head, p, "exec"), ns)      # noqa: S102
            else:
                import contextlib
                import io
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    exec(compile(src, p, "exec"), ns)   # noqa: S102
        except Exception as e:                          # noqa: BLE001
            raise AssertionError(f"参照实现无法加载: {p} -> {e}") from None
        if "resid" not in ns:
            raise AssertionError(f"参照实现里没有 resid: {p}")
        return ns["resid"], f"{p}（exec 源码，未复制内容）"
    return None, f"未找到 full_handeye.py（找过 {GOLDEN_DIRS}）"


# ----------------------------------------------------------------------
# 合成 oracle（真值约定注入 + 相机侧成对观测）
# ----------------------------------------------------------------------
def mat(R, t) -> np.ndarray:
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


class Oracle:
    """真值手眼 X（T_cam2tool）+ 真值 T_target2base，产出机器人位姿原文与相机侧观测。"""

    def __init__(self, seed=7):
        rng = np.random.default_rng(seed)
        self.X = mat(Rot.random(random_state=rng).as_matrix(), rng.uniform(-50, 50, 3))
        self.Tt2b = mat(Rot.random(random_state=rng).as_matrix(), rng.uniform(200, 500, 3))

    def build(self, n, conv="XYZ", unit="deg", seed=11, mode="general",
              tmode="random", spread=6.0, noise_t_mm=0.0, noise_r_deg=0.0,
              noise_seed=99):
        rng = np.random.default_rng(seed)
        nrng = np.random.default_rng(noise_seed)
        xyz, abc, Tgb = [], [], []
        for _ in range(n):
            if mode == "zonly":
                r = Rot.from_rotvec(np.deg2rad(rng.uniform(-40, 40)) * np.array([0, 0, 1.0]))
            elif mode == "zsmallY":
                r = Rot.from_euler("XYZ", [0, rng.uniform(-spread, spread),
                                           rng.uniform(-40, 40)], degrees=True)
            elif mode == "axis2d":
                r = Rot.from_euler("XYZ", [rng.uniform(-spread, spread), 0,
                                           rng.uniform(-40, 40)], degrees=True)
            else:
                r = Rot.random(random_state=rng)
            if tmode == "random":
                t = rng.uniform(-300, 300, 3)
            elif tmode == "line":
                s = rng.uniform(-300, 300)
                t = np.array([s, 2 * s, -0.5 * s])
            elif tmode == "plane":
                t = np.array([rng.uniform(-300, 300), rng.uniform(-300, 300), 120.0])
            else:                                   # free：平移展成 3 维（非共线非共面）
                t = np.array([rng.uniform(-300, 300), rng.uniform(-300, 300),
                              rng.uniform(-300, 300)])
            A = mat(r.as_matrix(), t)
            Tgb.append(A)
            xyz.append(t)
            abc.append(r.as_euler(conv, degrees=(unit == "deg")))
        Ttc = [self.X @ np.linalg.inv(A) @ self.Tt2b for A in Tgb]
        if noise_t_mm or noise_r_deg:
            noisy = []
            for M in Ttc:
                d = mat(Rot.from_rotvec(
                    np.deg2rad(nrng.normal(0, noise_r_deg, 3))).as_matrix(),
                    nrng.normal(0, noise_t_mm, 3))
                noisy.append(M @ d)             # 相机侧观测带噪（现场真实形态）
            Ttc = noisy
        return np.array(xyz), np.array(abc), Ttc


OC = Oracle()

print("=" * 78)
print("[0] 内核等价性：与 @verify 原始实现（参照）逐元素比对")
golden_resid, src_desc = load_golden_resid()
check(golden_resid is not None, "参照实现可加载（缺失即测试失败，不静默跳过 —— A1 口径）",
      src_desc)
if golden_resid is not None:
    xyz, abc, Ttc = OC.build(6, conv="XYZ", seed=11)
    br = od.Branch("XYZ", "deg")
    Tgb = [od.branch_matrix(br, xyz[i], abc[i]) for i in range(6)]
    Tgb_inv = np.asarray([np.linalg.inv(T) for T in Tgb], dtype=np.float64)
    Ttc_inv = np.asarray([np.linalg.inv(T) for T in Ttc], dtype=np.float64)
    worst = 0.0
    for k in range(6):
        p = np.random.default_rng(100 + k).normal(0.0, 40.0, 12)
        ref = golden_resid(p, Tgb, Ttc)
        mine = od._residual(p, Tgb_inv, Ttc_inv)
        worst = max(worst, float(np.max(np.abs(ref - mine))))
    p_true = np.concatenate([Rot.from_matrix(OC.X[:3, :3]).as_rotvec(), OC.X[:3, 3],
                             Rot.from_matrix(OC.Tt2b[:3, :3]).as_rotvec(), OC.Tt2b[:3, 3]])
    p0 = od._axzb_init(Tgb_inv, np.asarray(Ttc, dtype=np.float64))
    worst = max(worst, float(np.max(np.abs(golden_resid(p_true, Tgb, Ttc) -
                                           od._residual(p_true, Tgb_inv, Ttc_inv)))))
    worst = max(worst, float(np.max(np.abs(golden_resid(p0, Tgb, Ttc) -
                                           od._residual(p0, Tgb_inv, Ttc_inv)))))
    check(worst < 1e-12, "残差向量逐元素一致（6 个随机点 + 真值点 + 闭式初值点）",
          f"max|Δ|={worst:.3e}")
    # 结论一致：用参照残差自己拟合真值分支，看是否也收敛到 ~0
    best = None
    for k in range(3):
        r = least_squares(golden_resid, np.random.default_rng(k).normal(0, 0.3, 12),
                          args=(Tgb, Ttc), method="lm", max_nfev=500)
        if best is None or r.cost < best.cost:
            best = r
    ref_rms = math.sqrt(2.0 * best.cost / (6 * len(Tgb)))
    res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, leave_one_out=False)
    note(res)
    check(ref_rms < 1e-6 and res["verdict"] == "OK" and res["order"] == "XYZ",
          "参照残差拟合真值分支同样收敛到 ~0，结论一致",
          f"参照 rms={ref_rms:.3e}；本实现 verdict={res['verdict']} order={res['order']} "
          f"rms={fnum(res['rms'])}")
    check(isinstance(res["rms"], float) and abs(ref_rms - res["rms"]) < 1e-6,
          "两条内核给出同一 rms（差 <1e-6）",
          f"|Δ|={fnum(abs(ref_rms - res['rms']) if isinstance(res['rms'], float) else None)}")

print("=" * 78)
print("[1] A11-1 正例：12 个 Tait-Bryan 真值逐一注入 → 必须唯一挑出真值")
hits = 0
for conv in od.CANDIDATE_ORDERS:
    xyz, abc, Ttc = OC.build(5, conv=conv, seed=23)
    res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                          leave_one_out=False)
    note(res)
    passed = [r["key"] for r in res["ranking"] if r["pass"]]
    ok = (res["verdict"] == "OK" and res["order"] == conv
          and res["angle_unit"] == "deg" and passed == [f"{conv}/deg"]
          and len(res["ranking"]) == len(od.CANDIDATE_BRANCHES))
    hits += 1 if ok else 0
    runner = res["ranking"][1]["resid"]
    print(f"  [{'OK  ' if ok else 'FAIL'}] 真值 {conv:4s} → order={res['order']} "
          f"rms={fnum(res['rms'])} 通过={passed} 次佳={fnum(runner, '.3f')}"
          f"（{fnum((runner / res['rms']) if res['rms'] else None, '.3g')}×）")
check(hits == len(od.CANDIDATE_ORDERS),
      "12/12 真值唯一通过（其余候选全部超阈）", f"{hits}/{len(od.CANDIDATE_ORDERS)}")

print("=" * 78)
print("[2] A11-2 位数下限")
for n in (3, 4, 5):
    xyz, abc, Ttc = OC.build(n, seed=13)
    res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                          leave_one_out=False)
    note(res)
    check(res["verdict"] == "OK" and res["order"] == "XYZ"
          and sum(1 for r in res["ranking"] if r["pass"]) == 1,
          f"n={n} 一般位姿 → 唯一通过真值", f"rms={fnum(res['rms'])}")
xyz2, abc2, Ttc2 = OC.build(2, seed=13)
res = od.detect_order(xyz2, abc2, Ttc2, unit="mm", n_starts=1, leave_one_out=False)
note(res)
check(res["verdict"] == "INSUFFICIENT" and any("2 < 硬下限 3" in s for s in res["notes"]),
      "n=2 → 拒绝执行（不给答案）", f"{res['verdict']} | {res['notes']}")
res = od.detect_order(np.zeros((0, 3)), np.zeros((0, 3)), [], unit="mm",
                      leave_one_out=False)
note(res)
check(res["verdict"] == "INVALID" and any("列表为空" in s for s in res["notes"]),
      "空表 → INVALID（输入不可用，与 INSUFFICIENT 分开）", f"{res['notes']}")

print("=" * 78)
print("[3] A11-3 退化激励必须报多解（不许给答案）")
xyz, abc, Ttc = OC.build(8, seed=5, mode="zonly")
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, leave_one_out=False)
note(res)
check(res["verdict"] == "INSUFFICIENT" and res["order"] is None
      and any("只绕单轴" in s for s in res["notes"])
      and any("夹角 ≥5°" in s for s in res["notes"]),
      "纯 Z 单轴 8 位姿 → INSUFFICIENT 且只说'补什么方向'", f"{res['notes'][:2]}")
check(not res["ranking"], "激励不足时不出排名表（不出任何候选，防'猜一个最像的'）")
xyz, abc, Ttc = OC.build(8, seed=5, mode="zsmallY")
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
check(res["verdict"] == "OK" and res["order"] == "XYZ",
      "加上 ±6° 第二轴激励 → 回到唯一通过", f"rms={fnum(res['rms'])}")
# ±vec(R) 符号坑定点靶点（@verify 复核用）：AX=ZB 的 SVD 零空间是整条直线 span(vec(R))，
# 解可能是 +vec(R) 或 −vec(R) —— 对 −R 直接做 SO(3) 投影得到的是**错旋转**。n=3 seed=2
# 这一例在无符号修正时真值分支不收敛、错误约定 ZXY 反而夺冠（MULTI + champion rms≈14.8）；
# 有修正 → OK/XYZ 唯一通过。把 `_axzb_init` 里 `if np.linalg.det(RZ) < 0:` 改成 `if False:`
# 必须让本行 FAIL。
xyz, abc, Ttc = OC.build(3, seed=2)
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
check(res["verdict"] == "OK" and res["order"] == "XYZ"
      and [r["key"] for r in res["ranking"] if r["pass"]] == ["XYZ/deg"],
      "±vec 符号坑定点用例（n=3 seed=2）：零空间 −R 不做修正则真值分支不收敛",
      f"verdict={res['verdict']} order={res['order']} champion={res['ranking'][0]['key']} "
      f"rms={fnum(res['ranking'][0]['resid'], '.4f')}")
for label, tmode, kw in (("平移共线", "line", "共线"), ("平移共面", "plane", "共面")):
    xyz, abc, Ttc = OC.build(8, seed=5, tmode=tmode)
    res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, leave_one_out=False)
    note(res)
    check(res["verdict"] == "INSUFFICIENT"
          and any("平移散布不足" in s and kw in s for s in res["notes"]),
          f"{label} → INSUFFICIENT（{kw}判据）", f"{res['notes'][:1]}")

print("=" * 78)
print("[4] A11-4 弱判据禁用（相对旋转角不变性不得用于定案）")
xyz, abc, Ttc = OC.build(3, seed=13)
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
passed = [r["key"] for r in res["ranking"] if r["pass"]]
check(res["verdict"] == "OK" and len(passed) == 1 and passed == ["XYZ/deg"],
      "n=3 给 1 个候选（弱判据在 n=3 会放行 6/24 个 → 行为证据：没用弱判据定案）",
      f"通过={passed}")
with open(os.path.join(CORE, "order_detect.py"), encoding="utf-8") as f:
    src = f.read()
uses = [m.start() for m in re.finditer(r"_rel_rotation_angle_deg\(", src)]
check(len(uses) == 2,
      "源码里相对旋转角只出现在 1 处定义 + 1 处调用（均在激励门禁内，无定案分支）",
      f"出现 {len(uses)} 次")
check(not any("弱判据" in ln and "pass" in ln for ln in src.splitlines()),
      "源码无'弱判据 → pass'式分支")

print("=" * 78)
print("[5] A11-5 稳定性（@lead v2.3-④ 口径：边界不给答案 + 掩码不变量）")
print("  覆盖范围如实标注：本机未找到'留一冠军自然翻转'的合成用例（@lead 已裁定不为此卡批次），")
print("  故此处断言的是 ①边界数据只出 MULTI/INSUFFICIENT ②排名表并列全部候选 ③掩码不变量。")
# --- (a) 自然边界：弱激励（绕 X ±6°）+ 现场级噪声（σ_t=1mm / σ_r=0.2°，σ 由现场声明）
#     → pass_tol = max(0.05, 3σ) = 1.0 → 恰好 1 个候选通过（真值 XYZ），但倍数差只有 ~5.4 < 10
#     → 必须判 MULTI（边界、需补数据）而不给答案。**这一条同时是 A11-③ 倍数差条件的定向
#     变异靶点**：把 gap 门关掉，同一批数据会直接给出 OK（错误答案）。
xyz, abc, Ttc = OC.build(8, seed=5, mode="axis2d", spread=6.0, noise_t_mm=1.0,
                         noise_r_deg=0.2, noise_seed=505)
res = od.detect_order(xyz, abc, Ttc, unit="mm", sigma=1.0 / 3.0, n_starts=1,
                      max_nfev=200, leave_one_out=False)
note(res)
ratio = res["gap"]["ratio"]
n_pass = sum(1 for r in res["ranking"] if r["pass"])
check(res["verdict"] == "MULTI" and res["order"] is None and n_pass == 1
      and ratio is not None and 1.0 < ratio < od.MIN_GAP,
      "自然边界（1 个通过但倍数差 < 10）→ 判边界不给答案",
      f"通过={n_pass} 冠军={res['ranking'][0]['key']} "
      f"rms={fnum(res['ranking'][0]['resid'], '.4f')} 次佳={res['ranking'][1]['key']} "
      f"倍数差={fnum(ratio, '.2f')} verdict={res['verdict']} notes={res['notes']}")
check(res["gap"]["ok"] is False and res["gap"]["min_gap"] == od.MIN_GAP == 10.0,
      "倍数差条件显形（gap.ok=False / min_gap=10）", f"{res['gap']}")
res_relaxed = od.detect_order(xyz, abc, Ttc, unit="mm", sigma=1.0 / 3.0, n_starts=1,
                              max_nfev=200, min_gap=1.0, leave_one_out=False)
note(res_relaxed)
check(res_relaxed["verdict"] == "OK" and res_relaxed["order"] == "XYZ",
      "同一批数据把倍数差放宽到 1 → 给出真值（证明该条是唯一在拦的判据）",
      f"verdict={res_relaxed['verdict']} order={res_relaxed['order']}")
check(len(res["ranking"]) == len(od.CANDIDATE_BRANCHES),
      "边界时排名表仍并列全部候选", f"{len(res['ranking'])} 个")
check(not any(isinstance(r["resid"], float) and math.isnan(r["resid"])
              for r in res["ranking"]), "排名表无 NaN（缺失填 None）")
# --- (b) 另一种边界形态：两个约定同时落在阈内（pass_tol 取到次佳 rms 之上）
xyz, abc, Ttc = OC.build(6, seed=31, mode="zsmallY")
base = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                       leave_one_out=False)
second = base["ranking"][1]["resid"]
tol_tight = second * 1.01
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      pass_tol=tol_tight, leave_one_out=True)
note(res)
n_pass = sum(1 for r in res["ranking"] if r["pass"])
check(res["verdict"] == "MULTI" and res["order"] is None and n_pass >= 2,
      "边界（两个约定同时落在阈内）→ 不给唯一答案",
      f"pass_tol={tol_tight:.4f} 通过={n_pass} verdict={res['verdict']} "
      f"并列={[r['key'] for r in res['ranking'] if r['pass']]}")
res2 = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                       leave_one_out=True)
note(res2)
check(res2["verdict"] == "OK" and res2["leave_one_out"]["stable"] is True,
      "同一批数据用默认倍数差 → OK 且留一冠军不变",
      f"gap={fnum(res2['gap']['ratio'], '.3g')} loo={res2['leave_one_out']}")
inv_bad = []
for n, mode, seed in ((5, "general", 2), (5, "zsmallY", 7), (6, "axis2d", 3)):
    xyz, abc, Ttc = OC.build(n, seed=seed, mode=mode)
    r = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                        leave_one_out=True)
    note(r)
    if r["leave_one_out"]["stable"] is False and r["verdict"] == "OK":
        inv_bad.append(f"n={n}/{mode}/seed={seed}")
check(not inv_bad, "掩码不变量：冠军变化必须伴随结论降级（无'翻转但仍 OK'）",
      f"违例={inv_bad or '无'}")

print("=" * 78)
print("[6] A11-6 单位先行：排名必须与单位声明无关")
xyz, abc, Ttc = OC.build(6, seed=19)
r_mm = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                       leave_one_out=False)
r_m = od.detect_order(xyz / 1000.0, abc, Ttc, unit="m", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(r_mm)
note(r_m)
keys_mm = [(r["key"], fnum(r["resid"], ".9e")) for r in r_mm["ranking"]]
keys_m = [(r["key"], fnum(r["resid"], ".9e")) for r in r_m["ranking"]]
check(keys_mm == keys_m and r_mm["order"] == r_m["order"] == "XYZ",
      "同批数据 mm / m 两种声明 → 排名逐位一致、结论一致",
      f"前 3：{keys_mm[:3]}")
res = od.detect_order(xyz / 1000.0, abc, Ttc, unit="mm", n_starts=1,
                      leave_one_out=False)
note(res)
check(res["verdict"] == "INVALID" and any("米制位姿被当毫米读入" in s for s in res["notes"]),
      "米制数值标成 mm → A2 范数窗口直接拒（静默错 1000× 的老坑）", f"{res['notes'][:1]}")

print("=" * 78)
print("[7] R19 候选基数公式 / PE 诊断分支 / rad 单位分支 / R25 平移判据按维数")
card = od.candidate_cardinality()
check(card["decided_orders"] == len(od.CANDIDATE_ORDERS) == 12
      and card["decided_branches"] == len(od.CANDIDATE_BRANCHES) == 24
      and card["pe_orders"] == len(od.DIAGNOSTIC_PE_ORDERS) == 12
      and card["pe_branches"] == len(od.DIAGNOSTIC_PE_BRANCHES) == 24,
      "基数公式（3! × 旋向2 × 单位2）== 实际条数", f"{card}")
check(len(set(od.CANDIDATE_ORDERS) | set(od.DIAGNOSTIC_PE_ORDERS)) == 24
      and not (set(od.CANDIDATE_ORDERS) & set(od.DIAGNOSTIC_PE_ORDERS)),
      "定案候选（TB 12）与诊断候选（PE 12）不混集、并集 24",
      f"TB∩PE={set(od.CANDIDATE_ORDERS) & set(od.DIAGNOSTIC_PE_ORDERS)}")
xyz, abc, Ttc = OC.build(8, conv="XYX", seed=17)
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
check(res["verdict"] == "MULTI" and res["order"] is None
      and sum(1 for r in res["ranking"] if r["pass"]) == 0,
      "真值 = proper Euler → 定案候选 0 通过（fail-closed，不给错答案）",
      f"verdict={res['verdict']}")
check(res["pe_diagnostic"] is not None
      and res["pe_diagnostic"]["best"].upper().startswith("XYX")
      and any("像重复轴约定" in s for s in res["notes"]),
      "PE 诊断分支命中并只提示'需人工确认'（不进定案）",
      f"{res['pe_diagnostic']}")
xyz, abc, Ttc = OC.build(8, conv="xyz", unit="rad", seed=17)
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
check(res["verdict"] == "OK" and res["order"] == "xyz" and res["angle_unit"] == "rad",
      "rad 制数据 → 单位分支识别出 xyz/rad（唯一通过）", f"rms={fnum(res['rms'])}")
xyz, abc, Ttc = OC.build(6, seed=19)
res = od.detect_order(np.vstack([xyz, xyz[:2]]), np.vstack([abc, abc[:2]]),
                      Ttc + Ttc[:2], unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
check(res["verdict"] == "OK"
      and res["excitation"]["n_distinct_rotations"] == 6
      and res["n_records"] == 8,
      "逐位相同的重复位姿按去重后条数计（8 条 → 6 条不同旋转）",
      f"去重={res['excitation']['n_distinct_rotations']}/{res['n_records']}")
xyz, abc, Ttc = OC.build(3, seed=13)
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False)
note(res)
exc = res["excitation"]
check(res["verdict"] == "OK" and exc["ok"]
      and exc["translation_degenerate"] is False
      and exc["translation_degeneracy_check"] == "无"
      and exc["translation_check"].startswith("共线判据")
      and exc["translation_sv_mm"][1] > 5.0,
      "R25：n=3 只查共线（第 2 奇异值），不被'共面'判死",
      f"判据项={exc['translation_pca_min_sv_mm']:.1f} mm sv={[round(v, 1) for v in exc['translation_sv_mm']]}")

print("=" * 78)
print("[8] R24 引擎参数化 / 排名表字段 / verdict 枚举 / A11-④ 输出口径")
res = od.detect_order(xyz, abc, Ttc, unit="mm", n_starts=1, max_nfev=200,
                      leave_one_out=False, sigma=0.111)
note(res)
top_keys = {"verdict", "order", "angle_unit", "rms", "pass_tol", "sigma", "engine",
            "criterion_level", "n_records", "n_effective", "row_idx", "dropped_idx",
            "xyz_rxryrz", "T_handeye_mm", "T_target2base_mm", "ranking", "gap",
            "excitation", "leave_one_out", "notes", "pe_diagnostic"}
check(top_keys <= set(res.keys()), "排名表/结果结构含 R24 全部字段",
      f"缺={sorted(top_keys - set(res.keys())) or '无'}")
row = res["ranking"][0]
check(set(row.keys()) == RANK_ROW_KEYS, "排名行字段冻结（两引擎共用，缺失填 None）",
      f"差={sorted(set(row.keys()) ^ RANK_ROW_KEYS)}")
check(res["engine"] == "fit" and row["n_kept"] is None and row["tme"] is None
      and row["baseline_diff"] is None,
      "fit 引擎缺的字段恒为 None（不臆造数值）",
      f"n_kept={row['n_kept']} tme={row['tme']} baseline_diff={row['baseline_diff']}")
check(abs(res["pass_tol"] - max(0.05, 3 * 0.111)) < 1e-12,
      "σ 给了就用 pass_tol = max(0.05, 3σ)（阈值是噪声底不是魔数）",
      f"pass_tol={res['pass_tol']:.4f} σ={res['sigma']}")
for bad, kw in (("sdk", "未接线"), ("bogus", "engine 必须是")):
    try:
        od.detect_order(xyz, abc, Ttc, unit="mm", engine=bad)
        err = ""
    except od.OrderDetectError as e:
        err = str(e)
    check(kw in err, f"engine={bad!r} → 报错（sdk 不静默退回 fit）", err[:70])
check(VERDICT_SEEN <= VERDICT_ENUM and VERDICT_SEEN >= {"OK", "MULTI", "INSUFFICIENT",
                                                        "INVALID"},
      "verdict 取值恰为冻结四值 OK/MULTI/INSUFFICIENT/INVALID",
      f"实际出现 {sorted(VERDICT_SEEN)}")
T = np.asarray(res["T_handeye_mm"], dtype=np.float64)
vals = od.to_xyz_rxryrz(T, "XYZ", unit="mm")
Rb = Rot.from_euler("XYZ", vals[3:6], degrees=True).as_matrix()
check(np.allclose(Rb, T[:3, :3], atol=1e-12)
      and np.allclose(vals[:3], T[:3, 3], atol=1e-12),
      "A11-④ to_xyz_rxryrz 往返一致（xyz mm + Rx Ry Rz 度）", f"{od.format_xyz_rxryrz(vals)[:60]}…")
check(len(od.format_xyz_rxryrz(vals).split()) == 6
      and "." in od.format_xyz_rxryrz(vals), "输出全精度（repr 级，6 个数一行）")
vals_m = od.to_xyz_rxryrz(T, "XYZ", unit="m")
check(abs(vals_m[0] - vals[0] / 1000.0) < 1e-15, "unit='m' 时平移按米输出")
try:
    od.to_xyz_rxryrz(T, "XYZ_RPY")
    err = ""
except od.OrderDetectError as e:
    err = str(e)
check("不支持的欧拉顺序" in err, "未知顺序 → 报错（不静默换口径）", err)

print("=" * 78)
print("[11] golden 交叉校验：min_poses.py 与 full_handeye.py 互为印证（引用，不复制）")
GOLDEN_MP, mp_desc = load_golden_head("min_poses.py")
check(GOLDEN_MP is not None, "min_poses.py 可加载（golden，缺失即 FAIL）", mp_desc)
if GOLDEN_MP is not None:
    mp_names = {s.lower() for s in GOLDEN_MP["SEQS"]}
    od_names = {s.lower() for s in od.CANDIDATE_ORDERS}
    check(len(GOLDEN_MP["SEQS"]) == len(od.CANDIDATE_ORDERS) == 12
          and mp_names == od_names and len(mp_names) == 6,
          "golden 的 12 个候选 = 本内核 CANDIDATE_ORDERS（6 个轴序名 × 内外旋两支）",
          f"golden={sorted(GOLDEN_MP['SEQS'])} 本内核={sorted(od.CANDIDATE_ORDERS)}")
    if golden_resid is not None:
        xyz, abc, Ttc = OC.build(5, seed=41)
        Tgb_g = [od.branch_matrix(od.Branch("XYZ", "deg"), xyz[i], abc[i]) for i in range(5)]
        worst_gg = 0.0
        for k in range(4):
            p = np.random.default_rng(700 + k).normal(0.0, 30.0, 12)
            a = np.asarray(golden_resid(p, Tgb_g, Ttc), dtype=float)
            b = np.asarray(GOLDEN_MP["resid"](p, Tgb_g, Ttc), dtype=float)
            worst_gg = max(worst_gg, float(np.max(np.abs(a - b))))
        check(worst_gg < 1e-12, "两个 golden 内核互相逐元素一致（同一 p 同残差）",
              f"max|Δ|={worst_gg:.3e}")
    print("  [NOTE] 口径对照（**未在测试内执行 golden 全量 sweep**，实测单例 27.1 s 代价不进测试）：")
    print("         min_poses 的纯拟合口径（无激励门）在 n=2 上是**数据相关**的 —— 它自己的数据 1/12，")
    print("         本机另取一批 n=2 数据（seed=13）实测 **0/12**；本内核按 A11-2 硬下限 n<3 直接")
    print("         INSUFFICIENT。两者都不给答案，本内核更严（RG-16 记此口径差异）。")

print("=" * 78)
if FAILURES:
    print(f"[FAIL] test_order_detect：{len(FAILURES)} 项失败 -> {FAILURES}")
    sys.exit(1)
print("[ALL OK] test_order_detect")
