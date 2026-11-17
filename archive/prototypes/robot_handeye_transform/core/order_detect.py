# -*- coding: utf-8 -*-
"""欧拉角顺序自动判定（order_detect）—— A11-③。

候选全枚举 + 完整 6DOF 手眼最小二乘拟合 + **全候选残差排名表**。

口径来源：`docs/机器人手眼变换原型_补充方案_矩阵落文件与欧拉顺序自动判定_20260923.md`
v2.2 §1（判据细则 5 条）、§10.5-②（候选集基数公式）、§10.6（真实数据 sweep 修正）、R24。

设计要点（每条都被实测钉死，不许简化）：

1. **候选集基数公式**（R19 定案，禁止只硬编码数字）：
      轴序维数  = 3! = 6（三轴互异排列）
      旋向维数  = 2（大写 = 内旋/绕动轴，小写 = 外旋/固定轴）
      → 定案候选（序） = 6 × 2 = 12
      单位维数  = 2（deg / rad）
      → 识别分支     = 12 × 2 = 24
   proper Euler（重复轴，6 序 × 2 旋向 × 2 单位 = 24）**只作诊断分支**，不进定案：
   命中即提示"像重复轴约定，需人工确认"，不改结论。
2. **排名表必须含全部候选**（含未通过者）—— 禁止"只给一个答案"（@verify 对主方案的硬要求，
   也是与"品牌先验"划清界限的证据）。**弱判据**（相对旋转角不变性）禁止用于定案（A11-4）：
   本模块里出现的角度只服务于"能否支撑定案"的门禁，不参与候选排序。
3. **阈值分引擎且是噪声底不是魔数**：`pass_tol = max(0.05 mm, 3σ)`；σ 缺省 `None` → 0.05。
   `0.05 mm` 在 SDK 引擎里的正确含义是"**与 `poseType=0` 基线的差值**"（一级判据），
   不是绝对门限 —— 真实数据真值 `tme = 2.05 mm`，按绝对 0.05 判会把真值自己判失败（§10.6-③）。
4. **倍数差条件只用全量数据判**（§10.6-④）：留一掩码下错约定的误差会掉到真值附近
   （实测剔除 #13/#25 时 9.77× / 9.98×），若允许在掩码上判倍数差，A11 四条门禁会互相打架。
   留一检验只断言"**冠军不变**"（真实数据实测 27/27 不变）。
5. **激励质量前置校验（存在性版，R21）**：去重后不同旋转条数 ≥ 3；旋转轴集合张成 ≥ 2 维
   （**存在**一对主轴夹角 ≥ 5°，而非"任意一对 <5° 即拒"）；平移点集 PCA 最小奇异值 ≥ 5 mm。
   不满足 → `INSUFFICIENT` 并只说"缺哪个方向的激励"，**绝不"猜一个最像的"**。
6. **平移一律先归一到 mm**（A11-6）：残差是 deg 与 mm 同权的混合量纲，不归一则排名与阈值
   不可复现。
7. **引擎参数化**（R24）：`engine="fit"` 已接线；`engine="sdk"` 属批 6C —— 现在调用**直接报错**
   （fail-closed，不静默退回 fit）。两引擎共用同一排名表结构，缺失字段恒以 `null` 占位
   （`pass_tol` / `sigma` / `n_kept` / `baseline_diff`）。

verdict 取值：`OK` / `MULTI`（多解或边界，附全部候选）/ `INSUFFICIENT`（激励不足）/
`INVALID`（输入不可用于判定：记录非法、缺相机侧配对 = 纯位姿表）。后两者都是**直接拒绝**，
不给答案 —— 方案原文"纯位姿表必须直接拒绝并说明原因"与"激励不足只输出缺什么方向"即为此。
`INVALID` 是方案枚举 {OK, MULTI, INSUFFICIENT} 之外的补充取值，语义上仍属"拒绝出结论"。

拟合内核收编自 @verify 的 `full_handeye.py`（R14 spike，12 参数最小二乘 + 多起点），
残差定义按 §1 细则 1：

    E_i = inv(T_target2cam_i) @ (X @ inv(T_base2tool_i) @ T_target2base)
    resid_i = [rotvec_deg(E_i.R) (3), E_i.t (mm) (3)]
    rms = sqrt(sum(resid²) / (6·n))
"""

from __future__ import annotations

import itertools
import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

try:
    from . import unit_guard
    from .pose_source import admit_pose, euler_to_matrix
except ImportError:  # 测试以顶层模块方式引入时
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import unit_guard
    from pose_source import admit_pose, euler_to_matrix

# ----------------------------------------------------------------------
# 常量（门禁与判据）
# ----------------------------------------------------------------------
MIN_RECORDS = 3                 # A11-2 工具硬下限（与 A3 戳点门禁同为 3）
MIN_DISTINCT_ROTATIONS = 3      # R21：按去重后的不同旋转条数计，不按总条数
MIN_AXIS_SPREAD_DEG = 5.0       # R21：存在一对主轴夹角 ≥ 5°（张成 ≥2 维）
MIN_TRANSLATION_SV_MM = 5.0     # 平移点集 PCA 最小奇异值下限
MIN_GAP = 10.0                  # 全量倍数差（第一名/第二名）
SYNTHETIC_TOL = 0.05            # 合成无噪口径；有 σ 时取 max(0.05, 3σ)
BASELINE_TOL_MM = 0.05          # 一级判据：|tme(候选) − tme(poseType=0)| < 0.05
DEDUP_ROT_EPS_DEG = 1e-6        # 旋转逐位相同 → 同一条（去重判据，单位：度）
RMS_ZERO = 1e-12                # 残差视为 0 的门限（倍数差比值用）
ENGINES = ("fit", "sdk")

