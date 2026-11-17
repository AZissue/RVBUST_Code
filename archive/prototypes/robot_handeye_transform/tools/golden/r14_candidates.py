"""R14：候选集口径 / 角度单位 / proper Euler 真值 —— 三项 spike（独立验证，合成真值 oracle）
判据：完整 6DOF 手眼重投影残差 rms（deg/mm 混合，仅用于本 spike 内部排名）
"""
import itertools, json, sys
import numpy as np
from scipy.spatial.transform import Rotation as Rot
from scipy.optimize import least_squares

TB12 = ['XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'] + ['xyz', 'xzy', 'yxz', 'yzx', 'zxy', 'zyx']
PE12 = ['XYX', 'XZX', 'YXY', 'YZY', 'ZXZ', 'ZYZ'] + ['xyx', 'xzx', 'yxy', 'yzy', 'zxz', 'zyz']
ALL24 = TB12 + PE12
TOL = 0.05   # 合成无噪口径（lead 已注明现场噪声下需重标 R13）

def T(R, t):
    M = np.eye(4); M[:3, :3] = R; M[:3, 3] = t; return M

def gen(n, truth_seq, unit, seed=11, degenerate=False):
    rng = np.random.default_rng(7)
    X_true = T(Rot.random(random_state=rng).as_matrix(), rng.uniform(-50, 50, 3))
    T_t2b = T(Rot.random(random_state=rng).as_matrix(), rng.uniform(200, 500, 3))
    rng = np.random.default_rng(seed)
    eul, xyz, Tgb = [], [], []
    for _ in range(n):
        if degenerate:
            r = Rot.from_rotvec(np.deg2rad(rng.uniform(-40, 40)) * np.array([0, 0, 1.0]))
        else:
            r = Rot.random(random_state=rng)
        t = rng.uniform(-300, 300, 3)
        Tgb.append(T(r.as_matrix(), t)); xyz.append(t)
        eul.append(r.as_euler(truth_seq, degrees=(unit == 'deg')))
    Ttc = [X_true @ np.linalg.inv(A) @ T_t2b for A in Tgb]
    return np.array(eul), np.array(xyz), Ttc

def resid(p, Tgb, Ttc):
    X = T(Rot.from_rotvec(p[:3]).as_matrix(), p[3:6])
    Tb = T(Rot.from_rotvec(p[6:9]).as_matrix(), p[9:12])
    out = []
    for A, B in zip(Tgb, Ttc):
        E = np.linalg.inv(B) @ X @ np.linalg.inv(A) @ Tb
        out.append(np.concatenate([Rot.from_matrix(E[:3, :3]).as_rotvec(degrees=True), E[:3, 3]]))
    return np.concatenate(out)

def fit(eul, xyz, Ttc, cand, unit):
    """返回 (rms, 是否<阈值)，用候选约定重建旋转；unit 为该分支假设的角度单位"""
    Tgb = [T(Rot.from_euler(cand, a, degrees=(unit == 'deg')).as_matrix(), t) for a, t in zip(eul, xyz)]
    best = None
    for k in range(2):
        r0 = np.random.default_rng(k).normal(0, 0.3, 12)
        try:
            r = least_squares(resid, r0, args=(Tgb, Ttc), method='lm', max_nfev=8000)
        except Exception:
            continue
        if best is None or r.cost < best.cost:
            best = r
    rms = float(np.sqrt(2 * best.cost / (6 * len(Tgb))))
    return rms

def sweep(eul, xyz, Ttc, cands, unit):
    res = {c: fit(eul, xyz, Ttc, c, unit) for c in cands}
    ok = sorted([c for c, v in res.items() if v < TOL], key=lambda c: res[c])
    return ok, res

print("=" * 78)
print("[1] 候选集口径：真值=内旋 XYZ(deg)，一般位姿 n=8，看通过集合")
eul, xyz, Ttc = gen(8, 'XYZ', 'deg')
for name, cands in (('12 (6 TB × 内外旋)', TB12), ('18 (TB12 + PE 内旋6)', TB12 + PE12[:6]), ('24 (全)', ALL24)):
    ok, res = sweep(eul, xyz, Ttc, cands, 'deg')
    print(f"  {name:22s} 通过 {len(ok):2d}/{len(cands):2d} -> {ok}")
    if name.startswith('18'):
        print("      18 集合的次佳（未通过）=", sorted(((v, c) for c, v in res.items() if c not in ok))[:3])

print("\n[2] 真值=proper Euler 时，现行 12-TB 管线输出什么")
for truth in ('XYX', 'ZYZ', 'xyx'):
    eul, xyz, Ttc = gen(8, truth, 'deg')
    ok, res = sweep(eul, xyz, Ttc, TB12, 'deg')
    truth_in_tb = truth in TB12        # proper Euler 不在 12-TB 集合内
    print(f"  真值 {truth:4s}(不在12-TB内={not truth_in_tb})：12-TB 通过 {len(ok)} 个 -> {ok}"
          f"  {'【错误答案：给了通过的候选但不是真值】' if ok else '【无候选通过 → fail-closed，符合预期】'}")
    if ok:
        print(f"        误判候选 rms={res[ok[0]]:.3e}；全12-TB最小三个={sorted((v,c) for c,v in res.items())[:3]}")

print("\n[3] 角度单位：真值数据是 rad，工具假设 deg")
for truth in ('XYZ', 'ZYX'):
    eul_r, xyz, Ttc = gen(8, truth, 'rad')
    print(f"  真值 {truth} 用 rad 写、按 deg 解析（现行口径）：|角度|范围 = "
          f"[{np.abs(eul_r).min():.3f}, {np.abs(eul_r).max():.3f}]")
    ok, res = sweep(eul_r, xyz, Ttc, TB12, 'deg')
    print(f"      12-TB(deg 假设) 通过 {len(ok)} 个 -> {ok}"
          f"  {'【给了错误答案】' if ok else '【无候选通过 → fail-closed】'}")
    # 双单位分支
    best = []
    for unit in ('deg', 'rad'):
        oku, resu = sweep(eul_r, xyz, Ttc, TB12, unit)
        for c in oku:
            best.append((resu[c], c, unit))
    best.sort()
    print(f"      48 分支(12TB×deg/rad) 通过 {len(best)} 个 -> {[(c,u,round(v,6)) for v,c,u in best[:4]]}")
    print(f"      是否唯一命中 (真值={truth}, rad) ? {'是' if len(best)==1 and best[0][1]==truth and best[0][2]=='rad' else '否'}")

print("\n[4] 退化激励（全绕 Z，n=8）在各候选集下的通过数")
eul, xyz, Ttc = gen(8, 'XYZ', 'deg', degenerate=True)
for name, cands in (('12', TB12), ('18', TB12 + PE12[:6]), ('24', ALL24)):
    ok, _ = sweep(eul, xyz, Ttc, cands, 'deg')
    print(f"  {name:3s} 通过 {len(ok):2d}/{len(cands):2d} -> {ok}")
