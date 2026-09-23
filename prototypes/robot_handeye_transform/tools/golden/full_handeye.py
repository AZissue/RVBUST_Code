"""决定性判据：完整 6DOF 手眼拟合（12 参数最小二乘），看候选约定能否被唯一区分。"""
import numpy as np
from scipy.spatial.transform import Rotation as Rot
from scipy.optimize import least_squares
PROPER=['XYX','XZX','YXY','YZY','ZXZ','ZYZ']; TAIT=['XYZ','XZY','YXZ','YZX','ZXY','ZYX']
SEQS=TAIT+[s.lower() for s in TAIT]
def T(R,t):
    M=np.eye(4); M[:3,:3]=R; M[:3,3]=t; return M
def rt(v): return Rot.from_rotvec(v[:3]).as_matrix(), v[3:6]
def resid(p, Tgb, Ttc, weight=1.0):
    X=T(*rt(p[:6])); Tt2b=T(*rt(p[6:12]))
    out=[]
    for A,B in zip(Tgb,Ttc):
        pred=X@np.linalg.inv(A)@Tt2b
        E=np.linalg.inv(B)@pred
        out.append(np.concatenate([Rot.from_matrix(E[:3,:3]).as_rotvec(degrees=True), E[:3,3]]))
    return np.concatenate(out)
rng=np.random.default_rng(7)
X_true=T(Rot.random(random_state=rng).as_matrix(), rng.uniform(-50,50,3))     # gripper->cam
T_t2b=T(Rot.random(random_state=rng).as_matrix(), rng.uniform(200,500,3))     # target in base
n=8; Tgb_true=[]; eul=[]; xyz=[]
for _ in range(n):
    r=Rot.random(random_state=rng); t=rng.uniform(-300,300,3)
    Tgb_true.append(T(r.as_matrix(),t)); eul.append(r.as_euler('XYZ',degrees=True)); xyz.append(t)
Ttc=[X_true@np.linalg.inv(A)@T_t2b for A in Tgb_true]
eul=np.array(eul); xyz=np.array(xyz)
print("候选约定   6DOF拟合代价(最终cost)   平均重投影残差")
for s in SEQS:
    Tgb=[T(Rot.from_euler(s,a,degrees=True).as_matrix(),t) for a,t in zip(eul,xyz)]
    best=None
    for seed in range(3):
        r0=np.random.default_rng(seed).normal(0,0.3,12)
        try: r=least_squares(resid,r0,args=(Tgb,Ttc),method='lm',max_nfev=20000)
        except Exception: continue
        if best is None or r.cost<best.cost: best=r
    n_res=len(resid(best.x,Tgb,Ttc)); rms=np.sqrt(2*best.cost/n_res)
    flag='  <== 通过' if rms<0.05 else ''
    print(f"  {s:4s}   cost={best.cost:14.6f}   rms={rms:12.6f}{flag}")