# ----------------------------------------------------------------------
# 候选集（R19）
# ----------------------------------------------------------------------
TB_SEQS = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")          # 三轴互异排列
PE_SEQS = ("XYX", "XZX", "YXY", "YZY", "ZXZ", "ZYZ")          # 重复轴（诊断用）
ANGLE_UNITS = ("deg", "rad")
_ROTATION_SENSE = 2     # 1 内旋（大写）+ 1 外旋（小写）


@dataclass(frozen=True)
class Branch:
    """一个候选分支 = （欧拉序，角度单位）。`order` 直接给 scipy：
    大写 = 内旋（绕动轴），小写 = 外旋（固定轴）。"""

    order: str
    angle_unit: str = "deg"

    @property
    def key(self) -> str:
        return f"{self.order}/{self.angle_unit}"

    @property
    def is_intrinsic(self) -> bool:
        return self.order.isupper()


CANDIDATE_ORDERS: Tuple[str, ...] = tuple(
    list(TB_SEQS) + [s.lower() for s in TB_SEQS])              # 12 = 6 × 2
CANDIDATE_BRANCHES: Tuple[Branch, ...] = tuple(
    Branch(o, u) for o in CANDIDATE_ORDERS for u in ANGLE_UNITS)   # 24 = 12 × 2
DIAGNOSTIC_PE_ORDERS: Tuple[str, ...] = tuple(
    list(PE_SEQS) + [s.lower() for s in PE_SEQS])              # 12 = 6 × 2
DIAGNOSTIC_PE_BRANCHES: Tuple[Branch, ...] = tuple(
    Branch(o, u) for o in DIAGNOSTIC_PE_ORDERS for u in ANGLE_UNITS)   # 24 = 12 × 2


def candidate_cardinality() -> Dict[str, int]:
    """候选集基数公式（R19）：返回各维数与乘积。

    测试必须断言实际条数 == 公式结果（禁止只硬编码一个数字 —— 否则改了候选集
    基数公式没人发现，排名表的"12 个候选"就变成假话）。
    """
    n_axis_orders = math.factorial(3)          # 6
    n_sense = _ROTATION_SENSE                  # 2
    n_units = len(ANGLE_UNITS)                 # 2
    return {
        "n_axis_orders": n_axis_orders,
        "n_rotation_sense": n_sense,
        "n_angle_units": n_units,
        "decided_orders": n_axis_orders * n_sense,                 # 12
        "decided_branches": n_axis_orders * n_sense * n_units,     # 24
        "pe_orders": n_axis_orders * n_sense,                      # 12
        "pe_branches": n_axis_orders * n_sense * n_units,          # 24
    }


class OrderDetectError(Exception):
    """程序性错误（引擎未接线、入参形状不对）—— 与"数据不可判定"区分开。"""


# ----------------------------------------------------------------------
# 4×4 / 旋转小工具
# ----------------------------------------------------------------------
def _T(R: np.ndarray, t: Sequence[float]) -> np.ndarray:
    M = np.eye(4, dtype=np.float64)
    M[:3, :3] = R
    M[:3, 3] = np.asarray(t, dtype=np.float64).reshape(3)
    return M


def _rotation(T: np.ndarray) -> np.ndarray:
    return np.asarray(T, dtype=np.float64)[:3, :3]


def _as_T4(T, label: str = "矩阵") -> np.ndarray:
    arr = np.asarray(T, dtype=np.float64)
    if arr.ndim == 1 and arr.size == 16:
        arr = arr.reshape(4, 4)
    if arr.shape != (4, 4):
        raise OrderDetectError(f"{label} 必须是 4×4 或 16 个数（行优先），实际 {np.shape(T)}")
    if not np.all(np.isfinite(arr)):
        raise OrderDetectError(f"{label} 含非有限值（NaN/Inf）")
    return arr


def _rel_rotation_angle_deg(Ra: np.ndarray, Rb: np.ndarray) -> float:
    """Ra→Rb 的相对旋转角（度）—— 仅用于去重（不参与候选排序，A11-4）。"""
    R = Ra.T @ Rb
    cos = (np.trace(R) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, float(cos)))))


# ----------------------------------------------------------------------
# 候选分支 → T_base2tool
# ----------------------------------------------------------------------
def _branch_is_pe(order: str) -> bool:
    u = order.upper()
    return u in PE_SEQS


def branch_matrix(branch: Branch, xyz_mm: Sequence[float],
                  abc_raw: Sequence[float]) -> np.ndarray:
    """按候选分支把 (mm 平移, 原始角度三值) 还原成 T_base2tool（mm 域）。

    Tait-Bryan 分支走 `pose_source.euler_to_matrix`（A2 单实现，禁第二份）：
    分支的角度单位在这里折算成度后传入 —— deg 分支直接用，rad 分支 `rad2deg`。
    proper Euler 是**诊断分支**，不在 `EULER_ORDERS` 内，用 scipy 直接构造（不进定案）。
    """
    abc = np.asarray(abc_raw, dtype=np.float64).reshape(3)
    rpy_deg = np.rad2deg(abc) if branch.angle_unit == "rad" else abc
    xyz = np.asarray(xyz_mm, dtype=np.float64).reshape(3)
    if _branch_is_pe(branch.order):
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = Rotation.from_euler(branch.order, rpy_deg, degrees=True).as_matrix()
        T[:3, 3] = xyz
        return T
    return euler_to_matrix(xyz, rpy_deg, branch.order)


