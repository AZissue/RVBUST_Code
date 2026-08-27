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

import numpy as np
import cv2
import open3d as o3d

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QFileDialog, QMessageBox, QSizePolicy, QSplitter
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

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # --------------------------- 左侧面板 ---------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
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

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(180)
        self.txt_log.setPlaceholderText("运行信息...")
        left_layout.addWidget(self.txt_log)

        splitter.addWidget(left)

        # --------------------------- 右侧面板 ---------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
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
        right_layout.addWidget(self.viewer_3d, 1)

        splitter.addWidget(right)
        splitter.setSizes([320, 1080])

        # 加载遮罩（复用主程序 LoadingOverlay）
        self._overlay = LoadingOverlay(central)
        self._overlay.hide()

    def _center_on_screen(self):
        """屏幕居中。"""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)

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

        count, msg = self.stitcher.load_directory(directory)
        self.lbl_dir.setText(directory)
        self._log(msg)

        for pair in self.stitcher.pairs:
            item = QListWidgetItem(pair.name)
            item.setData(Qt.UserRole, pair)
            self.list_files.addItem(item)

        self.btn_stitch.setEnabled(count > 0)
        if count == 0:
            QMessageBox.information(self, "提示", "未找到名称对应的图像/点云文件对")

    def _on_file_selected(self, item: QListWidgetItem):
        pair: FramePair = item.data(Qt.UserRole)
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

        # 3D 点云
        pcd = o3d.io.read_point_cloud(pair.ply_path)
        if pcd is None or len(pcd.points) == 0:
            self._log(f"无法读取点云: {pair.ply_path}")
            return
        self.viewer_3d.clear_all()
        self.viewer_3d.set_pointcloud(pair.name, pcd)
        self._log(f"{pair.name}: 点云 {len(pcd.points)} 点")

    def _on_stitch(self):
        if not self.stitcher.pairs:
            QMessageBox.warning(self, "警告", "没有可拼接的文件对")
            return

        self._overlay.show_message("正在拼接...")

        # 逐个加入拼接链
        for pair in self.stitcher.pairs:
            ok, msg = self.stitcher.add_pair_to_chain(pair)
            self._log(f"{pair.name}: {msg}")
            if not ok:
                continue

        merged, msg = self.stitcher.stitch()
        self._log(msg)
        self._overlay.hide_overlay()

        if merged is not None:
            self.viewer_3d.clear_all()
            self.viewer_3d.set_pointcloud_merged(merged)
            self._log(f"合并点云已显示，共 {len(merged.points)} 点")

            reply = QMessageBox.question(
                self, "保存", "拼接完成，是否保存合并点云？",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                path, _ = QFileDialog.getSaveFileName(
                    self, "保存合并点云", "merged.ply", "PLY (*.ply)")
                if path:
                    ok, save_msg = self.stitcher.save_merged(path)
                    self._log(save_msg)

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


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    window = OfflineStitchWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
