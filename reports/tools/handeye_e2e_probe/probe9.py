"""Round 9: the euler pass-through, measured.

Every robot used before the pose-format change went through:
    card line -> normalizePoseLine() -> "x,y,z,rx,ry,rz" -> SDK poseType=0
The new code keeps that exact path for RotationFormat::EulerRpy. This checks it
empirically against the SDK *directly*, with the same data:

  A) he_app_e2e  <dir> rpy deg     -- our code, EulerRpy + degrees
  B) he_sdk_probe touch <dir> 0 1 1 -- raw SDK, poseType=0, mm, degrees

A == B on totalMeanError and every matrix cell means our euler path is still
"just the SDK", i.e. the already-validated FANUC results cannot have moved.
"""
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\Users\rvbust\AppData\Local\Temp\he_sdk_probe")
APP_EXE = ROOT / "build" / "Release" / "he_app_e2e.exe"
SDK_EXE = ROOT / "build" / "Release" / "he_sdk_probe.exe"
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


rng = np.random.default_rng(7)
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

d = ROOT / "data" / "euler_passthrough"
d.mkdir(parents=True, exist_ok=True)
(d / "camera.txt").write_text("\n".join(nums(p) for p in cam) + "\n")
(d / "tcp.txt").write_text("\n".join(nums(p) for p in tcp) + "\n")
# 卡片格式（空格 6 个数）—— 我们的入口读这个
(d / "card_pose.txt").write_text(
    "\n".join(f"{nums(pt)} {nums(rv)}" for rv, pt in poses) + "\n")
# SDK 直接读的规范化格式（逗号）—— 我们的 normalizePoseLine 会写出的样子
(d / "pose.txt").write_text(
    "\n".join(f"{','.join(repr(float(v)) for v in list(pt) + list(rv))}" for rv, pt in poses) + "\n")

env = dict(os.environ)
env["PATH"] = QT_BIN + ";" + env["PATH"]

a = subprocess.run([str(APP_EXE), str(d), "rpy", "deg"], capture_output=True, text=True, env=env)
b = subprocess.run([str(SDK_EXE), "touch", str(d), "0", "1", "1"], capture_output=True, text=True, env=env)
print("A) app code, EulerRpy + deg")
print("\n".join("   " + ln for ln in a.stdout.strip().splitlines()))
print("B) raw SDK, poseType=0, mm, deg")
print("\n".join("   " + ln for ln in b.stdout.strip().splitlines()))

ma = [float(v) for v in a.stdout.split("totalMeanError")[1].split("\n", 1)[1].split()][:16]
mb = [float(v) for v in b.stdout.split("matrix row-major:")[1].split()][:16]
ea = float(a.stdout.split("totalMeanError=")[1].split()[0])
eb = float(b.stdout.split("totalMeanError=")[1].split()[0])
print(f"\ntotalMeanError  A={ea}  B={eb}  identical={ea == eb}")
print(f"matrix max|delta| = {np.abs(np.array(ma) - np.array(mb)).max()}")