# ----------------------------------------------------------------------
# 6DOF 拟合内核（收编 @verify full_handeye.py）
# ----------------------------------------------------------------------
def _residual(p: np.ndarray, Tgb_inv: np.ndarray,
              Ttc_inv: np.ndarray) -> np.ndarray:
    """残差向量：每条记录 3（度）+ 3（mm）。p = [X(rotvec3,t3), T_target2base(rotvec3,t3)]。

    `Tgb_inv` / `Ttc_inv` = (n,4,4) 的**预先求逆**数组（逐分支一次）：
      · 不放进目标函数 —— 每次评估都求逆会让"排全部候选"慢一个量级；
      · 全记录向量化 —— LM 的数值雅可比要评估 12+1 次残差，逐记录 Python 循环
        把一次判定从秒级拖到分钟级（实测 n=8 全程 175 s → 向量化后 < 10 s）。
    """
    X = _T(Rotation.from_rotvec(p[:3]).as_matrix(), p[3:6])
    T_t2b = _T(Rotation.from_rotvec(p[6:9]).as_matrix(), p[9:12])
    E = np.matmul(Ttc_inv, np.matmul(X, np.matmul(Tgb_inv, T_t2b)))   # (n,4,4)
    rot = Rotation.from_matrix(E[:, :3, :3]).as_rotvec(degrees=True)
    return np.concatenate([rot, E[:, :3, 3]], axis=1).ravel()


def _axzb_init(Tgb_inv: np.ndarray, Ttc: np.ndarray) -> Optional[np.ndarray]:
    """闭式初值：AX = ZB 的 SVD 零空间（旋转）+ 线性最小二乘（平移）。

    模型是 `B_i = X · A_i · Z`（A_i = inv(T_base2tool_i)=Tgb_inv[i]，B_i = T_target2cam_i，
    Z = T_target2base）。取相对运动 A' = A_i⁻¹A_j、B' = B_i⁻¹B_j 得经典 `A' Z = Z B'`：
        R_A' R_Z = R_Z R_B'   →   [I⊗R_A' − R_B'ᵀ⊗I] vec(R_Z) = 0（堆叠 → SVD 零空间）
        (R_A' − I) t_Z = R_Z t_B' − t_A'          （堆叠 → 线性最小二乘）
    再由 `X = B_0 Z⁻¹ A_0⁻¹` 回代出手眼 X。

    **为什么需要它**：随机起点全部落在同一个（错的）盆地 —— `[V-spike]` 的 3~4 起点在
    n=3~5 的一般位姿上会把**真值分支**也停在 rms 8~80 的局部极小（实测 ns=1..6 都救不回
    某些 seed），于是判成"0 个候选通过"。闭式初值让真值分支确定性地收敛到 ~0。
    随机起点保留作兜底（噪声/非刚性数据上闭式解可能不够准）。
    """
    n = int(Tgb_inv.shape[0])
    if n < 3:
        return None
    A = Tgb_inv                       # A_i = inv(T_base2tool_i)
    B = np.asarray(Ttc, dtype=np.float64)
    A0_inv = np.linalg.inv(A[0])
    B0 = B[0]
    M_rows = []
    rel = []
    for j in range(1, n):
        Ap = A0_inv @ A[j]                       # A' = A_0⁻¹ A_j
        Bp = np.linalg.inv(B[0]) @ B[j]          # B' = B_0⁻¹ B_j
        # [I⊗R_A' − R_B'ᵀ⊗I] vec(R_Z) = 0  →  堆叠成 (3(n−1), 9)
        M_rows.append(np.kron(np.eye(3), Ap[:3, :3]) -
                      np.kron(Bp[:3, :3].T, np.eye(3)))
        rel.append((Ap, Bp))
    try:
        M = np.vstack(M_rows)
        _, _, Vt = np.linalg.svd(M)
        RZ = Vt[-1].reshape(3, 3, order="F")
        # 零空间是**整条直线** span(vec(R))：解可能是 +vec(R) 也可能是 −vec(R)。
        # 若直接对 −R 做 SO(3) 投影，得到的是"离 −R 最近的合法旋转"（≠ R，实测错解）——
        # 必须先按 det 定符号（−(−R)=R，det(R)=+1），再做投影去数值噪声。
        if np.linalg.det(RZ) < 0:
            RZ = -RZ
        U, _, Vt2 = np.linalg.svd(RZ)
        RZ = U @ np.diag([1.0, 1.0, float(np.sign(np.linalg.det(U @ Vt2)))]) @ Vt2
        # 平移： (R_A' − I) t_Z = R_Z t_B' − t_A'
        H = np.vstack([Ap[:3, :3] - np.eye(3) for Ap, _ in rel])
        y = np.concatenate([RZ @ Bp[:3, 3] - Ap[:3, 3] for Ap, Bp in rel])
        tZ, *_ = np.linalg.lstsq(H, y, rcond=None)
        Z = np.eye(4)
        Z[:3, :3] = RZ
        Z[:3, 3] = tZ
        Xin = B0 @ np.linalg.inv(Z) @ A0_inv
        RX = Xin[:3, :3]
        if not np.all(np.isfinite(Xin)):
            return None
        return np.concatenate([Rotation.from_matrix(RX).as_rotvec(), Xin[:3, 3],
                               Rotation.from_matrix(RZ).as_rotvec(), tZ])
    except (np.linalg.LinAlgError, ValueError):
        return None


