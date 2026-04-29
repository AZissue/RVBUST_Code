import os
import re
import sys
import traceback
from datetime import datetime

import cv2
import numpy as np
import PyRVC as RVC
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QSpinBox, QDoubleSpinBox, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QCheckBox
)

from .core.camera_controller import RVCCameraController
from .core.frame_data import CaptureSession
from .core.marker_detector import MarkerDetector
from .core.rvc_resource import safe_destroy
from .core.project_manager import ProjectManager
from .core.stitch_engine import (
    HAS_OPEN3D, build_merged_pointcloud, extract_numpy_from_pcd, stitch_chain
)
from .threads.detection_worker import DetectionParamSearchWorker
from .threads.preview_thread import PreviewThread
from .ui.styles import STYLESHEET
from .ui.zoomable_label import ZoomableImageLabel
from .ui.overlay_loading import OverlayLoadingWidget
from .utils.logging_config import setup_module_logger
from .utils.ply_io import save_binary_ply
from .utils.preview_process import PointCloudPreviewProcess

logger = setup_module_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("编码圆拼接工具 v2")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)

        self._detection_results = []  # 收集参数搜索结果

        self.camera = RVCCameraController()
        self.detector = MarkerDetector()

        # 会话状态（封装帧数据与 RVC 资源生命周期）
        self.prev_session = CaptureSession(frame_id=-1)
        self.current_session = CaptureSession(frame_id=-1)

        # 预览
        self.preview_thread = None
        self._detection_worker = None

        # 2D 曝光实时调节防抖定时器
        self._exp2d_debounce_timer = QTimer(self)
        self._exp2d_debounce_timer.setSingleShot(True)
        self._exp2d_debounce_timer.timeout.connect(self._apply_exp_2d_live)

        # 拼接数据（RVC 资源由本窗口管理生命周期）
        self.stitch_sessions = []      # List[CaptureSession]
        self.merged_o3d_pcd = None     # Open3D 点云
        self.merged_points = None      # np.ndarray
        self.merged_colors = None      # np.ndarray
        self._stitch_poses = []        # 保存拼接时的位姿 (R, t) 列表
        self._preview_process = PointCloudPreviewProcess()  # 非阻塞 Open3D 预览

        ok, msg = self.camera.initialize()
        self.setup_ui()
        self.apply_styles()
        self.load_settings()

        if ok:
            self.log("RVC系统初始化完成")
        else:
            self.log(f"初始化失败: {msg}")
            QMessageBox.critical(self, "初始化失败", msg)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        left = self.create_left_panel()
        right = self.create_right_panel()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 1180])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def create_left_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        panel = QWidget()
        panel.setMinimumWidth(400)
        panel.setMaximumWidth(480)
        layout = QVBoxLayout(panel)
        layout.setSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        title = QLabel("🔧 编码圆拼接工具 v2")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # --- 设备与拍摄 ---
        dev_grp = QGroupBox("📷 设备与拍摄")
        dev_lo = QVBoxLayout(dev_grp)
        dev_lo.setSpacing(6)

        self.btn_find = QPushButton("🔍 查找设备")
        self.btn_find.setObjectName("primaryButton")
        self.btn_find.setMinimumHeight(32)
        self.btn_find.clicked.connect(self.on_find_devices)
        dev_lo.addWidget(self.btn_find)

        conn_lo = QHBoxLayout()
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("successButton")
        self.btn_connect.setMinimumHeight(32)
        self.btn_connect.clicked.connect(self.on_connect)
        conn_lo.addWidget(self.btn_connect, 2)

        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("dangerButton")
        self.btn_disconnect.setMinimumHeight(32)
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        conn_lo.addWidget(self.btn_disconnect, 1)
        dev_lo.addLayout(conn_lo)

        st_lo = QHBoxLayout()
        st_lo.addWidget(QLabel("状态:"))
        self.lbl_status = QLabel("未连接")
        self.lbl_status.setObjectName("statusLabel")
        self.lbl_status.setProperty("status", "disconnected")
        st_lo.addWidget(self.lbl_status)
        st_lo.addStretch()
        dev_lo.addLayout(st_lo)

        self.btn_capture_3d = QPushButton("📷 3D 拍照")
        self.btn_capture_3d.setToolTip("投射结构光，获取3D数据")
        self.btn_capture_3d.setMinimumHeight(36)
        self.btn_capture_3d.setObjectName("primaryButton")
        self.btn_capture_3d.setEnabled(False)
        self.btn_capture_3d.clicked.connect(self.on_capture_3d)
        dev_lo.addWidget(self.btn_capture_3d)

        pv_lo = QHBoxLayout()
        self.btn_start_preview = QPushButton("▶ 开始预览")
        self.btn_start_preview.setMinimumHeight(32)
        self.btn_start_preview.setEnabled(False)
        self.btn_start_preview.clicked.connect(self.on_start_preview)
        pv_lo.addWidget(self.btn_start_preview)

        self.btn_stop_preview = QPushButton("⏹ 停止")
        self.btn_stop_preview.setMinimumHeight(32)
        self.btn_stop_preview.setEnabled(False)
        self.btn_stop_preview.clicked.connect(self.on_stop_preview)
        pv_lo.addWidget(self.btn_stop_preview)
        dev_lo.addLayout(pv_lo)

        self.chk_realtime_detect = QCheckBox("实时检测编码圆")
        self.chk_realtime_detect.setChecked(True)
        self.chk_realtime_detect.setEnabled(False)
        dev_lo.addWidget(self.chk_realtime_detect)

        self.btn_test_detect = QPushButton("🔍 测试当前帧检测")
        self.btn_test_detect.setMinimumHeight(32)
        self.btn_test_detect.setEnabled(False)
        self.btn_test_detect.clicked.connect(self.on_test_detect)
        dev_lo.addWidget(self.btn_test_detect)

        layout.addWidget(dev_grp)

        # --- 拍摄参数 ---
        self.grp_capture_params = QGroupBox("📐 拍摄参数")
        self.grp_capture_params.setEnabled(False)
        cap_lo = QGridLayout(self.grp_capture_params)
        cap_lo.setSpacing(4)

        cap_lo.addWidget(QLabel("2D 曝光(ms):"), 0, 0)
        self.spin_exp_2d = QDoubleSpinBox()
        self.spin_exp_2d.setRange(3.0, 100.0)
        self.spin_exp_2d.setDecimals(1)
        self.spin_exp_2d.setValue(20.0)
        self.spin_exp_2d.valueChanged.connect(self.on_exp_2d_changed_live)
        cap_lo.addWidget(self.spin_exp_2d, 0, 1)

        cap_lo.addWidget(QLabel("3D 曝光(ms):"), 0, 2)
        self.spin_exp_3d = QDoubleSpinBox()
        self.spin_exp_3d.setRange(3.0, 100.0)
        self.spin_exp_3d.setDecimals(1)
        self.spin_exp_3d.setValue(20.0)
        cap_lo.addWidget(self.spin_exp_3d, 0, 3)

        cap_lo.addWidget(QLabel("2D 增益:"), 1, 0)
        self.spin_gain_2d = QSpinBox()
        self.spin_gain_2d.setRange(0, 48)
        self.spin_gain_2d.setValue(0)
        cap_lo.addWidget(self.spin_gain_2d, 1, 1)

        cap_lo.addWidget(QLabel("3D 增益:"), 1, 2)
        self.spin_gain_3d = QSpinBox()
        self.spin_gain_3d.setRange(0, 48)
        self.spin_gain_3d.setValue(0)
        cap_lo.addWidget(self.spin_gain_3d, 1, 3)

        cap_btn_lo = QHBoxLayout()
        self.btn_read_params = QPushButton("读取当前参数")
        self.btn_read_params.clicked.connect(self.on_read_capture_options)
        cap_btn_lo.addWidget(self.btn_read_params)

        self.btn_apply_params = QPushButton("应用并保存")
        self.btn_apply_params.setObjectName("primaryButton")
        self.btn_apply_params.clicked.connect(self.on_apply_capture_options)
        cap_btn_lo.addWidget(self.btn_apply_params)
        cap_lo.addLayout(cap_btn_lo, 2, 0, 1, 4)

        layout.addWidget(self.grp_capture_params)

        # --- 编码圆参数 ---
        mk_grp = QGroupBox("⚙️ 编码圆参数")
        mk_lo = QGridLayout(mk_grp)
        mk_lo.setSpacing(4)

        mk_lo.addWidget(QLabel("N值:"), 0, 0)
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 100)
        self.spin_n.setValue(8)
        self.spin_n.valueChanged.connect(self.on_marker_params_changed)
        mk_lo.addWidget(self.spin_n, 0, 1)

        mk_lo.addWidget(QLabel("r1/r0:"), 1, 0)
        self.spin_r1 = QDoubleSpinBox()
        self.spin_r1.setRange(0.1, 10.0)
        self.spin_r1.setDecimals(3)
        self.spin_r1.setValue(2.0)
        self.spin_r1.valueChanged.connect(self.on_marker_params_changed)
        mk_lo.addWidget(self.spin_r1, 1, 1)

        mk_lo.addWidget(QLabel("r2/r0:"), 2, 0)
        self.spin_r2 = QDoubleSpinBox()
        self.spin_r2.setRange(0.1, 10.0)
        self.spin_r2.setDecimals(3)
        self.spin_r2.setValue(3.0)
        self.spin_r2.valueChanged.connect(self.on_marker_params_changed)
        mk_lo.addWidget(self.spin_r2, 2, 1)

        layout.addWidget(mk_grp)

        # --- 拼接 ---
        stch_grp = QGroupBox("🔗 彩色点云拼接")
        stch_lo = QVBoxLayout(stch_grp)
        stch_lo.setSpacing(6)

        fi_lo = QHBoxLayout()
        self.lbl_frame_count = QLabel("已采集: 0 帧")
        fi_lo.addWidget(self.lbl_frame_count)
        fi_lo.addStretch()
        stch_lo.addLayout(fi_lo)

        btn_lo = QHBoxLayout()
        self.btn_add_frame = QPushButton("➕ 添加")
        self.btn_add_frame.setMinimumHeight(32)
        self.btn_add_frame.setEnabled(False)
        self.btn_add_frame.clicked.connect(self.on_add_stitch_frame)
        btn_lo.addWidget(self.btn_add_frame, 2)

        self.btn_clear_frames = QPushButton("🗑️ 清空")
        self.btn_clear_frames.setMinimumHeight(32)
        self.btn_clear_frames.setEnabled(False)
        self.btn_clear_frames.clicked.connect(self.on_clear_stitch_frames)
        btn_lo.addWidget(self.btn_clear_frames, 1)
        stch_lo.addLayout(btn_lo)

        cd_lo = QHBoxLayout()
        cd_lo.addWidget(QLabel("坐标系:"))
        self.combo_stitch_coord = QComboBox()
        self.combo_stitch_coord.addItems(["第一帧", "最后一帧"])
        cd_lo.addWidget(self.combo_stitch_coord)
        cd_lo.addStretch()
        stch_lo.addLayout(cd_lo)

        self.btn_stitch = QPushButton("🔗 执行拼接")
        self.btn_stitch.setObjectName("successButton")
        self.btn_stitch.setMinimumHeight(36)
        self.btn_stitch.setEnabled(False)
        self.btn_stitch.clicked.connect(self.on_stitch_pointclouds)
        stch_lo.addWidget(self.btn_stitch)

        self.btn_save_stitched = QPushButton("💾 保存结果")
        self.btn_save_stitched.setMinimumHeight(32)
        self.btn_save_stitched.setEnabled(False)
        self.btn_save_stitched.clicked.connect(self.on_save_stitched_pointcloud)
        stch_lo.addWidget(self.btn_save_stitched)

        # 工程文件操作按钮
        proj_btn_lo = QHBoxLayout()
        self.btn_save_project = QPushButton("💾 保存工程")
        self.btn_save_project.setMinimumHeight(32)
        self.btn_save_project.setEnabled(False)
        self.btn_save_project.clicked.connect(self.on_save_project)
        proj_btn_lo.addWidget(self.btn_save_project, 2)

        self.btn_load_project = QPushButton("📂 加载工程")
        self.btn_load_project.setMinimumHeight(32)
        self.btn_load_project.clicked.connect(self.on_load_project)
        proj_btn_lo.addWidget(self.btn_load_project, 1)
        stch_lo.addLayout(proj_btn_lo)

        self.btn_export_poses = QPushButton("📊 导出位姿矩阵")
        self.btn_export_poses.setMinimumHeight(32)
        self.btn_export_poses.setEnabled(False)
        self.btn_export_poses.clicked.connect(self.on_export_poses)
        stch_lo.addWidget(self.btn_export_poses)

        self.lbl_stitch_result = QLabel("状态: 未开始")
        self.lbl_stitch_result.setObjectName("infoLabel")
        stch_lo.addWidget(self.lbl_stitch_result)

        layout.addWidget(stch_grp)

        # --- 预览 ---
        prev_grp = QGroupBox("☁️ 拼接点云预览")
        prev_lo = QVBoxLayout(prev_grp)
        self.lbl_pointcloud_info = QLabel("点数: - | 帧数: -")
        self.lbl_pointcloud_info.setObjectName("infoLabel")
        prev_lo.addWidget(self.lbl_pointcloud_info)

        self.btn_preview_pc = QPushButton("🔍 Open3D 预览")
        self.btn_preview_pc.setObjectName("primaryButton")
        self.btn_preview_pc.setMinimumHeight(40)
        self.btn_preview_pc.setEnabled(False)
        self.btn_preview_pc.clicked.connect(self.on_preview_pointcloud)
        prev_lo.addWidget(self.btn_preview_pc)

        layout.addWidget(prev_grp)
        layout.addStretch()

        scroll.setWidget(panel)
        return scroll

    def create_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        v_splitter = QSplitter(Qt.Vertical)
        layout.addWidget(v_splitter)

        # 上半：图像预览
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        h_splitter = QSplitter(Qt.Horizontal)

        prev_group = QGroupBox("⏮️ 前一帧 (滚轮缩放/右键拖动/双击恢复)")
        prev_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        prev_lo = QVBoxLayout(prev_group)
        prev_lo.setContentsMargins(4, 12, 4, 4)

        self.lbl_prev_image = ZoomableImageLabel()
        self.lbl_prev_image.setObjectName("previewLabel")
        self.lbl_prev_image.setMinimumSize(400, 300)
        self.lbl_prev_image.setText("无数据")
        prev_lo.addWidget(self.lbl_prev_image, 1)

        self.lbl_prev_info = QLabel("分辨率: - | 编码圆: - | 缩放: 100%")
        self.lbl_prev_info.setObjectName("infoLabel")
        self.lbl_prev_info.setAlignment(Qt.AlignCenter)
        prev_lo.addWidget(self.lbl_prev_info)

        h_splitter.addWidget(prev_group)

        curr_group = QGroupBox("⏭️ 当前帧 (滚轮缩放/右键拖动/双击恢复)")
        curr_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        curr_lo = QVBoxLayout(curr_group)
        curr_lo.setContentsMargins(4, 12, 4, 4)

        self.lbl_curr_image = ZoomableImageLabel()
        self.lbl_curr_image.setObjectName("previewLabel")
        self.lbl_curr_image.setMinimumSize(400, 300)
        self.lbl_curr_image.setText("请点击连接相机并开始拍照")
        curr_lo.addWidget(self.lbl_curr_image, 1)

        self.lbl_curr_info = QLabel("分辨率: - | 编码圆: - | 缩放: 100%")
        self.lbl_curr_info.setObjectName("infoLabel")
        self.lbl_curr_info.setAlignment(Qt.AlignCenter)
        curr_lo.addWidget(self.lbl_curr_info)

        h_splitter.addWidget(curr_group)
        h_splitter.setSizes([600, 600])

        self.lbl_prev_image.scale_changed.connect(
            lambda s: self._update_scale_info(self.lbl_prev_info, s)
        )
        self.lbl_curr_image.scale_changed.connect(
            lambda s: self._update_scale_info(self.lbl_curr_info, s)
        )

        preview_layout.addWidget(h_splitter)
        v_splitter.addWidget(preview_container)

        # 下半：数据与日志
        data_container = QWidget()
        data_layout = QHBoxLayout(data_container)
        data_layout.setContentsMargins(0, 0, 0, 0)

        frames_group = QGroupBox("📋 拼接帧列表")
        frames_layout = QVBoxLayout(frames_group)
        frames_layout.setContentsMargins(4, 12, 4, 4)
        self.table_frames = QTableWidget()
        self.table_frames.setColumnCount(3)
        self.table_frames.setHorizontalHeaderLabels(["帧ID", "编码圆数", "状态"])
        self.table_frames.horizontalHeader().setStretchLastSection(True)
        self.table_frames.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_frames.setMaximumHeight(150)
        self.table_frames.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_frames.customContextMenuRequested.connect(self.on_frame_table_context_menu)
        frames_layout.addWidget(self.table_frames)
        data_layout.addWidget(frames_group, 1)

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)

        common_group = QGroupBox("🔍 共有编码圆详情")
        common_layout = QVBoxLayout(common_group)
        common_layout.setContentsMargins(4, 12, 4, 4)
        self.table_common = QTableWidget()
        self.table_common.setColumnCount(3)
        self.table_common.setHorizontalHeaderLabels(["编码", "前一帧坐标", "当前帧坐标"])
        self.table_common.horizontalHeader().setStretchLastSection(True)
        self.table_common.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_common.setMaximumHeight(120)
        common_layout.addWidget(self.table_common)
        details_layout.addWidget(common_group)

        log_group = QGroupBox("📝 操作日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 12, 4, 4)
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setMaximumHeight(100)
        log_layout.addWidget(self.text_log)

        btn_clear = QPushButton("清空日志")
        btn_clear.setMaximumWidth(80)
        btn_clear.setMinimumHeight(24)
        btn_clear.clicked.connect(self.text_log.clear)
        log_layout.addWidget(btn_clear, alignment=Qt.AlignRight)
        details_layout.addWidget(log_group)

        data_layout.addWidget(details_widget, 2)
        v_splitter.addWidget(data_container)
        v_splitter.setSizes([550, 350])

        return panel

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def load_settings(self):
        settings = QSettings("RVBUST", "CodedCircleStitchApp_v2")
        geom = settings.value("geometry")
        if geom is not None:
            try:
                from PySide6.QtCore import QByteArray
                if isinstance(geom, str):
                    geom = QByteArray.fromBase64(geom.encode())
                self.restoreGeometry(geom)
            except Exception:
                pass
        try:
            self.spin_n.setValue(int(settings.value("marker_n", 8)))
        except Exception:
            self.spin_n.setValue(8)
        try:
            self.spin_r1.setValue(float(settings.value("marker_r1", 2.0)))
        except Exception:
            self.spin_r1.setValue(2.0)
        try:
            self.spin_r2.setValue(float(settings.value("marker_r2", 3.0)))
        except Exception:
            self.spin_r2.setValue(3.0)
        try:
            self.combo_stitch_coord.setCurrentIndex(int(settings.value("coord_mode", 0)))
        except Exception:
            self.combo_stitch_coord.setCurrentIndex(0)
        try:
            self.spin_exp_2d.setValue(float(settings.value("exp_2d", 20.0)))
        except Exception:
            self.spin_exp_2d.setValue(20.0)
        try:
            self.spin_exp_3d.setValue(float(settings.value("exp_3d", 20.0)))
        except Exception:
            self.spin_exp_3d.setValue(20.0)
        try:
            self.spin_gain_2d.setValue(int(settings.value("gain_2d", 0)))
        except Exception:
            self.spin_gain_2d.setValue(0)
        try:
            self.spin_gain_3d.setValue(int(settings.value("gain_3d", 0)))
        except Exception:
            self.spin_gain_3d.setValue(0)
        self.on_marker_params_changed()

    def save_settings(self):
        settings = QSettings("RVBUST", "CodedCircleStitchApp_v2")
        geom = self.saveGeometry()
        try:
            # 存为 base64 字符串，跨会话更稳定
            settings.setValue("geometry", geom.toBase64().data().decode())
        except Exception:
            settings.setValue("geometry", geom)
        settings.setValue("marker_n", self.spin_n.value())
        settings.setValue("marker_r1", self.spin_r1.value())
        settings.setValue("marker_r2", self.spin_r2.value())
        settings.setValue("coord_mode", self.combo_stitch_coord.currentIndex())
        settings.setValue("exp_2d", self.spin_exp_2d.value())
        settings.setValue("exp_3d", self.spin_exp_3d.value())
        settings.setValue("gain_2d", self.spin_gain_2d.value())
        settings.setValue("gain_3d", self.spin_gain_3d.value())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.text_log.append(f"[{timestamp}] {message}")
        max_lines = 1000
        if self.text_log.document().blockCount() > max_lines:
            cursor = self.text_log.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        sb = self.text_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_scale_info(self, info_label, scale):
        text = info_label.text()
        scale_pct = int(scale * 100)
        text = re.sub(r'缩放:\d+%', f'缩放:{scale_pct}%', text)
        info_label.setText(text)

    def numpy_to_pixmap(self, image):
        if image is None:
            return None
        if len(image.shape) == 3:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            h, w, c = rgb.shape
            qimg = QImage(rgb.data, w, h, c * w, QImage.Format_RGB888).copy()
        else:
            h, w = image.shape
            qimg = QImage(image.data, w, h, w, QImage.Format_Grayscale8).copy()
        return QPixmap.fromImage(qimg)

    def draw_markers(self, image, markers, common_codes=None, highlight_color=(0, 0, 255)):
        if image is None or not markers:
            return image
        img_display = image.copy()
        if len(img_display.shape) == 2:
            img_display = cv2.cvtColor(img_display, cv2.COLOR_GRAY2BGR)

        common_codes = common_codes or set()
        font = cv2.FONT_HERSHEY_SIMPLEX
        COLOR_GREEN = (0, 255, 0)
        COLOR_BLACK = (0, 0, 0)
        COLOR_DARK_RED = (0, 0, 139)

        for marker in markers:
            center = marker['center']
            code = marker['code']
            cx, cy = center
            is_common = code in common_codes
            color = highlight_color if is_common else COLOR_GREEN
            thickness = 3 if is_common else 2
            radius = 12 if is_common else 8
            size = 15

            cv2.line(img_display, (cx - size, cy), (cx + size, cy), color, thickness)
            cv2.line(img_display, (cx, cy - size), (cx, cy + size), color, thickness)
            cv2.circle(img_display, center, radius, color, thickness)

            text = f"#{code}"
            font_scale = 0.5
            tt = 1
            (tw, th), _ = cv2.getTextSize(text, font, font_scale, tt)
            bg_x1, bg_y1 = cx + 8, cy - th - 8
            bg_x2, bg_y2 = bg_x1 + tw + 4, cy - 4
            bg_color = COLOR_DARK_RED if is_common else COLOR_BLACK
            cv2.rectangle(img_display, (bg_x1, bg_y1), (bg_x2, bg_y2), bg_color, -1)
            cv2.putText(img_display, text, (bg_x1 + 2, bg_y2 - 2), font, font_scale, color, tt)

        common_count = len(common_codes)
        total_count = len(markers)
        info = f"Total: {total_count}"
        if common_count > 0:
            info += f" | Common: {common_count}"
        cv2.putText(img_display, info, (10, 20), font, 0.6, (0, 255, 255), 1)
        return img_display

    def update_display(self, label, image, markers, common_codes=None, info_label=None, reset_zoom=True):
        if image is None:
            return
        display_image = self.draw_markers(image, markers, common_codes)
        if isinstance(label, ZoomableImageLabel):
            label.set_image(display_image, reset_zoom=reset_zoom)
        else:
            pixmap = self.numpy_to_pixmap(display_image)
            if pixmap:
                label.setPixmap(pixmap)
                label.setText("")

        if info_label:
            mc = len(markers) if markers else 0
            cc = len(common_codes) if common_codes else 0
            scale = int(label.get_current_scale() * 100) if isinstance(label, ZoomableImageLabel) else 100
            info = f"{image.shape[1]}x{image.shape[0]} | 编码圆:{mc} | 缩放:{scale}%"
            if cc > 0:
                info += f" | 共有:{cc}"
            info_label.setText(info)

    def find_common_markers(self, markers1, markers2):
        if not markers1 or not markers2:
            return set(), [], []
        codes1 = {m['code'] for m in markers1}
        codes2 = {m['code'] for m in markers2}
        common = codes1 & codes2
        return common, [m for m in markers1 if m['code'] in common], [m for m in markers2 if m['code'] in common]

    def update_common_markers_table(self, common_codes, markers_prev, markers_curr):
        prev_dict = {m['code']: m for m in markers_prev}
        curr_dict = {m['code']: m for m in markers_curr}
        sorted_codes = sorted(common_codes)

        self.table_common.setRowCount(len(sorted_codes))
        for i, code in enumerate(sorted_codes):
            self.table_common.setItem(i, 0, QTableWidgetItem(str(code)))
            if code in prev_dict:
                m = prev_dict[code]
                self.table_common.setItem(i, 1, QTableWidgetItem(f"({m['x']:.1f}, {m['y']:.1f})"))
            if code in curr_dict:
                m = curr_dict[code]
                self.table_common.setItem(i, 2, QTableWidgetItem(f"({m['x']:.1f}, {m['y']:.1f})"))

    def set_connection_state(self, connected):
        self.btn_find.setEnabled(not connected)
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.grp_capture_params.setEnabled(connected)
        self.btn_capture_3d.setEnabled(connected and not self.is_preview_running())
        has_frame = self.current_session.has_pointcloud
        self.btn_add_frame.setEnabled(connected and has_frame and not self.is_preview_running())
        self.btn_test_detect.setEnabled(connected)
        self.chk_realtime_detect.setEnabled(connected)

        if self.is_preview_running():
            self.btn_start_preview.setEnabled(False)
            self.btn_stop_preview.setEnabled(True)
        else:
            self.btn_start_preview.setEnabled(connected)
            self.btn_stop_preview.setEnabled(False)

        if connected:
            self.lbl_status.setText("已连接")
            self.lbl_status.setProperty("status", "connected")
            info = self.camera.device_info
            self.status_bar.showMessage(f"已连接: {info.name} [{self.camera.camera_type}]")
        else:
            self.lbl_status.setText("未连接")
            self.lbl_status.setProperty("status", "disconnected")
            self.lbl_prev_image.setText("无数据")
            self.lbl_prev_image.clear()
            self.lbl_curr_image.setText("请点击连接相机并开始拍照")
            self.lbl_curr_image.clear()
            self.status_bar.showMessage("就绪")
            self.on_clear_stitch_frames()
            self.prev_session.release()
            self.current_session.release()

        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def is_preview_running(self):
        return self.preview_thread is not None and self.preview_thread.isRunning()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def on_find_devices(self):
        devices = self.camera.find_devices()
        if len(devices) == 0:
            self.log("未找到RVC相机设备")
            QMessageBox.information(self, "提示", "未找到相机设备，请检查连接、驱动和电源")
        else:
            self.log(f"发现 {len(devices)} 个设备")
            lines = []
            for i, dev in enumerate(devices):
                ret, info = dev.GetDeviceInfo()
                name = info.name if ret else f"设备{i}"
                sn = info.sn if ret else "Unknown"
                lines.append(f"[{i}] {name} | SN:{sn}")
                self.log(f"  {lines[-1]}")
            QMessageBox.information(self, "发现的设备", "\n".join(lines))

    def on_connect(self):
        self.log("正在连接相机...")
        success, msg = self.camera.connect()
        if success:
            self.log(f"已连接: {msg}")
            self.set_connection_state(True)
            self.on_read_capture_options()
        else:
            self.log(f"连接失败: {msg}")
            QMessageBox.critical(self, "连接失败", msg)

    def on_disconnect(self):
        self.log("正在断开连接...")
        if self.is_preview_running():
            self.on_stop_preview()
        self.camera.disconnect()
        self.set_connection_state(False)
        self.log("已断开连接")

    def on_read_capture_options(self):
        ret, opts = self.camera.get_capture_options()
        if not ret or opts is None:
            self.log("读取相机拍摄参数失败")
            return
        self.spin_exp_2d.setValue(float(opts.exposure_time_2d))
        self.spin_exp_3d.setValue(float(opts.exposure_time_3d))
        self.spin_gain_2d.setValue(int(opts.gain_2d))
        self.spin_gain_3d.setValue(int(opts.gain_3d))
        self.log("已同步相机拍摄参数到界面")

    def on_apply_capture_options(self):
        ret, opts = self.camera.get_capture_options()
        if not ret or opts is None:
            QMessageBox.warning(self, "提示", "无法读取相机当前参数基线")
            return
        opts.exposure_time_2d = int(self.spin_exp_2d.value())
        opts.exposure_time_3d = int(self.spin_exp_3d.value())
        opts.gain_2d = self.spin_gain_2d.value()
        opts.gain_3d = self.spin_gain_3d.value()
        if self.camera.set_capture_options(opts):
            self.log("拍摄参数已应用并保存到相机")
            self.save_settings()
        else:
            self.log("拍摄参数保存到相机失败")
            QMessageBox.warning(self, "提示", "拍摄参数保存到相机失败")

    def on_exp_2d_changed_live(self):
        """2D 曝光变化时，若处于预览状态则防抖后实时写入相机。"""
        if self.is_preview_running() and self.camera.is_connected:
            self._exp2d_debounce_timer.start(200)

    def _apply_exp_2d_live(self):
        ret, opts = self.camera.get_capture_options()
        if not ret or opts is None:
            return
        opts.exposure_time_2d = int(self.spin_exp_2d.value())
        if self.camera.set_capture_options(opts):
            self.log(f"2D 曝光已实时调整为 {opts.exposure_time_2d}ms")

    def on_capture_3d(self):
        # 创建简单的文字提示对话框（无动画）
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
        from PySide6.QtCore import Qt
        
        loading_dialog = QDialog(self)
        loading_dialog.setWindowTitle("3D拍摄")
        loading_dialog.setFixedSize(400, 150)
        loading_dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        loading_dialog.setStyleSheet("""
            QDialog {
                background-color: #2d2d2d;
                border: 3px solid #2196F3;
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
                font-size: 18px;
                font-weight: bold;
            }
        """)
        
        layout = QVBoxLayout(loading_dialog)
        lbl_msg = QLabel("📷 正在拍摄 3D 图像\n请保持相机和物体静止...")
        lbl_msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_msg)
        
        loading_dialog.show()
        QApplication.processEvents()
        
        try:
            self.log("3D拍摄中...")
            
            was_preview = self.is_preview_running()
            if was_preview:
                self.on_stop_preview()

            # 前一帧滚动：释放旧资源，转移当前会话
            if self.current_session.image_np is not None:
                self.prev_session.release()
                self.prev_session = CaptureSession(
                    frame_id=self.current_session.frame_id,
                    image_np=self.current_session.image_np.copy() if self.current_session.image_np is not None else None,
                    markers=self.current_session.markers.copy() if self.current_session.markers else [],
                    pointmap=self.current_session.pointmap,
                    rvc_image=self.current_session.rvc_image,
                )
                # 清空当前会话（资源已转移给 prev_session）
                self.current_session = CaptureSession(frame_id=-1)

                self.update_display(
                    self.lbl_prev_image, self.prev_session.image_np, self.prev_session.markers,
                    info_label=self.lbl_prev_info, reset_zoom=False
                )

            # 执行拍摄
            image_np, pm_clone, img_clone, msg = self.camera.capture_3d()
            
            if image_np is not None:
                markers = self.detector.detect(image_np)
                self.current_session = CaptureSession(
                    frame_id=self.current_session.frame_id + 1,
                    image_np=image_np,
                    markers=markers,
                    pointmap=pm_clone,
                    rvc_image=img_clone,
                )

                common_codes, common_prev, common_curr = self.find_common_markers(
                    self.prev_session.markers, self.current_session.markers
                )
                self.update_display(
                    self.lbl_curr_image, self.current_session.image_np, self.current_session.markers,
                    common_codes, info_label=self.lbl_curr_info, reset_zoom=False
                )
                self.update_common_markers_table(common_codes, common_prev, common_curr)

                self.log(f"3D拍摄成功 | {image_np.shape[1]}x{image_np.shape[0]} | "
                         f"编码圆:{len(markers)} | 共有:{len(common_codes)}")
                self.btn_add_frame.setEnabled(True)
                if len(common_codes) > 0:
                    self.log(f"共有编码: {sorted(common_codes)}")
                if self.prev_session.image_np is not None and len(common_codes) < 3:
                    self.log("⚠️ 共有编码圆少于3个，可能影响拼接精度")
            else:
                self.log(f"拍摄失败: {msg}")
                QMessageBox.critical(self, "拍摄失败", msg)
        except Exception as e:
            self.log(f"拍摄异常: {e}")
            QMessageBox.critical(self, "拍摄异常", str(e))
        finally:
            # 关闭提示对话框
            loading_dialog.close()

    def on_marker_params_changed(self):
        """编码圆参数变化时更新检测器，并进行输入校验。"""
        n = self.spin_n.value()
        r1 = self.spin_r1.value()
        r2 = self.spin_r2.value()
        
        # 输入校验：r2 必须大于 r1
        if r2 <= r1:
            self.log(f"⚠️ 参数错误: r2/r0 ({r2:.3f}) 必须大于 r1/r0 ({r1:.3f})")
            # 禁用拍摄和添加帧按钮，防止使用错误参数
            self.btn_capture_3d.setEnabled(False)
            self.btn_add_frame.setEnabled(False)
            return
        
        # 恢复按钮状态（如果相机已连接）
        if self.camera.is_connected:
            self.btn_capture_3d.setEnabled(not self.is_preview_running())
            has_frame = self.current_session.has_pointcloud
            self.btn_add_frame.setEnabled(has_frame and not self.is_preview_running())
        
        self.detector.set_params(n, r1, r2)
        self.log(f"检测参数: N={n}, r1/r0={r1:.3f}, r2/r0={r2:.3f}")

    def on_test_detect(self):
        if self.current_session.image_np is None:
            QMessageBox.warning(self, "提示", "当前没有图像，请先拍照或预览")
            return

        self.log("=" * 40)
        self.log("【异步参数搜索】启动后台线程...")
        self.btn_test_detect.setEnabled(False)
        self._detection_results = []  # 清空历史结果

        self._detection_worker = DetectionParamSearchWorker(self.detector, self.current_session.image_np.copy(), self)
        self._detection_worker.result_found.connect(self._on_search_result_found)
        self._detection_worker.search_finished.connect(self._on_test_detect_finished)
        self._detection_worker.start()

    def _on_search_result_found(self, n, r1, r2, count, message):
        """收集参数搜索结果。"""
        self._detection_results.append({"n": n, "r1": r1, "r2": r2, "count": count, "msg": message})
        self.log(f"  命中 {message}")

    def _on_test_detect_finished(self, found_any, summary):
        self.btn_test_detect.setEnabled(True)
        if not found_any:
            self.log("⚠️ 未检测到编码圆，建议检查以下项:")
            self.log("  1. N 值是否与实际编码圆匹配")
            self.log("  2. r1/r0 和 r2/r0 比值是否合适")
            self.log("  3. 高分辨率相机建议使用更小的比值")
        self.log(summary)
        self.log("=" * 40)

        # 如果有结果，弹出选择对话框
        if found_any and self._detection_results:
            self._show_search_result_dialog()

    def _show_search_result_dialog(self):
        """显示参数搜索结果列表，支持一键回填。"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem

        dialog = QDialog(self)
        dialog.setWindowTitle("参数搜索结果")
        dialog.setMinimumSize(400, 300)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"找到 {len(self._detection_results)} 组可用参数，选择一组应用:"))

        list_widget = QListWidget()
        # 按检测到的编码圆数量降序排列
        sorted_results = sorted(self._detection_results, key=lambda x: x["count"], reverse=True)
        for i, r in enumerate(sorted_results):
            item_text = f"N={r['n']}, r1={r['r1']}, r2={r['r2']} → {r['count']} 个编码圆"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, r)  # 绑定数据
            list_widget.addItem(item)
            if i == 0:
                list_widget.setCurrentItem(item)  # 默认选中最佳
        layout.addWidget(list_widget)

        btn_lo = QHBoxLayout()
        btn_apply = QPushButton("✅ 应用选中参数")
        btn_apply.setObjectName("successButton")
        btn_apply.setMinimumHeight(32)
        btn_apply.clicked.connect(lambda: self._apply_search_result(list_widget.currentItem(), dialog))
        btn_lo.addWidget(btn_apply)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dialog.reject)
        btn_lo.addWidget(btn_cancel)
        layout.addLayout(btn_lo)

        dialog.exec()

    def _apply_search_result(self, item, dialog):
        """将选中的参数回填到 UI。"""
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return

        n, r1, r2 = data["n"], data["r1"], data["r2"]
        self.spin_n.setValue(n)
        self.spin_r1.setValue(r1)
        self.spin_r2.setValue(r2)
        # on_marker_params_changed 会自动更新检测器
        self.log(f"【参数已应用】N={n}, r1={r1}, r2={r2}")
        dialog.accept()
        QMessageBox.information(self, "应用成功", f"参数已更新:\nN={n}, r1/r0={r1}, r2/r0={r2}")

    def on_start_preview(self):
        self.log("启动实时预览...")
        if self.current_session.image_np is not None and self.prev_session.image_np is None:
            self.prev_session.release()
            self.prev_session = CaptureSession(
                frame_id=self.current_session.frame_id,
                image_np=self.current_session.image_np.copy() if self.current_session.image_np is not None else None,
                markers=self.current_session.markers.copy() if self.current_session.markers else [],
                pointmap=self.current_session.pointmap,
                rvc_image=self.current_session.rvc_image,
            )
            self.current_session = CaptureSession(frame_id=-1)
            self.update_display(
                self.lbl_prev_image, self.prev_session.image_np, self.prev_session.markers,
                info_label=self.lbl_prev_info
            )

        self.current_session = CaptureSession(frame_id=-1)
        self.preview_thread = PreviewThread(self.camera, self.detector)
        self.preview_thread.frame_ready.connect(self.on_preview_frame)
        self.preview_thread.error_occurred.connect(self.on_preview_error)
        self.preview_thread.start()

        self.btn_start_preview.setEnabled(False)
        self.btn_stop_preview.setEnabled(True)
        self.btn_capture_3d.setEnabled(False)
        self.btn_add_frame.setEnabled(False)
        self.log("实时预览运行中 (~25fps)")

    def on_stop_preview(self):
        if self.preview_thread:
            self.log("停止预览...")
            self.preview_thread.stop()
            self.preview_thread = None
        self.btn_start_preview.setEnabled(True)
        self.btn_stop_preview.setEnabled(False)
        self.btn_capture_3d.setEnabled(True)
        if self.current_session.has_pointcloud:
            self.btn_add_frame.setEnabled(True)
        self.log("预览已停止")

    def on_preview_frame(self, image, markers):
        if image is None:
            return
        if self.chk_realtime_detect.isChecked():
            self.current_session.image_np = image.copy()
            self.current_session.markers = markers
            common_codes, _, _ = self.find_common_markers(self.prev_session.markers, self.current_session.markers)
            self.update_display(
                self.lbl_curr_image, self.current_session.image_np, self.current_session.markers,
                common_codes, info_label=self.lbl_curr_info, reset_zoom=False
            )
            if self.prev_session.image_np is not None:
                _, cp, cc = self.find_common_markers(self.prev_session.markers, self.current_session.markers)
                self.update_common_markers_table(common_codes, cp, cc)
        else:
            self.current_session.image_np = image.copy()
            self.current_session.markers = []
            self.update_display(
                self.lbl_curr_image, self.current_session.image_np, [],
                info_label=self.lbl_curr_info, reset_zoom=False
            )

    def on_preview_error(self, error_msg):
        self.log(f"预览错误: {error_msg}")
        self.on_stop_preview()

    def on_add_stitch_frame(self):
        if not self.current_session.has_pointcloud:
            QMessageBox.warning(self, "提示", "请先进行3D拍摄获取点云")
            return
        try:
            # 从 current_session 创建新的拼接会话，转移所有权
            stitch_session = CaptureSession(
                frame_id=len(self.stitch_sessions),
                image_np=self.current_session.image_np.copy() if self.current_session.image_np is not None else None,
                markers=self.current_session.markers.copy() if self.current_session.markers else [],
                pointmap=self.current_session.pointmap,
                rvc_image=self.current_session.rvc_image,
            )
            # 清空当前会话的 RVC 资源引用（已转移）
            self.current_session.pointmap = None
            self.current_session.rvc_image = None
            self.current_session.image_np = None
            self.current_session.markers = []

            self.stitch_sessions.append(stitch_session)

            row = self.table_frames.rowCount()
            self.table_frames.insertRow(row)
            self._update_frame_table_row(row, stitch_session)

            self.lbl_frame_count.setText(f"已采集: {len(self.stitch_sessions)} 帧")
            self.btn_clear_frames.setEnabled(True)
            self.btn_stitch.setEnabled(len(self.stitch_sessions) >= 2)
            self.btn_add_frame.setEnabled(False)

            self.log(f"添加帧 #{stitch_session.frame_id}: {stitch_session.marker_count} 个编码圆")
            if stitch_session.marker_count < 3:
                QMessageBox.warning(self, "警告", f"当前帧仅 {stitch_session.marker_count} 个编码圆，建议至少3个以保证精度")
        except Exception as e:
            self.log(f"添加帧失败: {e}")
            QMessageBox.critical(self, "错误", f"添加帧失败: {e}")

    def _update_frame_table_row(self, row: int, session: CaptureSession):
        """更新拼接帧列表中某一行的显示。"""
        self.table_frames.setItem(row, 0, QTableWidgetItem(f"Frame_{session.frame_id}"))
        self.table_frames.setItem(row, 1, QTableWidgetItem(str(session.marker_count)))
        self.table_frames.setItem(row, 2, QTableWidgetItem("已添加"))

    def on_clear_stitch_frames(self):
        for session in self.stitch_sessions:
            # 安全释放 RVC 对象
            if session.pointmap is not None:
                try:
                    RVC.PointMap.Destroy(session.pointmap)
                except:
                    pass
                session.pointmap = None
            if session.rvc_image is not None:
                try:
                    RVC.Image.Destroy(session.rvc_image)
                except:
                    pass
                session.rvc_image = None
            session.release()
        self.stitch_sessions.clear()
        self.merged_o3d_pcd = None
        self.merged_points = None
        self.merged_colors = None
        self._stitch_poses.clear()  # 清空位姿数据

        self.table_frames.setRowCount(0)
        self.lbl_frame_count.setText("已采集: 0 帧")
        self.lbl_stitch_result.setText("状态: 未开始")
        self.btn_clear_frames.setEnabled(False)
        self.btn_stitch.setEnabled(False)
        self.btn_save_stitched.setEnabled(False)
        self.btn_save_project.setEnabled(False)
        self.btn_export_poses.setEnabled(False)
        self.btn_preview_pc.setEnabled(False)
        self.lbl_pointcloud_info.setText("点数: - | 帧数: -")
        self.log("已清空所有拼接帧")

    # ------------------------------------------------------------------
    # 拼接帧列表右键菜单：删除 / 上移 / 下移
    # ------------------------------------------------------------------
    def on_frame_table_context_menu(self, position):
        row = self.table_frames.rowAt(position.y())
        if row < 0 or row >= len(self.stitch_sessions):
            return

        menu = QMenu(self)
        act_remove = menu.addAction("🗑️ 删除此帧")
        act_move_up = menu.addAction("⬆️ 上移")
        act_move_down = menu.addAction("⬇️ 下移")

        # 边界禁用
        act_move_up.setEnabled(row > 0)
        act_move_down.setEnabled(row < len(self.stitch_sessions) - 1)

        action = menu.exec(self.table_frames.viewport().mapToGlobal(position))
        if action == act_remove:
            self.on_remove_stitch_frame(row)
        elif action == act_move_up:
            self.on_move_stitch_frame_up(row)
        elif action == act_move_down:
            self.on_move_stitch_frame_down(row)

    def on_remove_stitch_frame(self, row: int):
        if row < 0 or row >= len(self.stitch_sessions):
            return
        session = self.stitch_sessions.pop(row)
        session.release()
        self._refresh_frame_table()
        self.lbl_frame_count.setText(f"已采集: {len(self.stitch_sessions)} 帧")
        self.btn_stitch.setEnabled(len(self.stitch_sessions) >= 2)
        self.btn_clear_frames.setEnabled(len(self.stitch_sessions) > 0)
        if len(self.stitch_sessions) == 0:
            self.btn_save_stitched.setEnabled(False)
            self.btn_preview_pc.setEnabled(False)
        self.log(f"已删除帧 Frame_{session.frame_id}")

    def on_move_stitch_frame_up(self, row: int):
        if row <= 0 or row >= len(self.stitch_sessions):
            return
        self.stitch_sessions[row - 1], self.stitch_sessions[row] = \
            self.stitch_sessions[row], self.stitch_sessions[row - 1]
        self._refresh_frame_table()
        self.log(f"帧 Frame_{self.stitch_sessions[row - 1].frame_id} 已上移")

    def on_move_stitch_frame_down(self, row: int):
        if row < 0 or row >= len(self.stitch_sessions) - 1:
            return
        self.stitch_sessions[row + 1], self.stitch_sessions[row] = \
            self.stitch_sessions[row], self.stitch_sessions[row + 1]
        self._refresh_frame_table()
        self.log(f"帧 Frame_{self.stitch_sessions[row + 1].frame_id} 已下移")

    def _refresh_frame_table(self):
        """根据 stitch_sessions 完全重绘表格。"""
        self.table_frames.setRowCount(len(self.stitch_sessions))
        for i, session in enumerate(self.stitch_sessions):
            self._update_frame_table_row(i, session)

    def on_stitch_pointclouds(self):
        if len(self.stitch_sessions) < 2:
            QMessageBox.warning(self, "提示", "至少需要2帧才能进行拼接")
            return

        # 检查是否有从工程加载的点云（非实时捕获的）
        has_loaded_only = any(
            getattr(s, 'point_cloud_loaded', False) and s.pointmap is None 
            for s in self.stitch_sessions
        )
        if has_loaded_only:
            QMessageBox.warning(self, "提示", 
                "当前帧数据是从工程文件加载的PLY点云，\n"
                "缺少RVC SDK需要的原始数据，无法重新拼接。\n"
                "如需拼接，请重新拍摄。")
            return

        n_frames = len(self.stitch_sessions)
        
        # 创建遮罩层 loading - 更大更醒目
        loading = OverlayLoadingWidget(
            self,
            message=f"🔄 准备拼接 {n_frames} 帧点云...",
            show_progress=True
        )
        loading.set_progress(0)
        loading.show()
        loading.raise_()
        QApplication.processEvents()
        
        try:
            self.log("=" * 40)
            self.log("开始彩色点云拼接...")
            self.lbl_stitch_result.setText("状态: 进行中...")

            marker_type = RVC.CodedCircleMarkerType()
            marker_type.N = self.spin_n.value()
            marker_type.r1_to_r0_ratio = self.spin_r1.value()
            marker_type.r2_to_r0_ratio = self.spin_r2.value()

            coord = "last" if self.combo_stitch_coord.currentIndex() == 1 else "first"
            self.log(f"编码圆参数: N={marker_type.N}, r1/r0={marker_type.r1_to_r0_ratio:.3f}, r2/r0={marker_type.r2_to_r0_ratio:.3f}")

            frames = [s.pointmap for s in self.stitch_sessions]
            images = [s.rvc_image for s in self.stitch_sessions]
            
            # 阶段1: 计算位姿 (0-40%)
            loading.set_message("🔍 正在计算帧间位姿...")
            loading.set_detail(f"分析 {n_frames} 帧的编码圆匹配关系")
            loading.set_progress(10)
            QApplication.processEvents()
            
            success, msg, poses = stitch_chain(frames, images, marker_type, coord)
            
            if not success:
                loading.error(f"❌ 拼接失败")
                self.log(msg)
                QMessageBox.critical(self, "拼接失败", msg)
                self.lbl_stitch_result.setText("状态: 失败")
                return

            self.log(msg)
            
            # 阶段2: 合并点云 (40-80%)
            loading.set_progress(45)
            loading.set_message("🎨 正在生成彩色点云...")
            loading.set_detail("合并多帧点云数据...")
            QApplication.processEvents()
            
            self.merged_o3d_pcd = build_merged_pointcloud(frames, images)
            
            loading.set_progress(70)
            loading.set_detail("提取点云坐标和颜色...")
            QApplication.processEvents()
            
            self.merged_points, self.merged_colors = extract_numpy_from_pcd(self.merged_o3d_pcd)

            # 保存位姿并启用导出按钮
            self._stitch_poses = poses
            self.btn_export_poses.setEnabled(True)
            self.btn_save_project.setEnabled(True)

            total = len(self.merged_points) if self.merged_points is not None else 0
            
            # 阶段3: 完成 (80-100%)
            loading.set_progress(90)
            loading.set_message("✅ 正在完成...")
            loading.set_detail(f"总点数: {total:,}")
            QApplication.processEvents()
            
            # 短暂显示完成状态
            loading.set_progress(100)
            loading.finish(f"✓ 拼接完成！共 {total:,} 点")
            
            self.lbl_pointcloud_info.setText(f"点数: {total:,} | 帧数: {n_frames}")
            self.lbl_stitch_result.setText(f"状态: 成功 ({n_frames} 帧)")
            self.btn_save_stitched.setEnabled(True)
            self.btn_preview_pc.setEnabled(True)
            self.log("彩色点云拼接完成!")
            self.log("=" * 40)
            QMessageBox.information(self, "拼接成功", f"成功拼接 {n_frames} 帧\n总点数: {total:,}")
        except Exception as e:
            loading.error(f"❌ 拼接异常: {str(e)}")
            self.log(f"拼接异常: {e}")
            self.lbl_stitch_result.setText("状态: 错误")
            QMessageBox.critical(self, "拼接失败", str(e))
        finally:
            # 确保 loading 关闭（如果还没关闭的话）
            if loading and loading.isVisible():
                loading.finish()

    def on_save_stitched_pointcloud(self):
        if len(self.stitch_sessions) == 0:
            return
        save_path = QFileDialog.getExistingDirectory(self, "选择保存路径", "Data")
        if not save_path:
            return
        os.makedirs(save_path, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        folder = os.path.join(save_path, f"Stitched_{timestamp}")
        os.makedirs(folder, exist_ok=True)
        self.log("保存拼接结果...")

        try:
            n = len(self.stitch_sessions)
            for i in range(n):
                session = self.stitch_sessions[i]
                filepath = os.path.join(folder, f"frame_{i}_stitched.ply")
                ret = session.pointmap.SaveWithImage(
                    filepath, session.rvc_image,
                    RVC.PointMapUnitEnum.Millimeter, True
                )
                if ret:
                    self.log(f"  已保存: frame_{i}_stitched.ply")
                else:
                    self.log(f"  保存失败: frame_{i}_stitched.ply")

            # 保存合并点云（二进制，快且小）
            if self.merged_points is not None and len(self.merged_points) > 0:
                merged_path = os.path.join(folder, "merged_stitched.ply")
                save_binary_ply(merged_path, self.merged_points, self.merged_colors)
                self.log(f"  已保存合并点云: merged_stitched.ply (binary)")

            self.log(f"已保存到: {folder}")
            self.status_bar.showMessage(f"已保存: {folder}", 5000)
            QMessageBox.information(self, "保存成功", f"结果已保存到:\n{folder}")
        except Exception as e:
            self.log(f"保存失败: {e}")
            QMessageBox.critical(self, "保存失败", str(e))

    def on_preview_pointcloud(self):
        if not HAS_OPEN3D:
            QMessageBox.critical(self, "错误", "未安装Open3D，请执行: pip install open3d")
            return
        if self.merged_o3d_pcd is None or len(self.merged_o3d_pcd.points) == 0:
            QMessageBox.warning(self, "提示", "没有可预览的点云数据，请先执行拼接")
            return

        n_points = len(self.merged_o3d_pcd.points)
        self.log(f"启动Open3D预览 ({n_points:,} 点)...")

        # 使用独立进程预览，不阻塞 GUI
        success = self._preview_process.show(
            self.merged_o3d_pcd,
            window_title=f"拼接点云预览 - {n_points:,} 点",
            width=1280,
            height=720
        )
        if success:
            self.log("Open3D 预览窗口已在独立进程中启动")
        else:
            self.log("Open3D 预览启动失败")
            QMessageBox.critical(self, "错误", "Open3D 预览启动失败")

    def on_save_project(self):
        """保存完整工程文件。"""
        if len(self.stitch_sessions) == 0:
            QMessageBox.warning(self, "提示", "没有可保存的拼接帧")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存工程", f"StitchProject_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ccproj",
            "CCProj Files (*.ccproj);;All Files (*)")
        if not file_path:
            return
        
        pm = ProjectManager(file_path)
        
        marker_params = {"N": self.spin_n.value(), "r1": self.spin_r1.value(), "r2": self.spin_r2.value()}
        capture_params = {
            "exp_2d": self.spin_exp_2d.value(),
            "exp_3d": self.spin_exp_3d.value(),
            "gain_2d": self.spin_gain_2d.value(),
            "gain_3d": self.spin_gain_3d.value()
        }
        coord_mode = "first" if self.combo_stitch_coord.currentIndex() == 0 else "last"
        
        if pm.save_project(marker_params, capture_params, coord_mode, 
                           self.stitch_sessions, self._stitch_poses, self.merged_o3d_pcd):
            self.log(f"工程已保存: {file_path}")
            QMessageBox.information(self, "保存成功", f"工程已保存到:\n{file_path}")
        else:
            QMessageBox.critical(self, "保存失败", "保存工程时发生错误")

    def on_load_project(self):
        """加载工程文件。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载工程", "", 
            "CCProj Files (*.ccproj);;All Files (*)")
        if not file_path:
            return
        
        pm = ProjectManager(file_path)
        data = pm.load_project()
        
        if not data:
            QMessageBox.critical(self, "加载失败", "无法读取工程文件")
            return
        
        # 清空现有数据
        self.on_clear_stitch_frames()
        
        # 恢复参数
        mp = data.get("marker_params", {})
        self.spin_n.setValue(mp.get("N", 8))
        self.spin_r1.setValue(mp.get("r1", 2.0))
        self.spin_r2.setValue(mp.get("r2", 3.0))
        
        cp = data.get("capture_params", {})
        self.spin_exp_2d.setValue(cp.get("exp_2d", 20.0))
        self.spin_exp_3d.setValue(cp.get("exp_3d", 20.0))
        self.spin_gain_2d.setValue(cp.get("gain_2d", 0))
        self.spin_gain_3d.setValue(cp.get("gain_3d", 0))
        
        self.combo_stitch_coord.setCurrentIndex(0 if data.get("coord_mode") == "first" else 1)
        
        # 加载帧数据 - 从文件重建 RVC 对象
        load_errors = []
        
        for i, frame in enumerate(data.get("frames", [])):
            session = CaptureSession(
                frame_id=frame.get("frame_id", i),
                markers=frame.get("markers", [])
            )
            
            img_file = frame.get("image_file")
            ply_file = frame.get("pointcloud_file")
            img_size = frame.get("image_size", {})
            unit_str = frame.get("pointcloud_unit", "millimeter")
            
            # 确定单位
            unit = RVC.PointMapUnitEnum.Millimeter if unit_str == "millimeter" else RVC.PointMapUnitEnum.Meter
            
            # 加载图像 (RVC.Image)
            if img_file:
                img_path = pm.data_dir / img_file
                if img_path.exists():
                    try:
                        session.rvc_image = RVC.Image.CreateFromFile(str(img_path))
                        if session.rvc_image and session.rvc_image.IsValid():
                            # 获取图像尺寸用于加载点云
                            if not img_size:
                                img_size = {"width": session.rvc_image.GetSize().width, 
                                           "height": session.rvc_image.GetSize().height}
                            self.log(f"  加载图像 {i}: {img_path.name}")
                        else:
                            load_errors.append(f"帧{i}: 图像无效")
                    except Exception as e:
                        load_errors.append(f"帧{i}: 图像加载失败 - {e}")
            
            # 加载点云 (RVC.PointMap)
            if ply_file and img_size:
                ply_path = pm.data_dir / ply_file
                if ply_path.exists():
                    try:
                        # 使用 Size 结构体 (PyRVC 中 ImageSize 可能不存在)
                        try:
                            img_sz = RVC.Size(img_size.get("width", 1920), img_size.get("height", 1200))
                        except AttributeError:
                            # 如果 Size 也不存在，直接使用 tuple
                            img_sz = (img_size.get("width", 1920), img_size.get("height", 1200))
                        session.pointmap = RVC.PointMap.CreateFromFile(str(ply_path), img_sz, unit)
                        if session.pointmap and session.pointmap.IsValid():
                            session.point_cloud_loaded = True  # 标记为从文件加载
                            self.log(f"  加载点云 {i}: {ply_path.name}")
                        else:
                            load_errors.append(f"帧{i}: 点云无效")
                    except Exception as e:
                        load_errors.append(f"帧{i}: 点云加载失败 - {e}")
                else:
                    load_errors.append(f"帧{i}: 点云文件不存在")
            else:
                load_errors.append(f"帧{i}: 缺少图像尺寸信息，无法加载点云")
            
            # 尝试加载图像到 numpy (用于显示)
            if session.rvc_image and session.rvc_image.IsValid():
                try:
                    # 复用之前定义的 img_file 变量加载图像
                    if img_file:
                        img_path = pm.data_dir / img_file
                        session.image_np = cv2.imread(str(img_path))
                except Exception as e:
                    self.log(f"  警告: 帧{i} 图像转换失败 - {e}")
            
            self.stitch_sessions.append(session)
        
        self._refresh_frame_table()
        self.lbl_frame_count.setText(f"已采集: {len(self.stitch_sessions)} 帧")
        
        # 启用拼接按钮（如果所有帧都有有效的 pointmap 和 image）
        all_valid = all(s.pointmap is not None and s.pointmap.IsValid() and 
                       s.rvc_image is not None and s.rvc_image.IsValid() 
                       for s in self.stitch_sessions)
        
        self.btn_stitch.setEnabled(len(self.stitch_sessions) >= 2 and all_valid)
        self.btn_clear_frames.setEnabled(len(self.stitch_sessions) > 0)
        
        # 显示加载结果
        if load_errors:
            error_msg = "\n".join(load_errors[:5])  # 最多显示5条
            if len(load_errors) > 5:
                error_msg += f"\n... 还有 {len(load_errors) - 5} 个错误"
            QMessageBox.warning(self, "加载警告", 
                f"工程加载完成，但存在以下问题:\n{error_msg}\n\n"
                f"有效的帧: {len(self.stitch_sessions) - len(load_errors)}/{len(self.stitch_sessions)}")
        else:
            self.log(f"工程加载成功: {len(self.stitch_sessions)} 帧 (全部有效，支持离线拼接)")
            QMessageBox.information(self, "加载成功", 
                f"已加载工程: {file_path}\n"
                f"共 {len(self.stitch_sessions)} 帧\n"
                f"所有数据完整，可以执行离线拼接")

    def on_export_poses(self):
        """导出位姿矩阵到JSON。"""
        if not self._stitch_poses:
            QMessageBox.warning(self, "提示", "没有可导出的位姿数据")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出位姿矩阵", f"poses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;All Files (*)")
        if not file_path:
            return
        
        import json
        poses_data = []
        for i, (R, t) in enumerate(self._stitch_poses):
            poses_data.append({
                "frame_id": i,
                "R": R.tolist(),
                "t": t.tolist()
            })
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                "exported_at": datetime.now().isoformat(),
                "coord_mode": "first" if self.combo_stitch_coord.currentIndex() == 0 else "last",
                "poses": poses_data
            }, f, indent=2, ensure_ascii=False)
        
        self.log(f"位姿矩阵已导出: {file_path}")
        QMessageBox.information(self, "导出成功", f"位姿矩阵已导出到:\n{file_path}")

    def closeEvent(self, event):
        try:
            self.save_settings()
            if self.is_preview_running():
                self.on_stop_preview()
            self._preview_process.stop()  # 停止 Open3D 预览进程
            if self._detection_worker and self._detection_worker.isRunning():
                self._detection_worker.cancel()
            self.on_clear_stitch_frames()
            self.prev_session.release()
            self.current_session.release()
            self.camera.shutdown()
            event.accept()
        except Exception as e:
            logger.critical(f"关闭异常: {e}")
            reply = QMessageBox.question(
                self, "关闭异常",
                f"程序关闭时发生错误:\n{e}\n\n是否强制退出?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                event.accept()
            else:
                event.ignore()

