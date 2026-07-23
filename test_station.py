# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration 单相机多站位模式测试（Phase 5，offscreen + 合成数据）

  [1] StationManager：mock 物理相机拍 3 个站位 → 站位 ID 正确、
      帧存盘文件存在、get_frames 返回 3 个离线帧
  [2] 站位帧持久性：模拟物理相机连续拍 3 次（每次新的 RVC 数据），
      确认站位 1 的帧仍可从磁盘加载且内容不被后续拍摄覆盖
  [3] UI：站位模式添加 1 台物理相机 → 拍 3 个站位 →
      网格 4 个卡片（1 物理固定第一位 + 3 站位）
  [4] 端到端：3 站位合成编码圆 → 检测 → 标定（station_1 为 ref，2 对 pair）
      → 拼接 → 对齐误差 < 2mm
  [5] 删除站位：删 station_2 后标定结果 / 卡片 / 帧正确更新
  [6] 新会话：清空后 station_count == 0，站位卡片清空
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

from ui.main_window import MainWindow, STYLESHEET
from core.frame_data import FrameData
from core.station_manager import StationManager

app.setStyleSheet(STYLESHEET)


# ------------------------------------------------------------------
# 工具函数（与 test_integration.py 相同的合成数据方法）
# ------------------------------------------------------------------
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
# [3] UI：站位模式 1 台物理相机 + 3 站位 → 网格 4 卡片
# ------------------------------------------------------------------
print("\n[3] UI：站位模式添加 1 台物理相机 → 拍 3 个站位")
window = MainWindow()
window.left_tabs.setCurrentIndex(1)  # 切到「单相机站位」Tab
window._on_station_connect(0)        # 无真实设备：连接失败但物理卡片照常生成
assert MainWindow.PHYSICAL_ID in window.cards, "物理相机卡片未生成"
assert "当前相机" in window.cards[MainWindow.PHYSICAL_ID].lbl_title.text()

# mock 物理相机拍摄（替换站位管理器内部的相机管理器）
mock2 = MockCameraManager()
for i in range(3):
    mock2.push(make_station_frame(i + 1, station_pts[i], tmp_dir, seed=100 + i))
window.station_manager._cam_mgr = mock2
window.station_manager._base_dir = os.path.join(tmp_dir, "stations_ui")

for _ in range(3):
    window._on_capture_station()
assert window.station_manager.station_count() == 3
assert len(window.cards) == 4, f"应有 4 个卡片（1 物理 + 3 站位），实际 {len(window.cards)}"
assert window.grid_layout.count() == 4, f"网格应有 4 个卡片，实际 {window.grid_layout.count()}"
# 物理相机卡片固定网格第一位
first_card = window.grid_layout.itemAt(0).widget()
assert first_card.camera_id == MainWindow.PHYSICAL_ID, \
    f"网格第一位应为物理相机卡片: {first_card.camera_id}"
# 站位卡片标题与按钮状态
for i, sid in enumerate(["station_1", "station_2", "station_3"]):
    card = window.cards[sid]
    assert f"站位 {i + 1}" in card.lbl_title.text(), f"站位卡片标题异常: {card.lbl_title.text()}"
    assert card.btn_capture.isHidden(), "站位卡片不应有拍摄按钮"
    assert card.preview._pixmap is not None and not card.preview._pixmap.isNull(), \
        f"站位卡片 {sid} 预览未更新"
# 标定面板拿到站位 ID 集合，默认参考 station_1
combo_items = [window.calibration_panel.combo_ref.itemText(i)
               for i in range(window.calibration_panel.combo_ref.count())]
assert combo_items == ["station_1", "station_2", "station_3"], \
    f"标定面板相机列表异常: {combo_items}"
assert window.calibration_panel.get_reference() == "station_1"
# 站位面板列表显示
assert window.station_panel.list_stations.count() == 3
assert "站位 1 - " in window.station_panel.list_stations.item(0).text()
print(f"  网格 4 卡片: {list(window.cards.keys())}（物理卡片在第一位）")
print(f"  标定面板参考下拉: {combo_items}，默认参考 station_1")
print("  [OK] UI 站位模式通过")

