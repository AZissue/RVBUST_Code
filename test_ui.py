# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
MultiCameraCalibration UI 测试（QApplication offscreen 模式，无需相机）

验证：
  [1] UI 实例化（offscreen 模式，无相机环境不崩溃，拍摄按钮禁用）
  [2] 模拟添加 3 台相机 → 网格布局正确生成 3 个卡片
  [3] 模拟拍摄（合成图像）→ 卡片 2D 预览更新
  [4] 模拟标定（合成编码圆）→ 标定面板显示结果 + 4x4 矩阵
  [5] 模拟拼接（合成 PLY 点云）→ 3D 查看器接收点云
  [6] 标定结果 save / load（经 CalibrationEngine，UI 表刷新）
  [9] 后处理自动参数：set_process_params 回填 / 信号 / 过滤保护标红
  [10] 日志面板布局：提示区 QSplitter / 收起按钮 / 高度可拖无上限
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from PySide6.QtWidgets import QApplication

print("=" * 60)
print("MultiCameraCalibration UI 测试（offscreen）")
print("=" * 60)

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow, STYLESHEET
from core.frame_data import FrameData

app.setStyleSheet(STYLESHEET)


def make_markers(pts: np.ndarray, code_offset: int = 0):
    """由 Nx3 点数组构造编码圆 markers 列表（含 2D 坐标供叠加显示）。"""
    return [
        {'code': i + code_offset,
         'x': 100.0 + i * 10, 'y': 100.0 + i * 10,
         'x_2d': 100.0 + i * 10, 'y_2d': 100.0 + i * 10,
         'x_3d': float(pts[i, 0]), 'y_3d': float(pts[i, 1]), 'z_3d': float(pts[i, 2])}
        for i in range(len(pts))
    ]


def rotz(deg: float) -> np.ndarray:
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0],
                     [np.sin(a),  np.cos(a), 0],
                     [0, 0, 1]])


