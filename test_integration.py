# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration 端到端集成测试（offscreen + 合成数据）

覆盖完整离线工作流：
  [1]  模拟 3 相机连接（无真实设备，卡片照常生成）
  [2]  模拟拍摄 5 对帧（3 台相机 × 合成编码圆 3D 标记 + 合成 PLY 点云）
  [3]  保存到离线会话（目录结构 + 会话 meta.json 校验）
  [4]  重新加载会话
  [5]  批量检测（注入 FakeDetector 模拟编码圆检测）
  [6]  批量标定（多帧平均，验证外参精度）
  [7]  批量拼接（验证合并点数）
  [8]  验证拼接结果（变换矩阵精度 / 点云对齐误差）
  [9]  保存标定结果 JSON
  [10] 重新加载标定结果，验证一致
"""
import os
import sys
import json
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from PySide6.QtWidgets import QApplication

print("=" * 60)
print("MultiCameraCalibration 集成测试（offscreen + 合成数据）")
print("=" * 60)

app = QApplication.instance() or QApplication(sys.argv)

import open3d as o3d

from ui.main_window import MainWindow, STYLESHEET
from core.frame_data import FrameData
from core.calibration_engine import CalibrationEngine

app.setStyleSheet(STYLESHEET)


# ------------------------------------------------------------------
# 工具函数
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
        # 统一规范化路径分隔符后查表
        key = os.path.normpath(offline_ply_path)
        return list(self._table.get(key, []))


# ------------------------------------------------------------------
# 场景参数（真值）
# ------------------------------------------------------------------
CAM_IDS = ["cam0", "cam1", "cam2"]
REF_ID = "cam0"
N_CAPTURES = 5
N_MARKERS = 8
N_OBJ_PTS = 200
MARKER_NOISE_MM = 0.3

np.random.seed(2026)

# 各非参考相机 cam→ref 真值外参
T_TRUE = {
    "cam1": np.vstack([np.hstack([rotz(15), np.array([[100.0], [50.0], [20.0]])]), [0, 0, 0, 1]]),
    "cam2": np.vstack([np.hstack([rotz(-12), np.array([[-80.0], [60.0], [30.0]])]), [0, 0, 0, 1]]),
}

# 标定板基准点（ref 坐标系），每拍摄一次板子移动一个位姿
board0 = np.random.rand(N_MARKERS, 3) * 200 + np.array([50, 50, 300])
board_poses = []  # 每拍板子在 ref 坐标系的点
for i in range(N_CAPTURES):
    R_i = rotz(-20 + i * 10)
    t_i = np.array([i * 15.0, -i * 10.0, i * 5.0])
    board_poses.append(board0 @ R_i.T + t_i)

# 静态物体点云（ref 坐标系真值，各拍相同）
obj_ref = np.random.rand(N_OBJ_PTS, 3) * 150 + np.array([-60, -60, 250])

# 每拍/每相机的 markers 真值（含噪声）：(frame_id, camera_id) → markers
markers_truth = {}
for i in range(N_CAPTURES):
    fid = i + 1
    markers_truth[(fid, REF_ID)] = make_markers(
        board_poses[i] + np.random.randn(N_MARKERS, 3) * MARKER_NOISE_MM)
    for cid in ("cam1", "cam2"):
        pts_cam = world_to_cam(board_poses[i], T_TRUE[cid]) \
            + np.random.randn(N_MARKERS, 3) * MARKER_NOISE_MM
        markers_truth[(fid, cid)] = make_markers(pts_cam)

tmp_dir = tempfile.mkdtemp(prefix="mcc_integration_")

# ------------------------------------------------------------------
# [1] 模拟 3 相机连接
# ------------------------------------------------------------------
print("\n[1] 模拟 3 相机连接")
window = MainWindow()
window._on_add_cameras([0, 1, 2])  # 无真实设备：连接失败但卡片照常生成
assert list(window.cards.keys()) == CAM_IDS, f"相机卡片异常: {list(window.cards.keys())}"
assert not window.camera_panel.btn_save_frame.isEnabled(), "拍摄前保存帧按钮应禁用"
print(f"  相机 ID: {CAM_IDS}（无真实设备，卡片已生成）")
print("  [OK] 3 相机模拟连接通过")

# ------------------------------------------------------------------
# [2] + [3] 模拟拍摄 5 对帧并逐拍保存到离线会话
# ------------------------------------------------------------------
print(f"\n[2] 模拟拍摄 {N_CAPTURES} 对帧（3 相机 × 合成图像 + PLY 点云）")
for i in range(N_CAPTURES):
    fid = i + 1
    for cid in CAM_IDS:
        # 各相机坐标系下的物体点云（静态物体）
        if cid == REF_ID:
            obj_cam = obj_ref
        else:
            obj_cam = world_to_cam(obj_ref, T_TRUE[cid])
        ply_path = os.path.join(tmp_dir, f"cap{fid}_{cid}.ply")
        write_ply(obj_cam, ply_path)
        frame = FrameData(frame_id=fid, camera_name=cid,
                          image_np=make_synthetic_image(seed=fid * 10 + int(cid[-1])),
                          is_offline=True,
                          offline_pointmap_path=ply_path)
        window._store_frame(cid, frame)
    # 每拍完一组立即保存到会话（模拟真实工作流）
    window._on_save_frame_to_session()
assert window.camera_panel.btn_save_frame.isEnabled(), "拍摄后保存帧按钮应启用"
print(f"  {N_CAPTURES} 拍 × {len(CAM_IDS)} 相机已拍摄并保存")

print("\n[3] 校验离线会话目录结构")
session_dir = window.offline_session.session_dir
assert session_dir and os.path.isdir(session_dir), "会话目录未创建"
print(f"  会话目录: {session_dir}")
for fid in range(1, N_CAPTURES + 1):
    frame_dir = os.path.join(session_dir, f"frame_{fid:04d}")
    assert os.path.isdir(frame_dir), f"缺帧目录: {frame_dir}"
    for cid in CAM_IDS:
        assert os.path.exists(os.path.join(frame_dir, f"{cid}.png")), f"缺图像: frame_{fid:04d}/{cid}.png"
        assert os.path.exists(os.path.join(frame_dir, f"{cid}.ply")), f"缺点云: frame_{fid:04d}/{cid}.ply"
    meta_path = os.path.join(frame_dir, "meta.json")
    with open(meta_path, 'r', encoding='utf-8') as f:
        fmeta = json.load(f)
    assert set(fmeta.get("cameras", {}).keys()) == set(CAM_IDS), f"帧 meta 相机列表异常: {fmeta}"
with open(os.path.join(session_dir, "meta.json"), 'r', encoding='utf-8') as f:
    smeta = json.load(f)
assert smeta["frame_count"] == N_CAPTURES, f"会话帧数异常: {smeta}"
assert set(smeta["camera_ids"]) == set(CAM_IDS), f"会话相机列表异常: {smeta}"
assert "created" in smeta
print(f"  会话 meta: {smeta['frame_count']} 帧, 相机 {smeta['camera_ids']}")
print("  [OK] 会话保存通过（frame_XXXX/{cam}.png+{cam}.ply+meta.json）")

# ------------------------------------------------------------------
# [4] 重新加载会话
# ------------------------------------------------------------------
print("\n[4] 重新加载会话")
# 保存前未做检测 → meta 中 markers 为空，验证加载后也为空
assert window._load_session_from(session_dir), "会话加载失败"
loaded = window.offline_session.frames
assert set(loaded.keys()) == set(CAM_IDS)
assert all(len(v) == N_CAPTURES for v in loaded.values()), "每台相机应有 5 帧"
assert all(f.markers == [] for v in loaded.values() for f in v), "加载的帧应无标记（未检测）"
assert set(window.frames.keys()) == set(CAM_IDS), "主窗口当前帧应同步为会话最新帧"
print(f"  加载: {len(loaded)} 台相机 × {N_CAPTURES} 帧, 标记为空（待检测）")
print("  [OK] 会话加载通过")

# ------------------------------------------------------------------
# [5] 批量检测（FakeDetector 按 PLY 路径查表）
# ------------------------------------------------------------------
print("\n[5] 批量检测会话标记")
table = {}
for cid, frames in loaded.items():
    for f in frames:
        table[os.path.normpath(f.offline_pointmap_path)] = markers_truth[(f.frame_id, cid)]
window.marker_detector = FakeDetector(table)
window._on_batch_detect()
for cid, frames in loaded.items():
    for f in frames:
        assert len(f.markers) == N_MARKERS, \
            f"{cid} frame_{f.frame_id} 标记数异常: {len(f.markers)}"
print(f"  全部 {len(loaded)} 台相机 × {N_CAPTURES} 帧均检测到 {N_MARKERS} 个编码圆")
# 验证检测结果已回写到帧 meta.json
with open(os.path.join(session_dir, "frame_0001", "meta.json"), 'r', encoding='utf-8') as f:
    fmeta = json.load(f)
assert len(fmeta["cameras"]["cam0"]["markers"]) == N_MARKERS, "检测结果未回写 meta.json"
print("  [OK] 批量检测通过（结果已回写帧 meta.json）")

# ------------------------------------------------------------------
# [6] 批量标定（多帧平均）
# ------------------------------------------------------------------
print("\n[6] 批量标定会话（多帧平均）")
assert window.calibration_panel.get_reference() == REF_ID
window._on_batch_calibrate()
engine = window.calibration_engine
assert len(engine.pair_results) == 2, f"应有 2 对标定结果: {list(engine.pair_results.keys())}"
for cid in ("cam1", "cam2"):
    res = engine.pair_results[(REF_ID, cid)]
    assert res.get('success'), f"{cid} 标定失败: {res.get('message')}"
    assert res.get('valid_frames') == N_CAPTURES, f"{cid} 有效帧数异常: {res.get('valid_frames')}"
    assert res.get('total_frames') == N_CAPTURES, f"{cid} 总帧数异常: {res.get('total_frames')}"
    # 内点语义与单帧统一：按标记统计（合成数据无离群点 → 全部内点）
    assert res.get('total_pairs') == N_CAPTURES * N_MARKERS, \
        f"{cid} 匹配标记总数异常: {res.get('total_pairs')}"
    assert res.get('inlier_count') == res.get('total_pairs'), \
        f"{cid} 无离群点时内点标记应等于匹配标记: {res.get('inlier_count')}"
    assert res.get('outlier_count') == 0, f"{cid} 不应有离群点: {res.get('outlier_codes')}"
    R_err = np.linalg.norm(res['T'][:3, :3] - T_TRUE[cid][:3, :3], ord='fro')
    t_err = np.linalg.norm(res['T'][:3, 3] - T_TRUE[cid][:3, 3])
    print(f"  {cid}→{REF_ID}: 有效帧 {res['valid_frames']}/{N_CAPTURES} | "
          f"RMS {res['rms_mm']:.4f} mm | 旋转误差 {R_err:.6f} | 平移误差 {t_err:.4f} mm")
    assert R_err < 0.05, f"{cid} 旋转误差过大: {R_err}"
    assert t_err < 2.0, f"{cid} 平移误差过大: {t_err}"
assert window.calibration_panel.table_pairs.rowCount() == 2, "标定面板应显示 2 行结果"
print("  [OK] 批量标定通过（多帧平均精度满足要求）")

# ------------------------------------------------------------------
# [7] 批量拼接
# ------------------------------------------------------------------
print("\n[7] 批量拼接会话")
window._on_stitch_session()
merged = window.viewer_3d._pcd_merged
assert merged is not None, "3D 查看器应收到批量拼接点云"
expect_pts = N_CAPTURES * len(CAM_IDS) * N_OBJ_PTS
assert len(merged.points) == expect_pts, \
    f"合并点数应为 {expect_pts}，实际 {len(merged.points)}"
print(f"  合并点云: {len(merged.points):,} 点 "
      f"({N_CAPTURES} 拍 × {len(CAM_IDS)} 相机 × {N_OBJ_PTS} 点)")
print("  [OK] 批量拼接通过")

# ------------------------------------------------------------------
# [8] 验证拼接结果（变换矩阵精度 / 点云对齐误差）
# ------------------------------------------------------------------
print("\n[8] 拼接结果精度验证")
for cid in ("cam1", "cam2"):
    T_est = engine.get_transform(cid, REF_ID)
    obj_cam = world_to_cam(obj_ref, T_TRUE[cid])
    obj_h = np.hstack([obj_cam, np.ones((N_OBJ_PTS, 1))])
    obj_in_ref = (T_est @ obj_h.T).T[:, :3]
    align_err = np.linalg.norm(obj_in_ref - obj_ref, axis=1).mean()
    print(f"  {cid} 点云经估计外参变换到 {REF_ID} 后平均对齐误差: {align_err:.4f} mm")
    assert align_err < 2.0, f"{cid} 对齐误差过大: {align_err}"
print("  [OK] 拼接精度满足要求（对齐误差 < 2mm）")

# ------------------------------------------------------------------
# [9] 保存标定结果 JSON
# ------------------------------------------------------------------
print("\n[9] 保存标定结果")
cal_path = os.path.join(tmp_dir, "calibration.json")
assert engine.save_calibration(cal_path), "标定保存失败"
assert os.path.exists(cal_path)
print(f"  已保存: {cal_path}")
print("  [OK] 标定结果保存通过")

# ------------------------------------------------------------------
# [10] 重新加载标定结果，验证一致
# ------------------------------------------------------------------
print("\n[10] 重新加载标定结果并验证一致性")
engine2 = CalibrationEngine()
assert engine2.load_calibration(cal_path), "标定加载失败"
assert engine2.reference_id == REF_ID
assert len(engine2.pair_results) == 2
for cid in ("cam1", "cam2"):
    T1 = engine.pair_results[(REF_ID, cid)]['T']
    T2 = engine2.pair_results[(REF_ID, cid)]['T']
    assert np.allclose(T1, T2, atol=1e-12), f"{cid} 保存/加载矩阵不一致"
    # 加载后的矩阵同样满足精度要求
    R_err = np.linalg.norm(T2[:3, :3] - T_TRUE[cid][:3, :3], ord='fro')
    t_err = np.linalg.norm(T2[:3, 3] - T_TRUE[cid][:3, 3])
    assert R_err < 0.05 and t_err < 2.0, f"{cid} 加载后精度不足"
print("  保存/加载矩阵完全一致，且精度保持")
print("  [OK] 标定结果保存/加载一致性通过")

# ------------------------------------------------------------------
# 收尾
# ------------------------------------------------------------------
import shutil
shutil.rmtree(tmp_dir, ignore_errors=True)
shutil.rmtree(session_dir, ignore_errors=True)  # 清理测试生成的会话目录

print("\n" + "=" * 60)
print("全部集成测试通过 [ALL OK]")
print("=" * 60)
