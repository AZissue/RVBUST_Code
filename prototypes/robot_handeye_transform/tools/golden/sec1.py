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


print("[1] 候选集口径：真值=内旋 XYZ(deg)，一般位姿 n=8")
eul, xyz, Ttc = gen(8, 'XYZ', 'deg')
for name, cands in (('12 (6 TB × 内外旋)', TB12), ('18 (TB12 + PE 内旋6)', TB12 + PE12[:6]), ('24 (全)', ALL24)):
    ok, res = sweep(eul, xyz, Ttc, cands, 'deg')
    near = sorted(((v, c) for c, v in res.items() if c not in ok))[:3]
    print(f"  {name:22s} 通过 {len(ok):2d}/{len(cands):2d} -> {ok}")
    print(f"      次佳三个(未通过) = {[(c, round(v,4)) for v,c in near]}")