# ------------------------------------------------------------------
# [4] 端到端：3 站位合成编码圆 → 检测 → 标定 → 拼接（对齐 < 2mm）
# ------------------------------------------------------------------
print("\n[4] 端到端：3 站位检测 → 标定 → 拼接")
STATION_IDS = ["station_1", "station_2", "station_3"]
REF_ID = "station_1"
N_MARKERS = 8
N_OBJ_PTS = 200
MARKER_NOISE_MM = 0.3

# 各非参考站位 station→station_1 真值外参
T_TRUE = {
    "station_2": np.vstack([np.hstack([rotz(15), np.array([[100.0], [50.0], [20.0]])]),
                            [0, 0, 0, 1]]),
    "station_3": np.vstack([np.hstack([rotz(-12), np.array([[-80.0], [60.0], [30.0]])]),
                            [0, 0, 0, 1]]),
}
# 标定板编码圆（station_1 坐标系真值，所有站位共视同一块板）
np.random.seed(7)
board_ref = np.random.rand(N_MARKERS, 3) * 200 + np.array([50, 50, 300])
# 静态物体点云（station_1 坐标系真值）
obj_ref = np.random.rand(N_OBJ_PTS, 3) * 150 + np.array([-60, -60, 250])

markers_truth = {}
for sid in STATION_IDS:
    if sid == REF_ID:
        pts = board_ref + np.random.randn(N_MARKERS, 3) * MARKER_NOISE_MM
    else:
        pts = world_to_cam(board_ref, T_TRUE[sid]) \
            + np.random.randn(N_MARKERS, 3) * MARKER_NOISE_MM
    markers_truth[sid] = make_markers(pts)

window2 = MainWindow()
window2.left_tabs.setCurrentIndex(1)
window2._on_station_connect(0)
mock3 = MockCameraManager()
for i, sid in enumerate(STATION_IDS):
    if sid == REF_ID:
        obj_cam = obj_ref
    else:
        obj_cam = world_to_cam(obj_ref, T_TRUE[sid])
    mock3.push(make_station_frame(i + 1, obj_cam, tmp_dir, seed=200 + i))
window2.station_manager._cam_mgr = mock3
window2.station_manager._base_dir = os.path.join(tmp_dir, "stations_e2e")
for _ in range(3):
    window2._on_capture_station()
assert window2.station_manager.station_count() == 3

# 注入 FakeDetector（按站位帧落盘后的 PLY 路径查表）
table = {}
for sid, frame in window2.station_manager.get_frames().items():
    table[os.path.normpath(frame.offline_pointmap_path)] = markers_truth[sid]
window2.marker_detector = FakeDetector(table)
window2._on_detect_markers()
for sid in STATION_IDS:
    assert len(window2.frames[sid].markers) == N_MARKERS, \
        f"{sid} 标记数异常: {len(window2.frames[sid].markers)}"
# 检测叠加已画到站位卡片
assert len(window2.cards["station_1"].preview._markers) == N_MARKERS
print(f"  3 个站位各检测到 {N_MARKERS} 个编码圆（叠加已上卡）")

# 标定（station_1 为 ref，2 对 pair）
assert window2.calibration_panel.get_reference() == REF_ID
window2.calibration_panel._on_calibrate_all()
engine = window2.calibration_engine
assert len(engine.pair_results) == 2, f"应有 2 对标定结果: {list(engine.pair_results.keys())}"
for sid in ("station_2", "station_3"):
    res = engine.pair_results[(REF_ID, sid)]
    assert res.get('success'), f"{sid} 标定失败: {res.get('message')}"
    R_err = np.linalg.norm(res['T'][:3, :3] - T_TRUE[sid][:3, :3], ord='fro')
    t_err = np.linalg.norm(res['T'][:3, 3] - T_TRUE[sid][:3, 3])
    print(f"  {sid}→{REF_ID}: RMS {res['rms_mm']:.4f} mm | "
          f"旋转误差 {R_err:.6f} | 平移误差 {t_err:.4f} mm")
    assert R_err < 0.05, f"{sid} 旋转误差过大: {R_err}"
    assert t_err < 2.0, f"{sid} 平移误差过大: {t_err}"