def _fit_one(Tgb_inv: np.ndarray, Ttc: np.ndarray, Ttc_inv: np.ndarray, *,
             n_starts: int, seed: int, max_nfev: int) -> Tuple[float, np.ndarray]:
    """闭式初值 + 多起点 LM 兜底，返回 (rms, p_best)。rms 定义见模块 docstring。"""
    n_res = 6 * int(Tgb_inv.shape[0])
    starts: List[np.ndarray] = []
    p0 = _axzb_init(Tgb_inv, Ttc)
    if p0 is not None:
        starts.append(p0)
    for k in range(max(1, n_starts)):
        starts.append(np.random.default_rng(seed + k).normal(0.0, 0.3, 12))
    best_cost: Optional[float] = None
    best_x: Optional[np.ndarray] = None
    for r0 in starts:
        try:
            r = least_squares(_residual, r0, args=(Tgb_inv, Ttc_inv), method="lm",
                              max_nfev=max_nfev)
        except Exception:       # noqa: BLE001 —— LM 不收敛就换下一个起点，不许把异常透给 UI
            continue
        if best_cost is None or r.cost < best_cost:
            best_cost, best_x = float(r.cost), np.asarray(r.x, dtype=np.float64)
    if best_cost is None or best_x is None:
        return float("inf"), np.zeros(12)
    return math.sqrt(2.0 * best_cost / n_res), best_x


def _rank_branches(branches: Sequence[Branch], xyz_mm: np.ndarray, abc: np.ndarray,
                   Ttc_mm: List[np.ndarray], *, n_starts: int, seed: int,
                   max_nfev: int) -> List[Dict[str, Any]]:
    """对给定分支集合排全部候选（不做任何定案，供主判定与留一检验共用）。"""
    Ttc_inv = np.asarray([np.linalg.inv(np.asarray(T, dtype=np.float64))
                          for T in Ttc_mm], dtype=np.float64)
    rows: List[Dict[str, Any]] = []
    for br in branches:
        try:
            Tgb = [branch_matrix(br, xyz_mm[i], abc[i]) for i in range(len(abc))]
            Tgb_inv = np.asarray([np.linalg.inv(T) for T in Tgb], dtype=np.float64)
        except Exception as e:      # noqa: BLE001 —— 单分支构造失败不影响其余候选
            rows.append({"key": br.key, "order": br.order, "angle_unit": br.angle_unit,
                         "resid": None, "pass": False, "n_kept": None,
                         "tme": None, "baseline_diff": None,
                         "note": f"该分支位姿构造失败：{e}"})
            continue
        rms, p = _fit_one(Tgb_inv, np.asarray(Ttc_mm, dtype=np.float64), Ttc_inv,
                          n_starts=n_starts, seed=seed, max_nfev=max_nfev)
        rows.append({
            "key": br.key, "order": br.order, "angle_unit": br.angle_unit,
            "resid": rms, "pass": False,          # pass 由阈值阶段填
            "n_kept": None,                       # 拟合引擎不丢组；SDK 引擎填保留组数
            "tme": None, "baseline_diff": None,
            "x_rotvec_t": [float(v) for v in p[:6]],
            "tt2b_rotvec_t": [float(v) for v in p[6:12]],
            "note": "",
        })
    rows.sort(key=lambda r: (r["resid"] is None, r["resid"] if r["resid"] is not None
                             else float("inf")))
    return rows


def _gap_ratio(r1: Optional[float], r2: Optional[float]) -> Optional[float]:
    """全量倍数差（第一名/第二名）。两个都 ≈0 → 1.0（无分辨力，不给 inf 假象）。"""
    if r1 is None or r2 is None:
        return None
    if r2 <= RMS_ZERO:
        return 1.0
    if r1 <= RMS_ZERO:
        return float("inf")
    return r2 / r1