def make_synthetic_image(seed: int = 0) -> np.ndarray:
    """合成 BGR 测试图像（渐变 + 随机噪声）。"""
    rng = np.random.default_rng(seed)
    h, w = 480, 640
    grad = np.linspace(0, 180, w, dtype=np.uint8)[None, :].repeat(h, axis=0)
    img = np.stack([grad, grad // 2, 255 - grad], axis=-1)
    noise = rng.integers(0, 30, (h, w, 3), dtype=np.uint8)
    return np.clip(img.astype(np.int32) + noise, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------
# [1] UI 实例化（无相机环境）
# ------------------------------------------------------------------
print("\n[1] UI 实例化测试（offscreen，无相机）")
window = MainWindow()
assert window.camera_panel is not None
assert window.calibration_panel is not None
assert window.stitch_panel is not None
assert window.viewer_3d is not None
assert len(window.cards) == 0, "初始应无相机卡片"
assert not window.camera_panel.btn_capture_all.isEnabled(), "无相机时拍摄按钮应禁用"
print("  主窗口 / 三面板 / 3D 查看器实例化成功")
print("  [OK] 无相机环境启动不崩溃，拍摄按钮已禁用")

# ------------------------------------------------------------------
# [2] 模拟添加 3 台相机 → 网格布局 3 个卡片
# ------------------------------------------------------------------
print("\n[2] 模拟添加 3 台相机")
window._on_add_cameras([0, 1, 2])  # 无真实设备：连接失败但卡片照常生成
assert len(window.cards) == 3, f"应有 3 个卡片，实际 {len(window.cards)}"
assert window.grid_layout.count() == 3, f"网格应有 3 个卡片，实际 {window.grid_layout.count()}"
assert window.camera_panel.list_cameras.count() == 3, "左面板相机列表应有 3 项"
assert window.calibration_panel.combo_ref.count() == 3, "参考相机下拉应有 3 项"
cam_ids = list(window.cards.keys())
print(f"  相机 ID: {cam_ids}")
# 3 台相机 → 2 列布局：(0,0) (0,1) (1,0)
positions = []
for i in range(window.grid_layout.count()):
    item = window.grid_layout.itemAt(i)
    r, c, _, _ = window.grid_layout.getItemPosition(i)
    positions.append((r, c))
assert positions == [(0, 0), (0, 1), (1, 0)], f"3 相机应为 2×2 网格布局: {positions}"
print(f"  网格位置: {positions}（2×2 布局正确）")
print("  [OK] 3 个卡片生成，网格布局正确")

# ------------------------------------------------------------------
# [3] 模拟拍摄（合成图像）→ 卡片更新
# ------------------------------------------------------------------
print("\n[3] 模拟拍摄（合成图像）")
for i, cid in enumerate(cam_ids):
    frame = FrameData(frame_id=0, camera_name=cid,
                      image_np=make_synthetic_image(seed=i))
    window._store_frame(cid, frame)
for cid in cam_ids:
    card = window.cards[cid]
    assert card.preview._pixmap is not None and not card.preview._pixmap.isNull(), \
        f"卡片 {cid} 预览未更新"
    assert "640×480" in card.lbl_info.text(), f"分辨率显示异常: {card.lbl_info.text()}"
assert len(window.frames) == 3, "主窗口应保存 3 帧"
print("  3 个卡片 2D 预览均已更新（640×480 合成图像）")
print("  [OK] 模拟拍摄 → 卡片更新通过")

# ------------------------------------------------------------------
# [4] 模拟标定（合成编码圆）→ 标定面板显示结果
# ------------------------------------------------------------------
print("\n[4] 模拟标定（cam0 为参考）")
np.random.seed(42)
n_markers = 8
pts_ref = np.random.rand(n_markers, 3) * 200 + np.array([50, 50, 100])  # mm
# cam1：绕 z 轴 15° + 平移；cam2：绕 z 轴 -10° + 平移
transforms = {
    cam_ids[1]: (rotz(15), np.array([100.0, 50.0, 20.0])),
    cam_ids[2]: (rotz(-10), np.array([-80.0, 60.0, 30.0])),
}
window.frames[cam_ids[0]].markers = make_markers(pts_ref)
for cid in (cam_ids[1], cam_ids[2]):
    R, t = transforms[cid]
    pts_cam = (pts_ref @ R.T + t) + np.random.randn(n_markers, 3) * 0.3
    window.frames[cid].markers = make_markers(pts_cam)

# 走面板信号路径：标定所有 pair（cam0 为参考）
assert window.calibration_panel.get_reference() == cam_ids[0]
window.calibration_panel._on_calibrate_all()

table = window.calibration_panel.table_pairs
assert table.rowCount() == 2, f"结果表应有 2 行，实际 {table.rowCount()}"
for row in range(2):
    rms_text = table.item(row, 1).text()
    rms = float(rms_text)
    quality = table.item(row, 5).text()
    print(f"  {table.item(row, 0).text()} | RMS {rms:.4f} mm | 质量: {quality}")
    assert rms < 2.0, f"RMS 过大: {rms}"
    assert quality in ("优", "良", "合格"), f"质量评分异常: {quality}"

# 选中第一行 → 显示 4x4 矩阵
table.selectRow(0)
mat_item = window.calibration_panel.table_matrix.item(0, 0)
assert mat_item is not None and mat_item.text(), "矩阵表应有内容"
print(f"  矩阵 T[0,:] = {[window.calibration_panel.table_matrix.item(0, j).text() for j in range(4)]}")
print("  [OK] 标定面板结果表 + 4x4 矩阵显示正确")

# 多帧累积 + 多帧标定
window._on_add_frame()
# 模拟移动标定板后重新拍摄：检测会生成新的 markers 列表，指纹不同，应正常累积
for cid in cam_ids:
    window.frames[cid].markers = [
        dict(m, x_3d=m['x_3d'] + 0.1) for m in window.frames[cid].markers]
window._on_add_frame()
assert "2" in window.calibration_panel.lbl_frames.text(), "累积帧数应为 2"
# 重复累积防护：数据未变（指纹相同）应跳过，帧数不增加
window._on_add_frame()
assert "2" in window.calibration_panel.lbl_frames.text(), "重复数据应跳过，帧数仍为 2"
window._on_calibrate_multi()
assert window.calibration_panel.table_pairs.rowCount() == 2
# 多帧结果内点列应带帧数信息，如 "32/32 (2帧)"
cell = window.calibration_panel.table_pairs.item(0, 3).text()
assert "帧" in cell and "/" in cell, f"多帧内点列应含帧数信息: {cell}"
print(f"  多帧结果内点列: {cell}")
print("  [OK] 多帧累积 + 重复跳过防护 + 多帧标定通过")

# ------------------------------------------------------------------
# [5] 模拟拼接（合成 PLY 点云）→ 3D 查看器接收点云
# ------------------------------------------------------------------
print("\n[5] 模拟拼接（合成 PLY 点云）")
import open3d as o3d

tmp_dir = tempfile.mkdtemp(prefix="mcc_ui_test_")
rng = np.random.default_rng(7)
for i, cid in enumerate(cam_ids):
    # 每台相机 2000 个随机点（围绕标定板区域）
    pts = rng.random((2000, 3)) * 300 + np.array([0, 0, 100])
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    ply_path = os.path.join(tmp_dir, f"{cid}.ply")
    o3d.io.write_point_cloud(ply_path, pcd)
    # 切到离线帧（保留标记数据用于标定结果复用）
    old = window.frames[cid]
    frame = FrameData(frame_id=1, camera_name=cid,
                      image_np=old.image_np,
                      markers=old.markers,
                      is_offline=True,
                      offline_pointmap_path=ply_path)
    window.frames[cid] = frame

window._on_stitch()
assert window.viewer_3d._pcd_merged is not None, "3D 查看器应收到合并点云"
n_merged = len(window.viewer_3d._pcd_merged.points)
assert n_merged == 6000, f"合并点数应为 6000，实际 {n_merged}"
assert len(window.viewer_3d._pcds) == 3, "3D 查看器应收到 3 路点云"
assert "6,000" in window.stitch_panel.lbl_points.text(), \
    f"拼接面板点数显示异常: {window.stitch_panel.lbl_points.text()}"
# 查看器内部渲染数据（numpy 层，不触发 GL）
assert window.viewer_3d._viewer.point_count == 6000
print(f"  合并点云: {n_merged:,} 点 | 面板显示: {window.stitch_panel.lbl_points.text()}")
print(f"  3D 查看器: 3 路点云 + 合并结果已接收，模式下拉 {window.viewer_3d.combo_mode.count()} 项")
print("  [OK] 模拟拼接 → 3D 查看器接收点云通过")

# ------------------------------------------------------------------
# [6] 标定结果 save / load
# ------------------------------------------------------------------
print("\n[6] 标定结果 save / load")
cal_path = os.path.join(tmp_dir, "calibration.json")
assert window.calibration_engine.save_calibration(cal_path)
window.calibration_panel.clear_results()
assert window.calibration_panel.table_pairs.rowCount() == 0
assert window.calibration_engine.load_calibration(cal_path)
window.calibration_panel.update_results(window.calibration_engine.pair_results)
assert window.calibration_panel.table_pairs.rowCount() == 2, "加载后结果表应恢复 2 行"
print(f"  保存/加载: {cal_path}")
print("  [OK] 标定结果 save / load 通过")

# ------------------------------------------------------------------
# [7] 3D 查看器工具栏：着色 / 点大小 / 视角预设 / 参考元素 / 最大化
# ------------------------------------------------------------------
print("\n[7] 3D 查看器工具栏功能（数据层，offscreen 不触发 GL）")
viewer = window.viewer_3d
gl = viewer._viewer

# 着色模式切换（合并模式下应能基于缓存数据重算颜色，不崩溃）
assert viewer.combo_color.count() == 3
for i in range(viewer.combo_color.count()):
    viewer.combo_color.setCurrentIndex(i)
    assert gl.point_count == 6000, f"着色切换后点数异常: {gl.point_count}"
    mode = viewer.combo_color.currentData()
    z = gl.points[:, 2]
    if mode == viewer.COLOR_HEIGHT:
        # jet 渐变：z 最小≈蓝，z 最大≈红
        lo, hi = np.argmin(z), np.argmax(z)
        assert gl.colors[hi, 0] > gl.colors[lo, 0], "按高度着色红色分量应随 z 增大"
    elif mode == viewer.COLOR_GRAY:
        assert np.allclose(gl.colors, 0.5, atol=0.05), "灰度着色应接近 0.5"
viewer.combo_color.setCurrentIndex(0)  # 恢复按站位
print("  着色模式（站位 / 高度 / 灰度）切换通过，点数不变")

# 点大小
viewer.set_point_size(3)
assert gl._point_size == 3.0
viewer.spin_point_size.setValue(1)
assert gl._point_size == 1.0
print("  点大小设置通过 (1~5 px)")

# 视角预设
viewer.set_view_preset("top")
assert gl.camera.rotation_x == 89.0 and gl.camera.rotation_y == 0.0
viewer.set_view_preset("front")
assert gl.camera.rotation_x == 0.0 and gl.camera.rotation_y == 0.0
viewer.set_view_preset("side")
assert gl.camera.rotation_y == 90.0
viewer.set_view_preset("iso")
assert gl.camera.rotation_x == 30.0 and gl.camera.rotation_y == -45.0
print("  视角预设（顶 / 前 / 侧 / 等轴）调用通过")

# 坐标轴 / 网格开关（checkable 图标按钮，toggled → 渲染标志）
assert viewer.btn_axes.isCheckable() and viewer.btn_axes.isChecked()
assert viewer.btn_grid.isCheckable() and viewer.btn_grid.isChecked()
assert not viewer.btn_axes.icon().isNull(), "view_axes.png 应已加载"
assert not viewer.btn_grid.icon().isNull(), "view_grid.png 应已加载"
viewer.btn_axes.setChecked(False)
assert gl._show_axes is False
viewer.btn_axes.setChecked(True)
assert gl._show_axes is True
viewer.btn_grid.setChecked(False)
assert gl._show_grid is False
viewer.btn_grid.setChecked(True)
assert gl._show_grid is True
print("  坐标轴 / 网格开关（图标按钮 toggled）通过")

# 背景切换
viewer.btn_bg.setChecked(True)
assert gl._bg_color[0] > 0.5, "浅色背景应亮度 > 0.5"
viewer.btn_bg.setChecked(False)
assert gl._bg_color[0] < 0.5, "深色背景应亮度 < 0.5"
print("  背景深 / 浅切换通过")

# 折叠 / 展开（view_iso.png 图标）
assert not viewer.btn_collapse.icon().isNull(), "view_iso.png 应已加载"
viewer.btn_collapse.setChecked(False)
assert not viewer.viewer_container.isVisible()
viewer.btn_collapse.setChecked(True)
print("  折叠 / 展开切换通过")

# 最大化：隐藏卡片区与左右面板，再恢复
window.show()
viewer.btn_maximize.setChecked(True)
assert not window.grid_scroll.isVisible()
assert not window.left_tabs.isVisible()
assert not window.right_tabs.isVisible()
viewer.btn_maximize.setChecked(False)
assert window.grid_scroll.isVisible()
assert window.left_tabs.isVisible()
assert window.right_tabs.isVisible()
window.hide()
print("  最大化 / 恢复切换通过（卡片区 + 左右面板联动）")
print("  [OK] 3D 查看器工具栏功能全部通过")

# ------------------------------------------------------------------
# [8] 图标系统（assets/icons/ 自定义图标，无文件 emoji 兜底）
# ------------------------------------------------------------------
print("\n[8] 图标系统测试")
from ui.icons import (icons_dir, has_icon, get_icon, icon_text, apply_icon,
                      reload_icons, strip_emoji)
from ui.panels.camera_panel import CameraPanel
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QPushButton

# 8.1 icons_dir() 路径定位（项目根/assets/icons）
d = icons_dir()
assert d.name == "icons" and d.parent.name == "assets", f"icons_dir 异常: {d}"
assert (d / "README.md").is_file(), "assets/icons/README.md 应存在"
print(f"  icons_dir(): {d}")

# 8.2 兜底逻辑：不存在的图标名 → 空 QIcon + 原文本
reload_icons()
assert not has_icon("__missing_icon__"), "不存在的图标名应返回 False"
assert get_icon("__missing_icon__").isNull(), "无文件时 get_icon 应为空 QIcon"
assert icon_text("__missing_icon__", "📸 拍摄") == "📸 拍摄", "无文件时应返回原文本"
print("  兜底：缺失图标名返回空 QIcon / 原文本")

# 8.2b 项目自带图标已生效：文本剥离 emoji + 图标非空（assets/icons/ 已随项目提供）
assert window.camera_panel.btn_capture_all.text() == "拍摄所有相机（同步软触发）"
assert not window.camera_panel.btn_capture_all.icon().isNull()
assert window.station_panel.btn_capture.text() == "拍摄站位"
assert not window.station_panel.btn_capture.icon().isNull()
assert window.left_tabs.tabText(0) == "多相机"
assert not window.left_tabs.tabIcon(0).isNull()
assert window.right_tabs.tabText(0) == "标定"
assert not window.right_tabs.tabIcon(0).isNull()
assert window.viewer_3d.btn_maximize.text() == "最大化"
assert not window.viewer_3d.btn_maximize.icon().isNull()
assert window.cards[cam_ids[0]].btn_capture.text() == "拍摄"
# 新实例化面板同样应用自带图标
_p = CameraPanel()
assert _p.btn_refresh.text() == "查找设备"
assert not _p.btn_refresh.icon().isNull()
_p.deleteLater()
print("  自带图标：文本剥离 emoji / setIcon 生效 / 新实例一致")

# 8.3 模拟放入临时 PNG：has_icon / get_icon / icon_text / apply_icon
tmp_icon = d / "test_icon.png"
pix = QPixmap(16, 16)
pix.fill(QColor("#4fc3f7"))
assert pix.save(str(tmp_icon), "PNG"), "临时测试图标写入失败"
try:
    reload_icons()  # 清缓存模拟热刷新
    assert has_icon("test_icon"), "放入 PNG 后 has_icon 应为 True"
    assert not get_icon("test_icon").isNull(), "放入 PNG 后 get_icon 应非空"
    assert icon_text("test_icon", "📸 拍摄") == "拍摄", "有文件时应剥离开头 emoji+空格"
    assert strip_emoji("⛶ 最大化") == "最大化"
    assert strip_emoji("🔎 检测标记（所有相机当前帧）") == "检测标记（所有相机当前帧）"
    btn = QPushButton(icon_text("test_icon", "📸 拍摄"))
    apply_icon(btn, "test_icon")
    assert not btn.icon().isNull(), "apply_icon 应设置图标"
    assert btn.iconSize() == QSize(16, 16), f"默认图标尺寸应 16×16: {btn.iconSize()}"
    assert btn.text() == "拍摄"
    apply_icon(btn, "test_icon", size=20)
    assert btn.iconSize() == QSize(20, 20), "大按钮图标尺寸应 20×20"
    btn.deleteLater()
    print("  临时 PNG：has_icon / get_icon / icon_text 剥离 emoji / apply_icon 均正确")
finally:
    tmp_icon.unlink(missing_ok=True)  # 测试完删除临时文件
    reload_icons()
assert not has_icon("test_icon"), "删除文件并 reload 后 has_icon 应恢复 False"
assert get_icon("test_icon").isNull()
print("  临时文件已清理，reload_icons 热刷新正常")

# 8.4 分组框图标（make_group_box + apply_group_icon）
from ui.icons import make_group_box, apply_group_icon, GROUP_ICON_LABEL_NAME
from PySide6.QtWidgets import QVBoxLayout, QLabel

# 有图标文件（assets/icons/ 已随项目提供 13 个分组图标）：
# group.title() 为空，布局顶部有图标 QLabel + 剥离 emoji 的标题文字
GROUP_CASES = [
    (window.camera_panel.grp_devices, "设备列表"),
    (window.camera_panel.grp_list, "已添加相机"),
    (window.camera_panel.grp_capture, "采集控制"),
    (window.camera_panel.grp_offline, "离线会话"),
    (window.station_panel.grp_cam, "物理相机"),
    (window.station_panel.grp_cap, "站位采集"),
    (window.station_panel.grp_list, "站位列表"),
    (window.calibration_panel.grp_ref, "参考相机"),
    (window.calibration_panel.grp_ctrl, "标定控制"),
    (window.calibration_panel.grp_result, "标定结果"),
    (window.calibration_panel.grp_matrix, "变换矩阵 T（cam→ref）"),
    (window.stitch_panel.grp_stitch, "拼接控制"),
    (window.stitch_panel.grp_proc, "后处理"),
    (window.stitch_panel.grp_result, "拼接结果"),
]
for grp, text in GROUP_CASES:
    assert grp.title() == "", f"有图标时分组框 title 应为空: {grp.title()}"
    lbl_icon = grp.findChild(QLabel, GROUP_ICON_LABEL_NAME)
    assert lbl_icon is not None, f"分组框「{text}」缺少图标 QLabel"
    assert not lbl_icon.pixmap().isNull(), f"分组框「{text}」图标 QLabel 无 pixmap"
    titles = [w.text() for w in grp.findChildren(QLabel) if w.text() == text]
    assert titles, f"分组框缺少剥离 emoji 的标题文字「{text}」"
print(f"  分组框图标：{len(GROUP_CASES)} 个 QGroupBox 均为图标标题行（title 为空）")

# 无图标文件兜底：setTitle 含 emoji 原文，apply_group_icon 不插入任何内容
g = make_group_box("__missing_icon__", "📷 设备列表")
assert g.title() == "📷 设备列表", "无图标文件时应 setTitle 含 emoji 原文"
g_lo = QVBoxLayout(g)
g_lo.addWidget(QLabel("内容"))
apply_group_icon(g)
assert g_lo.count() == 1, "无图标文件时 apply_group_icon 不应插入标题行"
assert g.title() == "📷 设备列表"
g.deleteLater()
print("  分组框兜底：缺失图标名 → setTitle 含 emoji / 不插入标题行")

# 有图标文件：title 为空，标题行插入布局顶部
g2 = make_group_box("camera", "📷 物理相机")
assert g2.title() == ""
g2_lo = QVBoxLayout(g2)
apply_group_icon(g2)
assert g2_lo.count() == 1, "标题行应插入空布局"
g2_lo.addWidget(QLabel("内容"))
assert g2_lo.count() == 2, "标题行应在内容之前（insert 0）"
lbl2 = g2.findChild(QLabel, GROUP_ICON_LABEL_NAME)
assert lbl2 is not None and not lbl2.pixmap().isNull()
g2.deleteLater()
print("  分组框有图标：title 为空 / 标题行含 16px 图标 QLabel")

# 8.5 日志面板标题图标（log.png）
assert not window.log_panel.lbl_log_icon.isHidden(), "log.png 存在时日志图标应显示"
assert not window.log_panel.lbl_log_icon.pixmap().isNull()
print("  日志面板：log.png 图标已接入标题行")
print("  [OK] 图标系统全部通过")

# ------------------------------------------------------------------
# [9] 后处理自动参数：面板回填 + 信号 + 过滤保护标红
# ------------------------------------------------------------------
print("\n[9] 后处理自动参数面板测试")
panel9 = window.stitch_panel
assert hasattr(panel9, 'auto_params_requested'), "缺少 auto_params_requested 信号"
assert panel9.btn_auto_params.objectName() == "primaryButton"

emitted9 = []
panel9.process_params_changed.connect(lambda d: emitted9.append(d))
params9 = {
    'crop_mode': 'aabb', 'crop_ratio': 0.85, 'crop_radius': 320.0,
    'enable_voxel_downsample': True, 'voxel_size': 1.25,
    'enable_outlier_removal': True, 'outlier_nb_neighbors': 30,
    'outlier_std_ratio': 1.5,
}
panel9.set_process_params(params9)
assert panel9.combo_crop.currentData() == 'aabb'
assert abs(panel9.spin_crop_ratio.value() - 0.85) < 1e-9
assert abs(panel9.spin_crop_radius.value() - 320.0) < 1e-9
assert panel9.chk_voxel.isChecked() is True
assert abs(panel9.spin_voxel.value() - 1.25) < 1e-9
assert panel9.chk_outlier.isChecked() is True
assert panel9.spin_nb.value() == 30
assert abs(panel9.spin_std.value() - 1.5) < 1e-9
assert len(emitted9) == 1, \
    f"set_process_params 应只触发一次信号: {len(emitted9)}"
assert emitted9[0]['crop_mode'] == 'aabb' and emitted9[0]['outlier_nb_neighbors'] == 30
assert window._process_params['crop_mode'] == 'aabb', "主窗口应同步收到参数"
print("  set_process_params 回填正确，且只触发一次 process_params_changed")

panel9.set_auto_notes(["依据甲", "依据乙"])
assert "依据甲" in panel9.lbl_auto_notes.text()
assert not panel9.lbl_auto_notes.isHidden(), "有内容时 lbl_auto_notes 应显示"
panel9.set_auto_notes([])
assert panel9.lbl_auto_notes.isHidden(), "空 notes 时应隐藏"
panel9.set_auto_notes(["依据甲", "依据乙"])
print("  lbl_auto_notes 依据显示 / 隐藏通过")

# 过滤保护标红 / 恢复
panel9.set_points_alert(True)
assert "dc2626" in panel9.lbl_points.styleSheet().lower(), "过激时应标红"
panel9.set_points_alert(False)
assert panel9.lbl_points.styleSheet() == "", "正常时应恢复默认样式"
print("  点数标红 / 恢复通过")
print("  [OK] 后处理自动参数面板测试通过")

# ------------------------------------------------------------------
# [10] 日志面板布局：提示区 QSplitter / 收起按钮 / 高度可拖无上限
# ------------------------------------------------------------------
print("\n[10] 日志面板布局测试")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

lp = window.log_panel

# 内容区为水平 QSplitter：左提示 / 右日志
assert isinstance(lp.splitter, QSplitter), "日志面板内容区应为 QSplitter"
assert lp.splitter.orientation() == Qt.Horizontal
assert lp.splitter.widget(0) is lp.tips_edit, "splitter 第 0 项应为 tips_edit"
assert lp.splitter.widget(1) is lp.log_content, "splitter 第 1 项应为 log_content"
assert lp.tips_edit.minimumWidth() == 0, "tips_edit 不应再有固定 240px 宽"
assert lp.tips_edit.maximumWidth() > 240, "tips_edit 宽度不应被固定"
print("  内容区 QSplitter(提示|日志) 结构正确，tips 固定宽度已移除")

# 提示收起 / 展开按钮行为
assert hasattr(lp, 'btn_tips'), "缺少 btn_tips 收起提示按钮"
assert lp.btn_tips.text() == "◀ 提示"
assert not lp.tips_edit.isHidden(), "初始提示区应可见"
lp.btn_tips.click()
assert lp.tips_edit.isHidden(), "收起后 tips_edit 应隐藏"
assert not lp.log_content.isHidden(), "收起后日志区应仍可见"
assert lp.btn_tips.text() == "▶ 提示"
assert lp._tips_sizes is not None, "收起时应记忆 splitter 位置"
lp.btn_tips.click()
assert not lp.tips_edit.isHidden(), "展开后 tips_edit 应恢复可见"
assert lp.btn_tips.text() == "◀ 提示"
assert lp.splitter.sizes()[0] > 0, "展开后提示区宽度应恢复"
print("  btn_tips 收起/展开：隐藏、占满、恢复位置均正确")

# 日志整体折叠（▼ 日志）不受影响
lp.btn_toggle.click()
assert lp.content.isHidden(), "▼ 日志折叠后内容区应隐藏"
lp.btn_toggle.click()
assert not lp.content.isHidden(), "再次点击应恢复展开"
print("  日志整体折叠功能不受影响")

# 日志字号 9pt
assert "font-size: 9pt" in lp.log_content.styleSheet(), "日志字号应为 9pt"

# 高度无硬上限，由外层垂直 QSplitter 决定
assert lp.maximumHeight() >= 1000, \
    f"日志面板 maximumHeight 不应受限: {lp.maximumHeight()}"
assert isinstance(window.outer_splitter, QSplitter), "根布局应为垂直 QSplitter"
assert window.outer_splitter.orientation() == Qt.Vertical
assert window.outer_splitter.widget(1) is lp, "outer_splitter 第 1 项应为日志面板"
print("  maximumHeight 无上限，outer_splitter(主区|日志) 结构正确")
print("  [OK] 日志面板布局测试通过")

# ------------------------------------------------------------------
# 收尾
# ------------------------------------------------------------------
import shutil
shutil.rmtree(tmp_dir, ignore_errors=True)

print("\n" + "=" * 60)
print("全部 UI 测试通过 [ALL OK]")
print("=" * 60)
