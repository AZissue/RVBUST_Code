"""@lead v2.3-⑥② 用 6B-1 新内核复跑 r14 三项（12/18/24 唯一性、退化、PE、rad），
输出与 @verify 早期随机多起点内核的数字对照。合成真值 oracle，无噪。
"""
import sys, pathlib, json
import numpy as np
from scipy.spatial.transform import Rotation as Rot

ROOT = pathlib.Path(r"D:/RVC_SRC/Python/MultiCameraCalibration/prototypes/robot_handeye_transform")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "core"))
try:
    from core.order_detect import detect_order, candidate_cardinality
except Exception:
    from order_detect import detect_order, candidate_cardinality

TB12 = ['XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'] + ['xyz', 'xzy', 'yxz', 'yzx', 'zxy', 'zyx']

def T(R, t):
    M = np.eye(4); M[:3, :3] = R; M[:3, 3] = t; return M

def gen(n, seq, unit="deg", seed=11, degenerate=False, x_seed=7):
    rng = np.random.default_rng(x_seed)
    X = T(Rot.random(random_state=rng).as_matrix(), rng.uniform(-50, 50, 3))
    T_t2b = T(Rot.random(random_state=rng).as_matrix(), rng.uniform(200, 500, 3))
    rng = np.random.default_rng(seed)
    xyz, abc, Tgb = [], [], []
    for _ in range(n):
        if degenerate:
            r = Rot.from_rotvec(np.deg2rad(rng.uniform(-40, 40)) * np.array([0., 0., 1.]))
        else:
            r = Rot.random(random_state=rng)
        t = rng.uniform(-300, 300, 3)
        Tgb.append(T(r.as_matrix(), t)); xyz.append(t)
        abc.append(r.as_euler(seq, degrees=(unit == "deg")))
    Ttc = [X @ np.linalg.inv(A) @ T_t2b for A in Tgb]
    return np.array(xyz), np.array(abc), Ttc

def run(xyz, abc, Ttc, **kw):
    kw.setdefault("leave_one_out", False)
    kw.setdefault("n_starts", 3)
    r = detect_order(xyz, abc, Ttc, unit="mm", ttc_unit="mm", **kw)
    npass = sum(1 for x in r.get("ranking", []) if x.get("pass"))
    return r, npass

def s(v, nd=10):
    return "None" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))

print("内核基数公式（R19）:", candidate_cardinality())
print("\n[A11-1 / 早期 r14-①] 一般位姿 n=8，真值逐一注入 12 个 Tait-Bryan（deg）")
ok_hit = 0
for seq in TB12:
    xyz, abc, Ttc = gen(8, seq, "deg")
    r, npass = run(xyz, abc, Ttc)
    hit = (r.get("verdict") == "OK" and r.get("order") == seq)
    ok_hit += hit
    gap = (r.get("gap") or {}).get("ratio")
    print(f"  {seq:4s} verdict={str(r.get('verdict')):12s} order={str(r.get('order')):5s} "
          f"unit={str(r.get('angle_unit')):4s} rms={s(r.get('rms'))} 通过数={npass}/24 gap={s(gap, 3)}")
print(f"  → 命中 = {ok_hit}/12")

print("\n[早期 r14-② 口径对照] 退化：全部绕单轴 Z（n=8），真值 XYZ")
xyz, abc, Ttc = gen(8, "XYZ", "deg", degenerate=True)
r, npass = run(xyz, abc, Ttc)
print(f"  verdict={r.get('verdict')} 通过数={npass} ranking条数={len(r.get('ranking', []))}")
print(f"  notes={r.get('notes')}")
ex = r.get("excitation") or {}
keys = ("ok", "verdict", "n_distinct_rotations", "axis_spread_deg", "reason", "hint")
print("  excitation:", json.dumps({k: ex.get(k) for k in keys if k in ex}, ensure_ascii=False, default=str))
print("  [对照] 旧内核（纯拟合排名、无激励门）同数据：12→4/12 通过 —— 口径不同，不可互相引用")

print("\n[早期 r14-③] 真值=proper Euler（XYX / ZYZ）：TB 主候选 + PE 诊断分支")
for seq in ("XYX", "ZYZ"):
    xyz, abc, Ttc = gen(8, seq, "deg")
    r, npass = run(xyz, abc, Ttc)
    pe = r.get("pe_diagnostic") or {}
    print(f"  {seq}: verdict={r.get('verdict')} TB通过数={npass} "
          f"PE诊断={json.dumps({k: pe.get(k) for k in ('best', 'resid', 'note')}, ensure_ascii=False, default=str)}")

print("\n[早期 r14-④] 角度单位：真值数据用 rad 写")
for seq in ("XYZ", "ZYX"):
    xyz, abc, Ttc = gen(8, seq, "rad")
    r, npass = run(xyz, abc, Ttc)
    print(f"  {seq}(rad): verdict={r.get('verdict')} order={str(r.get('order'))} "
          f"unit={str(r.get('angle_unit'))} 通过数={npass}/24 rms={s(r.get('rms'))}")

print("\n[对照：纯位姿表（无相机侧数据）]")
xyz, abc, Ttc = gen(6, "XYZ", "deg")
try:
    r, npass = run(xyz, abc, None)
    print("  传入 Ttc=None ->", r.get("verdict"), r.get("notes"))
except Exception as e:
    print(f"  传入 Ttc=None -> 抛 {type(e).__name__}: {str(e)[:100]}")