# ----------------------------------------------------------------------
# 激励质量前置校验（A11-③ 前置硬条款，存在性版 R21）
# ----------------------------------------------------------------------
def _excitation_metrics(Tgb: List[np.ndarray]) -> Dict[str, Any]:
    """在给定 T_base2tool 序列上算激励质量（与候选排序无关）。

    平移散布按**维数**判，不按字面"最小奇异值"判：n 条记录的中心化点集最多张成
    n-1 维，n=3 时第三奇异值**必然** ≈0（方案原文按字面读会把所有 n=3 数据集判死，
    与 A11-2 "n=3/4/5 均唯一通过"自相矛盾）。故：
      n < 4 → 只查**共线**（第 2 奇异值 ≥ 5 mm）
      n ≥ 4 → 查**共面**（第 3 奇异值 ≥ 5 mm）
    真实数据集（n=27）实测最小奇异值 50.0 mm，两种读法一致。
    """
    n = len(Tgb)
    distinct: List[np.ndarray] = []
    for T in Tgb:
        R = _rotation(T)
        if not any(_rel_rotation_angle_deg(R0, R) < DEDUP_ROT_EPS_DEG for R0 in distinct):
            distinct.append(R)
    n_distinct = len(distinct)

    axes: List[np.ndarray] = []
    if n:
        R0 = _rotation(Tgb[0])
        for T in Tgb:
            rv = Rotation.from_matrix(R0.T @ _rotation(T)).as_rotvec()
            ang = float(np.linalg.norm(rv))
            if ang > 1e-9:
                axes.append(rv / ang)
    max_pair = 0.0
    for a, b in itertools.combinations(axes, 2):
        c = abs(float(np.dot(a, b)))        # 轴的正负无意义 → 取 |cos|
        max_pair = max(max_pair, math.degrees(math.acos(max(-1.0, min(1.0, c)))))

    t = np.array([np.asarray(T, dtype=np.float64)[:3, 3] for T in Tgb], dtype=np.float64)
    if len(t) >= 2:
        sv = list(np.linalg.svd(t - t.mean(axis=0), compute_uv=False))
    else:
        sv = []
    sv = [float(v) for v in sv] + [0.0] * (3 - len(sv))
    linear_deg = sv[1] < MIN_TRANSLATION_SV_MM
    planar_deg = n >= 4 and sv[2] < MIN_TRANSLATION_SV_MM
    translation_degenerate = bool(linear_deg or planar_deg)
    if linear_deg:
        degenerate_fit = "共线（点集退化成一条线）"
    elif planar_deg:
        degenerate_fit = "共面（点集落在一个平面上）"
    else:
        degenerate_fit = ""
    # R25：判据按**维数**选 —— n 条记录的中心化点集最多张成 n−1 维，n=3 时第三奇异值
    # 必然 ≈0，按字面"最小奇异值"读会把所有 n=3 数据集判死（与 A11-2 打架）。
    translation_check = ("共线判据（n<4：只查是否退化成一条线）" if n < 4
                         else "共面判据（n≥4：查是否落在一个平面上）")
    t_min = sv[1] if n < 4 else sv[2]

    reasons: List[str] = []
    hints: List[str] = []
    if n_distinct < MIN_DISTINCT_ROTATIONS:
        reasons.append(f"去重后不同旋转条数 {n_distinct} < {MIN_DISTINCT_ROTATIONS}")
        hints.append("补：至少 3 条**旋转互不相同**的位姿（逐位相同的重复位姿对顺序判定零贡献）")
    if max_pair < MIN_AXIS_SPREAD_DEG:
        reasons.append(f"旋转轴集合张成 <2 维（主轴两两最大夹角 {max_pair:.3f}° "
                       f"< {MIN_AXIS_SPREAD_DEG}°）→ 只绕单轴")
        hints.append("补：与当前旋转轴夹角 ≥5° 的另一个旋转方向的位姿（只绕单轴的激励多解，"
                     "实测纯 Z 轴 8 位姿有 4/12 个约定同时拟合通过）")
    if degenerate_fit:
        reasons.append(f"平移散布不足（{degenerate_fit}：奇异值 {[round(v, 3) for v in sv]} "
                       f"mm，判据项 {t_min:.3f} mm < {MIN_TRANSLATION_SV_MM} mm）")
        hints.append("补：平移不要都在一条线/一个平面上（换机位或改变末端姿态带动位置散布）")
    return {
        "ok": not reasons,
        "n_records": n,
        "n_distinct_rotations": n_distinct,
        "axis_max_pair_angle_deg": max_pair,
        "translation_sv_mm": sv,
        "translation_pca_min_sv_mm": t_min,
        "translation_check": translation_check,
        "translation_degenerate": translation_degenerate,
        "translation_degeneracy_check": degenerate_fit or "无",
        "reasons": reasons,
        "hints": hints,
    }


def excitation_report(xyz_mm: np.ndarray, abc: np.ndarray) -> Dict[str, Any]:
    """激励质量前置校验（对全部候选分支取**最宽松**结论）。

    为什么对分支取最宽松：这些指标依赖"欧拉序"才能还原出旋转，而欧拉序正是未知量。
    逐分支算一遍（不做拟合，成本极低），只要**存在**一个分支认为激励充足就继续往下判
    （真正的安全网是排名表的"通过数 != 1 → MULTI"）；**全部**分支都说不足才判
    `INSUFFICIENT`（fail-closed：不给答案）。报告里给出各分支计数与冠军分支的明细。
    """
    xyz_mm = np.asarray(xyz_mm, dtype=np.float64).reshape(-1, 3)
    abc = np.asarray(abc, dtype=np.float64).reshape(-1, 3)
    per_branch: Dict[str, Dict[str, Any]] = {}
    ok_branches: List[str] = []
    for br in CANDIDATE_BRANCHES:
        try:
            Tgb = [branch_matrix(br, xyz_mm[i], abc[i]) for i in range(len(abc))]
        except Exception:       # noqa: BLE001
            continue
        m = _excitation_metrics(Tgb)
        per_branch[br.key] = m
        if m["ok"]:
            ok_branches.append(br.key)
    if not per_branch:
        return {"ok": False, "n_records": len(abc), "n_distinct_rotations": 0,
                "axis_max_pair_angle_deg": 0.0, "translation_pca_min_sv_mm": 0.0,
                "reasons": ["全部候选分支的位姿构造都失败（原始数值不可用）"],
                "hints": ["补：检查位姿行的数值与单位声明"],
                "n_branches_ok": 0, "n_branches": 0, "ok_branches": [],
                "per_branch": per_branch}
    ref = per_branch[sorted(per_branch.keys())[0]]
    out = {"ok": bool(ok_branches),
           "n_records": ref["n_records"],
           "n_distinct_rotations": ref["n_distinct_rotations"],
           "axis_max_pair_angle_deg": ref["axis_max_pair_angle_deg"],
           "translation_pca_min_sv_mm": ref["translation_pca_min_sv_mm"],
           "reasons": [] if ok_branches else ref["reasons"],
           "hints": [] if ok_branches else ref["hints"],
           "n_branches_ok": len(ok_branches), "n_branches": len(per_branch),
           "ok_branches": ok_branches, "per_branch": per_branch,
           "translation_sv_mm": ref.get("translation_sv_mm"),
           "translation_check": ref.get("translation_check"),
           "translation_degenerate": ref.get("translation_degenerate"),
           "translation_degeneracy_check": ref.get("translation_degeneracy_check")}
    return out