assert window2.calibration_panel.table_pairs.rowCount() == 2

# 拼接
window2._on_stitch()
merged = window2.viewer_3d._pcd_merged
assert merged is not None, "3D 查看器应收到拼接点云"
assert len(merged.points) == 3 * N_OBJ_PTS, \
    f"合并点数应为 {3 * N_OBJ_PTS}，实际 {len(merged.points)}"
# 对齐误差验证
for sid in ("station_2", "station_3"):
    T_est = engine.get_transform(sid, REF_ID)
    obj_cam = world_to_cam(obj_ref, T_TRUE[sid])
    obj_h = np.hstack([obj_cam, np.ones((N_OBJ_PTS, 1))])
    obj_in_ref = (T_est @ obj_h.T).T[:, :3]
    align_err = np.linalg.norm(obj_in_ref - obj_ref, axis=1).mean()
    print(f"  {sid} 点云对齐误差: {align_err:.4f} mm")
    assert align_err < 2.0, f"{sid} 对齐误差过大: {align_err}"
print(f"  合并点云: {len(merged.points):,} 点（3 站位 × {N_OBJ_PTS} 点）")
print("  [OK] 端到端标定拼接通过（对齐误差 < 2mm）")

# ------------------------------------------------------------------
# [5] 删除站位：删 station_2 后标定结果正确更新
# ------------------------------------------------------------------
print("\n[5] 删除站位 station_2")
s2_dir = window2.station_manager.get_frame("station_2").offline_dir
window2._on_remove_station("station_2")
assert window2.station_manager.station_count() == 2
assert window2.station_manager.get_station_ids() == ["station_1", "station_3"]
assert "station_2" not in window2.frames, "站位 2 帧未移除"
assert "station_2" not in window2.cards, "站位 2 卡片未移除"
assert not os.path.exists(s2_dir), "站位 2 磁盘目录未清理"
# 涉及 station_2 的标定结果已清理，station_3 的结果保留
assert (REF_ID, "station_2") not in engine.pair_results, "站位 2 标定结果未清理"
assert (REF_ID, "station_3") in engine.pair_results, "站位 3 标定结果应保留"
assert window2.calibration_panel.table_pairs.rowCount() == 1, \
    f"结果表应剩 1 行，实际 {window2.calibration_panel.table_pairs.rowCount()}"
assert window2.grid_layout.count() == 3, "网格应剩 3 个卡片（1 物理 + 2 站位）"
print("  标定结果仅剩 station_3→station_1，卡片 / 帧 / 磁盘目录均已清理")
print("  [OK] 删除站位通过")

# ------------------------------------------------------------------
# [6] 新会话：清空后 station_count == 0
# ------------------------------------------------------------------
print("\n[6] 新会话")
old_session = window2.station_manager.session_dir
window2._on_new_station_session()
assert window2.station_manager.station_count() == 0, "新会话后站位应清空"
assert window2.station_manager.get_station_ids() == []
new_session = window2.station_manager.session_dir
assert new_session and new_session != old_session and os.path.isdir(new_session), \
    "新会话目录未创建"
# 站位卡片清空，物理相机卡片保留
assert list(window2.cards.keys()) == [MainWindow.PHYSICAL_ID], \
    f"应只剩物理相机卡片: {list(window2.cards.keys())}"
assert not any(sid.startswith("station_") for sid in window2.frames), "站位帧应清空"
assert window2.station_panel.list_stations.count() == 0
# 旧会话目录归档保留（不删历史数据），但其中站位目录已被清空操作移除
assert os.path.isdir(old_session), "旧会话目录应归档保留"
print(f"  新会话目录: {new_session}")
print(f"  站位清空，物理相机卡片保留，旧会话归档: {old_session}")
print("  [OK] 新会话通过")

# ------------------------------------------------------------------
# 收尾
# ------------------------------------------------------------------
shutil.rmtree(tmp_dir, ignore_errors=True)

print("\n" + "=" * 60)
print("全部站位模式测试通过 [ALL OK]")
print("=" * 60)
