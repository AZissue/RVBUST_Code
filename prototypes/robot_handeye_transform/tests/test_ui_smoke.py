# -*- coding: utf-8 -*-
"""
offscreen 端到端测试（test_ui_smoke）—— 批 4 / A4 / A5。

跑法：conda rvc python 直跑，看退出码，勿用 pytest（须 offscreen 环境：
`export QT_QPA_PLATFORM=offscreen`，测试内也会自行设置）。

覆盖：
  [1] A3 导出门禁接线：UNVERIFIED 时「保存合并 PLY / 保存会话」置灰，
      VERIFIED 后解锁（按钮状态机，不经过鼠标）
  [2] A4 端到端：真实窗口 + MockPoseSource 3 位姿 → 采集 3 帧 → **三帧逐帧**
      解析真值比对（A4 加严，v4.2）→ merge_pointclouds 合并 → 保存 PLY →
      重新加载 → 点数一致；合并云 vs 解析真值最近邻中位数 < 0.5 mm
  [3] 清空后导出回锁（fail-closed）
  [4] A5 实时性：30 万点**单帧**「复制 + 变换 + 合并入累加器」计时 < 50 ms
      （@qa 基线 17.0 ms；@feas 15.4 ms——本测试只守门限，不冒用基线口径）
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "core"))
sys.path.insert(0, os.path.join(_HERE, "..", "app"))

# R12：仓库根定位（window 也会自己找；这里提前钉死，便于直接引 src 做计时段）
_REPO_ROOT = os.environ.get("MCC_REPO_ROOT")
if not (_REPO_ROOT and os.path.isfile(os.path.join(
        _REPO_ROOT, "src", "core", "pcd_utils.py"))):
    cur = _HERE
    while True:
        if os.path.isfile(os.path.join(cur, "src", "core", "pcd_utils.py")):
            _REPO_ROOT = cur
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            _REPO_ROOT = None
            break
        cur = parent
if _REPO_ROOT:
    os.environ.setdefault("MCC_REPO_ROOT", _REPO_ROOT)
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import numpy as np           # noqa: E402

import handeye_result as he_mod      # noqa: E402  core/
import pose_source as ps_mod         # noqa: E402  core/
import transform_chain               # noqa: E402  core/

FAILURES = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


print("=" * 70)
print("[0] 环境")
check(_REPO_ROOT is not None, "仓库根定位（src/core/pcd_utils.py）",
      _REPO_ROOT or "未找到")

from PySide6.QtWidgets import QApplication      # noqa: E402
from window import RobotHandEyeWindow           # noqa: E402  app/
from core.pcd_utils import merge_pointclouds    # noqa: E402  src/
import open3d as o3d                            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
win = RobotHandEyeWindow()

# 演示矩阵与位姿（同 --smoke 口径；eye-in-hand）
HE_VALS = [1, 0, 0, 20, 0, 1, 0, -10, 0, 0, 1, 120, 0, 0, 0, 1]
DEMO = [ps_mod.euler_to_matrix([x, y, z], [rx, ry, rz], "ZYX")
        for x, y, z, rx, ry, rz in
        [(400, 100, 420, 0, 0, 0),
         (420, 110, 430, 0, 20, 25),
         (410, 120, 425, 25, 0, -20)]]
P_TIP_BASE = np.array([400.0, 100.0, 420.0])

ok_he, msg_he, he_res = he_mod.HandEyeResult.from_matrix(HE_VALS, "mm", True)
check(ok_he, "演示手眼矩阵加载（A7 守卫通过）", msg_he[:50])

print("=" * 70)
print("[1] A3 导出门禁接线（按钮状态机）")
win._on_handeye_result(ok_he, msg_he, he_res)
check(not win.panel.btn_save_ply.isEnabled(),
      "UNVERIFIED → 保存合并 PLY 置灰")
check(not win.panel.btn_export.isEnabled(),
      "UNVERIFIED → 保存会话置灰")
check(not win.panel.btn_tip_record.isEnabled() is False,
      "矩阵已加载 → 戳点按钮可用")

print("=" * 70)
print("[2] A4 端到端：3 位姿采集 → 三帧逐帧真值 → 合并 → PLY 往返")
win.pose_src = ps_mod.MockPoseSource(DEMO, "mm", "absolute")
win._mock_started = False
truth_pts = []
for i in range(3):
    ok, msg, pcd = win.capture_job()
    check(ok, f"第 {i + 1} 帧采集", msg[:60])
    # 解析真值（内联矩阵乘，不调被测函数；与 A1 §[1] / smoke 同口径）
    cam = np.asarray(
        __import__("window").make_camera_frame(seed=i + 1).points)
    T_bt = DEMO[i]
    T_cb = T_bt @ he_res.T_handeye_mm
    hom = np.concatenate([cam, np.ones((len(cam), 1))], axis=1)
    truth = (T_cb @ hom.T).T[:, :3]
    truth_pts.append(truth)
    got = np.asarray(pcd.points)
    err = float(np.max(np.abs(got - truth)))
    check(err < 1e-9, f"第 {i + 1} 帧基座系点云 vs 解析真值 < 1e-9 mm",
          f"err={err:.3e}")
check(len(win.captured_frames) == 3 and len(win.captured_poses) == 3,
      "帧/位姿列表入列（A6 数据源）", f"frames={len(win.captured_frames)}")

# 戳点 → VERIFIED（真值链针尖观测；位姿取自位姿源当前帧，录一个步进一次）
for _ in range(3):
    okp, _, Tp = win.pose_src.get_pose()
    T_cb = Tp @ he_res.T_handeye_mm
    tip_cam = (np.linalg.inv(T_cb) @ np.append(P_TIP_BASE, 1.0))[:3]
    win.on_tip_record(", ".join(f"{v:.3f}" for v in tip_cam))
    win.pose_src.step_next()
win.on_tip_check()
check(win.handeye.validated, "戳点门禁 PASS → VERIFIED",
      f"err_mean={win.tip_report['err_mean_mm']:.3f} mm")
check(win.panel.btn_save_ply.isEnabled() and win.panel.btn_export.isEnabled(),
      "VERIFIED → 保存合并 PLY / 保存会话解锁")

# 合并 → 保存 PLY → 重新加载
import tempfile
work = tempfile.mkdtemp(prefix="mcc_a4_")
merged = win.merged_pcd()
check(merged is not None and len(merged.points) == 3 * 20000,
      "merge_pointclouds 合并点数 = 3×20000（保色合并不丢点）",
      f"n={len(merged.points)} colors={np.asarray(merged.colors).shape[0]}")
ply_path = os.path.join(work, "merged_base.ply")
o3d.io.write_point_cloud(ply_path, merged)
reloaded = o3d.io.read_point_cloud(ply_path)
check(len(reloaded.points) == len(merged.points),
      "PLY 重载点数与内存一致（A4 门槛）",
      f"mem={len(merged.points)} disk={len(reloaded.points)}")
from scipy.spatial import cKDTree
truth_all = np.vstack(truth_pts)
dist, _ = cKDTree(np.asarray(reloaded.points)).query(truth_all, k=1)
median = float(np.median(dist))
check(median < 0.5, "合并云 vs 解析真值最近邻中位数 < 0.5 mm（A4 门槛）",
      f"median={median:.6f} mm")

print("=" * 70)
print("[3] 清空后保存合并 PLY 回锁（fail-closed；会话保存仍允许 0 帧）")
win.on_clear()
check(not win.panel.btn_save_ply.isEnabled(),
      "清空（0 帧）→ 保存合并 PLY 回锁")
check(win.panel.btn_export.isEnabled(),
      "会话保存保持解锁（矩阵仍 VERIFIED，0 帧会话合法）——两键语义不同")
check(len(win.captured_frames) == 0, "帧列表已清空", "")

print("=" * 70)
print("[4] A5 实时性：30 万点**单帧** 复制+变换+合并 < 50 ms（方案口径）")
rng = np.random.default_rng(0)
big = rng.uniform([-150, -100, 400], [150, 100, 600], (300000, 3))
big_pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(big))
big_pcd.colors = o3d.utility.Vector3dVector(rng.random((300000, 3)))
# 累加器种子 30 万点（稳态：往已有合并结果上并一帧）。重建属被测外的准备，不计时——
# 被测两段与 @qa 基线口径严格同项：copy+transform（transform_pcd 内含 copy）/ merge。
acc_seed = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
    rng.uniform([-150, -100, 400], [150, 100, 600], (300000, 3))))
acc_seed.colors = o3d.utility.Vector3dVector(rng.random((300000, 3)))
T_cb = DEMO[0] @ he_res.T_handeye_mm
import time
durs = []
for _ in range(5):
    acc = o3d.geometry.PointCloud(acc_seed)                # 准备（不计时）
    t0 = time.perf_counter()
    c1 = transform_chain.transform_pcd(big_pcd, T_cb)      # copy + transform（单帧）
    m = merge_pointclouds(acc, c1)                         # 保色合并入累加器
    durs.append((time.perf_counter() - t0) * 1000.0)
med = float(np.median(durs))
check(med < 50.0, "30 万点单帧 复制+变换+合并 中位耗时 < 50 ms（A5 门槛）",
      f"median={med:.1f} ms  runs={['%.1f' % d for d in durs]}")
check(len(m.points) == 600000, "合并后点数 600000", f"n={len(m.points)}")

win.close()
import shutil
shutil.rmtree(work, ignore_errors=True)

print("=" * 70)
if FAILURES:
    print(f"[FAILED] {len(FAILURES)} 项失败:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("[ALL OK] test_ui_smoke")
sys.exit(0)
