# -*- coding: utf-8 -*-
"""
转台 360° 拼接原型 UI（在线相机模式）。

流程：
  1. 初始化 RVC、查找设备、连接相机；
  2. 在转台上放置标记物，点击「拍摄 frame0」并检测标记；
  3. 手动旋转转台一小段角度，点击「拍摄 frame1」并检测标记；
  4. 点击「在线标定转台」，得到旋转角 θ 与 360° 步数；
  5. 勾选「自动实时拼接」后，每按 θ 旋转并拍摄一帧，右侧立即更新拼接结果；
  6. 点击「保存合并 PLY」或「保存会话」导出数据。

布局：
  - 左侧：控制面板
  - 右侧：2D 预览窗口（左） + 3D 点云查看器（右）水平分布，下方为日志。

本 UI 不控制转台，只负责：
  - 相机连接与拍摄；
  - 从 frame0/frame1 对应标记点计算旋转轴、角度、360° 步数；
  - 按计算出的角度把后续帧变换到参考系并合并；
  - 保存合并结果 PLY 与原始帧数据。
"""

from __future__ import annotations

import json
import sys
import os
import time
from typing import List, Optional

import numpy as np
import open3d as o3d
import cv2

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QFileDialog, QMessageBox,
    QDoubleSpinBox, QGroupBox, QComboBox, QSpinBox, QCheckBox,
    QProgressDialog, QSplitter, QSizePolicy,
)

# 引入本子功能的核心算法
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from turntable_calibrator import TurntableCalibrator, OnlineTurntableSession

# 引入主项目核心模块（app 在 prototypes/turntable_360_stitch/app/，向上三级到 MultiCameraCalibration）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
try:
    from core.camera_manager import CameraManager
    from core.marker_detector import MarkerDetector, MARKER_TYPE_CODED_CIRCLE, MARKER_TYPE_ASYMMETRIC_GRID
    from core.frame_data import FrameData
    from ui.worker_thread import WorkerThread
    from ui.viewer_3d import EmbeddedPointCloudViewer
    HAS_VIEWER = True
except Exception as e:
    print(f"项目模块引入失败: {e}")
    CameraManager = None
    MarkerDetector = None
    MARKER_TYPE_CODED_CIRCLE = "coded_circle"
    MARKER_TYPE_ASYMMETRIC_GRID = "asymmetric_grid"
    FrameData = None
    WorkerThread = None
    HAS_VIEWER = False


def _pcd_from_frame(frame) -> Optional[o3d.geometry.PointCloud]:
    """从 FrameData 中提取 open3d 点云。"""
    if frame is None:
        return None
    try:
        return frame.load_pointcloud_o3d()
    except Exception as e:
        print(f"加载点云失败: {e}")
        return None


def _markers_to_json(markers: List[dict]) -> dict:
    """把 markers 列表保存为可序列化的字典。"""
    return {"markers": markers, "count": len(markers)}


def _np_to_qpixmap(image_np: np.ndarray) -> Optional[QPixmap]:
    """把 numpy 图像转为 QPixmap 用于 QLabel 显示。"""
    if image_np is None:
        return None
    try:
        if len(image_np.shape) == 2:
            # 灰度
            h, w = image_np.shape
            bytes_per_line = w
            qimg = QImage(image_np.data, w, h, bytes_per_line, QImage.Format_Grayscale8)
        elif len(image_np.shape) == 3 and image_np.shape[2] == 3:
            # BGR
            h, w, _ = image_np.shape
            rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        elif len(image_np.shape) == 3 and image_np.shape[2] == 4:
            h, w, _ = image_np.shape
            qimg = QImage(image_np.data, w, h, 4 * w, QImage.Format_RGBA8888)
        else:
            return None
        return QPixmap.fromImage(qimg.copy())
    except Exception as e:
        print(f"图像转 QPixmap 失败: {e}")
        return None


class TurntableProtoUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("转台 360° 拼接原型（在线相机版）")
        self.resize(1600, 900)

        self.calib = TurntableCalibrator()
        self.session = OnlineTurntableSession()
        self.merged: Optional[o3d.geometry.PointCloud] = None

        self.cam_mgr: Optional[CameraManager] = None
        self.marker_detector: Optional[MarkerDetector] = None
        self.current_frame0: Optional[FrameData] = None
        self.current_frame1: Optional[FrameData] = None
        self.current_markers0: List[dict] = []
        self.current_markers1: List[dict] = []
        self._loading_dlg: Optional[QProgressDialog] = None
        self._active_workers: List[WorkerThread] = []

        self._setup_ui()
        self._reset_online_state()

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        hlo = QHBoxLayout(central)

        # 左侧控制面板
        left = QVBoxLayout()
        left.setSpacing(10)

        info = QLabel(
            "<b>转台拼接原型（在线相机版）</b><br>"
            "连相机 → 拍摄 frame0/1 → 标定 → 步进采集 → 实时拼接"
        )
        info.setWordWrap(True)
        left.addWidget(info)

        # 1) 在线相机连接区
        left.addWidget(self._build_online_camera_group())

        # 2) 在线标定区
        left.addWidget(self._build_online_calib_group())

        # 3) 步进采集区
        left.addWidget(self._build_online_capture_group())

        # 4) 拼接输出区
        left.addWidget(self._build_stitch_group())

        left.addStretch(1)

        # 右侧：2D/3D 预览 + 日志
        right = QVBoxLayout()

        # 上方水平 splitter：2D 预览 | 3D 查看器
        preview_splitter = QSplitter(Qt.Horizontal)
        preview_splitter.setChildrenCollapsible(False)

        # 2D 预览窗口
        self.preview_2d_label = QLabel("2D 预览区")
        self.preview_2d_label.setAlignment(Qt.AlignCenter)
        self.preview_2d_label.setStyleSheet("background-color: #0a0a0a; color: #666666; border: 1px solid #3a3a3a;")
        self.preview_2d_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_2d_label.setMinimumSize(400, 300)
        preview_splitter.addWidget(self.preview_2d_label)

        # 3D 点云查看器
        if HAS_VIEWER:
            self.viewer = EmbeddedPointCloudViewer()
            preview_splitter.addWidget(self.viewer)
        else:
            self.viewer = None
            no_viewer = QLabel("OpenGL 查看器不可用")
            no_viewer.setStyleSheet("background-color: #1a1a1a; color: #888888;")
            preview_splitter.addWidget(no_viewer)

        preview_splitter.setSizes([700, 900])
        right.addWidget(preview_splitter, 3)

        # 日志
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180)
        right.addWidget(self.log_box, 1)

        hlo.addLayout(left, 1)
        hlo.addLayout(right, 3)

    def _build_online_camera_group(self) -> QGroupBox:
        grp = QGroupBox("相机连接")
        v = QVBoxLayout(grp)

        h = QHBoxLayout()
        self.btn_rvc_init = QPushButton("初始化 RVC")
        self.btn_rvc_init.clicked.connect(self._on_rvc_init)
        h.addWidget(self.btn_rvc_init)

        self.btn_rvc_shutdown = QPushButton("关闭 RVC")
        self.btn_rvc_shutdown.clicked.connect(self._on_rvc_shutdown)
        self.btn_rvc_shutdown.setEnabled(False)
        h.addWidget(self.btn_rvc_shutdown)
        v.addLayout(h)

        h = QHBoxLayout()
        self.combo_devices = QComboBox()
        self.combo_devices.setMinimumWidth(160)
        h.addWidget(self.combo_devices)

        self.btn_refresh_devices = QPushButton("刷新")
        self.btn_refresh_devices.clicked.connect(self._on_refresh_devices)
        h.addWidget(self.btn_refresh_devices)
        v.addLayout(h)

        h = QHBoxLayout()
        self.btn_connect_cam = QPushButton("连接相机")
        self.btn_connect_cam.clicked.connect(self._on_connect_camera)
        self.btn_connect_cam.setEnabled(False)
        h.addWidget(self.btn_connect_cam)

        self.btn_disconnect_cam = QPushButton("断开")
        self.btn_disconnect_cam.clicked.connect(self._on_disconnect_camera)
        self.btn_disconnect_cam.setEnabled(False)
        h.addWidget(self.btn_disconnect_cam)
        v.addLayout(h)

        self.lbl_cam_status = QLabel("RVC 未初始化")
        self.lbl_cam_status.setWordWrap(True)
        v.addWidget(self.lbl_cam_status)

        # 标记物类型
        h = QHBoxLayout()
        h.addWidget(QLabel("标记物:"))
        self.combo_marker_type = QComboBox()
        self.combo_marker_type.addItem("编码圆", MARKER_TYPE_CODED_CIRCLE)
        self.combo_marker_type.addItem("非对称圆标定板", MARKER_TYPE_ASYMMETRIC_GRID)
        self.combo_marker_type.currentIndexChanged.connect(self._on_marker_type_changed)
        h.addWidget(self.combo_marker_type)
        v.addLayout(h)

        return grp

    def _build_online_calib_group(self) -> QGroupBox:
        grp = QGroupBox("标定 frame0 / frame1")
        v = QVBoxLayout(grp)

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
        self.btn_online_calib.clicked.connect(self._on_online_calibrate)
        self.btn_online_calib.setEnabled(False)
        v.addWidget(self.btn_online_calib)

        self.lbl_online_calib = QLabel("未标定")
        self.lbl_online_calib.setWordWrap(True)
        v.addWidget(self.lbl_online_calib)

        return grp

    def _build_online_capture_group(self) -> QGroupBox:
        grp = QGroupBox("步进采集")
        v = QVBoxLayout(grp)

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

        return grp

    def _build_stitch_group(self) -> QGroupBox:
        grp = QGroupBox("拼接与输出")
        v = QVBoxLayout(grp)

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

    # ------------------------------------------------------------------
    # 通用日志 / loading / worker
    # ------------------------------------------------------------------
    def log(self, text: str):
        self.log_box.append(text)

    def _show_loading(self, text: str):
        self._loading_dlg = QProgressDialog(text, "取消", 0, 0, self)
        self._loading_dlg.setWindowModality(Qt.WindowModal)
        self._loading_dlg.setCancelButton(None)
        self._loading_dlg.setMinimumDuration(0)
        self._loading_dlg.show()
        QApplication.processEvents()

    def _hide_loading(self):
        if self._loading_dlg is not None:
            self._loading_dlg.close()
            self._loading_dlg = None

    def _run_worker(self, func, on_done, *args, **kwargs):
        """启动后台线程并保留引用，防止 QThread 被 GC 销毁。"""
        if WorkerThread is None:
            self.log("[ERROR] WorkerThread 不可用")
            return None
        worker = WorkerThread(func, *args, **kwargs)
        worker.finished.connect(lambda res, err, w=worker: self._on_worker_finished(res, err, on_done, w))
        self._active_workers.append(worker)
        worker.start()
        return worker

    def _on_worker_finished(self, result, error, on_done, worker):
        """后台线程完成回调：释放引用、隐藏 loading、转发结果。"""
        try:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
        except Exception:
            pass
        self._hide_loading()
        if error:
            self.log(f"[ERROR] {error}")
            QMessageBox.warning(self, "执行失败", str(error))
            return
        on_done(result)

    # ------------------------------------------------------------------
    # 在线相机连接
    # ------------------------------------------------------------------
    def _reset_online_state(self):
        self.current_frame0 = None
        self.current_frame1 = None
        self.current_markers0 = []
        self.current_markers1 = []
        self.session.reset()
        self.merged = None
        if self.viewer:
            self.viewer.clear_all()
        self.preview_2d_label.setPixmap(QPixmap())
        self.preview_2d_label.setText("2D 预览区")
        self._update_online_ui()

    def _update_online_ui(self):
        connected = (self.cam_mgr is not None and
                     self.cam_mgr.get_connected_ids())
        has_cam = bool(connected)

        self.btn_rvc_init.setEnabled(self.cam_mgr is None)
        self.btn_rvc_shutdown.setEnabled(self.cam_mgr is not None)
        self.btn_connect_cam.setEnabled(self.cam_mgr is not None and self.combo_devices.count() > 0)
        self.btn_disconnect_cam.setEnabled(has_cam)
        self.btn_preview_2d.setEnabled(has_cam)
        self.btn_capture_frame0.setEnabled(has_cam)

        frame0_shot = self.current_frame0 is not None
        f0_ok = frame0_shot and len(self.current_markers0) >= 3
        self.btn_capture_frame1.setEnabled(frame0_shot)

        f1_ok = self.current_frame1 is not None and len(self.current_markers1) >= 3
        self.btn_online_calib.setEnabled(f0_ok and f1_ok)

        calibrated = self.session.is_calibrated()
        self.btn_capture_step.setEnabled(calibrated)
        self.btn_auto_capture.setEnabled(calibrated)
        self.chk_auto_stitch.setEnabled(calibrated)
        self.btn_stitch.setEnabled(self.session.can_stitch())
        self.btn_save.setEnabled(self.merged is not None)
        self.btn_save_session.setEnabled(self.session.get_all_frames() or self.current_frame0 is not None)

        if has_cam:
            cam_id = self.cam_mgr.get_connected_ids()[0]
            cam = self.cam_mgr._cameras.get(cam_id)
            info = cam.device_info if cam else None
            name = getattr(info, "name", "unknown") if info else cam_id
            sn = getattr(info, "sn", "-") if info else "-"
            self.lbl_cam_status.setText(f"已连接: {name} ({sn})")
        else:
            self.lbl_cam_status.setText("未连接相机")

        self.lbl_frame0.setText(
            f"frame0: {'已拍摄 ' + str(len(self.current_markers0)) + ' 个标记' if self.current_frame0 else '未拍摄'}"
        )
        self.lbl_frame1.setText(
            f"frame1: {'已拍摄 ' + str(len(self.current_markers1)) + ' 个标记' if self.current_frame1 else '未拍摄'}"
        )

        self.lbl_step_info.setText(
            f"当前步: {self.session.current_step} / 总步: {self.session.total_steps_needed() if calibrated else '—'}"
        )
        self.lbl_step_info.repaint()
        self.lbl_sequence.setText(f"已采集序列: {len(self.session.sequence)} 帧")
        self.lbl_sequence.repaint()

    def _on_marker_type_changed(self, _idx):
        if self.marker_detector is not None:
            mtype = self.combo_marker_type.currentData()
            self.marker_detector.set_marker_type(mtype)
            self.log(f"标记物类型切换为: {mtype}")

    def _on_rvc_init(self):
        if CameraManager is None:
            QMessageBox.warning(self, "无 SDK", "PyRVC 未安装，无法使用在线模式")
            return
        self.cam_mgr = CameraManager()
        ok, msg = self.cam_mgr.initialize()
        if ok:
            self.marker_detector = MarkerDetector(self.combo_marker_type.currentData())
            self.log("RVC 初始化成功")
            self._on_refresh_devices()
        else:
            self.log(f"RVC 初始化失败: {msg}")
            self.cam_mgr = None
        self._update_online_ui()

    def _on_rvc_shutdown(self):
        if self.cam_mgr is not None:
            self.cam_mgr.shutdown()
            self.cam_mgr = None
        self.marker_detector = None
        self._reset_online_state()
        self.combo_devices.clear()
        self.log("RVC 已关闭")
        self._update_online_ui()

    def _on_refresh_devices(self):
        if self.cam_mgr is None:
            return
        self.combo_devices.clear()
        devices = self.cam_mgr.find_devices()
        if not devices:
            self.log("未找到 RVC 设备")
            return
        for i, dev in enumerate(devices):
            try:
                ok, info = dev.GetDeviceInfo()
                name = info.name if ok else f"设备{i}"
                sn = getattr(info, "sn", "-") if ok else "-"
                self.combo_devices.addItem(f"[{i}] {name} ({sn})", i)
            except Exception as e:
                self.log(f"读取设备 {i} 信息失败: {e}")
        self.log(f"发现 {len(devices)} 台设备")
        self._update_online_ui()

    def _on_connect_camera(self):
        if self.cam_mgr is None:
            return
        idx = self.combo_devices.currentData()
        if idx is None:
            return
        self._show_loading("连接相机中...")

        def _connect():
            self.cam_mgr.add_camera("cam0")
            return self.cam_mgr.connect("cam0", idx)

        def _done(result):
            ok, msg = result
            self.log(f"连接相机: {msg}")
            if not ok:
                self.cam_mgr.remove_camera("cam0")
            self._update_online_ui()

        self._run_worker(_connect, _done)

    def _on_disconnect_camera(self):
        if self.cam_mgr is not None:
            self.cam_mgr.remove_camera("cam0")
            self._reset_online_state()
            self.log("相机已断开")
        self._update_online_ui()

    # ------------------------------------------------------------------
    # 在线 2D 预览 / 拍摄 / 检测
    # ------------------------------------------------------------------
    def _display_2d(self, image_np: np.ndarray):
        """在 2D 预览窗口显示图像，按 QLabel 空间等比缩放，不保存文件。"""
        pixmap = _np_to_qpixmap(image_np)
        if pixmap is None:
            self.preview_2d_label.setText("2D 预览区（图像格式不支持）")
            return
        label_size = self.preview_2d_label.size()
        if pixmap.width() > label_size.width() or pixmap.height() > label_size.height():
            scaled = pixmap.scaled(
                label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            scaled = pixmap
        self.preview_2d_label.setPixmap(scaled)
        self.preview_2d_label.setText("")

    def _on_preview_2d(self):
        if self.cam_mgr is None or not self.cam_mgr.get_connected_ids():
            return
        self._show_loading("2D 预览拍摄中...")

        def _capture():
            return self.cam_mgr.capture_2d_preview("cam0")

        def _done(frame):
            if frame is None or frame.image_np is None:
                self.log("2D 预览失败")
                return
            self.log(f"2D 预览: {frame.image_np.shape}")
            self._display_2d(frame.image_np)

        self._run_worker(_capture, _done)

    def _on_capture_frame0(self):
        self._capture_frame_for_calib(is_frame0=True)

    def _on_capture_frame1(self):
        self._capture_frame_for_calib(is_frame0=False)

    def _capture_frame_for_calib(self, is_frame0: bool):
        if self.cam_mgr is None or not self.cam_mgr.get_connected_ids():
            return
        label = "frame0" if is_frame0 else "frame1"
        self._show_loading(f"拍摄 {label} 中...")

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
                if self.viewer:
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
                if self.viewer:
                    self.viewer.set_pointcloud("frame1", pcd)
                if len(markers) < 3:
                    QMessageBox.warning(
                        self, "标记点不足",
                        f"frame1 仅检测到 {len(markers)} 个标记点，标定至少需要 3 个。\n"
                        "请调整标记物位置、光照或曝光后重拍。"
                    )
            self._update_online_ui()

        self._run_worker(_capture, _done)

    def _on_online_calibrate(self):
        mtype = self.combo_marker_type.currentData()
        key = "index" if mtype == MARKER_TYPE_ASYMMETRIC_GRID else "code"
        self._show_loading("在线标定中...")

        def _calib():
            return self.session.calibrate(marker_key=key)

        def _done(result):
            ok, msg, info = result
            self.log(f"在线标定: {msg}")
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
                self.current_frame0 = None
                self.current_frame1 = None
                self.current_markers0 = []
                self.current_markers1 = []
                if self.viewer:
                    self.viewer.set_pointcloud("frame0", None)
                    self.viewer.set_pointcloud("frame1", None)
                self.log("标定完成，请将转台回到起始位置，从 step 1 开始采集")
            else:
                QMessageBox.warning(self, "标定失败", msg)
            self._update_online_ui()

        self._run_worker(_calib, _done)

    # ------------------------------------------------------------------
    # 步进采集
    # ------------------------------------------------------------------
    def _on_capture_step(self):
        if not self.session.is_calibrated():
            return
        if self.session.current_step > self.session.total_steps_needed():
            QMessageBox.information(self, "采集完成", "已达到 360° 所需步数")
            return
        self._capture_sequence_step()

    def _capture_sequence_step(self):
        if self.cam_mgr is None or not self.cam_mgr.get_connected_ids():
            return
        step = self.session.current_step
        self._show_loading(f"拍摄第 {step} 步...")

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
            step_idx = self.session.current_step - 1
            total = self.session.total_steps_needed()
            self.log(
                f"第 {step_idx} 步采集完成: {len(pcd.points)} 点 "
                f"(current_step={self.session.current_step}, 序列 {len(self.session.sequence)}/{total})"
            )
            self._display_2d(frame.image_np)
            if self.viewer:
                self.viewer.set_pointcloud(f"step_{step_idx}", pcd)
            if self.chk_auto_stitch.isChecked():
                self.log("自动实时拼接...")
                self._do_stitch_online(silent=True)
            if self.session.current_step > total:
                self.log("360° 采集完成，可以拼接")
            self._update_online_ui()

        self._run_worker(_capture, _done)

    def _on_toggle_auto_capture(self, checked: bool):
        if checked:
            if not self.session.is_calibrated():
                self.btn_auto_capture.setChecked(False)
                return
            self.btn_auto_capture.setText("停止自动采集")
            self._auto_capture_next()
        else:
            self.btn_auto_capture.setText("开始自动采集")

    def _auto_capture_next(self):
        if not self.btn_auto_capture.isChecked():
            return
        if self.session.current_step > self.session.total_steps_needed():
            self.btn_auto_capture.setChecked(False)
            self.btn_auto_capture.setText("开始自动采集")
            self.log("自动采集完成")
            return
        self._capture_sequence_step()
        interval_ms = self.spin_auto_interval.value() * 1000
        QTimer.singleShot(interval_ms, self._auto_capture_next)

    # ------------------------------------------------------------------
    # 拼接 / 保存
    # ------------------------------------------------------------------
    def _on_stitch(self):
        if not self.session.can_stitch():
            QMessageBox.warning(self, "无法拼接", "请先完成标定并采集至少 2 帧")
            return
        self._do_stitch_online(silent=False)

    def _do_stitch_online(self, silent: bool = False):
        if not silent:
            self._show_loading("在线拼接中...")
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
            if self.viewer:
                self.viewer.clear_all()
                self.viewer.set_pointcloud_merged(merged)
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
        """保存在线采集的原始帧到目录。"""
        if not self.session.get_all_frames():
            return
        base_dir = QFileDialog.getExistingDirectory(self, "选择会话保存目录")
        if not base_dir:
            return
        session_dir = os.path.join(base_dir, f"turntable_session_{time.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(session_dir, exist_ok=True)
        self.session.session_dir = session_dir

        self._show_loading("保存会话中...")

        def _save():
            # frame0
            if self.session.frame0 is not None:
                self.session.frame0.save(session_dir)
                with open(os.path.join(session_dir, "markers_frame0.json"), "w", encoding="utf-8") as f:
                    json.dump(_markers_to_json(self.session.markers0), f, ensure_ascii=False, indent=2)
            # frame1
            if self.session.frame1 is not None:
                self.session.frame1.save(session_dir)
                with open(os.path.join(session_dir, "markers_frame1.json"), "w", encoding="utf-8") as f:
                    json.dump(_markers_to_json(self.session.markers1), f, ensure_ascii=False, indent=2)
            # sequence
            for i, frame in enumerate(self.session.sequence):
                frame_dir = os.path.join(session_dir, f"frame_{i + 2:04d}")
                os.makedirs(frame_dir, exist_ok=True)
                frame.save(frame_dir)
            # calib info
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

        self._run_worker(_save, _done)

    def closeEvent(self, event):
        if self.cam_mgr is not None:
            self.cam_mgr.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = TurntableProtoUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
