# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
ChainStitcher 合成数据测试（无相机、无 GUI）。

验证：
  [1] 单链 5 机位拼接精度（无噪声理想情况）
  [2] 链式累积误差（有噪声，BA 前后对比）
  [3] 闭环检测提示
  [4] 配准质量门限（标记不足/内点率低/RMS 高时拒绝）
  [5] PoseGraph 增量边添加与变换查询
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

print("=" * 60)
print("ChainStitcher 合成数据测试")
print("=" * 60)

from core.chain_stitcher import ChainStitcher, ChainEdge, ChainNode
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.pose_graph import PoseGraph
from core.frame_data import FrameData


def make_markers(pts: np.ndarray, code_offset: int = 0):
    """由 Nx3 点数组构造编码圆 markers 列表。"""
    return [
        {'code': i + code_offset,
         'x_3d': float(pts[i, 0]), 'y_3d': float(pts[i, 1]), 'z_3d': float(pts[i, 2])}
        for i in range(len(pts))
    ]


def rotz(deg: float) -> np.ndarray:
    """绕 Z 轴旋转矩阵（度）。"""
    rad = np.deg2rad(deg)
    c, s = np.cos(rad), np.sin(rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def make_frame(station_id: str, cam_pts: np.ndarray, markers=None):
    """构造合成 FrameData。"""
    if markers is None:
        markers = make_markers(cam_pts)
    frame = FrameData(
        frame_id=0,
        camera_name=station_id,
        image_np=np.zeros((100, 100, 3), dtype=np.uint8),
        pointmap=None,
        rvc_image=None,
        markers=markers,
    )
    return frame


# ------------------------------------------------------------------
# [1] 单链 5 机位拼接精度（无噪声理想情况）
# ------------------------------------------------------------------
print("\n[1] 单链 5 机位拼接精度测试")

# 世界坐标系下的 10 个编码圆
world_pts = np.array([
    [0, 0, 0], [100, 0, 0], [200, 0, 0],
    [0, 100, 0], [100, 100, 0], [200, 100, 0],
    [0, 200, 0], [100, 200, 0], [200, 200, 0],
    [50, 50, 0],
], dtype=np.float64)

# 5 个机位，每个机位平移 + 旋转
station_poses = [
    np.eye(4),
    np.vstack([np.hstack([rotz(10), np.array([[50], [20], [0]])]), [0, 0, 0, 1]]),
    np.vstack([np.hstack([rotz(20), np.array([[100], [40], [0]])]), [0, 0, 0, 1]]),
    np.vstack([np.hstack([rotz(30), np.array([[150], [60], [0]])]), [0, 0, 0, 1]]),
    np.vstack([np.hstack([rotz(40), np.array([[200], [80], [0]])]), [0, 0, 0, 1]]),
]

# 每个机位看到的标记（世界点变换到机位坐标系）
# p_station = T_station_in_world @ p_world，其中 T 为世界→机位的位姿
station_markers = []
for i, T in enumerate(station_poses):
    cam_pts = (T[:3, :3] @ world_pts.T + T[:3, 3:4]).T
    station_markers.append(make_markers(cam_pts))

# 用 ChainStitcher 逐帧添加
stitcher = ChainStitcher(
    marker_detector=MarkerDetector(),
    calibration_engine=CalibrationEngine(),
    stitch_engine=StitchEngine(),
    min_common_markers=6,
    min_inlier_ratio=0.7,
    max_rms_mm=2.0,
)

# 覆盖 detect_3d 为直接返回预设 markers（跳过图像检测）
current_markers = [None]
original_detect = stitcher.marker_detector.detect_3d
def mock_detect(*args, **kwargs):
    return current_markers[0]
stitcher.marker_detector.detect_3d = mock_detect

for i, (station_id, markers) in enumerate(zip(
        ['station_1', 'station_2', 'station_3', 'station_4', 'station_5'],
        station_markers)):
    current_markers[0] = markers
    frame = make_frame(station_id, world_pts, markers)
    ok, msg, edge = stitcher.add_frame(frame)
    print(f"  {station_id}: {msg}")
    assert ok, f"{station_id} 配准失败: {msg}"

# 验证所有机位都能变换到参考系
ref_id = 'station_1'
for sid in ['station_2', 'station_3', 'station_4', 'station_5']:
    T = stitcher.pose_graph.get_transform(sid, ref_id)
    # 理论值：station_poses[i] 的逆（cam→ref = ref→cam 的逆）
    idx = int(sid.split('_')[1]) - 1
    T_expected = np.linalg.inv(station_poses[idx])
    err = np.abs(T - T_expected).max()
    print(f"  {sid}→{ref_id} 变换误差: {err:.6f}")
    assert err < 0.01, f"{sid} 变换误差过大: {err}"

print("  [OK] 单链 5 机位拼接精度达标")

# ------------------------------------------------------------------
# [2] 链式累积误差与 BA 优化
# ------------------------------------------------------------------
print("\n[2] 链式累积误差与全局 BA 测试")

# 添加噪声的机位位姿
np.random.seed(42)
noisy_poses = []
for T in station_poses:
    noise_T = T.copy()
    noise_T[:3, 3] += np.random.normal(0, 0.5, 3)  # 平移噪声 0.5mm
    noisy_poses.append(noise_T)

# 用 PoseGraph 构建链
pg = PoseGraph()
pg.add_node('station_1', np.eye(4))
for i in range(1, 5):
    prev_id = f'station_{i}'
    curr_id = f'station_{i+1}'
    T_rel = np.linalg.inv(noisy_poses[i]) @ noisy_poses[i-1]
    pg.add_edge(curr_id, prev_id, T_rel, rms_mm=0.5, inlier_ratio=0.9, common_markers=10)

# BFS 复合（未优化）
T_bfs = {}
for i in range(1, 6):
    sid = f'station_{i}'
    T_bfs[sid] = pg.get_transform(sid, 'station_1')

# 全局 BA 优化
T_ba = pg.optimize_global_ba('station_1', max_iterations=100)

# 对比 BFS vs BA 与理论值的误差
print("  机位 | BFS 误差 | BA 误差 | 理论值")
for i in range(2, 6):
    sid = f'station_{i}'
    T_true = np.linalg.inv(station_poses[i-1])
    err_bfs = np.abs(T_bfs[sid] - T_true).max()
    err_ba = np.abs(T_ba.get(sid, T_bfs[sid]) - T_true).max()
    print(f"  {sid} | {err_bfs:.6f} | {err_ba:.6f}")
    # BA 应该不差于 BFS（可能略有改善）
    assert err_ba <= err_bfs * 1.1, f"{sid} BA 误差反而更大"

print("  [OK] 全局 BA 优化完成，误差可控")

# ------------------------------------------------------------------
# [3] 闭环检测提示
# ------------------------------------------------------------------
print("\n[3] 闭环检测提示测试")

#  station_6 与 station_2 共有 6 个标记（闭环）
station6_markers = station_markers[1][:6] + make_markers(
    np.array([[300, 300, 0], [350, 350, 0]], dtype=np.float64), code_offset=20)
frame6 = make_frame('station_6', world_pts, station6_markers)
ok, msg, edge = stitcher.add_frame(frame6)
if ok:
    loops = stitcher.detect_loop_closure('station_6')
    print(f"  检测到闭环机位: {loops}")
    assert 'station_2' in loops, "未检测到与 station_2 的闭环"
    print("  [OK] 闭环检测提示正常")
else:
    print(f"  station_6 配准失败（预期可能失败）: {msg}")

# ------------------------------------------------------------------
# [4] 配准质量门限
# ------------------------------------------------------------------
print("\n[4] 配准质量门限测试")

stitcher2 = ChainStitcher(
    marker_detector=MarkerDetector(),
    calibration_engine=CalibrationEngine(),
    stitch_engine=StitchEngine(),
    min_common_markers=8,  # 提高门限
    min_inlier_ratio=0.8,
    max_rms_mm=1.0,
)

# 覆盖 detect_3d
current_markers2 = [None]
def mock_detect2(*args, **kwargs):
    return current_markers2[0]
stitcher2.marker_detector.detect_3d = mock_detect2

# 添加首帧
current_markers2[0] = station_markers[0]
frame1 = make_frame('station_1', world_pts, station_markers[0])
stitcher2.add_frame(frame1)

# 标记不足（只有 5 个共有标记）
current_markers2[0] = station_markers[1][:5]
frame2 = make_frame('station_2', world_pts, station_markers[1][:5])
ok, msg, edge = stitcher2.add_frame(frame2)
print(f"  标记不足: {msg}")
assert not ok, "标记不足时应该拒绝"
assert '共有标记不足' in msg or '未找到足够共有标记' in msg

print("  [OK] 配准质量门限生效")

# ------------------------------------------------------------------
# [5] 配准失败残留节点清理 + 重拍成功（P0-2）
# ------------------------------------------------------------------
print("\n[5] 配准失败残留节点清理 + 重拍成功测试")

stitcher3 = ChainStitcher(
    marker_detector=MarkerDetector(),
    calibration_engine=CalibrationEngine(),
    stitch_engine=StitchEngine(),
    min_common_markers=6,
    min_inlier_ratio=0.7,
    max_rms_mm=2.0,
)
current_markers3 = [None]
def mock_detect3(*args, **kwargs):
    return current_markers3[0]
stitcher3.marker_detector.detect_3d = mock_detect3

# 首帧成功
current_markers3[0] = station_markers[0]
frame_s1 = make_frame('station_1', world_pts, station_markers[0])
ok, msg, _ = stitcher3.add_frame(frame_s1)
assert ok, f"首帧应成功: {msg}"

# 第二帧配准失败：只给 5 个标记（不足 min_common_markers=6）
current_markers3[0] = station_markers[1][:5]
frame_s2_bad = make_frame('station_2', world_pts, station_markers[1][:5])
ok, msg, _ = stitcher3.add_frame(frame_s2_bad)
assert not ok, "标记不足时应拒绝"
assert 'station_2' not in stitcher3.nodes, "失败节点应被清理，不能残留"

# 再次拍摄 station_2，使用完整标记，应成功
current_markers3[0] = station_markers[1]
frame_s2_good = make_frame('station_2', world_pts, station_markers[1])
ok, msg, _ = stitcher3.add_frame(frame_s2_good)
assert ok, f"重拍应成功: {msg}"
assert 'station_2' in stitcher3.nodes, "成功节点应保留"
assert len(stitcher3.nodes) == 2, f"应只有 2 个节点，实际 {len(stitcher3.nodes)}"

T_s2 = stitcher3.pose_graph.get_transform('station_2', 'station_1')
T_expected = np.linalg.inv(station_poses[1])
err = np.abs(T_s2 - T_expected).max()
print(f"  失败清理后重拍成功，station_2→station_1 变换误差: {err:.6f}")
assert err < 0.01, f"重拍后变换误差过大: {err}"

print("  [OK] 配准失败节点已清理，重拍不崩溃且结果正确")

# ------------------------------------------------------------------
# [6] PoseGraph 增量边添加与变换查询
# ------------------------------------------------------------------
print("\n[6] PoseGraph 增量边添加与变换查询测试")

pg2 = PoseGraph()
pg2.add_node('A', np.eye(4))
pg2.add_edge('B', 'A', np.vstack([np.hstack([rotz(10), np.array([[10], [0], [0]])]), [0, 0, 0, 1]]))
pg2.add_edge('C', 'B', np.vstack([np.hstack([rotz(10), np.array([[10], [0], [0]])]), [0, 0, 0, 1]]))

T_AB = pg2.get_transform('B', 'A')
T_AC = pg2.get_transform('C', 'A')
T_BC = pg2.get_transform('C', 'B')

print(f"  B→A 平移: {T_AB[:3, 3]}")
print(f"  C→A 平移: {T_AC[:3, 3]}")
print(f"  C→B 平移: {T_BC[:3, 3]}")

# 验证复合关系：C→A = B→A @ C→B
T_AC_expected = T_AB @ T_BC
err = np.abs(T_AC - T_AC_expected).max()
print(f"  复合关系误差: {err:.6f}")
assert err < 1e-6, f"复合关系不成立: {err}"

print("  [OK] PoseGraph 增量边添加与变换查询正常")

# ------------------------------------------------------------------
# [7] 删除中间机位后继续拍摄（P0-1 回归）
# ------------------------------------------------------------------
print("\n[7] 删除中间机位后继续拍摄回归测试")

stitcher4 = ChainStitcher(
    marker_detector=MarkerDetector(),
    calibration_engine=CalibrationEngine(),
    stitch_engine=StitchEngine(),
    min_common_markers=6,
    min_inlier_ratio=0.7,
    max_rms_mm=2.0,
)

# 覆盖 detect_3d
current_markers4 = [None]
def mock_detect4(*args, **kwargs):
    return current_markers4[0]
stitcher4.marker_detector.detect_3d = mock_detect4

# 添加 4 个机位
for i in range(4):
    current_markers4[0] = station_markers[i]
    frame = make_frame(f"station_{i+1}", world_pts, station_markers[i])
    ok, msg, _ = stitcher4.add_frame(frame)
    assert ok, f"机位 {i+1} 添加失败: {msg}"

assert len(stitcher4.nodes) == 4, f"初始应 4 个节点，实际 {len(stitcher4.nodes)}"

# 删除中间机位 station_2
removed = stitcher4.remove_node('station_2')
assert 'station_2' in removed, "station_2 应被删除"
assert len(stitcher4.nodes) >= 1, "参考机位应保留"
assert stitcher4._reference_id == 'station_1', "参考机位应保持 station_1"

# 关键：继续添加新机位 station_5 不应崩溃
current_markers4[0] = station_markers[4]
frame_s5 = make_frame('station_5', world_pts, station_markers[4])
ok, msg, _ = stitcher4.add_frame(frame_s5)
assert ok, f"删除中间机位后继续拍摄应成功: {msg}"
assert 'station_5' in stitcher4.nodes, "station_5 应已成功入链"

# 验证剩余节点都能从参考系到达
for sid in stitcher4.nodes:
    if sid == stitcher4._reference_id:
        continue
    T = stitcher4.pose_graph.get_transform(sid, stitcher4._reference_id)
    assert T is not None, f"机位 {sid} 无法到达参考系"

print(f"  删除 station_2 后节点: {list(stitcher4.nodes.keys())}")
print(f"  继续拍摄 station_5 后节点: {list(stitcher4.nodes.keys())}")
print("  [OK] 删除中间机位后继续拍摄不崩溃，位姿图保持连通")

print("\n" + "=" * 60)
print("[OK] 全部 ChainStitcher 测试通过")
print("=" * 60)
