import numpy as np
from scipy.spatial.transform import Rotation as Rot
from scipy.optimize import least_squares
TAIT=['XYZ','XZY','YXZ','YZX','ZXY','ZYX']; SEQS=TAIT+[s.lower() for s in TAIT]
def T(R,t): M=np.eye(4); M[:3,:3]=R; M[:3,3]=t; return M
def resid(p,Tgb,Ttc):
    X=T(Rot.from_rotvec(p[:3]).as_matrix(),p[3:6]); Tb=T(Rot.from_rotvec(p[6:9]).as_matrix(),p[9:12])
    return np.concatenate([np.concatenate([Rot.from_matrix((np.linalg.inv(B)@X@np.linalg.inv(A)@Tb)[:3,:3]).as_rotvec(degrees=True),
                                           (np.linalg.inv(B)@X@np.linalg.inv(A)@Tb)[:3,3]]) for A,B in zip(Tgb,Ttc)])
def run(poses,labels,rt_axis=None):
    res=[]
    for s in SEQS:
        Tgb=[T(Rot.from_euler(s,a,degrees=True).as_matrix(),t) for a,t in zip(eul,xyz)]
        best=min((least_squares(resid,np.random.default_rng(k).normal(0,0.3,12),args=(Tgb,Ttc),method='lm',max_nfev=20000) for k in range(4)),key=lambda r:r.cost)
        rms=np.sqrt(2*best.cost/(6*len(Tgb)))
        if rms<0.05: res.append(s)
    return res
rng=np.random.default_rng(7)
X_true=T(Rot.random(random_state=rng).as_matrix(), rng.uniform(-50,50,3))
T_t2b=T(Rot.random(random_state=rng).as_matrix(), rng.uniform(200,500,3))
print("[一般位姿] 唯一正确约定所需的位姿数")
for n in (2,3,4,5):
    rng=np.random.default_rng(11); eul=[]; xyz=[]; Tgb_true=[]
    for _ in range(n):
        r=Rot.random(random_state=rng); t=rng.uniform(-300,300,3)
        Tgb_true.append(T(r.as_matrix(),t)); eul.append(r.as_euler('XYZ',degrees=True)); xyz.append(t)
    Ttc=[X_true@np.linalg.inv(A)@T_t2b for A in Tgb_true]
    eul=np.array(eul); xyz=np.array(xyz)
    r=run(None,None); print(f"  n={n}: 能拟合的约定 {len(r)}/12 -> {r}")
print("[退化] 机器人只绕Z轴旋转 (+小角度Y)")
for name,mode in (('全绕Z',0),('Z+±3°Y',1)):
    rng=np.random.default_rng(5); eul=[];xyz=[];Tgb_true=[]
    for _ in range(8):
        if mode==0: r=Rot.from_rotvec(np.deg2rad(rng.uniform(-40,40))*np.array([0,0,1.]))
        else: r=Rot.from_euler('XYZ',[0,rng.uniform(-3,3),rng.uniform(-40,40)],degrees=True)
        t=rng.uniform(-300,300,3); Tgb_true.append(T(r.as_matrix(),t)); eul.append(r.as_euler('XYZ',degrees=True)); xyz.append(t)
    Ttc=[X_true@np.linalg.inv(A)@T_t2b for A in Tgb_true]; eul=np.array(eul); xyz=np.array(xyz)
    r=run(None,None); print(f"  {name}(n=8): 能拟合的约定 {len(r)}/12 -> {r}")
