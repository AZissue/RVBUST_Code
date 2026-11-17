"""R13 sweep v2：关掉 autoRemoveLargeErrorData（v1 发现它会让错约定靠丢数据刷低误差），
24 分支（12 TB × deg/rad）→ 公平排名；再对最优分支做留一(27) + 子集重采样(10) 估噪声底 σ。
"""
import ctypes, json, os, time
import numpy as np
from scipy.spatial.transform import Rotation as Rot

FOLDER = "D:/RVC_SRC/Cpp/HandEyeCalibration_Test/build/data/marker/"
POSES = np.loadtxt(FOLDER + "robot_poses.txt")
N = len(POSES)
TB = ['XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX']
SEQS = TB + [s.lower() for s in TB]
DLL = ("E:/jingz/Desktop/RVCHandEyeCalibration_v3.9.0_20260828_win_release/"
       "RVCHandEyeCalibration/SDK/C++/External/HandEyeSDK/Win64/bin/HandEyeSDK.dll")

class Param(ctypes.Structure):
    _fields_ = [("poseType", ctypes.c_int), ("markerType", ctypes.c_int),
                ("isPointCloudMm", ctypes.c_bool), ("isPoseMm", ctypes.c_bool),
                ("isPoseDegree", ctypes.c_bool), ("isEyeInHand", ctypes.c_bool),
                ("dataMask", ctypes.c_bool * 100), ("autoRemoveLargeErrorData", ctypes.c_bool)]

class Result(ctypes.Structure):
    _fields_ = [("translationResult", ctypes.c_double * 3), ("eulerAngleResult", ctypes.c_double * 3),
                ("quaternionResult", ctypes.c_double * 4), ("matrix", ctypes.c_double * 16),
                ("success2D", ctypes.c_int * 100), ("success3D", ctypes.c_int * 100),
                ("error", ctypes.c_double * 100), ("totalMeanError", ctypes.c_double)]

dll = ctypes.CDLL(DLL)
dll.HandEyeCalibrationMarker.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                                         ctypes.POINTER(Param), ctypes.POINTER(Result)]
dll.HandEyeCalibrationMarker.restype = ctypes.c_int

def call(pose_file, pose_type=3, mask=None, auto_remove=False):
    p = Param(); p.poseType = pose_type; p.markerType = 0
    p.isPointCloudMm = False; p.isPoseMm = True; p.isPoseDegree = True
    p.isEyeInHand = False; p.autoRemoveLargeErrorData = auto_remove
    for i in range(100):
        p.dataMask[i] = (bool(mask[i]) if i < len(mask) else False) if mask is not None else (i < N)
    r = Result()
    ret = dll.HandEyeCalibrationMarker(FOLDER.encode(), pose_file.encode(), ctypes.byref(p), ctypes.byref(r))
    return ret, r

def write_pose_file(name, seq, unit):
    path = os.path.join(FOLDER, name)
    with open(path, "w", encoding="utf-8") as f:
        for P in POSES:
            R = Rot.from_euler(seq, P[3:], degrees=(unit == "deg")).as_matrix()
            M = np.eye(4); M[:3, :3] = R; M[:3, 3] = P[:3]
            f.write(" ".join(f"{v:.9f}" for v in M.reshape(-1)) + "\n")
    return path

t0 = time.time()
print("[参照] poseType=0 + pose.txt（SDK 自动判断）: ", end="")
ret0, r0 = call("pose.txt", 0, auto_remove=False)
print(f"ret={ret0} tme={r0.totalMeanError:.6f}")
ret0a, r0a = call("pose.txt", 0, auto_remove=True)
print(f"[参照] 同上但 autoRemove=true: ret={ret0a} tme={r0a.totalMeanError:.6f}")

print("\n[主扫 v2] 24 分支，autoRemoveLargeErrorData=FALSE（27 组全用，公平比较）")
rows = []
for seq in SEQS:
    for unit in ("deg", "rad"):
        fn = f"verify_c_{seq}_{unit}.txt"; write_pose_file(fn, seq, unit)
        ret, r = call(fn, 3, auto_remove=False)
        rows.append({"seq": seq, "unit": unit, "ret": ret, "tme": float(r.totalMeanError),
                     "errs": [float(r.error[i]) for i in range(N)],
                     "used": sum(1 for i in range(N) if r.success2D[i] == 1)})
        print(f"  {seq:4s} {unit:3s} ret={ret:3d} tme={r.totalMeanError:12.6f} 2D成功={rows[-1]['used']:2d}/27")
        os.remove(os.path.join(FOLDER, fn))

ok = sorted([x for x in rows if x["ret"] == 0], key=lambda x: x["tme"])
print(f"\n排名（ret=0 的 {len(ok)}/24 个分支）：")
for i, x in enumerate(ok[:6]):
    print(f"  #{i+1} {x['seq']:4s} {x['unit']:3s} tme={x['tme']:.6f}")
print(f"  倍数差 #2/#1 = {ok[1]['tme']/max(ok[0]['tme'],1e-12):.3f}   #3/#1 = {ok[2]['tme']/max(ok[0]['tme'],1e-12):.3f}")
best = ok[0]
print(f"\n最优分支 {best['seq']}/{best['unit']} 的 27 组误差：min={min(best['errs']):.4f} "
      f"max={max(best['errs']):.4f} 中位={np.median(best['errs']):.4f} mm")

# 噪声底：留一（27 次） + 子集重采样（B=10，每次随机去 4 组）
fn = f"verify_c_{best['seq']}_{best['unit']}.txt"; write_pose_file(fn, best["seq"], best["unit"])
loo = []
for i in range(N):
    m = [True] * N; m[i] = False
    ret, r = call(fn, 3, mask=m, auto_remove=False)
    if ret == 0: loo.append(float(r.totalMeanError))
rng = np.random.default_rng(0); sub = []
for _ in range(10):
    drop = set(rng.choice(N, 4, replace=False).tolist())
    m = [j not in drop for j in range(N)]
    ret, r = call(fn, 3, mask=m, auto_remove=False)
    if ret == 0: sub.append(float(r.totalMeanError))
os.remove(os.path.join(FOLDER, fn))
print(f"\n[噪声底] 留一 n={len(loo)}: 均值={np.mean(loo):.6f} 标准差 σ={np.std(loo, ddof=1):.6f} "
      f"极差={max(loo)-min(loo):.6f}")
print(f"[噪声底] 子集(23/27) n={len(sub)}: 均值={np.mean(sub):.6f} σ={np.std(sub, ddof=1):.6f} "
      f"极差={max(sub)-min(sub):.6f}")
sig = max(np.std(loo, ddof=1), np.std(sub, ddof=1))
print(f"[阈值建议] pass_tol = max(0.05 mm, 3σ) = max(0.05, {3*sig:.6f}) = {max(0.05, 3*sig):.6f} mm")
json.dump({"rows": rows, "loo": loo, "sub": sub, "best": best["seq"] + "/" + best["unit"],
           "sigma": float(sig)}, open("sdk_sweep_v2.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"\n耗时 {time.time()-t0:.1f}s -> sdk_sweep_v2.json")
