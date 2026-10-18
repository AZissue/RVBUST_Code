# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration 单相机多站位模式测试（Phase 5，offscreen + 合成数据）

  [1] StationManager：mock 物理相机拍 3 个站位 → 站位 ID 正确、
      帧存盘文件存在、get_frames 返回 3 个离线帧
  [2] 站位帧持久性：模拟物理相机连续拍 3 次（每次新的 RVC 数据），
      确认站位 1 的帧仍可从磁盘加载且内容不被后续拍摄覆盖
  [3] UIv2：站位时间线映射与删除后索引刷新
  [4] 删除站位：帧与磁盘目录同步清理
  [5] 新会话：清空站位、重置 UIv2、保留旧会话目录

链式标定与拼接数值回归见 test_chain_stitcher.py / test_workflows.py。
"""
import os
import sys
import json
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from PySide6.QtWidgets import QApplication

print("=" * 60)
print("MultiCameraCalibration 站位模式测试（offscreen + 合成数据）")
print("=" * 60)

app = QApplication.instance() or QApplication(sys.argv)

import cv2
import open3d as o3d

from ui_v2.workspaces.mobile_chain_workspace import MobileChainWorkspace
from core.frame_data import FrameData
from core.station_manager import StationManager




# ------------------------------------------------------------------
# 工具函数（与 test_integration.py 相同的合成数据方法）
# ------------------------------------------------------------------
def wait_workers(win, timeout=300):
    """等待主窗口后台 WorkerThread 全部完成（耗时操作已改为 QThread 异步执行）。"""
    import time
    deadline = time.time() + timeout
    while getattr(win, '_workers', None):
        assert time.time() < deadline, "后台任务超时未完成"
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def rotz(deg: float) -> np.ndarray:
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0],
                     [np.sin(a),  np.cos(a), 0],
                     [0, 0, 1]])


def world_to_cam(pts_ref: np.ndarray, T_c2r: np.ndarray) -> np.ndarray:
    """p_ref = p_cam @ R.T + t  →  p_cam = (p_ref - t) @ R"""
    R = T_c2r[:3, :3]
    t = T_c2r[:3, 3]
    return (pts_ref - t) @ R


def make_markers(pts: np.ndarray):
    """由 Nx3 点数组构造编码圆 markers 列表（mm 单位）。"""
    return [
        {'code': i,
         'x': 100.0 + i * 10, 'y': 100.0 + i * 10,
         'x_2d': 100.0 + i * 10, 'y_2d': 100.0 + i * 10,
         'x_3d': float(pts[i, 0]), 'y_3d': float(pts[i, 1]), 'z_3d': float(pts[i, 2])}
        for i in range(len(pts))
    ]


def make_synthetic_image(seed: int = 0) -> np.ndarray:
    """合成 BGR 测试图像（渐变 + 随机噪声）。"""
    rng = np.random.default_rng(seed)
    h, w = 480, 640
    grad = np.linspace(0, 180, w, dtype=np.uint8)[None, :].repeat(h, axis=0)
    img = np.stack([grad, grad // 2, 255 - grad], axis=-1)
    noise = rng.integers(0, 30, (h, w, 3), dtype=np.uint8)
    return np.clip(img.astype(np.int32) + noise, 0, 255).astype(np.uint8)


def write_ply(pts: np.ndarray, path: str):
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts.astype(np.float64))
    assert o3d.io.write_point_cloud(path, pcd), f"PLY 写入失败: {path}"


class FakeDetector:
    """模拟编码圆检测器：按 PLY 路径查表返回预置 markers（无 SDK 环境用）。"""

    def __init__(self, markers_by_ply: dict):
        self._table = markers_by_ply

    def detect_3d(self, image_np, pointmap=None, rvc_image=None, offline_ply_path=None):
        if offline_ply_path is None:
            return []
        key = os.path.normpath(offline_ply_path)
        return list(self._table.get(key, []))


class MockCameraManager:
    """模拟 CameraManager：capture 从预置队列取帧（每次返回新的帧数据）。"""

    def __init__(self):
        self._queue = []

    def push(self, frame: FrameData):
        self._queue.append(frame)

    def capture(self, camera_id, options=None):
        return self._queue.pop(0) if self._queue else None


def make_station_frame(seq: int, ply_pts: np.ndarray, tmp_dir: str,
                       seed: int = 0) -> FrameData:
    """构造一拍模拟帧：合成图像 + 预生成 PLY（离线引用，save 时复制进站位目录）。"""
    ply_path = os.path.join(tmp_dir, f"src_capture_{seq}.ply")
    write_ply(ply_pts, ply_path)
    return FrameData(frame_id=seq, camera_name="physical",
                     image_np=make_synthetic_image(seed=seed),
                     is_offline=True,
                     offline_pointmap_path=ply_path)


tmp_dir = tempfile.mkdtemp(prefix="mcc_station_")
rng = np.random.default_rng(2026)

# ------------------------------------------------------------------
# [1] StationManager：mock 物理相机拍 3 个站位
# ------------------------------------------------------------------
print("\n[1] StationManager：mock 物理相机拍摄 3 个站位")
mock = MockCameraManager()
station_pts = [rng.random((100, 3)) * 200 + np.array([0, 0, 300]) for _ in range(3)]
station_imgs = []
for i in range(3):
    frame = make_station_frame(i + 1, station_pts[i], tmp_dir, seed=i)
    station_imgs.append(frame.image_np.copy())
    mock.push(frame)

mgr = StationManager(mock, base_dir=os.path.join(tmp_dir, "stations"))
ids = []
for _ in range(3):
    sid, msg = mgr.capture_station("physical")
    assert sid is not None, f"站位拍摄失败: {msg}"
    ids.append(sid)
assert ids == ["station_1", "station_2", "station_3"], f"站位 ID 异常: {ids}"
assert mgr.station_count() == 3
session_dir = mgr.session_dir
assert session_dir and os.path.isdir(session_dir), "会话目录未创建"
for i, sid in enumerate(ids):
    sdir = os.path.join(session_dir, sid)
    assert os.path.isdir(sdir), f"缺站位目录: {sdir}"
    assert os.path.exists(os.path.join(sdir, f"{sid}.png")), f"缺图像: {sid}.png"
    assert os.path.exists(os.path.join(sdir, f"{sid}.ply")), f"缺点云: {sid}.ply"
    assert os.path.exists(os.path.join(sdir, "meta.json")), f"缺 meta: {sid}/meta.json"
frames = mgr.get_frames()
assert len(frames) == 3 and set(frames.keys()) == set(ids)
assert all(f.is_offline for f in frames.values()), "站位帧应为离线模式"
assert all(f.pointmap is None and f.rvc_image is None for f in frames.values()), \
    "站位帧不应持有 RVC 句柄"
with open(os.path.join(session_dir, "meta.json"), 'r', encoding='utf-8') as f:
    smeta = json.load(f)
assert smeta["stations"] == ids, f"会话 meta 站位列表异常: {smeta}"
print(f"  站位 ID: {ids} | 会话目录: {session_dir}")
print(f"  每站位目录含 {ids[0]}.png/.ply/meta.json，get_frames 返回 3 个离线帧")
print("  [OK] StationManager 拍摄存盘通过")

# ------------------------------------------------------------------
# [2] 站位帧持久性：连续拍摄后站位 1 的帧仍可从磁盘加载
# ------------------------------------------------------------------
print("\n[2] 站位帧持久性（后续拍摄不覆盖先拍站位）")
# 上一步已模拟物理相机连续拍 3 次（每次新的帧数据）。
# 验证站位 1 落盘文件仍存在且内容与拍摄时一致：
s1_dir = os.path.join(session_dir, "station_1")
img_disk = cv2.imread(os.path.join(s1_dir, "station_1.png"))
assert img_disk is not None, "站位 1 图像无法从磁盘加载"
assert np.array_equal(img_disk, station_imgs[0]), \
    "站位 1 图像内容被后续拍摄污染"
pcd_disk = o3d.io.read_point_cloud(os.path.join(s1_dir, "station_1.ply"))
assert len(pcd_disk.points) == 100, "站位 1 点云点数异常"
assert np.allclose(np.asarray(pcd_disk.points), station_pts[0], atol=1e-6), \
    "站位 1 点云内容被后续拍摄污染"
# 内存中的站位帧引用同样指向未受影响的磁盘文件
f1 = mgr.get_frame("station_1")
assert f1.has_pointcloud and f1.offline_pointmap_path.startswith(s1_dir)
assert np.array_equal(f1.image_np, station_imgs[0])
print("  3 次连续拍摄后，站位 1 的 PNG/PLY 均完好且内容与原始一致")
print("  [OK] 站位帧持久性通过")

# ------------------------------------------------------------------
view = MobileChainWorkspace()
view.set_stations([{'station_id': sid} for sid in ids])
assert [view.get_station_id(i) for i in range(1, 4)] == ids
assert mgr.remove_station('station_2')
assert mgr.get_frame('station_2') is None
assert not os.path.exists(os.path.join(session_dir, 'station_2'))
view.set_stations([{'station_id': sid} for sid in mgr.get_station_ids()])
assert view.get_station_id(2) == 'station_3'
old_session = mgr.session_dir
new_session = mgr.new_session()
assert new_session != old_session and os.path.isdir(old_session)
assert mgr.station_count() == 0
view.reset_session()
assert view.get_station_id(1) is None
view.deleteLater()
app.processEvents()
shutil.rmtree(tmp_dir)
print('Station persistence, UIv2 mapping, deletion and session reset: ALL OK')
