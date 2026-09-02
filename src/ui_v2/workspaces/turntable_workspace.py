# -*- coding: utf-8 -*-
"""
ui_v2.workspaces.turntable_workspace —— 转台 360° 拼接工作区。

作为主程序第三种独立模式：
  - 相机固定，转台带动物体/标记物旋转；
  - 拍摄 frame0 / frame1，用对应标记点标定转台轴、角度、360° 步数；
  - 按估算角度手动旋转转台并步进采集；
  - 按标定角度把每帧点云变换到参考系并合并；
  - 保存合并 PLY 或完整会话。

布局：
  - 左侧：控制面板（相机 / 标定 / 采集 / 拼接输出）
  - 右侧：2D 预览（左） + 3D 点云查看器（右）水平分布
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import List, Optional

import cv2
import numpy as np
import open3d as o3d

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..theme import BG_CARD, STATUS_ERR, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY
from .. import icons as ui_icons
from ..widgets import ViewerPanel
from ..widgets.device_table import DeviceInfo
from ui.worker_thread import WorkerThread

from core.camera_manager import CameraManager
from core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE, MARKER_TYPE_ASYMMETRIC_GRID
from core.frame_data import FrameData
from core.turntable_calibrator import TurntableCalibrator, OnlineTurntableSession


# ---------------------------------------------------------------------------
# 图像转换工具
# ---------------------------------------------------------------------------
def _np_to_qpixmap(image_np: np.ndarray) -> Optional[QPixmap]:
    """把 numpy 图像转为 QPixmap。"""
    if image_np is None:
        return None
    try:
        if len(image_np.shape) == 2:
            h, w = image_np.shape
            qimg = QImage(image_np.data, w, h, w, QImage.Format_Grayscale8)
        elif len(image_np.shape) == 3 and image_np.shape[2] == 3:
            h, w, _ = image_np.shape
            rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        elif len(image_np.shape) == 3 and image_np.shape[2] == 4:
            h, w, _ = image_np.shape
            qimg = QImage(image_np.data, w, h, w * 4, QImage.Format_RGBA8888)
        else:
            return None
        return QPixmap.fromImage(qimg.copy())
    except Exception as e:
        print(f"图像转 QPixmap 失败: {e}")
        return None


def _pcd_from_frame(frame: Optional[FrameData]) -> Optional[o3d.geometry.PointCloud]:
    """从 FrameData 中提取 open3d 点云。"""
    if frame is None:
        return None
    try:
        return frame.load_pointcloud_o3d()
    except Exception as e:
        print(f"加载点云失败: {e}")
        return None


def _markers_to_json(markers: List[dict]) -> dict:
    return {"markers": markers, "count": len(markers)}


class TurntableWorkspace(QWidget):
    """转台 360° 拼接工作区。"""

    STATES = ("idle", "connected", "capturing", "calibrated", "stitched")

    # ---------------------------------------------------------------- 信号
    log_message = Signal(str, str)
    """工作区日志（message, level）。"""

    dirty_changed = Signal(bool)
    """工作区数据脏标记变化（例如拍摄/标定/拼接后应设为 True）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._devices: List[DeviceInfo] = []

        # 核心对象
        self.calib = TurntableCalibrator()
        self.session = OnlineTurntableSession()
        self.cam_mgr: Optional[CameraManager] = None
        self.marker_detector: Optional[MarkerDetector] = None

        # 当前帧与标记
        self.current_frame0: Optional[FrameData] = None
        self.current_frame1: Optional[FrameData] = None
        self.current_markers0: List[dict] = []
        self.current_markers1: List[dict] = []
        self.merged: Optional[o3d.geometry.PointCloud] = None

        # worker 引用池（防止 QThread 被 GC）
        self._active_workers: List[WorkerThread] = []

        # 2D/3D 采集互斥门控：防止用户同时触发多个相机操作
        self._busy = False

        # 临时 PLY 文件路径，退出/重置时清理
        self._temp_files: List[str] = []

        self._setup_ui()
        self.set_state("idle")

    def _set_busy(self, busy: bool):
        """设置/释放相机操作忙状态，并刷新按钮使能。"""
        self._busy = busy
        self._update_online_ui()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ---- 左侧控制面板（可滚动，避免小屏幕显示不全）----
        self._left_panel = QScrollArea()
        self._left_panel.setWidgetResizable(True)
        self._left_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._left_panel.setFrameShape(QFrame.NoFrame)
        self._left_panel.setMinimumWidth(280)

        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setSpacing(10)
        left.setContentsMargins(4, 4, 4, 4)
        left.setAlignment(Qt.AlignTop)

        info = QLabel(
            "<b>转台 360° 拼接</b><br>"
            "连相机 → 拍摄 frame0/1 → 标定 → 步进采集 → 拼接"
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {TEXT_SECONDARY};")
        left.addWidget(info)

        left.addWidget(self._build_camera_group())
        left.addWidget(self._build_calib_group())
        left.addWidget(self._build_capture_group())
        left.addWidget(self._build_stitch_group())
        left.addStretch(1)

        self._left_panel.setWidget(left_widget)
        root.addWidget(self._left_panel, 1)

        # ---- 右侧：2D 预览 + 3D 查看器 ----
        self._right_split = QSplitter(Qt.Horizontal)
        self._right_split.setChildrenCollapsible(False)

        # 2D 预览面板（带标题栏的卡片式容器）
        self._preview_panel = QWidget()
        preview_lo = QVBoxLayout(self._preview_panel)
        preview_lo.setContentsMargins(0, 0, 0, 0)
        preview_lo.setSpacing(0)
        self._preview_panel.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid #3a3a3a; border-radius: 8px;"
        )

        preview_title = QLabel("2D 预览")
        preview_title.setFixedHeight(28)
        preview_title.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 600; "
            f"background-color: transparent; border: none; padding-left: 8px;"
        )
        preview_lo.addWidget(preview_title)

        self.preview_2d_label = QLabel("未启动预览")
        self.preview_2d_label.setAlignment(Qt.AlignCenter)
        self.preview_2d_label.setStyleSheet(
            f"background-color: #0f0f12; color: {TEXT_MUTED}; "
            "border: none; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;"
        )
        self.preview_2d_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_2d_label.setMinimumSize(360, 270)
        preview_lo.addWidget(self.preview_2d_label, 1)

        self._right_split.addWidget(self._preview_panel)

        self.viewer = ViewerPanel("3D 转台拼接预览")
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewer.setMinimumSize(360, 270)
        self.viewer.maximize_toggled.connect(self._on_viewer_maximize_toggled)
        self._right_split.addWidget(self.viewer)

        self._right_split.setSizes([540, 810])
        root.addWidget(self._right_split, 3)

        self._viewer_maximized = False
        self._pre_maximize_sizes = None

    def _build_camera_group(self) -> QGroupBox:
        """相机已由 LauncherDialog 连接，这里只显示状态与标记物类型。"""
        grp = QGroupBox("相机")
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        self.lbl_cam_status = QLabel("未连接相机")
        self.lbl_cam_status.setWordWrap(True)
        self.lbl_cam_status.setStyleSheet(f"color: {TEXT_MUTED};")
        v.addWidget(self.lbl_cam_status)

        h = QHBoxLayout()
        h.addWidget(QLabel("标记物:"))
        self.combo_marker_type = QComboBox()
        self.combo_marker_type.addItem("编码圆", MARKER_TYPE_CODED_CIRCLE)
        self.combo_marker_type.addItem("非对称圆标定板", MARKER_TYPE_ASYMMETRIC_GRID)
        self.combo_marker_type.currentIndexChanged.connect(self._on_marker_type_changed)
        h.addWidget(self.combo_marker_type)
        v.addLayout(h)

        return grp

    def _build_calib_group(self) -> QGroupBox:
        grp = QGroupBox("标定 frame0 / frame1")
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        h = QHBoxLayout()
        self.btn_preview_2d = QPushButton("2D 预览")
        self.btn_preview_2d.clicked.connect(self._on_preview_2d)
        self.btn_preview_2d.setEnabled(False)
        h.addWidget(self.btn_preview_2d)

        self.btn_capture_frame0 = QPushButton("拍摄 frame0")
        self.btn_capture_frame0.clicked.connect(self._on_capture_frame0)
        self.btn_capture_frame0.setEnabled(False)
        h.addWidget(self.btn_capture_frame0)
        v.addLayout(h)

        self.lbl_frame0 = QLabel("frame0: 未拍摄")
        self.lbl_frame0.setWordWrap(True)
        v.addWidget(self.lbl_frame0)

        h = QHBoxLayout()
        self.btn_capture_frame1 = QPushButton("拍摄 frame1")
        self.btn_capture_frame1.clicked.connect(self._on_capture_frame1)
        self.btn_capture_frame1.setEnabled(False)
        h.addWidget(self.btn_capture_frame1)
        v.addLayout(h)

        self.lbl_frame1 = QLabel("frame1: 未拍摄")
        self.lbl_frame1.setWordWrap(True)
        v.addWidget(self.lbl_frame1)

        self.btn_online_calib = QPushButton("在线标定转台")
        self.btn_online_calib.setObjectName("primary")
        self.btn_online_calib.clicked.connect(self._on_online_calibrate)
        self.btn_online_calib.setEnabled(False)
        v.addWidget(self.btn_online_calib)

        self.lbl_online_calib = QLabel("未标定")
        self.lbl_online_calib.setWordWrap(True)
        v.addWidget(self.lbl_online_calib)

        return grp

    def _build_capture_group(self) -> QGroupBox:
        grp = QGroupBox("步进采集")
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        self.lbl_step_info = QLabel("当前步: 0 / 总步: —")
        v.addWidget(self.lbl_step_info)

        h = QHBoxLayout()
        self.btn_capture_step = QPushButton("拍摄当前步")
        self.btn_capture_step.clicked.connect(self._on_capture_step)
        self.btn_capture_step.setEnabled(False)
        h.addWidget(self.btn_capture_step)

        self.btn_auto_capture = QPushButton("开始自动采集")
        self.btn_auto_capture.setCheckable(True)
        self.btn_auto_capture.clicked.connect(self._on_toggle_auto_capture)
        self.btn_auto_capture.setEnabled(False)
        h.addWidget(self.btn_auto_capture)
        v.addLayout(h)

        h = QHBoxLayout()
        h.addWidget(QLabel("间隔(s):"))
        self.spin_auto_interval = QSpinBox()
        self.spin_auto_interval.setRange(1, 60)
        self.spin_auto_interval.setValue(3)
        h.addWidget(self.spin_auto_interval)
        v.addLayout(h)

        self.chk_auto_stitch = QCheckBox("自动实时拼接")
        self.chk_auto_stitch.setToolTip("每采集一帧后自动根据标定角度拼接并刷新 3D 视图")
        self.chk_auto_stitch.setEnabled(False)
        v.addWidget(self.chk_auto_stitch)

        self.lbl_sequence = QLabel("已采集序列: 0 帧")
        v.addWidget(self.lbl_sequence)

        self.btn_clear_sequence = QPushButton("清空拍摄数据")
        self.btn_clear_sequence.setToolTip(
            "清空当前步进采集的点云数据，保留标定结果，便于更换工件后重新拍摄拼接"
        )
        self.btn_clear_sequence.clicked.connect(self._on_clear_sequence_data)
        self.btn_clear_sequence.setEnabled(False)
        v.addWidget(self.btn_clear_sequence)

        return grp

    def _build_stitch_group(self) -> QGroupBox:
        grp = QGroupBox("拼接与输出")
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        h = QHBoxLayout()
        h.addWidget(QLabel("合并后下采样体素(mm):"))
        self.spin_voxel = QDoubleSpinBox()
        self.spin_voxel.setRange(0, 20)
        self.spin_voxel.setValue(0)
        self.spin_voxel.setSuffix(" mm")
        self.spin_voxel.setSpecialValueText("不下采样")
        h.addWidget(self.spin_voxel)
        v.addLayout(h)

        self.btn_stitch = QPushButton("拼接并显示")
        self.btn_stitch.clicked.connect(self._on_stitch)
        self.btn_stitch.setEnabled(False)
        v.addWidget(self.btn_stitch)

        self.btn_save = QPushButton("保存合并 PLY")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        v.addWidget(self.btn_save)

        self.btn_save_session = QPushButton("保存会话")
        self.btn_save_session.clicked.connect(self._on_save_session)
        self.btn_save_session.setEnabled(False)
        v.addWidget(self.btn_save_session)

        self.lbl_stitch = QLabel("未拼接")
        self.lbl_stitch.setWordWrap(True)
        v.addWidget(self.lbl_stitch)

        return grp

    # ------------------------------------------------------------------ 公共接口
    def set_devices(self, devices: List[DeviceInfo]):
        """主窗口切换模式时传入设备。

        注意：状态（connected / idle）由 BackendBridge 在相机连接完成后设置，
        这里只刷新设备列表与 UI 门控，避免在连接过程中显示已连接。
        """
        self._devices = list(devices)
        self._reset_online_state()

    def set_camera_manager(self, cam_mgr: CameraManager, marker_detector: MarkerDetector):
        """接入主程序共享的相机管理器与标记物检测器（LauncherDialog 已连接相机）。"""
        self.cam_mgr = cam_mgr
        self.marker_detector = marker_detector
        self._update_online_ui()

    def set_state(self, state: str):
        if state not in self.STATES:
            raise ValueError(f"未知状态: {state}")
        self._state = state
        self._update_online_ui()

    def current_state(self) -> str:
        return self._state

    def log(self, text: str, level: str = "info"):
        self.log_message.emit(text, level)

    # ------------------------------------------------------------------ 状态与 UI 门控
    def _reset_online_state(self):
        # 先释放旧帧占用的 RVC 资源，再清空引用
        for frame in (self.current_frame0, self.current_frame1):
            if frame is not None:
                frame.release_rvc()
        for frame in self.session.sequence:
            if frame is not None:
                frame.release_rvc()
        self._cleanup_temp_files()
        self.current_frame0 = None
        self.current_frame1 = None
        self.current_markers0 = []
        self.current_markers1 = []
        self.merged = None
        self.session.reset()
        self.viewer.clear_all()
        self.preview_2d_label.setPixmap(QPixmap())
        self.preview_2d_label.setText("未启动预览")
        self.set_state("idle" if not self._is_connected() else "connected")

    def _is_connected(self) -> bool:
        return self.cam_mgr is not None and bool(self.cam_mgr.get_connected_ids())

    def _update_online_ui(self):
        try:
            connected = self._is_connected()
            busy = self._busy

            self.btn_preview_2d.setEnabled(connected and not busy)
            self.btn_capture_frame0.setEnabled(connected and not busy)

            frame0_shot = self.current_frame0 is not None
            f0_ok = frame0_shot and len(self.current_markers0) >= 3
            self.btn_capture_frame1.setEnabled(frame0_shot and not busy)

            f1_ok = self.current_frame1 is not None and len(self.current_markers1) >= 3
            self.btn_online_calib.setEnabled(f0_ok and f1_ok and not busy)

            calibrated = self.session.is_calibrated()
            total_steps = self.session.total_steps_needed() if calibrated else 0
            capture_finished = calibrated and self.session.current_step >= total_steps
            self.btn_capture_step.setEnabled(calibrated and not busy and not capture_finished)
            self.btn_auto_capture.setEnabled(calibrated and not busy and not capture_finished)
            self.chk_auto_stitch.setEnabled(calibrated)
            self.btn_stitch.setEnabled(self.session.can_stitch())
            self.btn_save.setEnabled(self.merged is not None)
            self.btn_save_session.setEnabled(bool(self.session.get_all_frames() or self.current_frame0 is not None))
            self.btn_clear_sequence.setEnabled(
                bool(self.session.sequence or self.merged is not None) and not busy
            )

            if connected:
                cam_id = self.cam_mgr.get_connected_ids()[0]
                cam = self.cam_mgr._cameras.get(cam_id)
                info = cam.device_info if cam else None
                name = getattr(info, "name", "unknown") if info else cam_id
                sn = getattr(info, "sn", "-") if info else "-"
                self.lbl_cam_status.setText(f"已连接: {name} ({sn})")
                self.lbl_cam_status.setStyleSheet(f"color: {STATUS_OK};")
            else:
                self.lbl_cam_status.setText("未连接相机（请从启动小窗连接）")
                self.lbl_cam_status.setStyleSheet(f"color: {STATUS_ERR};")

            self.lbl_frame0.setText(
                f"frame0: {'已拍摄 ' + str(len(self.current_markers0)) + ' 个标记' if self.current_frame0 else '未拍摄'}"
            )
            self.lbl_frame1.setText(
                f"frame1: {'已拍摄 ' + str(len(self.current_markers1)) + ' 个标记' if self.current_frame1 else '未拍摄'}"
            )

            self.lbl_step_info.setText(
                f"当前步: {self.session.current_step} / 总步: {self.session.total_steps_needed() if calibrated else '—'}"
            )
            self.lbl_sequence.setText(f"已采集序列: {len(self.session.sequence)} 帧")
        except Exception as e:
            self.log(f"[ERROR] 更新 UI 异常: {e}", "error")
            import traceback
            self.log(traceback.format_exc(), "error")

    def _display_2d(self, image_np: np.ndarray):
        pixmap = _np_to_qpixmap(image_np)
        if pixmap is None:
            self.preview_2d_label.setText("2D 预览区（图像格式不支持）")
            return
        label_size = self.preview_2d_label.size()
        if pixmap.width() > label_size.width() or pixmap.height() > label_size.height():
            scaled = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            scaled = pixmap
        self.preview_2d_label.setPixmap(scaled)
        self.preview_2d_label.setText("")

    # ------------------------------------------------------------------ Worker
    def _run_worker(self, func, on_done, *args, **kwargs):
        """启动后台线程并保留引用。"""
        worker = WorkerThread(func, *args, **kwargs)
        worker.finished.connect(lambda res, err, w=worker: self._on_worker_finished(res, err, on_done, w))
        self._active_workers.append(worker)
        worker.start()
        return worker

    def _on_worker_finished(self, result, error, on_done, worker):
        try:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
        except Exception:
            pass
        if error:
            self.log(f"[ERROR] {error}", "error")
            QMessageBox.warning(self, "执行失败", str(error))
            # 出错时也要释放忙状态，避免按钮一直不可用
            if self._busy:
                self._set_busy(False)
            return
        on_done(result)

    def _run_busy_worker(self, func, on_done, *args, **kwargs):
        """启动后台线程，并在 on_done 处理完成后释放 _busy 门控。"""
        self._set_busy(True)

        def _wrapped_done(result):
            try:
                on_done(result)
            except Exception as e:
                self.log(f"[ERROR] 处理拍摄结果异常: {e}", "error")
                import traceback
                self.log(traceback.format_exc(), "error")
            finally:
                self._set_busy(False)

        return self._run_worker(func, _wrapped_done, *args, **kwargs)

    # ------------------------------------------------------------------ 资源释放
    def _release_frame_rvc(self, frame: Optional[FrameData], pcd: Optional[o3d.geometry.PointCloud] = None):
        """释放帧占用的 RVC 资源，并用 Open3D 点云保留离线 PLY 路径供后续保存。"""
        if frame is None:
            return
        if pcd is not None and frame.offline_pointmap_path is None:
            try:
                fd, tmp_path = tempfile.mkstemp(suffix="_frame_pcd.ply")
                os.close(fd)
                o3d.io.write_point_cloud(tmp_path, pcd)
                frame.offline_pointmap_path = tmp_path
                frame.is_offline = True
                self._temp_files.append(tmp_path)
            except Exception as e:
                self.log(f"[WARN] 保存临时点云失败: {e}", "warning")
        frame.release_rvc()

    def _cleanup_temp_files(self):
        """清理本工作区产生的临时 PLY 文件。"""
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass
        self._temp_files.clear()

    # ------------------------------------------------------------------ 相机连接
    def _on_marker_type_changed(self, _idx):
        if self.marker_detector is not None:
            mtype = self.combo_marker_type.currentData()
            self.marker_detector.set_marker_type(mtype)
            self.log(f"标记物类型切换为: {mtype}")

    # ------------------------------------------------------------------ 2D 预览
    def _on_preview_2d(self):
        if not self._is_connected() or self._busy:
            return
        self.log("2D 预览拍摄中...")

        def _capture():
            return self.cam_mgr.capture_2d_preview("cam0")

        def _done(frame):
            if frame is None or frame.image_np is None:
                self.log("2D 预览失败", "error")
                return
            self.log(f"2D 预览: {frame.image_np.shape}")
            self._display_2d(frame.image_np)

        self._run_busy_worker(_capture, _done)

    # ------------------------------------------------------------------ frame0/frame1 拍摄
    def _on_capture_frame0(self):
        self._capture_frame_for_calib(is_frame0=True)

    def _on_capture_frame1(self):
        self._capture_frame_for_calib(is_frame0=False)

    def _capture_frame_for_calib(self, is_frame0: bool):
        if not self._is_connected() or self._busy:
            return
        label = "frame0" if is_frame0 else "frame1"

        # 释放旧帧占用的 RVC 资源，避免 SDK 缓冲被占满导致下一次拍摄阻塞
        old_frame = self.current_frame0 if is_frame0 else self.current_frame1
        if old_frame is not None:
            old_frame.release_rvc()

        self.log(f"拍摄 {label} 中...")

        def _capture():
            frame = self.cam_mgr.capture("cam0")
            if frame is None:
                raise RuntimeError("拍摄失败")
            pcd = _pcd_from_frame(frame)
            if pcd is None:
                raise RuntimeError("点云获取失败")
            markers = self.marker_detector.detect_3d(
                frame.image_np, frame.pointmap, frame.rvc_image
            ) if self.marker_detector else []
            return frame, pcd, markers

        def _done(result):
            frame, pcd, markers = result
            self.log(f"{label} 拍摄完成: {len(pcd.points)} 点, 检测到 {len(markers)} 个标记")
            self._display_2d(frame.image_np)
            if is_frame0:
                self.current_frame0 = frame
                self.current_markers0 = markers
                self.session.set_frame0(frame, markers, pcd)
                self.viewer.set_pointcloud("frame0", pcd)
                if len(markers) < 3:
                    QMessageBox.warning(
                        self, "标记点不足",
                        f"frame0 仅检测到 {len(markers)} 个标记点，标定至少需要 3 个。\n"
                        "请调整标记物位置、光照或曝光后重拍。"
                    )
            else:
                self.current_frame1 = frame
                self.current_markers1 = markers
                self.session.set_frame1(frame, markers, pcd)
                self.viewer.set_pointcloud("frame1", pcd)
                if len(markers) < 3:
                    QMessageBox.warning(
                        self, "标记点不足",
                        f"frame1 仅检测到 {len(markers)} 个标记点，标定至少需要 3 个。\n"
                        "请调整标记物位置、光照或曝光后重拍。"
                    )
            # 释放本次拍摄占用的 RVC 资源；已提取的 image_np / markers / pcd 仍保留
            self._release_frame_rvc(frame, pcd)
            self.dirty_changed.emit(True)
            self._update_online_ui()

        self._run_busy_worker(_capture, _done)

    # ------------------------------------------------------------------ 在线标定
    def _on_online_calibrate(self):
        mtype = self.combo_marker_type.currentData()
        key = "index" if mtype == MARKER_TYPE_ASYMMETRIC_GRID else "code"
        self.log("在线标定中...")

        def _calib():
            return self.session.calibrate(marker_key=key)

        def _done(result):
            ok, msg, info = result
            self.log(f"在线标定: {msg}", "success" if ok else "error")
            if ok:
                self.lbl_online_calib.setText(
                    f"角度: {info['angle_deg']:.2f}°\n"
                    f"360° 步数: {info['step_count']}\n"
                    f"总采集帧数: {info['step_count'] + 1}\n"
                    f"旋转轴: [{', '.join(f'{v:.3f}' for v in info['axis'])}]\n"
                    f"旋转中心: [{', '.join(f'{v:.1f}' for v in info['center'])}]"
                )
                self.calib = self.session.calib
                # 标定帧不进入最终拼接，清空 UI 层引用与 3D 查看器中的标定帧
                if self.current_frame0 is not None:
                    self.current_frame0.release()
                if self.current_frame1 is not None:
                    self.current_frame1.release()
                self.current_frame0 = None
                self.current_frame1 = None
                self.current_markers0 = []
                self.current_markers1 = []
                self.viewer.set_pointcloud("frame0", None)
                self.viewer.set_pointcloud("frame1", None)
                self.log("标定完成，请将转台回到起始位置，从 step 1 开始采集")
                self.set_state("calibrated")
                self.dirty_changed.emit(True)
            else:
                QMessageBox.warning(self, "标定失败", msg)
            self._update_online_ui()

        self._run_worker(_calib, _done)

    # ------------------------------------------------------------------ 会话恢复
    def apply_loaded_calibration(self, info: dict) -> bool:
        """用会话中保存的标定参数恢复标定状态，直接进入步进采集阶段。"""
        try:
            axis = info["axis"]
            center = info["center"]
            angle_deg = float(info["angle_deg"])
            step_count = int(info["step_count"])
        except Exception as e:
            self.log(f"会话标定参数不完整: {e}", "error")
            return False
        self.session.apply_calibration(axis, center, angle_deg, step_count)
        self.calib = self.session.calib
        # 标定帧不进入最终拼接，清空 UI 层引用与 3D 查看器中的标定帧
        self.current_frame0 = None
        self.current_frame1 = None
        self.current_markers0 = []
        self.current_markers1 = []
        self.viewer.set_pointcloud("frame0", None)
        self.viewer.set_pointcloud("frame1", None)
        self.lbl_online_calib.setText(
            f"角度: {angle_deg:.2f}°\n"
            f"360° 步数: {step_count}\n"
            f"总采集帧数: {step_count + 1}\n"
            f"旋转轴: [{', '.join(f'{v:.3f}' for v in axis)}]\n"
            f"旋转中心: [{', '.join(f'{v:.1f}' for v in center)}]"
        )
        self.set_state("calibrated")
        self.dirty_changed.emit(True)
        self._update_online_ui()
        return True

    def load_sequence_frames(self, frames: List[FrameData]) -> int:
        """把离线会话中的步进采集帧加载回当前会话与 3D 查看器。"""
        count = 0
        for i, frame in enumerate(frames, start=1):
            try:
                pcd = frame.load_pointcloud_o3d()
            except Exception as e:
                self.log(f"加载第 {i} 帧点云失败: {e}", "warning")
                pcd = None
            self.session.add_sequence_frame(frame, pcd)
            if pcd is not None:
                self.viewer.set_pointcloud(f"step_{i}", pcd)
            count += 1
        if count:
            self.set_state("capturing")
            self.dirty_changed.emit(True)
            self._update_online_ui()
        return count

    # ------------------------------------------------------------------ 步进采集
    def _on_capture_step(self):
        if not self.session.is_calibrated():
            return
        total = self.session.total_steps_needed()
        if self.session.current_step >= total:
            QMessageBox.information(
                self, "采集完成",
                "已完成 360° 步进采集。\n"
                "可以拼接保存，或点击「清空拍摄数据」后更换工件重新采集。"
            )
            return
        self._capture_sequence_step()

    def _capture_sequence_step(self, auto_continue: bool = False):
        if not self._is_connected() or self._busy:
            return
        total = self.session.total_steps_needed()
        if self.session.current_step >= total:
            self.log("360° 采集已完成，无需继续拍摄", "success")
            return
        step = self.session.current_step + 1
        self.log(f"拍摄第 {step} 步...")

        def _capture():
            frame = self.cam_mgr.capture("cam0")
            if frame is None:
                raise RuntimeError("拍摄失败")
            pcd = _pcd_from_frame(frame)
            if pcd is None:
                raise RuntimeError("点云获取失败")
            return frame, pcd

        def _done(result):
            frame, pcd = result
            self.session.add_sequence_frame(frame, pcd)
            step_idx = self.session.current_step
            total = self.session.total_steps_needed()
            self.log(
                f"第 {step_idx} 步采集完成: {len(pcd.points)} 点 "
                f"(current_step={self.session.current_step}, 序列 {len(self.session.sequence)}/{total})"
            )
            self._display_2d(frame.image_np)
            self.viewer.set_pointcloud(f"step_{step_idx}", pcd)
            # 释放本次拍摄占用的 RVC 资源，避免连续采集阻塞
            self._release_frame_rvc(frame, pcd)
            finished = self.session.current_step >= total
            if finished:
                self.log("360° 采集完成，可以拼接", "success")
                # 自动采集到最后一帧后停止
                self.btn_auto_capture.setChecked(False)
                self.btn_auto_capture.setText("开始自动采集")
                if not auto_continue:
                    QMessageBox.information(
                        self, "采集完成",
                        f"已完成 360° 步进采集（{self.session.current_step}/{total} 帧）。"
                    )
            if self.chk_auto_stitch.isChecked():
                self.log("自动实时拼接...")
                self._do_stitch(silent=True)
            self.set_state("capturing")
            self.dirty_changed.emit(True)
            self._update_online_ui()
            # 自动采集：等当前帧完成后再调度下一拍，避免 worker 堆积
            if auto_continue and not finished and self.btn_auto_capture.isChecked():
                interval_ms = self.spin_auto_interval.value() * 1000
                QTimer.singleShot(interval_ms, self._auto_capture_next)

        self._run_busy_worker(_capture, _done)

    def _on_toggle_auto_capture(self, checked: bool):
        if checked:
            if not self.session.is_calibrated():
                self.btn_auto_capture.setChecked(False)
                return
            if self.session.current_step >= self.session.total_steps_needed():
                self.btn_auto_capture.setChecked(False)
                self.log("360° 采集已完成，无需继续自动采集", "warning")
                return
            self.btn_auto_capture.setText("停止自动采集")
            self._auto_capture_next()
        else:
            self.btn_auto_capture.setText("开始自动采集")

    def _auto_capture_next(self):
        if not self.btn_auto_capture.isChecked():
            return
        if self.session.current_step >= self.session.total_steps_needed():
            self.btn_auto_capture.setChecked(False)
            self.btn_auto_capture.setText("开始自动采集")
            self.log("自动采集完成")
            return
        self._capture_sequence_step(auto_continue=True)

    def _on_clear_sequence_data(self):
        """清空当前步进采集的点云数据，保留标定结果，便于更换工件后重新采集。"""
        if not self.session.sequence and self.merged is None:
            return
        ret = QMessageBox.question(
            self, "清空拍摄数据",
            "确定清空当前步进采集的点云数据吗？\n"
            "标定结果将保留，可更换工件后重新拍摄拼接。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return
        # 停止自动采集
        self.btn_auto_capture.setChecked(False)
        self.btn_auto_capture.setText("开始自动采集")
        # 释放帧资源并清空序列
        for frame in self.session.sequence:
            if frame is not None:
                frame.release()
        self.session.sequence.clear()
        self.session.sequence_pcds.clear()
        self.session.current_step = 0
        self.merged = None
        self.lbl_stitch.setText("未拼接")
        self.viewer.clear_all()
        self.preview_2d_label.setPixmap(QPixmap())
        self.preview_2d_label.setText("未启动预览")
        self.set_state("calibrated" if self.session.is_calibrated() else "connected")
        self.dirty_changed.emit(False)
        self.log("已清空拍摄数据，保留标定结果，可重新采集")
        self._update_online_ui()

    # ------------------------------------------------------------------ 拼接 / 保存
    def _on_stitch(self):
        if not self.session.can_stitch():
            QMessageBox.warning(self, "无法拼接", "请先完成标定并采集至少 2 帧")
            return
        self._do_stitch(silent=False)

    def _do_stitch(self, silent: bool = False):
        voxel = self.spin_voxel.value()
        voxel = voxel if voxel > 0 else None

        def _stitch():
            return self.session.stitch(downsample_voxel=voxel)

        def _done(result):
            merged, msg = result
            self.log(msg)
            if merged is None:
                if not silent:
                    QMessageBox.warning(self, "拼接失败", msg)
                return
            self.merged = merged
            self.lbl_stitch.setText(f"合并后: {len(merged.points)} 点")
            self.viewer.clear_all()
            self.viewer.set_pointcloud_merged(merged)
            self.set_state("stitched")
            self.dirty_changed.emit(True)
            self._update_online_ui()

        self._run_worker(_stitch, _done)

    def _on_save(self):
        if self.merged is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存合并点云", "turntable_merged.ply", "PLY 文件 (*.ply)")
        if path:
            o3d.io.write_point_cloud(path, self.merged)
            self.log(f"已保存: {path}")

    def _on_save_session(self):
        if not self.session.get_all_frames():
            return
        base_dir = QFileDialog.getExistingDirectory(self, "选择会话保存目录")
        if not base_dir:
            return
        session_dir = os.path.join(base_dir, f"turntable_session_{time.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(session_dir, exist_ok=True)
        self.session.session_dir = session_dir
        self.log("保存会话中...")

        def _save():
            if self.session.frame0 is not None:
                self.session.frame0.save(session_dir)
                with open(os.path.join(session_dir, "markers_frame0.json"), "w", encoding="utf-8") as f:
                    json.dump(_markers_to_json(self.session.markers0), f, ensure_ascii=False, indent=2)
            if self.session.frame1 is not None:
                self.session.frame1.save(session_dir)
                with open(os.path.join(session_dir, "markers_frame1.json"), "w", encoding="utf-8") as f:
                    json.dump(_markers_to_json(self.session.markers1), f, ensure_ascii=False, indent=2)
            for i, frame in enumerate(self.session.sequence):
                frame_dir = os.path.join(session_dir, f"frame_{i + 2:04d}")
                os.makedirs(frame_dir, exist_ok=True)
                frame.save(frame_dir)
            if self.session.is_calibrated():
                info = {
                    "axis": self.session.calib.axis.tolist() if self.session.calib.axis is not None else None,
                    "center": self.session.calib.center.tolist() if self.session.calib.center is not None else None,
                    "angle_deg": float(np.degrees(self.session.calib.angle_rad)),
                    "step_count": self.session.calib.step_count,
                }
                with open(os.path.join(session_dir, "calibration.json"), "w", encoding="utf-8") as f:
                    json.dump(info, f, ensure_ascii=False, indent=2)
            return session_dir

        def _done(path):
            self.log(f"会话已保存: {path}")
            self.dirty_changed.emit(False)

        self._run_worker(_save, _done)

    def _on_viewer_maximize_toggled(self, maximized: bool):
        """3D 查看器最大化/恢复：隐藏/恢复左侧面板与 2D 预览区。"""
        self._viewer_maximized = maximized
        if maximized:
            self._pre_maximize_sizes = self._right_split.sizes()
            self._left_panel.hide()
            self._preview_panel.hide()
            total = max(self._right_split.width(), 100)
            self._right_split.setSizes([0, total])
        else:
            self._left_panel.show()
            self._preview_panel.show()
            if self._pre_maximize_sizes:
                self._right_split.setSizes(self._pre_maximize_sizes)
            else:
                self._right_split.setSizes([540, 810])
