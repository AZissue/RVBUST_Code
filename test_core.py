# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration core 模块测试（无 GUI、无需相机）

验证：
  [1] CalibrationEngine 合成数据标定精度（8 点对 + 噪声）
  [2] 多帧四元数平均 q/-q 符号歧义修复
  [3] N=3 相机 pair 标定（ref-A、ref-B 两对）
  [4] CameraManager 无相机环境优雅降级
  [5] get_transform 直达 / 求逆 / 链式复合三种路径
  [6] 标定结果 save / load
  [7] PoseGraph BFS：星型 / 链式 / 不连通 / 自身（Phase 2）
  [8] StitchEngine：3 相机拼接 / 空点云跳过 / 体素下采样（Phase 2）
  [9] 集成测试：3 相机标定 → get_transform → stitch 拼接（Phase 2）
  [10] PointCloudProcessor.auto_tune 自动参数估计（单位/点距/体素/裁切/全流程）
"""
import os
import sys
import tempfile
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

print("=" * 60)
print("MultiCameraCalibration core 模块测试")
print("=" * 60)

from core.calibration_engine import CalibrationEngine
from core.camera_manager import CameraManager
from core.calib_board_detector import CalibBoardDetector
from core.marker_detector import MarkerDetector, MARKER_TYPE_ASYMMETRIC_GRID
import cv2


def make_markers(pts: np.ndarray, code_offset: int = 0):
    """由 Nx3 点数组构造编码圆 markers 列表。"""
    return [
        {'code': i + code_offset,
         'x_3d': float(pts[i, 0]), 'y_3d': float(pts[i, 1]), 'z_3d': float(pts[i, 2])}
        for i in range(len(pts))
    ]


def rotz(deg: float) -> np.ndarray:
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0],
                     [np.sin(a),  np.cos(a), 0],
                     [0, 0, 1]])


# ------------------------------------------------------------------
# 1. 合成数据标定精度测试
# ------------------------------------------------------------------
print("\n[1] 标定精度测试（8 点对 + 0.5mm 噪声）")
engine = CalibrationEngine()

np.random.seed(42)
n_markers = 8
R_true = rotz(15)                    # ref→cam 的真实旋转
t_true = np.array([100.0, 50.0, 20.0])  # ref→cam 的真实平移（mm）

pts_ref = np.random.rand(n_markers, 3) * 200 + np.array([50, 50, 100])
pts_cam = (pts_ref @ R_true.T + t_true) + np.random.randn(n_markers, 3) * 0.5

res = engine.calibrate_pair("ref", "cam0",
                            make_markers(pts_ref), make_markers(pts_cam),
                            ransac_threshold=2.0)
assert res.get('success'), f"标定失败: {res.get('message')}"
print(f"  标定成功 | 内点: {res['inlier_count']}/{res['total_pairs']} | "
      f"RMS: {res['rms_mm']:.3f} mm | 内点率: {res['inlier_ratio']:.2f}")

# T 是 cam→ref，真值为 ref→cam 的逆
R_true_c2r = R_true.T
t_true_c2r = -R_true_c2r @ t_true
R_est = res['T'][:3, :3]
t_est = res['T'][:3, 3]
R_diff = np.linalg.norm(R_est - R_true_c2r, ord='fro')
t_diff = np.linalg.norm(t_est - t_true_c2r)
print(f"  旋转误差 (Frobenius): {R_diff:.6f}")
print(f"  平移误差: {t_diff:.3f} mm")
assert R_diff < 0.1, f"旋转误差过大: {R_diff}"
assert t_diff < 2.0, f"平移误差过大: {t_diff}"
assert engine.reference_id == "ref", "参考相机应自动设为 ref"
print("  [OK] 标定精度满足要求（旋转<0.1, 平移<2mm）")

# 1b. 含离谱离群点：rms_mm 只按内点统计，离群信息单独报告
print("\n[1b] 离群点排除统计测试（8 内点 + 1 离谱离群点）")
engine_ob = CalibrationEngine()
pts_ref_ob = np.vstack([pts_ref, [[100.0, 100.0, 150.0]]])  # 第 9 个标记（code=8）
pts_cam_ob = (pts_ref_ob @ R_true.T + t_true) + np.random.randn(9, 3) * 0.5
pts_cam_ob[8] += np.array([200.0, 0.0, 0.0])   # code=8 严重偏离 → 离群点
res_ob = engine_ob.calibrate_pair("ref", "cam0",
                                  make_markers(pts_ref_ob), make_markers(pts_cam_ob),
                                  ransac_threshold=2.0)
assert res_ob.get('success'), f"含离群点标定失败: {res_ob.get('message')}"
print(f"  内点 {res_ob['inlier_count']}/{res_ob['total_pairs']} | "
      f"内点 RMS {res_ob['rms_mm']:.3f} mm | 全量 RMS {res_ob['rms_all_mm']:.3f} mm | "
      f"离群 code: {res_ob['outlier_codes']}")
assert res_ob['inlier_count'] == 8 and res_ob['total_pairs'] == 9
assert res_ob['outlier_count'] == 1, f"离群点数应为 1: {res_ob['outlier_count']}"
assert res_ob['outlier_codes'] == [8], f"离群 code 应为 [8]: {res_ob['outlier_codes']}"
assert res_ob['rms_mm'] < 2.0, f"内点 RMS 应为内点级小值: {res_ob['rms_mm']}"
assert res_ob['rms_all_mm'] > res_ob['rms_mm'] * 5, \
    f"全量 RMS {res_ob['rms_all_mm']} 应远大于内点 RMS {res_ob['rms_mm']}"
# details 结构不变：按误差降序，离群点排在最前且 is_inlier=False
assert res_ob['details'][0]['code'] == 8 and not res_ob['details'][0]['is_inlier']
assert len(res_ob['details']) == 9
print("  [OK] 离群点已排除：内点 RMS 小值 / outlier_count=1 / outlier_codes=[8] / rms_all_mm 全量")

# ------------------------------------------------------------------
# 2. 多帧四元数平均符号歧义修复验证
# ------------------------------------------------------------------
print("\n[2] 四元数 q/-q 符号歧义修复测试")
from scipy.spatial.transform import Rotation

# 构造一对异号四元数（表示同一旋转）；未修复时 np.mean 相互抵消 → NaN
q1 = np.array([0.5, 0.5, 0.5, 0.5])   # 单位四元数
q2 = -q1                               # 同一旋转的异号表示
q_avg = CalibrationEngine._average_quaternions([q1, q2])
norm = np.linalg.norm(q_avg)
same_rotation = abs(np.dot(q_avg, q1)) > 0.9999
print(f"  平均四元数范数: {norm:.6f}（未修复时约为 0/NaN）")
print(f"  与 q1 同旋转: {same_rotation}")
assert np.isfinite(q_avg).all(), "平均四元数含 NaN（符号歧义未修复）"
assert abs(norm - 1.0) < 1e-9, f"平均四元数未归一: {norm}"
assert same_rotation, "平均结果与原旋转不一致"
print("  [OK] 异号四元数平均正确（半球统一生效）")

# 端到端：多帧标定走通 calibrate_multi_frame
engine_mf = CalibrationEngine()
for i in range(4):
    noise_ref = np.random.randn(n_markers, 3) * 0.3
    noise_cam = np.random.randn(n_markers, 3) * 0.3
    engine_mf.add_frame_data("ref", "cam0",
                             make_markers(pts_ref + noise_ref),
                             make_markers(pts_cam + noise_cam))
res_mf = engine_mf.calibrate_multi_frame("ref", "cam0", ransac_threshold=2.0)
assert res_mf.get('success'), f"多帧标定失败: {res_mf.get('message')}"
R_diff_mf = np.linalg.norm(res_mf['T'][:3, :3] - R_true_c2r, ord='fro')
t_diff_mf = np.linalg.norm(res_mf['T'][:3, 3] - t_true_c2r)
print(f"  多帧平均: 有效帧 {res_mf['valid_frames']}/4 | "
      f"旋转误差 {R_diff_mf:.6f} | 平移误差 {t_diff_mf:.3f} mm")
assert R_diff_mf < 0.1 and t_diff_mf < 2.0, "多帧平均精度不足"
# 内点语义与单帧模式统一：按标记统计（合成数据无离群点 → 全部内点）
assert res_mf['valid_frames'] == 4 and res_mf['total_frames'] == 4, "帧数统计异常"
assert res_mf['total_pairs'] == 4 * n_markers, \
    f"total_pairs 应为所有帧匹配标记总数: {res_mf['total_pairs']}"
assert res_mf['inlier_count'] == res_mf['total_pairs'], \
    f"无离群点时内点标记应等于匹配标记: {res_mf['inlier_count']}"
assert res_mf['outlier_count'] == 0 and res_mf['outlier_codes'] == []
assert res_mf['rms_mm'] == res_mf['rms_all_mm'], "无离群点时内点 RMS 应等于全量 RMS"
print(f"  内点标记 {res_mf['inlier_count']}/{res_mf['total_pairs']} "
      f"（{res_mf['valid_frames']} 帧 × {n_markers} 标记，语义与单帧统一）")
print("  [OK] 多帧标定端到端通过")

# ------------------------------------------------------------------
# 3. N=3 相机 pair 标定测试
# ------------------------------------------------------------------
print("\n[3] N=3 相机 pair 标定（ref / camA / camB）")
engine3 = CalibrationEngine()

# 标定板点（ref 坐标系真值）
np.random.seed(7)
board_ref = np.random.rand(10, 3) * 150 + np.array([0, 0, 200])

# 两台相机的 cam→ref 真值外参
T_a2r = np.eye(4); T_a2r[:3, :3] = rotz(20);  T_a2r[:3, 3] = [80, -30, 10]
T_b2r = np.eye(4); T_b2r[:3, :3] = rotz(-25); T_b2r[:3, 3] = [-60, 40, 25]

def world_to_cam(pts_ref_frame, T_c2r):
    """p_ref = p_cam @ R.T + t  →  p_cam = (p_ref - t) @ R"""
    R = T_c2r[:3, :3]
    t = T_c2r[:3, 3]
    return (pts_ref_frame - t) @ R

pts_in_a = world_to_cam(board_ref, T_a2r) + np.random.randn(10, 3) * 0.4
pts_in_b = world_to_cam(board_ref, T_b2r) + np.random.randn(10, 3) * 0.4

res_a = engine3.calibrate_pair("ref", "camA", make_markers(board_ref), make_markers(pts_in_a),
                               ransac_threshold=2.0)
res_b = engine3.calibrate_pair("ref", "camB", make_markers(board_ref), make_markers(pts_in_b),
                               ransac_threshold=2.0)
assert res_a.get('success') and res_b.get('success'), "N=3 pair 标定失败"

for name, res, T_true in [("camA", res_a, T_a2r), ("camB", res_b, T_b2r)]:
    Rd = np.linalg.norm(res['T'][:3, :3] - T_true[:3, :3], ord='fro')
    td = np.linalg.norm(res['T'][:3, 3] - T_true[:3, 3])
    print(f"  {name}→ref: 旋转误差 {Rd:.6f} | 平移误差 {td:.3f} mm | RMS {res['rms_mm']:.3f} mm")
    assert Rd < 0.1 and td < 2.0, f"{name} 标定精度不足"

assert len(engine3.pair_results) == 2
assert engine3.is_calibrated("ref", "camA") and engine3.is_calibrated("ref", "camB")
print("  [OK] N=3 两对 pair 标定精度均满足要求")

# ------------------------------------------------------------------
# 4. CameraManager 无相机环境优雅降级
# ------------------------------------------------------------------
print("\n[4] CameraManager 优雅降级测试（无相机/无 SDK 不崩溃）")
mgr = CameraManager()
ok_init, msg_init = mgr.initialize()
print(f"  initialize: {ok_init} ({msg_init})")

assert mgr.add_camera("cam0") is True
assert mgr.add_camera("cam0") is False, "重复 add_camera 应返回 False"

# 用越界索引连接：无论有无真实设备都必须返回 False 且不崩溃
ok, msg = mgr.connect("cam0", device_index=999)
assert ok is False, "越界索引连接应失败"
print(f"  connect 越界索引: 正确返回 False ({msg})")
assert mgr.is_connected("cam0") is False
assert mgr.get_connected_ids() == []

ok, msg = mgr.connect("ghost", device_index=0)
assert ok is False, "未注册相机连接应失败"
print(f"  connect 未注册相机: 正确返回 False ({msg})")

# 无连接时 capture / capture_all 返回空，不崩溃
assert mgr.capture("cam0") is None
frames = mgr.capture_all()
assert frames == {}, f"无连接时 capture_all 应返回空 dict, 实际: {frames}"
mgr.remove_camera("cam0")
mgr.disconnect_all()
mgr.shutdown()
print("  [OK] CameraManager 优雅降级通过")

# ------------------------------------------------------------------
# 5. get_transform 三种路径
# ------------------------------------------------------------------
print("\n[5] get_transform 直达 / 求逆 / 链式 hook")
# 直达：camA→ref（存储方向即 cam→ref）
T_direct = engine3.get_transform("camA", "ref")
assert np.allclose(T_direct, res_a['T']), "直达路径结果不一致"
print("  [OK] 直达 pair: camA→ref")

# 求逆：ref→camA（存储方向的逆）
T_inv = engine3.get_transform("ref", "camA")
assert np.allclose(T_inv, np.linalg.inv(res_a['T']), atol=1e-9), "求逆路径结果不一致"
# 验证 inv(T) @ T = I
assert np.allclose(T_inv @ T_direct, np.eye(4), atol=1e-9)
print("  [OK] 求逆 pair: ref→camA（与直达互逆）")

# 自身
assert np.allclose(engine3.get_transform("ref", "ref"), np.eye(4))

# 链式：camA→camB 无直达 pair → 委托 pose_graph BFS（Phase 2 已实现）
# 星型拓扑下走 ref 中转：T_camA→camB = inv(T_camB→ref) @ T_camA→ref
T_chain = engine3.get_transform("camA", "camB")
T_chain_expect = np.linalg.inv(res_b['T']) @ res_a['T']
assert np.allclose(T_chain, T_chain_expect, atol=1e-9), "链式复合结果不一致"
print("  [OK] 链式 hook: camA→camB 经 ref 中转复合正确")

# ------------------------------------------------------------------
# 6. save / load
# ------------------------------------------------------------------
print("\n[6] 标定结果保存 / 加载")
fd, tmp_path = tempfile.mkstemp(suffix=".json")
os.close(fd)
os.unlink(tmp_path)

assert engine3.save_calibration(tmp_path), "保存失败"
assert os.path.exists(tmp_path)
engine4 = CalibrationEngine()
assert engine4.load_calibration(tmp_path), "加载失败"
assert engine4.reference_id == "ref"
assert len(engine4.pair_results) == 2
assert np.allclose(engine4.pair_results[("ref", "camA")]['T'], res_a['T'])
os.unlink(tmp_path)
print("  [OK] save/load 一致（reference_id + 2 对 pair）")

# ------------------------------------------------------------------
# 7. PoseGraph BFS：星型 / 链式 / 不连通 / 自身
# ------------------------------------------------------------------
print("\n[7] PoseGraph BFS 路径复合测试")
from core import pose_graph

# 7a. 到自身：单位阵（即使图完全为空）
assert np.allclose(pose_graph.find_path_transform({}, "camX", "camX"), np.eye(4))
print("  [OK] 到自身返回单位矩阵")

# 7b. 星型拓扑：camA/camB 都有到 ref 的直达 pair
#     即使走 BFS（经 ref 中转）结果也必须正确
star_pairs = {
    ("ref", "camA"): {'T': T_a2r.copy(), 'success': True},
    ("ref", "camB"): {'T': T_b2r.copy(), 'success': True},
}
T_ab = pose_graph.find_path_transform(star_pairs, "camA", "camB")
T_ab_expect = np.linalg.inv(T_b2r) @ T_a2r   # camA→ref→camB
assert np.allclose(T_ab, T_ab_expect, atol=1e-9), "星型拓扑 BFS 复合错误"
print("  [OK] 星型拓扑: camA→camB 经 ref 中转复合正确")

# 7c. 链式拓扑：cam1-cam2、cam2-cam3 有 pair，cam1-cam3 无直达
T_2to1 = np.eye(4); T_2to1[:3, :3] = rotz(30);  T_2to1[:3, 3] = [10, 20, 30]
T_3to2 = np.eye(4); T_3to2[:3, :3] = rotz(-40); T_3to2[:3, 3] = [-5, 15, 25]
chain_pairs = {
    ("cam1", "cam2"): {'T': T_2to1.copy(), 'success': True},  # 存 cam2→cam1
    ("cam2", "cam3"): {'T': T_3to2.copy(), 'success': True},  # 存 cam3→cam2
}
T_1to3 = pose_graph.find_path_transform(chain_pairs, "cam1", "cam3")
T_1to3_expect = np.linalg.inv(T_3to2) @ np.linalg.inv(T_2to1)  # T_2→3 @ T_1→2
assert np.allclose(T_1to3, T_1to3_expect, atol=1e-9), "链式拓扑 BFS 链乘错误"

# 用随机点验证几何意义：p_cam3 = T_1to3 @ p_cam1
np.random.seed(11)
p1 = np.random.rand(50, 3) * 100
p1_h = np.hstack([p1, np.ones((50, 1))])
p3_via_chain = (T_1to3 @ p1_h.T).T[:, :3]
# 手动逐级变换：cam1→cam2 用 inv(T_2to1)，cam2→cam3 用 inv(T_3to2)
p2 = (np.linalg.inv(T_2to1) @ p1_h.T).T
p3_manual = (np.linalg.inv(T_3to2) @ p2.T).T[:, :3]
assert np.allclose(p3_via_chain, p3_manual, atol=1e-9), "链式复合几何意义错误"
# 反方向应互逆
T_3to1 = pose_graph.find_path_transform(chain_pairs, "cam3", "cam1")
assert np.allclose(T_3to1 @ T_1to3, np.eye(4), atol=1e-9), "往返复合应互逆"
print("  [OK] 链式拓扑: cam1→cam3 两步链乘正确（含几何验证与往返互逆）")

# 7d. 不连通：cam4 孤立 → ValueError
try:
    pose_graph.find_path_transform(chain_pairs, "cam1", "cam4")
    raise AssertionError("不连通图应抛 ValueError")
except ValueError as e:
    print(f"  [OK] 不连通图正确抛出 ValueError: {e}")

# 7d2. cam4/cam5 在图中但属于独立连通分量 → 同样 ValueError
disc_pairs = dict(chain_pairs)
disc_pairs[("cam4", "cam5")] = {'T': np.eye(4), 'success': True}
try:
    pose_graph.find_path_transform(disc_pairs, "cam1", "cam4")
    raise AssertionError("独立连通分量应抛 ValueError")
except ValueError as e:
    print(f"  [OK] 独立连通分量正确抛出 ValueError: {e}")

# 7e. optimize_global：BFS 生成树（链式图上以 cam1 为锚点）
global_T = pose_graph.optimize_global(chain_pairs, "cam1")
assert set(global_T.keys()) == {"cam1", "cam2", "cam3"}
assert np.allclose(global_T["cam1"], np.eye(4))
assert np.allclose(global_T["cam2"], T_2to1, atol=1e-9)
assert np.allclose(global_T["cam3"], np.linalg.inv(T_1to3), atol=1e-9)
print("  [OK] optimize_global: BFS 生成树输出各相机到锚点的变换")

# ------------------------------------------------------------------
# 8. StitchEngine：3 相机拼接 / 空点云跳过 / 体素下采样
# ------------------------------------------------------------------
print("\n[8] StitchEngine N 路拼接测试")
import open3d as o3d
from core.frame_data import FrameData
from core.point_cloud_processor import PointCloudProcessor
from core.stitch_engine import StitchEngine


def make_ply_frame(cam_id: str, pts: np.ndarray, tmpdir: str, frame_id: int = 0) -> FrameData:
    """把 Nx3 点写成临时 PLY，并构造指向它的离线 FrameData。"""
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts.astype(np.float64))
    path = os.path.join(tmpdir, f"{cam_id}_{frame_id}.ply")
    assert o3d.io.write_point_cloud(path, pcd)
    return FrameData(frame_id=frame_id, camera_name=cam_id,
                     is_offline=True, offline_dir=tmpdir,
                     offline_pointmap_path=path)


stitch_tmp = tempfile.mkdtemp(prefix="stitch_test_")
np.random.seed(21)
n_per_cam = 300
# 各相机坐标系下的点云（同一物体的三个视角：简单几何体点簇）
pts_camA = np.random.rand(n_per_cam, 3) * 50
pts_camB = np.random.rand(n_per_cam, 3) * 50 + 100
pts_camC = np.random.rand(n_per_cam, 3) * 50 + 200

frames8 = {
    "camA": make_ply_frame("camA", pts_camA, stitch_tmp),
    "camB": make_ply_frame("camB", pts_camB, stitch_tmp),
    "camC": make_ply_frame("camC", pts_camC, stitch_tmp),
}

# 标定引擎：手写已知外参（camA 为 ref）
engine8 = CalibrationEngine()
engine8.set_reference("camA")
T_b2a = np.eye(4); T_b2a[:3, :3] = rotz(10); T_b2a[:3, 3] = [30, 0, 0]
T_c2a = np.eye(4); T_c2a[:3, :3] = rotz(-15); T_c2a[:3, 3] = [60, 20, 0]
engine8.pair_results[("camA", "camB")] = {'T': T_b2a, 'success': True}
engine8.pair_results[("camA", "camC")] = {'T': T_c2a, 'success': True}

# 8a. 3 相机拼接：合并点数 = 总和
stitcher = StitchEngine()
merged, msg = stitcher.stitch(frames8, engine8, "camA")
assert merged is not None, f"拼接失败: {msg}"
assert len(merged.points) == 3 * n_per_cam, \
    f"合并点数应为 {3 * n_per_cam}, 实际 {len(merged.points)}"
# camB 的点应被平移约 +30（x 方向），验证变换确实生效
merged_pts = np.asarray(merged.points)
assert merged_pts[:, 0].max() > 120, "camB/camC 点云未正确变换到参考系"
print(f"  [OK] 3 相机拼接: 合并点数 {len(merged.points)} = 3×{n_per_cam}, 变换生效")

# 8b. 一台相机点云为空/无效 + 一台未标定 → 跳过不崩，其余正常合并
frames8b = {
    "camA": make_ply_frame("camA", pts_camA, stitch_tmp, frame_id=1),
    "camB": FrameData(frame_id=1, camera_name="camB", is_offline=True,
                      offline_dir=stitch_tmp),  # 无 pointmap → 点云无效
    "camC": make_ply_frame("camC", pts_camC, stitch_tmp, frame_id=1),
    "camX": make_ply_frame("camX", pts_camB, stitch_tmp, frame_id=1),  # 未标定
}
merged_b, msg_b = stitcher.stitch(frames8b, engine8, "camA")
assert merged_b is not None, f"部分失败时不应整体失败: {msg_b}"
assert len(merged_b.points) == 2 * n_per_cam, \
    f"有效 2 台相机应合并 {2 * n_per_cam} 点, 实际 {len(merged_b.points)}"
print("  [OK] 空点云 / 未标定相机自动跳过，其余 2 台正常合并")

# 8c. 全部不可用 → 返回 None
frames8c = {"camY": FrameData(frame_id=2, camera_name="camY", is_offline=True)}
merged_c, msg_c = stitcher.stitch(frames8c, engine8, "camA")
assert merged_c is None and "不可用" in msg_c
print("  [OK] 全部相机不可用时返回 (None, 原因)")

# 8d. 带后处理：体素下采样，点数减少
proc = PointCloudProcessor()
proc.enable_voxel_downsample = True
proc.voxel_size = 2.0
merged_d, msg_d = stitcher.stitch(frames8, engine8, "camA", processor=proc)
assert merged_d is not None
assert 0 < len(merged_d.points) < 3 * n_per_cam, "体素下采样后点数应减少"
print(f"  [OK] 后处理: 体素下采样 {3 * n_per_cam} → {len(merged_d.points)} 点")

# 8e. stitch_offline：两对帧批量拼接合并
session = [frames8, frames8]
merged_off, msg_off = stitcher.stitch_offline(session, engine8, "camA")
assert merged_off is not None
assert len(merged_off.points) == 2 * 3 * n_per_cam
print(f"  [OK] stitch_offline: 2 对帧合并 {len(merged_off.points)} 点")

# ------------------------------------------------------------------
# 9. 集成测试：3 相机合成标定 → get_transform → stitch
# ------------------------------------------------------------------
print("\n[9] 集成测试: 标定 → 变换 → 拼接")
engine9 = CalibrationEngine()
np.random.seed(31)
board9 = np.random.rand(12, 3) * 150 + np.array([0, 0, 300])

T_b2r9 = np.eye(4); T_b2r9[:3, :3] = rotz(18);  T_b2r9[:3, 3] = [70, -20, 15]
T_c2r9 = np.eye(4); T_c2r9[:3, :3] = rotz(-22); T_c2r9[:3, 3] = [-50, 35, 30]

pts_in_b9 = world_to_cam(board9, T_b2r9) + np.random.randn(12, 3) * 0.3
pts_in_c9 = world_to_cam(board9, T_c2r9) + np.random.randn(12, 3) * 0.3
r_b = engine9.calibrate_pair("ref9", "camB9", make_markers(board9), make_markers(pts_in_b9),
                             ransac_threshold=2.0)
r_c = engine9.calibrate_pair("ref9", "camC9", make_markers(board9), make_markers(pts_in_c9),
                             ransac_threshold=2.0)
assert r_b.get('success') and r_c.get('success'), "集成测试标定失败"

# 三台相机各自坐标系下拍同一物体（物体点在 ref 坐标系真值已知）
obj_ref = np.random.rand(200, 3) * 80 + np.array([-40, -40, 250])
obj_b = world_to_cam(obj_ref, T_b2r9)
obj_c = world_to_cam(obj_ref, T_c2r9)
frames9 = {
    "ref9":  make_ply_frame("ref9",  obj_ref, stitch_tmp, frame_id=9),
    "camB9": make_ply_frame("camB9", obj_b,   stitch_tmp, frame_id=9),
    "camC9": make_ply_frame("camC9", obj_c,   stitch_tmp, frame_id=9),
}
merged9, msg9 = stitcher.stitch(frames9, engine9, "ref9")
assert merged9 is not None, f"集成拼接失败: {msg9}"
assert len(merged9.points) == 600

# 关键验证：camB9 的点云经估计外参变换后应与 ref 坐标系真值重合
T_est = engine9.get_transform("camB9", "ref9")
obj_h = np.hstack([obj_b, np.ones((200, 1))])
obj_b_in_ref = (T_est @ obj_h.T).T[:, :3]
align_err = np.linalg.norm(obj_b_in_ref - obj_ref, axis=1).mean()
print(f"  camB9 拼接到 ref 后平均对齐误差: {align_err:.3f} mm")
assert align_err < 2.0, f"集成对齐误差过大: {align_err}"
print(f"  [OK] 集成测试通过: 3 相机标定→拼接, 合并 {len(merged9.points)} 点, "
      f"对齐误差 {align_err:.3f} mm")

# ------------------------------------------------------------------
# 10. PointCloudProcessor.auto_tune 自动参数估计
# ------------------------------------------------------------------
print("\n[10] PointCloudProcessor.auto_tune 自动参数估计")


def make_block_pcd(n_target: int, scale: float = 1.0):
    """生成 100×100×50 均匀网格块点云（scale=0.001 为米单位同款几何）。

    返回 (pcd, 网格间距[原始单位])。均匀网格使平均最近邻点距 ≈ (V/n)^(1/3)，
    与 auto_tune 的体素反推公式假设一致。
    """
    s = (100.0 * 100.0 * 50.0 / n_target) ** (1.0 / 3.0)
    xs = np.arange(0, 100.0, s)
    ys = np.arange(0, 100.0, s)
    zs = np.arange(0, 50.0, s)
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1) * scale
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    return pcd, s * scale


proc10 = PointCloudProcessor()

# 10a. mm 单位均匀块（~31 万点，无飞点）：单位 / 点距 / 体素反推 / 不裁切
pcd_mm, s_mm = make_block_pcd(300_000)
n_mm = len(pcd_mm.points)
params_mm = proc10.auto_tune(pcd_mm, target_points=50_000)
assert params_mm['unit'] == 'mm', f"单位应为 mm: {params_mm['unit']}"
assert abs(params_mm['avg_spacing_mm'] - s_mm) < s_mm * 0.2, \
    f"平均点距 {params_mm['avg_spacing_mm']:.3f} 应接近网格间距 {s_mm:.3f}"
assert params_mm['enable_voxel_downsample'] is True, "点数超目标应建议体素下采样"
assert params_mm['crop_mode'] == 'none', \
    f"无飞点集中点云应推荐不裁切: {params_mm['crop_mode']}"
est = params_mm['estimated_points']
assert abs(est - 50_000) < 50_000 * 0.3, \
    f"预估点数 {est:,} 应接近目标 50,000（±30%）"
assert params_mm['notes'] and all(isinstance(t, str) for t in params_mm['notes'])
print(f"  [OK] mm 块: 点距 {params_mm['avg_spacing_mm']:.3f}mm, "
      f"体素 {params_mm['voxel_size']:.2f}mm, 预估 {est:,} 点（目标 50,000）")
print(f"       notes[0]: {params_mm['notes'][0]}")

# 10b. 远处飞点（两侧各 0.5%）：推荐 AABB 裁切且 crop_ratio < 1.0
rng10 = np.random.default_rng(5)
n_fly = int(n_mm * 0.005)  # < 1% 分位，P1~P99 核心范围检测可检出
fly_l = rng10.random((n_fly, 3)) * [100, 100, 50] + [-700, 0, 0]
fly_r = rng10.random((n_fly, 3)) * [100, 100, 50] + [600, 0, 0]
pts_fly = np.vstack([np.asarray(pcd_mm.points), fly_l, fly_r])
pcd_fly = o3d.geometry.PointCloud()
pcd_fly.points = o3d.utility.Vector3dVector(pts_fly)
params_fly = proc10.auto_tune(pcd_fly, target_points=50_000)
assert params_fly['crop_mode'] == 'aabb', \
    f"飞点场景应推荐 AABB: {params_fly['crop_mode']}"
assert 0.3 <= params_fly['crop_ratio'] < 1.0, \
    f"飞点场景 crop_ratio 应 < 1.0: {params_fly['crop_ratio']}"
assert params_fly['outlier_std_ratio'] == 1.5, "飞点严重应收紧 std_ratio 到 1.5"
est_fly = params_fly['estimated_points']
assert abs(est_fly - 50_000) < 50_000 * 0.3, \
    f"飞点场景预估点数 {est_fly:,} 应接近目标 50,000（±30%）"
print(f"  [OK] 飞点场景: 推荐 AABB 裁切 ratio={params_fly['crop_ratio']:.2f}, "
      f"std=1.5, 预估 {est_fly:,} 点")

# 10c. 米单位同款几何：单位检测为 m，体素仍输出 mm 量级
pcd_m, _ = make_block_pcd(300_000, scale=0.001)
params_m = proc10.auto_tune(pcd_m, target_points=50_000)
assert params_m['unit'] == 'm', f"单位应为 m: {params_m['unit']}"
assert 0.5 <= params_m['voxel_size'] <= 10.0, \
    f"米单位点云的体素仍应输出 mm 量级: {params_m['voxel_size']}"
assert abs(params_m['estimated_points'] - 50_000) < 50_000 * 0.3, \
    f"米单位场景预估点数 {params_m['estimated_points']:,} 应接近目标（±30%）"
print(f"  [OK] 米单位: 检测为 m, 体素输出 {params_m['voxel_size']:.2f}mm, "
      f"预估 {params_m['estimated_points']:,} 点")

# 10d. 小点云（< 目标点数）：不建议启用体素下采样
pcd_small, _ = make_block_pcd(50_000)
params_small = proc10.auto_tune(pcd_small)  # 默认目标 80 万
assert params_small['enable_voxel_downsample'] is False, \
    "点数不足目标时不应建议体素下采样"
assert params_small['crop_mode'] == 'none'
print(f"  [OK] 小点云（{len(pcd_small.points):,} < 80 万）: "
      f"enable_voxel_downsample=False")

# 10e. 全流程：auto_tune → 参数写回 processor → process() 不会"全滤掉"
params_full = proc10.auto_tune(pcd_mm)  # 31 万点 < 默认 80 万目标
proc_flow = PointCloudProcessor()
for k, v in params_full.items():
    if hasattr(proc_flow, k):
        setattr(proc_flow, k, v)
result_flow, _stats_flow = proc_flow.process(pcd_mm)
n_remain = len(result_flow.points)
assert n_remain > n_mm * 0.5, \
    f"自动参数处理后剩余 {n_remain:,} 点，不应低于输入 50%（{n_mm:,}）"
print(f"  [OK] 全流程: {n_mm:,} → {n_remain:,} 点"
      f"（保留 {n_remain / n_mm * 100:.1f}%，不会全滤掉）")

# 10f. 含无效点（NaN/Inf/零点）的真实 RVC 场景回归：
#      auto_tune 不得被污染，process 不得坍缩全滤掉
pts_rvc = np.asarray(pcd_mm.points).copy()
n_nan = int(n_mm * 0.15)          # 模拟 RVC pointmap 15% 无效像素
pts_nan = np.full((n_nan, 3), np.nan)
pts_nan[: n_nan // 3] = 0.0       # 部分设备用 (0,0,0) 表示无效
pts_nan[n_nan // 3: n_nan // 2] = np.inf
pts_rvc = np.vstack([pts_rvc, pts_nan])
pcd_rvc = o3d.geometry.PointCloud()
pcd_rvc.points = o3d.utility.Vector3dVector(pts_rvc)
params_rvc = proc10.auto_tune(pcd_rvc, target_points=50_000)
assert np.isfinite(params_rvc['avg_spacing_mm']), \
    f"含无效点时平均点距必须为有限值: {params_rvc['avg_spacing_mm']}"
assert abs(params_rvc['avg_spacing_mm'] - s_mm) < s_mm * 0.2, \
    f"剔除无效点后点距 {params_rvc['avg_spacing_mm']:.3f} 应接近 {s_mm:.3f}"
assert abs(params_rvc['estimated_points'] - 50_000) < 50_000 * 0.3, \
    f"含无效点时预估点数 {params_rvc['estimated_points']:,} 应接近目标（±30%）"
assert any("无效点" in t for t in params_rvc['notes']), "notes 应说明剔除了无效点"
proc_rvc = PointCloudProcessor()
for k, v in params_rvc.items():
    if hasattr(proc_rvc, k):
        setattr(proc_rvc, k, v)
result_rvc, stats_rvc = proc_rvc.process(pcd_rvc)
assert stats_rvc.get('invalid_removed') >= n_nan, \
    f"process 应至少剔除 {n_nan:,} 个无效点: {stats_rvc}"
n_remain_rvc = len(result_rvc.points)
assert abs(n_remain_rvc - 50_000) < 50_000 * 0.3, \
    f"含无效点场景处理后应接近目标 50,000 点而非坍缩: 剩余 {n_remain_rvc:,}"
print(f"  [OK] 含 {n_nan:,} 个无效点(NaN/Inf/零): 点距 {params_rvc['avg_spacing_mm']:.3f}mm, "
      f"剔除后处理剩余 {n_remain_rvc:,} 点，不再坍缩")

# ------------------------------------------------------------------
# 11. 非对称圆标定板检测 + 位姿法标定
# ------------------------------------------------------------------
print("\n[11] 标定板检测与位姿法标定测试")


def _draw_board_image(img_size, img_pts, radius=12):
    """绘制黑底白圆标定板图像（带噪声/光照渐变）。"""
    img = np.zeros((img_size[1], img_size[0]), dtype=np.uint8)
    for pt in img_pts:
        cx, cy = int(round(pt[0])), int(round(pt[1]))
        cv2.circle(img, (cx, cy), radius, 255, -1)
    img = cv2.GaussianBlur(img, (5, 5), 1.5)
    Y, X = np.ogrid[:img_size[1], :img_size[0]]
    gradient = (X / img_size[0] * 30 + Y / img_size[1] * 30).astype(np.uint8)
    img = cv2.add(img, gradient)
    noise = np.random.normal(0, 10, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def _write_ply_full(path, points):
    """写完整 PLY（保留 NaN 以维持像素索引映射）。"""
    with open(path, 'w') as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {len(points)}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("end_header\n")
        for p in points:
            if np.isfinite(p).all():
                f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
            else:
                f.write("nan nan nan\n")


spacing = 50.0
img_size = (1024, 768)
ox = (img_size[0] - (11 - 1) * spacing) // 2
oy = (img_size[1] - (4 - 0.5) * spacing) // 2
img_pts = []
cam_pts = []
z_cam = 500.0
# 列优先：从右到左 11 列，每列从上到下 4 行（与 OpenCV 返回顺序一致）
for j in range(11 - 1, -1, -1):  # 列：从右到左
    for i in range(4):            # 行：从上到下
        x_img = ox + j * spacing
        y_img = oy + (i + 0.5 * (j % 2)) * spacing
        img_pts.append([x_img, y_img])
        cam_pts.append([x_img - img_size[0] / 2, y_img - img_size[1] / 2, z_cam])
img_pts = np.array(img_pts, dtype=np.float64)
cam_pts = np.array(cam_pts, dtype=np.float64)

img = _draw_board_image(img_size, img_pts)
points = np.full((img_size[1] * img_size[0], 3), np.nan, dtype=np.float64)
for pt2, pt3 in zip(img_pts, cam_pts):
    x, y = int(round(pt2[0])), int(round(pt2[1]))
    if 0 <= x < img_size[0] and 0 <= y < img_size[1]:
        points[y * img_size[0] + x] = pt3

fd, ply_path = tempfile.mkstemp(suffix=".ply")
os.close(fd)
_write_ply_full(ply_path, points)

detector = CalibBoardDetector(
    board_specs=[{"name": "4x11", "cols": 11, "rows": 4, "spacing_mm": spacing}],
    gamma=1.0,
)
result = detector.detect(img, offline_ply_path=ply_path)
os.unlink(ply_path)

assert result['success'], f"标定板检测失败: {result['message']}"
assert result['pattern_name'] == "4x11"
assert len(result['markers']) == 44
assert result['rms_mm'] < 0.1, f"标定板位姿 RMS 过大: {result['rms_mm']}"
print(f"  [OK] 4x11 标定板检测成功，RMS {result['rms_mm']:.4f} mm")

# 位姿法标定 pair：两个视角拍同一块板
R_rel = rotz(15)
t_rel = np.array([100.0, 50.0, 20.0])
T_board_in_ref = np.eye(4)
T_board_in_ref[:3, :3] = np.eye(3)
T_board_in_ref[:3, 3] = cam_pts.mean(axis=0) + np.array([0, 0, 0])

# 简化：ref 与 cam 的 board pose 只差一个刚性变换
T_board_in_cam = np.eye(4)
T_board_in_cam[:3, :3] = R_rel
T_board_in_cam[:3, 3] = t_rel

engine = CalibrationEngine()
res = engine.calibrate_pair_by_board_pose(
    "ref", "cam", T_board_in_ref, T_board_in_cam,
    pattern_name="4x11", inlier_count=44, total_pairs=44,
    rms_ref_mm=0.05, rms_cam_mm=0.05,
)
assert res['success'], f"位姿法标定失败: {res.get('message')}"
T_true = T_board_in_ref @ np.linalg.inv(T_board_in_cam)
R_diff = np.linalg.norm(res['T'][:3, :3] - T_true[:3, :3], ord='fro')
t_diff = np.linalg.norm(res['T'][:3, 3] - T_true[:3, 3])
assert R_diff < 1e-6 and t_diff < 1e-6, f"位姿法标定误差过大: R={R_diff}, t={t_diff}"
print(f"  [OK] 位姿法标定 pair 成功，旋转误差 {R_diff:.6f}，平移误差 {t_diff:.4f} mm")

# MarkerDetector 类型切换
md = MarkerDetector()
assert md.get_marker_type() == "coded_circle"
md.set_marker_type(MARKER_TYPE_ASYMMETRIC_GRID)
assert md.is_board_mode()
print("  [OK] MarkerDetector 标记物类型切换正常")

print("\n" + "=" * 60)
print("[OK] 所有测试通过！core 模块工作正常。")
print("=" * 60)
