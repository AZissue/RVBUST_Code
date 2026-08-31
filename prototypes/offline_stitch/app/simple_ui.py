# -*- coding: utf-8 -*-
"""
离线拼接测试 UI（基于主程序 ui_v2 组件重构）。

功能：
  - 选择本地图像/点云文件夹；
  - 列出按文件名前缀匹配的文件对；
  - 点击文件对：左侧显示 2D 图像（红点标出编码圆圆心），右侧显示 3D 点云；
  - 点击「拼接」：自动检测、配准、合并，输出结果信息；
  - 支持保存合并后的 PLY。

说明：
  - 使用主程序 ui_v2 的 GLOBAL_QSS 主题、ViewerPanel 3D 查看器、LoadingOverlay；
  - 仅作原型验证，不入主程序模式栈；后续由测试决定是否并入主程序。
"""

from __future__ import annotations

import os
import sys

# 把项目 src 和本原型 core 加入路径
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import json
import numpy as np
import cv2
import open3d as o3d

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QFileDialog, QMessageBox, QSizePolicy, QSplitter,
    QSpinBox, QDoubleSpinBox, QGroupBox, QCheckBox
)

# 复用主程序 ui_v2 的主题与控件
from ui_v2.theme import GLOBAL_QSS, BG_PANEL, TEXT_MUTED, TEXT_SECONDARY
from ui_v2.widgets.viewer_panel import ViewerPanel
from ui_v2.widgets.loading_overlay import LoadingOverlay

from core.marker_detector import MarkerDetector
from offline_stitcher import OfflineStitcher, FramePair


def cv_image_to_qpixmap(image_bgr: np.ndarray) -> QPixmap:
    """OpenCV BGR 图像转 QPixmap。"""
    if image_bgr is None or image_bgr.size == 0:
        return QPixmap()
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)


class OfflineStitchWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("离线拼接测试工具（ui_v2 重构版）")
        self.resize(1400, 900)
        self._center_on_screen()

        self.stitcher = OfflineStitcher()
        self.current_pair: FramePair | None = None

        # 合并点云缓存：full 用于保存，display 用于渲染（已下采样）
        self._merged_pcd_full: o3d.geometry.PointCloud | None = None
        self._merged_pcd_display: o3d.geometry.PointCloud | None = None
        self._merged_list_item: QListWidgetItem | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._main_splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self._main_splitter, 1)

        # --------------------------- 左侧面板 ---------------------------
        self._left_panel = QWidget()
        left_layout = QVBoxLayout(self._left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.btn_select_dir = QPushButton("选择数据文件夹")
        self.btn_select_dir.setObjectName("primary")
        self.btn_select_dir.setMinimumHeight(34)
        self.btn_select_dir.clicked.connect(self._on_select_directory)
        left_layout.addWidget(self.btn_select_dir)

        self.lbl_dir = QLabel("未选择文件夹")
        self.lbl_dir.setWordWrap(True)
        self.lbl_dir.setStyleSheet(f"color: {TEXT_MUTED};")
        left_layout.addWidget(self.lbl_dir)

        self.chk_recursive = QCheckBox("递归子目录")
        self.chk_recursive.setChecked(True)
        self.chk_recursive.setToolTip("勾选时扫描所选文件夹及其子文件夹")
        left_layout.addWidget(self.chk_recursive)

        # --------------------------- 标记物参数 ---------------------------
        self._build_marker_param_group(left_layout)

        self.list_files = QListWidget()
        self.list_files.setMinimumWidth(220)
        self.list_files.itemClicked.connect(self._on_file_selected)
        left_layout.addWidget(self.list_files, 1)

        self.btn_stitch = QPushButton("开始拼接")
        self.btn_stitch.setObjectName("primary")
        self.btn_stitch.setMinimumHeight(36)
        self.btn_stitch.setEnabled(False)
        self.btn_stitch.clicked.connect(self._on_stitch)
        left_layout.addWidget(self.btn_stitch)

        self.btn_save_merged = QPushButton("保存合并点云")
        self.btn_save_merged.setObjectName("secondary")
        self.btn_save_merged.setMinimumHeight(34)
        self.btn_save_merged.setEnabled(False)
        self.btn_save_merged.clicked.connect(self._on_save_merged)
        left_layout.addWidget(self.btn_save_merged)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(180)
        self.txt_log.setPlaceholderText("运行信息...")
        left_layout.addWidget(self.txt_log)

        self._main_splitter.addWidget(self._left_panel)

        # --------------------------- 右侧面板 ---------------------------
        self._right_panel = QWidget()
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 2D 预览
        self.lbl_image = QLabel("2D 预览")
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setStyleSheet(
            f"background-color: {BG_PANEL}; color: {TEXT_SECONDARY}; border: none; border-radius: 6px;"
        )
        self.lbl_image.setMinimumHeight(280)
        self.lbl_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.lbl_image, 1)

        # 3D 预览（复用主程序 ViewerPanel）
        self.viewer_3d = ViewerPanel("3D 点云预览", self)
        self.viewer_3d.setMinimumHeight(280)
        self.viewer_3d.maximize_toggled.connect(self._on_viewer_maximize_toggled)
        right_layout.addWidget(self.viewer_3d, 1)

        self._main_splitter.addWidget(self._right_panel)
        self._main_splitter.setSizes([320, 1080])

        # 加载遮罩（复用主程序 LoadingOverlay）
        self._overlay = LoadingOverlay(central)
        self._overlay.hide()

        self._viewer_maximized = False
        self._pre_maximize_sizes = None

    def _center_on_screen(self):
        """屏幕居中。"""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)

    def _build_marker_param_group(self, parent_layout: QVBoxLayout):
        """编码圆参数输入区。"""
        group = QGroupBox("编码圆参数")
        form = QFormLayout(group)
        form.setSpacing(6)
        form.setContentsMargins(8, 10, 8, 10)

        self.spin_n = QSpinBox()
        self.spin_n.setRange(4, 64)
        self.spin_n.setValue(8)
        self.spin_n.setToolTip("扇区数 N")
        self.spin_n.valueChanged.connect(self._on_marker_param_changed)
        form.addRow("扇区数 N:", self.spin_n)

        self.spin_r1 = QDoubleSpinBox()
        self.spin_r1.setRange(1.0, 20.0)
        self.spin_r1.setSingleStep(0.1)
        self.spin_r1.setValue(2.0)
        self.spin_r1.setDecimals(2)
        self.spin_r1.setToolTip("r1/r0 比值")
        self.spin_r1.valueChanged.connect(self._on_marker_param_changed)
        form.addRow("r1/r0:", self.spin_r1)

        self.spin_r2 = QDoubleSpinBox()
        self.spin_r2.setRange(1.0, 20.0)
        self.spin_r2.setSingleStep(0.1)
        self.spin_r2.setValue(3.0)
        self.spin_r2.setDecimals(2)
        self.spin_r2.setToolTip("r2/r0 比值")
        self.spin_r2.valueChanged.connect(self._on_marker_param_changed)
        form.addRow("r2/r0:", self.spin_r2)

        btn_load = QPushButton("加载编码圆配置...")
        btn_load.setObjectName("secondary")
        btn_load.setToolTip("从 coded_circle_meta.json 加载参数")
        btn_load.clicked.connect(self._on_load_marker_config)
        form.addRow(btn_load)

        parent_layout.addWidget(group)

    def _on_marker_param_changed(self):
        """参数变化时同步到 OfflineStitcher。"""
        self._apply_marker_params()

    def _apply_marker_params(self):
        n = self.spin_n.value()
        r1 = self.spin_r1.value()
        r2 = self.spin_r2.value()
        self.stitcher.set_coded_circle_params(n, r1, r2)
        self._log(f"编码圆参数已设置: N={n}, r1/r0={r1:.2f}, r2/r0={r2:.2f}")

    def _on_load_marker_config(self):
        """从生成器输出的 coded_circle_meta.json 加载参数。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择编码圆配置文件", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            params = meta.get("params", meta)
            n = int(params.get("N", params.get("n", 8)))
            r1 = float(params.get("r1_to_r0_ratio", 2.0))
            r2 = float(params.get("r2_to_r0_ratio", 3.0))
            self.spin_n.setValue(n)
            self.spin_r1.setValue(r1)
            self.spin_r2.setValue(r2)
            self._on_marker_param_changed()
            self._log(f"已加载编码圆配置: {path}")
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法解析配置文件:\n{e}")

    # ------------------------------------------------------------------
    # 合并点云缓存与显示
    # ------------------------------------------------------------------
    def _prepare_merged_for_display(self, pcd: o3d.geometry.PointCloud,
                                    target_points: int = 1_000_000
                                    ) -> o3d.geometry.PointCloud:
        """为 3D 查看器生成显示级点云：保留完整点云用于保存，显示时降采样。

        策略：
          1. 点数未超限直接返回；
          2. 超限时先快速均匀采样到 target*2，再体素采样到 target 左右；
          3. 任何异常回退均匀采样，避免 UI 卡死。
        """
        n = len(pcd.points)
        if n <= target_points:
            return pcd
        try:
            # 快速粗降：uniform_down_sample 在原始点云上 O(N)，非常快
            k = max(1, int(np.ceil(n / (target_points * 2))))
            coarse = pcd.uniform_down_sample(every_k_points=k)
            if len(coarse.points) <= target_points:
                return coarse

            # 精修：在有效点上体素降采样
            pts = np.asarray(coarse.points)
            valid_mask = np.isfinite(pts).all(axis=1)
            if not valid_mask.any():
                raise ValueError("无有效点")
            clean = o3d.geometry.PointCloud()
            clean.points = o3d.utility.Vector3dVector(pts[valid_mask])
            if pcd.has_colors():
                colors = np.asarray(pcd.colors)
                if len(colors) == n:
                    clean.colors = o3d.utility.Vector3dVector(
                        colors[::k][valid_mask])

            min_b = pts[valid_mask].min(axis=0)
            max_b = pts[valid_mask].max(axis=0)
            extent = max_b - min_b
            if not np.isfinite(extent).all() or (extent <= 0).any():
                raise ValueError("AABB 异常")
            voxel = max((float(extent.prod()) / target_points) ** (1.0 / 3.0), 1e-6)
            voxel = min(voxel, 3.0, float(extent.min()) / 10.0)
            ds = clean.voxel_down_sample(voxel_size=voxel)
            return ds if len(ds.points) > 0 else coarse
        except Exception as e:
            self._log(f"合并点云显示下采样失败({e})，回退均匀采样")
            k = max(1, int(np.ceil(n / target_points)))
            return pcd.uniform_down_sample(every_k_points=k)

    def _add_merged_list_item(self):
        """在文件列表顶部插入「合并结果」入口。"""
        if self._merged_list_item is not None:
            return
        item = QListWidgetItem("【合并结果】")
        item.setData(Qt.UserRole, "__merged__")
        item.setToolTip("点击显示拼接后的合并点云")
        # 用深红背景+白字突出显示
        item.setBackground(Qt.red)
        item.setForeground(Qt.white)
        self.list_files.insertItem(0, item)
        self._merged_list_item = item

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    def _log(self, text: str):
        self.txt_log.append(text)

    def _on_select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "选择离线数据文件夹")
        if not directory:
            return

        self.list_files.clear()
        self.viewer_3d.clear_all()
        self.lbl_image.setText("2D 预览")
        self.lbl_image.setPixmap(QPixmap())
        self.stitcher = OfflineStitcher()
        self._apply_marker_params()

        # 清空上一次合并结果缓存
        self._merged_pcd_full = None
        self._merged_pcd_display = None
        self._merged_list_item = None

        recursive = self.chk_recursive.isChecked()
        count, msg = self.stitcher.load_directory(directory, recursive=recursive)
        self.lbl_dir.setText(directory)
        self._log(msg)

        for pair in self.stitcher.pairs:
            item = QListWidgetItem(pair.name)
            item.setData(Qt.UserRole, pair)
            self.list_files.addItem(item)

        self.btn_stitch.setEnabled(count > 0)
        self.btn_save_merged.setEnabled(False)
        if count == 0:
            QMessageBox.information(
                self, "提示",
                "未找到名称对应的图像/点云文件对。\n\n"
                "支持的命名示例：\n"
                "  1.png + 1.ply\n"
                "  1_color.png + 1_depth.ply\n\n"
                "请勾选「递归子目录」以扫描子文件夹。")

    def _on_file_selected(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)

        # 合并结果入口
        if data == "__merged__":
            if self._merged_pcd_display is not None:
                self.viewer_3d.set_pointcloud_merged(self._merged_pcd_display)
                self.lbl_image.setText("合并点云预览")
                self.lbl_image.setPixmap(QPixmap())
                self._log(f"显示合并点云: {len(self._merged_pcd_full.points)} 点 "
                          f"(显示用 {len(self._merged_pcd_display.points)} 点)")
            else:
                QMessageBox.information(self, "提示", "暂无合并点云，请先执行拼接")
            return

        pair: FramePair = data
        self.current_pair = pair

        # 2D 检测 + 标注红点
        image = cv2.imread(pair.image_path)
        if image is None:
            self._log(f"无法读取图像: {pair.image_path}")
            return

        markers = self.stitcher.marker_detector.detect(image)
        annotated = image.copy()
        for m in markers:
            cx = int(round(m.get("x", 0)))
            cy = int(round(m.get("y", 0)))
            cv2.circle(annotated, (cx, cy), 5, (0, 0, 255), -1)
            cv2.circle(annotated, (cx, cy), 5, (255, 255, 255), 1)

        self.lbl_image.setPixmap(cv_image_to_qpixmap(annotated).scaled(
            self.lbl_image.width(), self.lbl_image.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._log(f"{pair.name}: 检测到 {len(markers)} 个编码圆")

        # 3D 点云：不再 clear_all，保留合并点云缓存；切换到该文件对的单相机视图
        pcd = o3d.io.read_point_cloud(pair.ply_path)
        if pcd is None or len(pcd.points) == 0:
            self._log(f"无法读取点云: {pair.ply_path}")
            return
        self.viewer_3d.set_pointcloud(pair.name, pcd)
        self.viewer_3d.show_camera(pair.name)
        self._log(f"{pair.name}: 点云 {len(pcd.points)} 点")

    def _on_stitch(self):
        if not self.stitcher.pairs:
            QMessageBox.warning(self, "警告", "没有可拼接的文件对")
            return

        total = len(self.stitcher.pairs)
        self._overlay.show_message("正在拼接...")

        # 逐个加入拼接链，并在 loading 上显示进度
        for i, pair in enumerate(self.stitcher.pairs, start=1):
            self._overlay.update_message(
                f"正在拼接... 检测/加入第 {i}/{total} 帧: {pair.name}")
            QApplication.processEvents()
            ok, msg = self.stitcher.add_pair_to_chain(pair)
            self._log(f"{pair.name}: {msg}")
            if not ok:
                continue

        self._overlay.update_message("正在拼接... 合并点云与计算误差")
        QApplication.processEvents()
        merged, msg = self.stitcher.stitch()
        self._log(msg)
        self._overlay.hide_overlay()

        if merged is not None:
            self._merged_pcd_full = merged
            self._merged_pcd_display = self._prepare_merged_for_display(merged)
            self.viewer_3d.clear_all()
            self.viewer_3d.set_pointcloud_merged(self._merged_pcd_display)
            self._add_merged_list_item()
            self._log(
                f"合并点云已缓存: 原始 {len(merged.points)} 点, "
                f"显示用 {len(self._merged_pcd_display.points)} 点"
            )
            self.btn_save_merged.setEnabled(True)

    def _on_save_merged(self):
        # 优先使用 UI 层缓存的完整点云，保留颜色/法线等全部信息
        pcd_to_save = self._merged_pcd_full or self.stitcher.merged_pcd
        if pcd_to_save is None:
            QMessageBox.warning(self, "警告", "没有可保存的合并点云")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存合并点云", "merged.ply", "PLY (*.ply)")
        if path:
            try:
                o3d.io.write_point_cloud(path, pcd_to_save)
                self._log(f"已保存完整合并点云 ({len(pcd_to_save.points)} 点): {path}")
                QMessageBox.information(self, "保存成功", f"合并点云已保存到:\n{path}")
            except Exception as e:
                self._log(f"保存失败: {e}")
                QMessageBox.warning(self, "保存失败", f"无法保存合并点云:\n{e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_overlay") and self._overlay.isVisible():
            self._overlay.setGeometry(0, 0, self.width(), self.height())
        if self.current_pair is not None:
            self._refresh_image()

    def _refresh_image(self):
        pm = self.lbl_image.pixmap()
        if pm is None or pm.isNull():
            return
        self.lbl_image.setPixmap(pm.scaled(
            self.lbl_image.width(), self.lbl_image.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_viewer_maximize_toggled(self, maximized: bool):
        """3D 查看器最大化/恢复：隐藏/恢复左侧面板与 2D 预览区。"""
        self._viewer_maximized = maximized
        if maximized:
            self._pre_maximize_sizes = self._main_splitter.sizes()
            self._left_panel.hide()
            self.lbl_image.hide()
            total = max(self._main_splitter.width(), 100)
            self._main_splitter.setSizes([0, total])
        else:
            self._left_panel.show()
            self.lbl_image.show()
            if self._pre_maximize_sizes:
                self._main_splitter.setSizes(self._pre_maximize_sizes)
            else:
                self._main_splitter.setSizes([320, 1080])


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    window = OfflineStitchWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