# ----------------------------------------------------------------------
# 输出口径（A11-④ 唯一实现）
# ----------------------------------------------------------------------
def to_xyz_rxryrz(T, order: str, unit: str = "mm") -> Tuple[float, ...]:
    """4×4 → `(x, y, z, Rx, Ry, Rz)`（全精度）。

    `xyz` 单位按 `unit`（"mm" | "m"）；`Rx Ry Rz` 按判定出的 `order` 换算、**单位度**。
    """
    if order not in CANDIDATE_ORDERS and order not in DIAGNOSTIC_PE_ORDERS:
        raise OrderDetectError(f"不支持的欧拉顺序 {order!r}")
    u = unit_guard.normalize_unit(unit)
    M = _as_T4(T, "位姿矩阵")
    t = M[:3, 3] if u == "mm" else M[:3, 3] / 1000.0
    e = Rotation.from_matrix(M[:3, :3]).as_euler(order, degrees=True)
    return tuple(float(v) for v in list(t) + list(e))


def format_xyz_rxryrz(values: Sequence[float]) -> str:
    """A11-④ 要求全精度（`repr` 级）—— 6 个数一行文本，供 UI/日志直出。"""
    return " ".join(repr(float(v)) for v in values)


# ----------------------------------------------------------------------
# SDK 引擎（批 6C 接线；现在 fail-closed）
# ----------------------------------------------------------------------
def _rank_branches_sdk(*_args, **_kwargs) -> List[Dict[str, Any]]:
    raise OrderDetectError(
        "engine='sdk' 尚未接线（批 6C）：SDK 路径需要 png/ply 成对落盘 + poseType=3 位姿文件，"
        "调用参数固定 poseType=3 / markerType=0 / isPointCloudMm=false / isPoseMm=true / "
        "isEyeInHand=false / autoRemoveLargeErrorData=false（厂商默认 true 会让排名失效）。"
        "本轮不静默退回 engine='fit' —— 请显式传 engine='fit'。")


