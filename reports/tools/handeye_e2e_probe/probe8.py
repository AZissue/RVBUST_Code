"""Round 8: end-to-end through the app's OWN CalibrationService.

probe4 proved the *math* (rotation vector -> matrix -> poseType=3) recovers X with
totalMeanError 0. This one proves the shipped code path does the same: the same
synthetic set is handed to he_app_e2e.exe, which links
src/logic/CalibrationService.cpp + src/sdk/HandEyeSDKBridge.cpp and calls
CalibrationService::calibrate() exactly like the GUI does.

Two runs on identical card data ("x y z rx ry rz", axis-angle in radians):
  * rpy    + deg  -- what the program did before this change
  * rotvec + rad  -- what the new pose-format preset does
"""
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\Users\rvbust\AppData\Local\Temp\he_sdk_probe")
EXE = ROOT / "build" / "Release" / "he_app_e2e.exe"
QT_BIN = r"D:\Program Files\Qt\5.14.2\msvc2017_64\bin"


def nums(x, sep=" "):
    return sep.join(repr(float(v)) for v in np.asarray(x, dtype=float).ravel())


def rodrigues(r):
    th = np.linalg.norm(r)
    if th < 1e-12:
        return np.eye(3)
    k = r / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def se3(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def inv(T):
    R, t = T[:3, :3], T[:3, 3]
    return se3(R.T, -R.T @ t)


rng = np.random.default_rng(7)                      # same seed as probe4
X = se3(rodrigues(np.array([0.30, -0.20, 0.10])), np.array([30.0, -20.0, 50.0]))

poses, cam, tcp = [], [], []
for i in range(12):
    rv = np.array([1.2 - 1.6 * (i % 3), -0.8 + 0.5 * (i % 4), 0.9 - 0.3 * (i % 5)])
    T = se3(rodrigues(rv), np.array([400.0, -150.0, 600.0]) + 25.0 * i * np.array([0.3, -0.7, 0.2]))
    p_base = np.array([400.0, -150.0, 600.0]) + rng.uniform(-40, 40, 3)
    p_cam = inv(T @ X) @ np.append(p_base, 1.0)
    poses.append((rv, T[:3, 3]))
    cam.append(p_cam[:3])
    tcp.append(p_base)

d = ROOT / "data" / "e2e_app"
d.mkdir(parents=True, exist_ok=True)
(d / "camera.txt").write_text("\n".join(nums(p) for p in cam) + "\n")
(d / "tcp.txt").write_text("\n".join(nums(p) for p in tcp) + "\n")
# 卡片格式：6 个数，空格分隔；旋转 = 轴角旋转矢量（弧度）——UR 就是这样报的。
(d / "card_pose.txt").write_text(
    "\n".join(f"{nums(pt)} {nums(rv)}" for rv, pt in poses) + "\n")

env = dict(os.environ)
env["PATH"] = QT_BIN + ";" + env["PATH"]

for label, fmt, unit in (("旧行为: 轴角当欧拉(度)", "rpy", "deg"),
                         ("新预设: 旋转矢量(弧度)", "rotvec", "rad")):
    print(f"--- {label}")
    p = subprocess.run([str(EXE), str(d), fmt, unit], capture_output=True, text=True, env=env)
    print("\n".join("    " + ln for ln in (p.stdout or p.stderr).strip().splitlines()))
    if "totalMeanError" in p.stdout:
        m = [float(v) for v in p.stdout.split("totalMeanError")[1].split("\n", 1)[1].split()]
        got = np.array(m[:16]).reshape(4, 4)
        for name, ref in (("X", X), ("X^-1", inv(X))):
            dR = np.abs(got[:3, :3] - ref[:3, :3]).max()
            dt = np.abs(got[:3, 3] - ref[:3, 3]).max()
            print(f"    vs {name}: max|dR|={dR:.6f}  max|dt|={dt:.4f} mm")
