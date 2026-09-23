"""留一稳定性：对最优 3 个候选在两两竞争中逐条剔除，看冠军是否翻盘（A11-5 的实测版）"""
import ctypes, json, os, time
import numpy as np
from scipy.spatial.transform import Rotation as Rot

FOLDER = "D:/RVC_SRC/Cpp/HandEyeCalibration_Test/build/data/marker/"
POSES = np.loadtxt(FOLDER + "robot_poses.txt"); N = len(POSES)
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

def call(fn, mask):
    p = Param(); p.poseType = 3; p.markerType = 0
    p.isPointCloudMm = False; p.isPoseMm = True; p.isPoseDegree = True
    p.isEyeInHand = False; p.autoRemoveLargeErrorData = False
    for i in range(100):
        p.dataMask[i] = bool(mask[i]) if i < N else False
    r = Result()
    ret = dll.HandEyeCalibrationMarker(FOLDER.encode(), fn.encode(), ctypes.byref(p), ctypes.byref(r))
    return ret, float(r.totalMeanError)

CANDS = [("xyz", "deg"), ("ZYX", "deg"), ("XZY", "deg")]
files = {}
for seq, unit in CANDS:
    fn = f"verify_loo_{seq}_{unit}.txt"; files[(seq, unit)] = fn
    with open(FOLDER + fn, "w", encoding="utf-8") as f:
        for P in POSES:
            R = Rot.from_euler(seq, P[3:], degrees=True).as_matrix()
            M = np.eye(4); M[:3, :3] = R; M[:3, 3] = P[:3]
            f.write(" ".join(f"{v:.9f}" for v in M.reshape(-1)) + "\n")

t0 = time.time(); flips = 0; winners = []
for i in range(N):
    m = [True] * N; m[i] = False
    res = {}
    for key, fn in files.items():
        ret, tme = call(fn, m)
        res[key] = tme if ret == 0 else float("inf")
    w = min(res, key=res.get); winners.append(w[0])
    if w != ("xyz", "deg"):
        flips += 1
        print(f"  剔除 #{i}: 冠军={w[0]}/{w[1]} tme={res[w]:.6f} | xyz/deg={res[('xyz','deg')]:.6f} 【翻盘】")
    else:
        print(f"  剔除 #{i}: 冠军=xyz/deg tme={res[w]:.6f} | 次佳 {min((v,k) for k,v in res.items() if k!=w)[1][0]}="
              f"{min(v for k,v in res.items() if k!=w):.6f}")

for fn in files.values():
    os.remove(FOLDER + fn)
print(f"\n留一 {N} 次：冠军翻转 {flips} 次 | 冠军集合={set(winners)} | 耗时 {time.time()-t0:.1f}s")