# ----------------------------------------------------------------------
# 主判定
# ----------------------------------------------------------------------
def detect_order(xyz, abc, Ttc_mm, *, unit: str = "mm", ttc_unit: str = "mm",
                 engine: str = "fit", pass_tol: Optional[float] = None,
                 sigma: Optional[float] = None, min_gap: float = MIN_GAP,
                 n_starts: int = 3, seed: int = 0, max_nfev: int = 500,
                 leave_one_out: bool = True, loo_n_starts: Optional[int] = None,
                 baseline_tme: Optional[float] = None,
                 row_idx: Optional[Sequence[int]] = None,
                 pe_diagnostic: bool = True,
                 dropped_idx: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """候选全枚举 → 激励前置校验 → 6DOF 拟合排名 → 定案四条件 → 留一检验。

    Args:
        xyz: 机器人拍照位姿的平移原文，形状 (n, 3)，单位由 `unit` 声明（A11-6 先归一 mm）。
        abc: 机器人拍照位姿的角度原文，(n, 3)。**角度单位是未知量**（deg/rad 属候选分支），
             按原样传入即可。
        Ttc_mm: 相机侧目标位姿 `T_target2cam`（成对观测，§10.1），4×4（mm）列表；
                **缺相机侧数据 = 纯位姿表 → 拒绝**（12 个约定各自自洽，数学上不可判定）。
        unit: `xyz` 的长度单位（"mm" | "m"），经 A2 入口归一。
        ttc_unit: `Ttc_mm` 的长度单位（默认 mm，走同一个 `unit_guard.to_mm`）。
        engine: "fit"（自研拟合，已接线）| "sdk"（批 6C）。
        pass_tol: 二级判据阈值；缺省 `max(0.05, 3σ)`（σ 给了就用 σ）。
        sigma: 真值分支上的噪声底 σ（留一/子集重采样，B ≥ 10）。
        min_gap: 全量倍数差下限（第一名/第二名）。
        n_starts: 每个候选的 LM 起点数（`[V-spike]` 用 3~4）。
        max_nfev: 单个候选 LM 的评估上限。**早停只会让错候选看起来更差**（LM 单调降代价），
                  不会造成假通过；真值分支几十次迭代即收敛（实测 rms < 1e-6）。默认 500 是
                  速度取舍，`test_order_detect` 里有一致性断言（500 与 2000 排名相同）。
        loo_n_starts: 留一检验时的起点数（缺省沿用 `n_starts`）。
        baseline_tme: SDK 引擎的 `poseType=0` 基线 `totalMeanError`（一级判据用）。
        row_idx: 每条记录在数据列表里的**行号**（A11-② 结论必须指回行号）。
        pe_diagnostic: 主候选全灭时是否跑 proper Euler 诊断分支。
        dropped_idx: 已被剔除、未参与本次判定的行号（R22：剔除必须落盘可见）。

    Returns:
        dict（两引擎共用结构；fit 引擎缺的字段恒为 `None`）::

            {verdict, order, angle_unit, rms, pass_tol, sigma, engine, criterion_level,
             n_records, n_effective, row_idx, dropped_idx, xyz_rxryrz, T_handeye_mm,
             T_target2base_mm, ranking:[{key, order, angle_unit, resid, pass, n_kept,
             tme, baseline_diff, note}...], gap:{ratio, min_gap, ok},
             excitation:{...}, leave_one_out:{stable, runs, champion_set, flips},
             notes:[...], pe_diagnostic:{...}|None}
    """
    if engine not in ENGINES:
        raise OrderDetectError(f"engine 必须是 {ENGINES} 之一，收到 {engine!r}")

    xyz_arr = np.asarray(xyz, dtype=np.float64)
    abc_arr = np.asarray(abc, dtype=np.float64)
    if xyz_arr.ndim != 2 or xyz_arr.shape[1] != 3 or abc_arr.shape != xyz_arr.shape:
        raise OrderDetectError(
            f"xyz / abc 必须是形状一致的 (n,3) 数组，实际 {xyz_arr.shape} / {abc_arr.shape}")
    n = xyz_arr.shape[0]
    rows_idx = list(row_idx) if row_idx is not None else list(range(1, n + 1))
    if len(rows_idx) != n:
        raise OrderDetectError(f"row_idx 条数 {len(rows_idx)} 与记录数 {n} 不一致")

    res: Dict[str, Any] = {
        "verdict": "INVALID", "order": None, "angle_unit": None, "rms": None,
        "pass_tol": float(pass_tol) if pass_tol is not None
                    else (max(SYNTHETIC_TOL, 3.0 * float(sigma)) if sigma is not None
                          else SYNTHETIC_TOL),
        "sigma": float(sigma) if sigma is not None else None,
        "engine": engine, "criterion_level": 2,
        "n_records": n, "n_effective": n,
        "row_idx": rows_idx,
        "dropped_idx": list(dropped_idx) if dropped_idx else [],
        "xyz_rxryrz": None, "T_handeye_mm": None, "T_target2base_mm": None,
        "ranking": [], "gap": {"ratio": None, "min_gap": float(min_gap), "ok": False},
        "excitation": None,
        "leave_one_out": {"stable": None, "runs": 0, "champion_set": [], "flips": []},
        "notes": [], "pe_diagnostic": None,
    }
    notes: List[str] = res["notes"]

    # --- 数据可用性（直接拒绝，不给答案）---
    if n == 0:
        if res["dropped_idx"]:
            notes.append(f"纯位姿表：{len(res['dropped_idx'])} 行全部没有相机侧成对观测"
                         f"（行号 {res['dropped_idx']}），12 个约定各自自洽，欧拉顺序"
                         f"数学上不可判定 → 拒绝出结论（§10.1）")
        else:
            notes.append("数据列表为空：无记录可判")
        return res
    if n < MIN_RECORDS:
        notes.append(f"位姿数 {n} < 硬下限 {MIN_RECORDS}（A11-2）：拒绝执行")
        res["verdict"] = "INSUFFICIENT"
        return res
    if Ttc_mm is None or len(Ttc_mm) == 0:
        notes.append("纯位姿表：无相机侧成对观测（T_target2cam），12 个约定各自自洽，"
                     "欧拉顺序数学上不可判定 → 拒绝出结论（§10.1）")
        return res
    if len(Ttc_mm) != n:
        notes.append(f"相机侧配对条数 {len(Ttc_mm)} 与位姿条数 {n} 不一致 → 拒绝执行")
        return res

    # --- A11-6：平移先归一 mm（复用 A2 入口 + 范数窗口，逐条一次，与分支无关）---
    xyz_mm = np.zeros((n, 3), dtype=np.float64)
    for i in range(n):
        T_len = np.eye(4, dtype=np.float64)
        T_len[:3, 3] = xyz_arr[i]
        ok, msg, T_mm = admit_pose(T_len, unit, "absolute", f"第 {rows_idx[i]} 行平移")
        if not ok:
            notes.append(f"第 {rows_idx[i]} 行平移非法（A2 入口）：{msg} → 拒绝执行")
            return res
        assert T_mm is not None
        xyz_mm[i] = T_mm[:3, 3]

    Ttc_list: List[np.ndarray] = []
    for i, T in enumerate(Ttc_mm):
        M = _as_T4(T, f"第 {rows_idx[i]} 行相机侧位姿")
        M = unit_guard.to_mm(M, ttc_unit)
        ok, msg = unit_guard.check_rigid_4x4(M)
        if not ok:
            notes.append(f"第 {rows_idx[i]} 行相机侧位姿非法：{msg} → 拒绝执行")
            return res
        Ttc_list.append(M)

    # --- 激励质量前置校验 ---
    exc = excitation_report(xyz_mm, abc_arr)
    res["excitation"] = exc
    if not exc["ok"]:
        notes.append("激励不足，拒绝出结论：" + "；".join(exc["reasons"]))
        notes.extend(exc["hints"])
        res["verdict"] = "INSUFFICIENT"
        return res

    # --- 候选排名（全候选）---
    ranking = (_rank_branches_sdk(branches=CANDIDATE_BRANCHES)
               if engine == "sdk"
               else _rank_branches(CANDIDATE_BRANCHES, xyz_mm, abc_arr, Ttc_list,
                                   n_starts=n_starts, seed=seed, max_nfev=max_nfev))
    tol = float(res["pass_tol"])
    for r in ranking:
        if r["resid"] is not None:
            r["pass"] = bool(r["resid"] < tol)
        if r["tme"] is not None and baseline_tme is not None:
            r["baseline_diff"] = abs(float(r["tme"]) - float(baseline_tme))
    res["ranking"] = ranking
    # R24：排名行结构两引擎共用且字段冻结 —— 拟合参数是内核内部量（不进 UI/报告），
    # 从公开发布的行里摘出来单独留用（真值分支的 X 用于组装结论）。
    fitted: Dict[str, Any] = {}
    for r in ranking:
        fitted[r["key"]] = (r.pop("x_rotvec_t", None), r.pop("tt2b_rotvec_t", None))

    # --- 定案：一级（SDK 基线差）优先，退化到二级（阈值唯一通过）---
    lvl1 = [r for r in ranking if r["baseline_diff"] is not None
            and r["baseline_diff"] < BASELINE_TOL_MM]
    if lvl1:
        res["criterion_level"] = 1
        passed = lvl1
        notes.append(f"一级判据命中 {len(lvl1)} 个候选（|tme − tme(poseType=0)| "
                     f"< {BASELINE_TOL_MM} mm）")
    else:
        passed = [r for r in ranking if r["pass"]]
        notes.append(f"二级判据：{len(passed)}/{len(ranking)} 个候选 rms < pass_tol={tol:g}")

    if len(passed) != 1:
        # proper Euler 诊断分支（只在主候选全灭时跑，只提示、不进定案 —— R19）
        if not passed and pe_diagnostic:
            pe_rows = _rank_branches(DIAGNOSTIC_PE_BRANCHES, xyz_mm, abc_arr, Ttc_list,
                                     n_starts=n_starts, seed=seed, max_nfev=max_nfev)
            pe_best = next((r for r in pe_rows if r["resid"] is not None and
                            np.isfinite(r["resid"])), None)
            tb_best = ranking[0]["resid"] if ranking else None
            if (pe_best is not None and tb_best is not None
                    and (pe_best["resid"] < tol or pe_best["resid"] * 10.0 < tb_best)):
                res["pe_diagnostic"] = {
                    "best": pe_best["key"], "resid": pe_best["resid"],
                    "note": "像重复轴约定（proper Euler），需人工确认；本结论不采用该分支",
                }
                notes.append(f"诊断：proper Euler 分支 {pe_best['key']} 拟合通过"
                             f"（rms={pe_best['resid']:.6g}）→ 像重复轴约定"
                             f"（同一轴出现两次），需人工确认顺序与数据来源")
        res["verdict"] = "MULTI"
        if not passed:
            notes.append("无候选通过 → 数据/口径存疑，按'多解'处理并列出全部候选（不给答案）")
        else:
            notes.append("多个候选同时通过 → 多解（激励不足的表现），列出全部并列候选："
                         + "、".join(r["key"] for r in passed))
        return res

    champ = passed[0]

    # --- 倍数差（只用全量数据判，§10.6-④）---
    ratio = _gap_ratio(champ["resid"], ranking[1]["resid"] if len(ranking) > 1 else None)
    res["gap"] = {"ratio": ratio, "min_gap": float(min_gap),
                  "ok": bool(ratio is not None and ratio >= min_gap)}
    if not res["gap"]["ok"]:
        res["verdict"] = "MULTI"
        notes.append(f"边界：全量倍数差 {ratio} < {min_gap:g}（第一名 {champ['key']} "
                     f"{champ['resid']:.6g} vs 第二名 "
                     f"{ranking[1]['resid'] if len(ranking) > 1 else float('nan'):.6g}）"
                     f"→ 按'需补数据'输出，不给唯一答案")
        return res

    # --- 留一检验：只断言"冠军不变"（§10.6-④）---
    loo = {"stable": None, "runs": 0, "champion_set": [], "flips": []}
    if leave_one_out and n > MIN_RECORDS:
        champ_set = {champ["key"]}
        flips: List[Dict[str, Any]] = []
        for i in range(n):
            keep = [j for j in range(n) if j != i]
            sub = _rank_branches(CANDIDATE_BRANCHES, xyz_mm[keep], abc_arr[keep],
                                 [Ttc_list[j] for j in keep],
                                 n_starts=loo_n_starts or n_starts, seed=seed,
                                 max_nfev=max_nfev)
            top = next((r for r in sub if r["resid"] is not None), None)
            key = top["key"] if top else None
            champ_set.add(key)
            if key != champ["key"]:
                flips.append({"dropped_row": rows_idx[i], "champion": key})
            loo["runs"] += 1
        loo["champion_set"] = sorted(k for k in champ_set if k)
        loo["flips"] = flips
        loo["stable"] = not flips
    res["leave_one_out"] = loo
    if loo["stable"] is False:
        res["verdict"] = "MULTI"
        notes.append(f"留一不稳定：剔除单条后冠军发生变化（{len(loo['flips'])} 次翻转，"
                     f"冠军集合 {loo['champion_set']}）→ 按'激励不足'处理")
        return res

    # --- 定案成立 ---
    res["verdict"] = "OK"
    res["order"] = champ["order"]
    res["angle_unit"] = champ["angle_unit"]
    res["rms"] = champ["resid"]
    params = fitted.get(champ["key"]) or (None, None)
    if params[0] is None or params[1] is None:
        notes.append("拟合参数缺失（引擎未返回参数）→ 结果只给 order/rms，不给矩阵")
        return res
    M = _T(Rotation.from_rotvec(params[0][:3]).as_matrix(), params[0][3:6])
    M2 = _T(Rotation.from_rotvec(params[1][:3]).as_matrix(), params[1][3:6])
    res["T_handeye_mm"] = [[float(v) for v in row] for row in M]
    res["T_target2base_mm"] = [[float(v) for v in row] for row in M2]
    res["xyz_rxryrz"] = to_xyz_rxryrz(M, champ["order"], unit="mm")
    return res


def conclusion_text(res: Dict[str, Any]) -> str:
    """把判定结果压成一行可读结论（带行号集合 —— 行号是结论的唯一索引，A11-②）。"""
    v = res.get("verdict")
    rows = res.get("row_idx") or []
    if v == "OK":
        return (f"order={res['order']}（{res['angle_unit']}）rms={res['rms']:.6g} "
                f"行号 {rows}")
    if v == "MULTI":
        keys = [r["key"] for r in res.get("ranking", []) if r.get("pass")]
        return f"多解/边界：{keys or '无候选通过'} 行号 {rows}"
    return f"{v}：{'；'.join(res.get('notes') or [])} 行号 {rows}"
