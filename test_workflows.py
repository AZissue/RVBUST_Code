# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
工作流测试（无相机、无 GUI）—— P2 阶段验证。

验证：
  [1] FixedMultiCamWorkflow 标定→扫描状态机
  [2] MobileChainWorkflow 链式拼接流程
  [3] SessionManager 统一会话创建与加载
"""

import os
import sys
import tempfile
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

print("=" * 60)
print("工作流测试（无相机、无 GUI）")
print("=" * 60)

from core.fixed_multi_cam_workflow import FixedMultiCamWorkflow
from core.mobile_chain_workflow import MobileChainWorkflow
from core.session_manager import SessionManager
from core.camera_manager import CameraManager
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.frame_data import FrameData


def make_markers(pts: np.ndarray, code_offset: int = 0):
    return [
        {'code': i + code_offset,
         'x_3d': float(pts[i, 0]), 'y_3d': float(pts[i, 1]), 'z_3d': float(pts[i, 2])}
        for i in range(len(pts))
    ]


def rotz(deg: float) -> np.ndarray:
    rad = np.deg2rad(deg)
    c, s = np.cos(rad), np.sin(rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def make_frame(station_id: str, cam_pts: np.ndarray, markers=None):
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


def make_workflow_components():
    camera_manager = CameraManager()
    marker_detector = MarkerDetector()
    calibration_engine = CalibrationEngine()
    stitch_engine = StitchEngine()
    return camera_manager, marker_detector, calibration_engine, stitch_engine


# ------------------------------------------------------------------
# [1] FixedMultiCamWorkflow 标定→扫描状态机
# ------------------------------------------------------------------
print("\n[1] FixedMultiCamWorkflow 标定→扫描状态机测试")

cam_mgr, marker_det, calib_eng, stitch_eng = make_workflow_components()
workflow = FixedMultiCamWorkflow(cam_mgr, marker_det, calib_eng, stitch_eng)

# 初始状态
assert workflow.get_state() == "idle"
assert workflow.get_mode_name() == "fixed_multi"

# 开始标定
ok, msg = workflow.start_calibration("cam0")
assert ok, f"开始标定失败: {msg}"
assert workflow.get_state() == "calibrating"

# 添加标定帧
world_pts = np.array([
    [0, 0, 0], [100, 0, 0], [200, 0, 0],
    [0, 100, 0], [100, 100, 0], [200, 100, 0],
], dtype=np.float64)
T_cam1 = np.vstack([np.hstack([rotz(10), np.array([[50], [20], [0]])]), [0, 0, 0, 1]])
cam1_pts = (np.linalg.inv(T_cam1)[:3, :3] @ world_pts.T + np.linalg.inv(T_cam1)[:3, 3:4]).T

frame_cam0 = make_frame("cam0", world_pts)
frame_cam1 = make_frame("cam1", cam1_pts)
workflow.add_calibration_frame(frame_cam0)
workflow.add_calibration_frame(frame_cam1)

# 覆盖 detect_3d 为直接返回 markers
current_markers = [None]
def mock_detect(*args, **kwargs):
    return current_markers[0]
workflow.marker_detector.detect_3d = mock_detect

# 检测标记
current_markers[0] = frame_cam0.markers
workflow.detect_markers()
current_markers[0] = frame_cam1.markers
workflow.detect_markers()

# 标定
ok, msg = workflow.calibrate()
assert ok, f"标定失败: {msg}"
assert workflow.get_state() == "calibrated"
assert workflow.is_calibration_locked

# 进入扫描
ok, msg = workflow.start_scanning()
assert ok, f"进入扫描失败: {msg}"
assert workflow.get_state() == "scanning"

# 添加扫描帧
frame_scan0 = make_frame("cam0", world_pts)
frame_scan1 = make_frame("cam1", cam1_pts)
workflow.add_scan_frame(frame_scan0)
workflow.add_scan_frame(frame_scan1)

# 覆盖 stitch_engine.stitch 为直接返回合并点云（合成数据无真实点云）
import open3d as o3d
def mock_stitch(frames, calibration_engine, reference_id, processor=None):
    merged = o3d.geometry.PointCloud()
    merged.points = o3d.utility.Vector3dVector(world_pts)
    return merged, "mock stitch"
workflow.stitch_engine.stitch = mock_stitch

# 拼接
ok, msg, merged = workflow.stitch()
assert ok, f"拼接失败: {msg}"
assert merged is not None
print(f"  拼接点数: {len(merged.points)}")

# 保存/加载标定结果（覆盖模式 A "保存" 链路）
import tempfile, json
with tempfile.TemporaryDirectory() as tmp:
    calib_path = os.path.join(tmp, "calibration.json")
    ok, msg = workflow.save_calibration(calib_path)
    assert ok, f"保存标定失败: {msg}"
    assert os.path.exists(calib_path)
    # 重新加载并验证锁定状态
    workflow2 = FixedMultiCamWorkflow(
        CameraManager(), MarkerDetector(), CalibrationEngine(), StitchEngine())
    ok, msg = workflow2.load_calibration(calib_path)
    assert ok, f"加载标定失败: {msg}"
    assert workflow2.is_calibration_locked
    print(f"  标定保存/加载: {calib_path}")

print("  [OK] FixedMultiCamWorkflow 标定→扫描→保存链路正常")

# ------------------------------------------------------------------
# [2] MobileChainWorkflow 链式拼接流程
# ------------------------------------------------------------------
print("\n[2] MobileChainWorkflow 链式拼接流程测试")

cam_mgr2, marker_det2, calib_eng2, stitch_eng2 = make_workflow_components()
workflow2 = MobileChainWorkflow(cam_mgr2, marker_det2, calib_eng2, stitch_eng2)

# 初始状态
assert workflow2.get_state() == "idle"
assert workflow2.get_mode_name() == "mobile_chain"

# 开始链式拼接
ok, msg = workflow2.start_chaining()
assert ok, f"开始链式拼接失败: {msg}"
assert workflow2.get_state() == "chaining"

# 模拟拍摄机位（覆盖 detect_3d）
station_poses = [
    np.eye(4),
    np.vstack([np.hstack([rotz(10), np.array([[50], [20], [0]])]), [0, 0, 0, 1]]),
    np.vstack([np.hstack([rotz(20), np.array([[100], [40], [0]])]), [0, 0, 0, 1]]),
]
station_markers = []
for T in station_poses:
    T_inv = np.linalg.inv(T)
    cam_pts = (T_inv[:3, :3] @ world_pts.T + T_inv[:3, 3:4]).T
    station_markers.append(make_markers(cam_pts))

current_markers2 = [None]
def mock_detect2(*args, **kwargs):
    return current_markers2[0]
workflow2.marker_detector.detect_3d = mock_detect2

# 拍摄机位 1
current_markers2[0] = station_markers[0]
frame1 = make_frame("station_1", world_pts, station_markers[0])
workflow2._chain_stitcher.add_frame(frame1)

# 拍摄机位 2
current_markers2[0] = station_markers[1]
frame2 = make_frame("station_2", world_pts, station_markers[1])
workflow2._chain_stitcher.add_frame(frame2)

# 拍摄机位 3
current_markers2[0] = station_markers[2]
frame3 = make_frame("station_3", world_pts, station_markers[2])
ok, msg, edge = workflow2._chain_stitcher.add_frame(frame3)
assert ok, f"机位 3 配准失败: {msg}"

# 检查状态
assert len(workflow2._chain_stitcher.nodes) == 3
stations = workflow2.get_station_list()
assert len(stations) == 3
print(f"  机位列表: {[s['station_id'] for s in stations]}")

# 误差报告
report = workflow2.get_error_report()
assert report['n_nodes'] == 3
assert report['n_edges'] == 2
print(f"  误差报告: {report['n_nodes']} 节点, {report['n_edges']} 边")

print("  [OK] MobileChainWorkflow 链式拼接流程正常")

# ------------------------------------------------------------------
# [2b] 模式 B 状态一致性回归（P1-1~P1-6）
# ------------------------------------------------------------------
print("\n[2b] 模式 B 状态一致性回归测试")

cam_mgr3, marker_det3, calib_eng3, stitch_eng3 = make_workflow_components()
workflow3 = MobileChainWorkflow(cam_mgr3, marker_det3, calib_eng3, stitch_eng3)
workflow3.start_chaining()

# mock detect_3d 按预设队列返回 markers，便于控制重拍场景
detect_queue = []
def mock_detect3(*args, **kwargs):
    return detect_queue.pop(0)
workflow3.marker_detector.detect_3d = mock_detect3

# mock 相机（返回空标记帧，具体标记由 detect_3d 队列注入）
cam_mgr3.get_connected_ids = lambda: ['physical']
cam_mgr3.capture = lambda cam: make_frame('physical', world_pts, [])

# 拍 3 个机位（走 capture_station，StationManager 与 ChainStitcher 同步）
detect_queue.extend([station_markers[0], station_markers[1], station_markers[2]])
for i in range(3):
    ok, msg, evaluation = workflow3.capture_station()
    assert ok, f"机位 {i+1} 拍摄/配准失败: {msg}"

original_ids = [s['station_id'] for s in workflow3.get_station_list()]
assert original_ids == ['station_1', 'station_2', 'station_3']

# P1-2: get_station_list 顺序与时间线索引 1-based 对应
stations = workflow3.get_station_list()
for idx, s in enumerate(stations, start=1):
    assert s['station_id'] == original_ids[idx - 1]

# P1-6: optimize_global 返回优化前后误差（需至少 3 个机位）
ok, msg, before_mm, after_mm = workflow3.optimize_global()
assert ok, f"全局优化失败: {msg}"
assert isinstance(before_mm, float) and isinstance(after_mm, float)
assert before_mm >= 0 and after_mm >= 0
print(f"  全局优化残差: {before_mm:.6f}mm -> {after_mm:.6f}mm")

# P1-5: _remove_station_from_chain 正确删除节点与关联边
removed = workflow3._remove_station_from_chain('station_2')
assert removed, "删除机位 2 失败"
assert 'station_2' not in workflow3._chain_stitcher.nodes
assert not any(e.from_id == 'station_2' or e.to_id == 'station_2'
               for e in workflow3._chain_stitcher.edges)
print(f"  删除机位 2 后列表: {[s['station_id'] for s in workflow3.get_station_list()]}")

# P1-1 / P1-3: 重拍链尾机位，用 station_2 的标记模拟相机回到 station_2 位置
detect_queue.append(station_markers[1])
ok, msg, evaluation = workflow3.recapture_station('station_3')
# station_3 是链尾，可重拍；重拍后仍应保持 2 个节点（替换 station_3）
assert ok, f"重拍失败: {msg}"
assert evaluation is not None
new_ids = [s['station_id'] for s in workflow3.get_station_list()]
assert len(new_ids) == 2, f"重拍后节点数应为 2，实际 {len(new_ids)}"
print(f"  重拍 station_3 后列表: {new_ids}")

print("  [OK] 模式 B 状态一致性回归通过")

# ------------------------------------------------------------------
# [3] SessionManager 统一会话创建与加载
# ------------------------------------------------------------------
print("\n[3] SessionManager 统一会话创建与加载测试")

with tempfile.TemporaryDirectory() as tmp_dir:
    sm = SessionManager(base_dir=tmp_dir)

    # 创建功能一会话
    session_dir = sm.create_session(SessionManager.MODE_FIXED_MULTI,
                                    camera_info={"model": "RVC-I2370", "count": 2})
    assert os.path.exists(session_dir)
    assert os.path.exists(os.path.join(session_dir, "frames_calib"))
    assert os.path.exists(os.path.join(session_dir, "frames_scan"))
    assert os.path.exists(os.path.join(session_dir, "meta.json"))

    # 保存标定结果
    calib_data = {"reference_id": "cam0", "pairs": {"cam1": {"T": np.eye(4).tolist()}}}
    assert sm.save_calibration(calib_data)

    # 加载会话
    sm2 = SessionManager(base_dir=tmp_dir)
    ok, msg = sm2.load_session(session_dir)
    assert ok, f"加载会话失败: {msg}"
    assert sm2.mode == SessionManager.MODE_FIXED_MULTI
    loaded_calib = sm2.load_calibration()
    assert loaded_calib is not None
    assert loaded_calib["reference_id"] == "cam0"

    # 创建功能二会话
    session_dir2 = sm.create_session(SessionManager.MODE_MOBILE_CHAIN,
                                     camera_info={"model": "RVC-I2370", "count": 1})
    assert os.path.exists(session_dir2)
    assert os.path.exists(os.path.join(session_dir2, "stations"))

    # 保存误差报告
    report = {"n_nodes": 3, "n_edges": 2, "edges": []}
    assert sm.save_error_report(report)
    loaded_report = sm.load_error_report()
    assert loaded_report is not None
    assert loaded_report["n_nodes"] == 3

print("  [OK] SessionManager 统一会话创建与加载正常")

print("\n" + "=" * 60)
print("[OK] 全部工作流测试通过")
print("=" * 60)
