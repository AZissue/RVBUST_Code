"""
手眼标定数据收集助手 - 主窗口
负责组装整体 UI 布局，连接各组件信号与槽，协调工作流。
"""

import os
import sys

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QShortcut, QMessageBox, QFileDialog,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox,
    QListWidget, QLabel, QPushButton, QGroupBox,
    QSizePolicy,
)

import resources as res
from widgets.top_nav_bar import TopNavBar
from widgets.mode_selector import ModeSelector
from widgets.image_view import Image2DView
from widgets.point_cloud_view import PointCloud3DView
from widgets.data_input_area import DataInputArea
from widgets.action_buttons import ActionButtons
from widgets.side_panel import SidePanel
from widgets.toast import ToastOverlay

from core.camera import CameraManager
from core.data_manager import DataManager
from core.marker_detector import MarkerDetector
from core.logger import LogManager
from core.config import SettingsManager


class MainWindow(QMainWindow):
    """手眼标定数据收集助手主窗口"""

    def __init__(self):
        super().__init__()
        # ── 加载持久化配置 ──
        self._settings = SettingsManager().load()

        # 设置窗口标题和默认尺寸
        self.setWindowTitle("手眼标定数据收集助手 V1.0")
        geo = self._settings.get_window_geometry()
        if geo["x"] < 0 or geo["y"] < 0:
            # 首次运行（无保存位置）：居中显示，大小为屏幕的 3/4
            screen = QApplication.primaryScreen().geometry()
            w = int(screen.width() * 0.75)
            h = int(screen.height() * 0.75)
            x = (screen.width() - w) // 2
            y = (screen.height() - h) // 2
            self.setGeometry(x, y, w, h)
        else:
            self.setGeometry(geo["x"], geo["y"], geo["width"], geo["height"])
        self.setMinimumSize(1200, 800)  # 最小尺寸保证基本可用

        # ── 初始化核心管理器 ──
        # 相机管理器：负责 RVC X2 相机的连接、预览和采集
        self._camera = CameraManager(self)
        # 数据管理器：负责采集记录的状态管理和文件导出
        self._data = DataManager(self)
        # 日志管理器：记录操作日志并通过信号通知 UI
        self._logger = LogManager(self)
        # 标记物检测器：封装 HandEyeSDK 和 PyRVC 的标记物检测功能
        self._detector = MarkerDetector()

        # ── 保存路径配置 ──
        # 从持久化配置中读取上次的保存路径，无则默认项目 data/ 目录
        self._save_base_dir = self._settings.get_save_base_dir()

        # ── 当前模式状态 ──
        # 从持久化配置恢复上次的模式
        self._eye_in_hand = self._settings.get_eye_in_hand()
        self._marker_type = self._settings.get_marker_type()

        # ── 临时采集数据（拍照后暂存，供识别和保存使用）──
        self._captured_png = None      # 最近一次拍照的 PNG 路径
        self._captured_ply = None      # 最近一次拍照的 PLY 路径
        self._captured_pm_np = None    # 最近一次拍照的点云 numpy 数组
        self._captured_image = None    # 最近一次拍照的 2D 图像 numpy 数组

        # 构建界面、连接信号、注册快捷键
        self._build_ui()
        self._wire_signals()
        self._register_shortcuts()

        # 将 UI 模式选择器同步到从配置加载的模式状态
        self._mode_selector.set_mode(self._eye_in_hand, self._marker_type)

        # 初始化卡片显隐状态（默认：眼在手上 + 标记物标定）
        self._data_input.update_visibility(self._eye_in_hand, self._marker_type)

        # 创建新的采集会话
        self._reset_session()

    # ═══════════════════════════════════════════════════════
    # 界面构建
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        """构建完整的 UI 布局树"""
        central = QWidget()
        self.setCentralWidget(central)

        # 根布局：垂直方向，从上到下排列所有区域
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 16, 0, 16)
        root.setSpacing(8)

        # ── 顶部导航栏：标题 + 进度条 + 设置/帮助按钮 ──
        self._top_nav = TopNavBar()
        self._top_nav.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._top_nav)

        # ── 模式选择区：标定模式 + 标定类型切换 ──
        self._mode_selector = ModeSelector()
        self._mode_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._mode_selector)

        # ── 中间区域：可视化窗口（左）+ 辅助面板（右）──
        # 使用 QSplitter 支持拖拽调整左右比例
        middle_splitter = QSplitter(Qt.Horizontal)
        middle_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 左侧：2D/3D 可视化 + 数据卡片 + 操作按钮
        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)
        viz_layout.setContentsMargins(24, 0, 0, 0)
        viz_layout.setSpacing(8)

        # 2D 和 3D 可视化窗口水平并排
        views_row = QWidget()
        views_layout = QHBoxLayout(views_row)
        views_layout.setContentsMargins(0, 0, 0, 0)
        views_layout.setSpacing(16)

        self._view_2d = Image2DView()
        self._view_2d.setMinimumSize(400, 300)
        views_layout.addWidget(self._view_2d, 1)

        self._view_3d = PointCloud3DView()
        self._view_3d.setMinimumSize(400, 300)
        views_layout.addWidget(self._view_3d, 1)

        viz_layout.addWidget(views_row, 1)  # stretch=1，占据剩余垂直空间

        # 数据输入卡片区
        self._data_input = DataInputArea()
        self._data_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        viz_layout.addWidget(self._data_input)

        # 操作按钮区
        self._action_buttons = ActionButtons()
        self._action_buttons.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        viz_layout.addWidget(self._action_buttons)

        middle_splitter.addWidget(viz_container)

        # 右侧：辅助面板（提示 + 注意事项）
        self._side_panel = SidePanel()
        self._side_panel.setMinimumWidth(280)
        middle_splitter.addWidget(self._side_panel)

        middle_splitter.setSizes([1200, 360])
        root.addWidget(middle_splitter, 1)  # stretch=1，占据剩余垂直空间

        # ── Toast 浮动通知 ──
        self._toast = ToastOverlay(self)

    # ═══════════════════════════════════════════════════════
    # 信号连接
    # ═══════════════════════════════════════════════════════

    def _wire_signals(self):
        """连接所有 Qt 信号与槽"""

        # 模式选择器 → 更新卡片显隐 + 侧边栏提示
        self._mode_selector.mode_changed.connect(self._on_mode_changed)

        # 相机预览帧 → 2D 视图实时更新
        self._camera.preview_frame_ready.connect(self._view_2d.update_frame)
        # 相机采集完成 → 显示 3D 点云 + 运行标记物检测
        self._camera.capture_complete.connect(self._on_capture_done)
        # 相机错误 → 日志 + Toast 提示
        self._camera.camera_error.connect(self._on_camera_error)
        # 相机连接/断开状态
        self._camera.camera_connected.connect(self._on_camera_connected)
        self._camera.camera_disconnected.connect(self._on_camera_disconnected)

        # 操作按钮 → 对应处理方法
        self._action_buttons.load_test_clicked.connect(self._on_load_test)
        self._action_buttons.capture_clicked.connect(self._on_capture)
        self._action_buttons.detect_clicked.connect(self._on_detect)
        self._action_buttons.save_clicked.connect(self._on_save)
        self._action_buttons.undo_clicked.connect(self._on_undo)

        # 数据输入卡片文字变化 → 更新数据管理器中的对应字段
        self._data_input.card1.value_changed.connect(
            lambda v: self._on_card_changed("camera_target_xyz", v))
        self._data_input.card2.value_changed.connect(
            lambda v: self._on_card_changed("robot_capture_pose", v))
        self._data_input.card3.value_changed.connect(
            lambda v: self._on_card_changed("robot_target_xyz", v))

        # 数据管理器进度变化 → 更新顶栏进度
        self._data.progress_updated.connect(self._top_nav.update_progress)
        # 数据管理器数据变化 → 更新文件预览 + 按钮状态
        self._data.data_changed.connect(self._update_file_preview)
        self._data.data_changed.connect(self._update_button_states)

        # 日志管理器 → 侧边栏日志显示
        # 顶栏设置/帮助/连接/断开按钮
        self._top_nav.settings_clicked.connect(self._show_settings_dialog)
        self._top_nav.help_clicked.connect(self._show_help_dialog)
        self._top_nav.connect_camera_clicked.connect(self._on_connect_camera)
        self._top_nav.disconnect_camera_clicked.connect(self._on_disconnect_camera)

    def _register_shortcuts(self):
        """注册全局键盘快捷键"""
        QShortcut(QKeySequence("Ctrl+S"), self, self._on_save)
        QShortcut(QKeySequence("Ctrl+Z"), self, self._on_undo)
        QShortcut(QKeySequence("F5"), self, self._on_refresh)
        QShortcut(QKeySequence("F11"), self, self._on_fullscreen)

    # ═══════════════════════════════════════════════════════
    # 模式切换
    # ═══════════════════════════════════════════════════════

    def _on_mode_changed(self, eye_in_hand, marker_type):
        """
        处理标定模式切换。
        切换标定类型（标记物↔戳点）时会清空已有数据。
        仅切换眼在手/眼在手外时不会清空数据。
        """
        old_eye, old_marker = self._eye_in_hand, self._marker_type
        self._eye_in_hand = eye_in_hand
        self._marker_type = marker_type

        # 根据当前模式更新数据输入卡片的显示/隐藏
        self._data_input.update_visibility(eye_in_hand, marker_type)

        # 更新右侧操作提示
        tips = self._get_tips_text(eye_in_hand, marker_type)
        self._side_panel.set_tip(tips)

        # 更新文件预览
        self._update_file_preview()

        # 仅当标定类型改变时（标记物↔戳点），弹出确认对话框
        if old_marker != marker_type:
            reply = QMessageBox.question(
                self, "切换标定类型",
                "切换标定类型将清空当前已采集的数据，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._reset_session()
            else:
                # 用户取消，恢复之前的选择
                self._mode_selector.blockSignals(True)
                self._mode_selector.set_mode(old_eye, old_marker)
                self._mode_selector.blockSignals(False)
                return

        # 记录模式切换日志
        self._logger.info(f"模式切换: {'眼在手上' if eye_in_hand else '眼在手外'} | "
                         f"{'标记物标定' if marker_type else '戳点标定'}")

    def _get_tips_text(self, eye_in_hand, marker_type):
        """根据当前模式返回操作提示文字"""
        if marker_type:
            return ("标记物固定不动 → 移动机器人到目标位姿 → "
                    "确认拍照质量 → 输入机器人位姿 → 点击保存")
        elif eye_in_hand:
            return ("目标物固定不动 → 移动机器人到拍照位姿 → "
                    "拍照识别目标点 → TCP戳点记录坐标 → 输入机器人位姿 → 点击保存")
        else:
            return ("目标物随机器人移动到位 → 拍照识别目标点 → "
                    "TCP戳点记录坐标 → 点击保存")

    def _reset_session(self):
        """重置采集会话：清空所有记录，创建新的保存目录"""
        self._data.new_session(self._save_base_dir, self._eye_in_hand, self._marker_type)
        self._top_nav.update_progress(0)
        # 清空所有输入卡片
        for card in [self._data_input.card1, self._data_input.card2, self._data_input.card3]:
            card.set_value("")
            card.set_status("empty")
        self._view_2d.clear()
        self._view_3d.clear()
        # 清空暂存的采集数据
        self._captured_png = None
        self._captured_ply = None
        self._captured_pm_np = None
        self._captured_image = None
        self._update_button_states()

    # ═══════════════════════════════════════════════════════
    # 相机连接管理
    # ═══════════════════════════════════════════════════════

    def _on_connect_camera(self):
        """
        连接相机按钮回调。
        弹出设备选择对话框，列出所有搜索到的相机及其型号、序列号、状态等信息。
        用户确认后连接所选设备。
        """
        try:
            import PyRVC as RVC
            RVC.SystemInit()
            ret, devices = RVC.SystemListDevices(RVC.SystemListDeviceTypeEnum.All)

            if len(devices) == 0:
                QMessageBox.warning(self, "未找到相机", "未检测到任何相机设备，请检查连接。")
                RVC.SystemShutdown()
                return

            # 始终弹出设备选择对话框（即使只有一台设备）
            dlg = QDialog(self)
            dlg.setWindowTitle("选择相机设备")
            dlg.resize(550, 400)
            dlg_layout = QVBoxLayout(dlg)

            dlg_layout.addWidget(QLabel(
                f"搜索到 {len(devices)} 台相机设备，请选择要连接的设备："
            ))

            # 设备列表，每行显示丰富的设备信息
            list_widget = QListWidget()
            list_widget.setMinimumHeight(200)
            for i, dev in enumerate(devices):
                ok, info = dev.GetDeviceInfo()
                if ok:
                    # 显示型号、序列号、IP 地址、相机ID支持
                    extra = "Extra彩色" if info.support_extra else "仅Left"
                    label = f"[{i}] {info.name}  |  SN: {info.sn}  |  {extra}"
                else:
                    label = f"[{i}] 未知设备（无法获取设备信息）"
                list_widget.addItem(label)
            list_widget.setCurrentRow(0)
            dlg_layout.addWidget(list_widget)

            # 确定/取消按钮
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            dlg_layout.addWidget(btns)

            if dlg.exec_() != QDialog.Accepted:
                RVC.SystemShutdown()
                return

            idx = list_widget.currentRow()
            if idx < 0 or idx >= len(devices):
                RVC.SystemShutdown()
                return
            selected_device = devices[idx]

            # 如果已连接，先断开旧连接
            if self._camera.is_connected():
                self._camera.stop_preview()
                self._camera.shutdown()

            # 连接选中的设备
            success = self._camera.init_with_device(selected_device)
            if success:
                self._camera.start_preview()
            else:
                self._side_panel.set_tip("相机连接失败，请检查设备后重试", is_error=True)

        except Exception as e:
            self._logger.error(f"相机连接异常: {e}")
            self._side_panel.set_tip(f"相机连接失败: {e}", is_error=True)

    def _on_disconnect_camera(self):
        """
        断开相机按钮回调。
        停止预览流、关闭相机、释放 RVC 系统资源。
        """
        if not self._camera.is_connected():
            return
        reply = QMessageBox.question(
            self, "断开相机",
            "确定要断开当前相机的连接吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._camera.stop_preview()
            self._camera.shutdown()
            self._view_2d.clear()
            self._view_3d.clear()
            self._logger.info("用户手动断开相机连接")

    def _on_camera_connected(self):
        """相机连接成功回调"""
        name = self._camera.get_device_name()
        self._logger.success(f"相机已连接: {name}")
        self._side_panel.set_tip(self._get_tips_text(self._eye_in_hand, self._marker_type))
        self._top_nav.set_camera_status(True, name)

    def _on_camera_disconnected(self):
        """相机断开回调"""
        self._logger.info("相机已断开")
        self._view_2d.clear()
        self._top_nav.set_camera_status(False, "")

    def _on_camera_error(self, msg):
        """相机错误回调"""
        self._logger.error(msg)
        self._toast.show_message(msg, "error")

    # ═══════════════════════════════════════════════════════
    # 图像采集完成处理
    # ═══════════════════════════════════════════════════════

    def _on_capture_done(self, png_path, ply_path, pm_np):
        """
        相机完整采集（3D结构光扫描）完成后的回调。
        暂存采集数据并更新 2D/3D 视图显示。
        """
        self._logger.success("拍照采集完成")

        # 暂存采集结果
        self._captured_png = png_path
        self._captured_ply = ply_path
        self._captured_pm_np = pm_np

        # 读取 2D 图像用于后续识别叠加
        if png_path and os.path.exists(png_path):
            img = cv2.imread(png_path)
            if img is not None:
                self._captured_image = img
                self._view_2d.update_frame(img)

        # 更新 3D 点云视图
        if pm_np is not None and len(pm_np) > 0:
            self._view_3d.update_point_cloud(pm_np)
        else:
            self._logger.warning("3D 点云数据为空，无法更新预览")

        self._update_button_states()

    # ═══════════════════════════════════════════════════════
    # 拍照 / 识别 / 保存 / 清除上一组
    # ═══════════════════════════════════════════════════════

    def _on_load_test(self):
        """
        加载测试数据（临时功能）：从 test_data/ 目录加载 PNG+PLY，
        模拟拍照完成后的状态，用于离线测试识别和保存流程。
        """
        test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data")
        png_path = os.path.join(test_dir, "0.png")
        ply_path = os.path.join(test_dir, "0.ply")

        if not os.path.exists(png_path) or not os.path.exists(ply_path):
            self._toast.show_message("测试数据不存在，请检查 test_data/ 目录", "error")
            return

        # 加载 2D 图像
        img = cv2.imread(png_path)
        if img is None:
            self._toast.show_message("无法读取测试图像", "error")
            return
        self._view_2d.update_frame(img)
        self._captured_image = img

        # 加载 3D 点云（优先 Open3D，回退 PyRVC）
        try:
            import open3d as o3d
            pcd = o3d.io.read_point_cloud(ply_path)
            pts = np.asarray(pcd.points)
            if len(pts) == 0:
                raise ValueError("点云文件为空")
            # 过滤 NaN
            pts = pts[~np.isnan(pts).any(axis=1)]
            self._view_3d.update_point_cloud(pts.astype(np.float32))
            self._captured_pm_np = pts.astype(np.float32)
        except Exception:
            # 回退 PyRVC 方式
            try:
                import PyRVC as RVC
                pm = RVC.PointMap.CreateFromFile(
                    ply_path, RVC.Size(0, 0), RVC.PointMapUnitEnum.Millimeter
                )
                if pm.IsValid():
                    pm_np = np.array(pm, copy=False).reshape(-1, 3)
                    valid = (pm_np[:, 2] != 0) | (pm_np[:, 1] != 0) | (pm_np[:, 0] != 0)
                    pm_np = pm_np[valid].astype(np.float32)
                    self._view_3d.update_point_cloud(pm_np)
                    self._captured_pm_np = pm_np
                else:
                    self._toast.show_message("点云文件无效", "error")
                    RVC.PointMap.Destroy(pm)
                    return
                RVC.PointMap.Destroy(pm)
            except Exception as e:
                self._toast.show_message(f"点云加载失败: {e}", "error")
                return

        # 设置暂存路径
        self._captured_png = png_path
        self._captured_ply = ply_path

        self._logger.success(f"已加载测试数据: 0.png + 0.ply")
        self._toast.show_message("测试数据已加载，可进行识别和保存", "success")
        self._update_button_states()

    def _on_capture(self):
        """
        拍照按钮回调：触发 3D 扫描，更新 2D/3D 视图。
        不会自动保存，仅暂存采集数据供后续识别和保存使用。
        """
        if not self._camera.is_connected():
            self._toast.show_message("请先连接相机", "error")
            return

        self._logger.info("拍照采集...")
        result = self._camera.capture_full_frame(
            self._data.save_dir, self._data.get_count() + 1
        )
        if result is None:
            self._toast.show_message("拍照失败，请检查相机", "error")
            return
        # _on_capture_done 回调自动暂存数据并更新视图
        self._toast.show_message("拍照完成", "success")

    def _on_detect(self):
        """
        识别按钮回调：对最近一次拍照结果运行标记物检测，
        在 2D/3D 视图上叠加检测结果，并自动填充输入卡片。
        - 标记物模式：检测同心圆
        - 戳点模式：检测非对称黑底白圆标定板
        """
        if not self._captured_png or not self._captured_ply:
            self._toast.show_message("请先拍照再进行识别", "error")
            return

        if not os.path.exists(self._captured_png) or not os.path.exists(self._captured_ply):
            self._toast.show_message("采集文件丢失，请重新拍照", "error")
            return

        self._view_2d.draw_markers([])
        self._view_3d.highlight_points([])

        try:
            if self._marker_type:
                self._detect_markers()
            else:
                self._detect_caliboard()
        except Exception as e:
            self._logger.error(f"识别异常: {e}")
            self._toast.show_message(f"识别失败: {e}", "error")

    def _detect_markers(self):
        """标记物模式：检测同心圆并叠加显示"""
        pts2d, pts3d = self._detector.detect_concentric(
            self._captured_png, self._captured_ply
        )
        if not pts2d:
            self._logger.warning("未检测到同心圆标记")
            self._toast.show_message("未检测到同心圆标记", "error")
            return

        overlay, highlights = self._detector.format_markers_for_overlay(pts2d, pts3d)
        self._view_2d.draw_markers(overlay)
        self._view_3d.highlight_points(highlights)
        self._logger.success(f"检测到 {len(pts2d)} 个同心圆标记")
        self._toast.show_message(f"识别完成: {len(pts2d)} 个同心圆标记", "success")

    def _detect_caliboard(self):
        """戳点模式：优先检测标定板，失败则尝试同心圆，自动填充卡片1"""
        intrinsic, distortion = self._camera.get_intrinsics()

        # 优先尝试标定板检测（需要内参）
        if intrinsic:
            px_list, pt_list, dist, err = self._detector.detect_caliboard(
                self._captured_png, self._captured_ply,
                intrinsic, distortion,
            )
            if px_list and len(px_list) >= 2:
                overlay, highlights = self._detector.format_markers_for_overlay(
                    px_list, pt_list
                )
                self._view_2d.draw_markers(overlay)
                self._view_3d.highlight_points(highlights)
                if highlights:
                    p = highlights[0]
                    self._data_input.card1.set_value(
                        f"{p[0]:.3f} {p[1]:.3f} {p[2]:.3f}"
                    )
                    self._data_input.card1.set_status("ok")
                num = len(pt_list) // 3
                self._logger.success(
                    f"检测到 {num} 个标定板圆心 "
                    f"(实测距离: {dist:.3f}mm, 误差: {err:.2f}%)"
                )
                self._toast.show_message(f"识别完成: {num} 个圆心", "success")
                return

        # 标定板未检测到，尝试同心圆检测（不需要内参）
        pts2d, pts3d = self._detector.detect_concentric(
            self._captured_png, self._captured_ply
        )
        if not pts2d:
            self._logger.warning("未检测到标定板或同心圆标记")
            self._toast.show_message("未检测到标记物，请确认目标在视野内", "error")
            return

        overlay, highlights = self._detector.format_markers_for_overlay(pts2d, pts3d)
        self._view_2d.draw_markers(overlay)
        self._view_3d.highlight_points(highlights)

        # 自动填充第一个同心圆的 3D 坐标到卡片1
        if highlights:
            p = highlights[0]
            self._data_input.card1.set_value(f"{p[0]:.3f} {p[1]:.3f} {p[2]:.3f}")
            self._data_input.card1.set_status("ok")

        self._logger.success(f"检测到 {len(pts2d)} 个同心圆")
        self._toast.show_message(f"识别完成: {len(pts2d)} 个同心圆", "success")

    def _on_save(self):
        """
        保存按钮回调：将最近一次拍照的数据和当前输入卡片的值
        添加到数据管理器并写出标定文件。
        """
        if not self._captured_png or not self._captured_ply:
            self._toast.show_message("请先拍照再保存", "error")
            return

        camera_xyz = self._data_input.card1.get_value()
        robot_pose = self._data_input.card2.get_value()
        robot_target = self._data_input.card3.get_value()

        self._data.add_record(
            self._captured_png, self._captured_ply,
            camera_xyz, robot_pose, robot_target,
        )
        self._data.write_handeye_output()

        count = self._data.get_count()
        self._logger.success(f"第 {count} 组数据保存成功")
        self._toast.show_message(f"第 {count} 组数据保存成功", "success")

        # 清空暂存，防止重复保存同一帧
        self._captured_png = None
        self._captured_ply = None
        self._captured_pm_np = None
        self._captured_image = None
        self._update_button_states()

    def _on_undo(self):
        """
        清除上一组按钮回调（Ctrl+Z）：删除最后一次保存的记录及其文件。
        """
        if self._data.get_count() == 0:
            self._toast.show_message("没有可清除的数据", "error")
            return
        reply = QMessageBox.question(
            self, "清除上一组",
            "确定要清除上一组数据吗？将同时删除对应的图片和点云文件。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if self._data.remove_last():
                self._data.write_handeye_output()
                self._view_2d.clear()
                self._view_3d.clear()
                for card in [self._data_input.card1, self._data_input.card2, self._data_input.card3]:
                    card.set_value("")
                    card.set_status("empty")
                self._logger.info("已清除上一组数据")
                self._toast.show_message("已清除上一组数据", "success")
                self._update_file_preview()

    def _on_refresh(self):
        """刷新相机（F5）：重启预览流"""
        if self._camera.is_connected():
            self._camera.stop_preview()
            self._camera.start_preview()
            self._logger.info("刷新相机图像")

    def _on_fullscreen(self):
        """全屏切换（F11）"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_card_changed(self, field, value):
        """输入卡片文字变化时同步更新数据管理器中的对应记录字段"""
        idx = self._data.get_current_index()
        if idx > 0:
            self._data.update_record(idx, field, value)

    def _update_button_states(self):
        """根据当前状态更新按钮启用/禁用"""
        has_capture = self._captured_png is not None
        has_data = self._data.get_count() > 0
        self._action_buttons.set_detect_enabled(has_capture)
        self._action_buttons.set_save_enabled(has_capture)
        self._action_buttons.set_undo_enabled(has_data)
        self._top_nav.update_progress(self._data.get_count())

    def _update_file_preview(self):
        """更新侧边栏文件预览"""
        eye_in_hand = self._eye_in_hand
        marker_type = self._marker_type
        records = self._data.all_records()
        self._side_panel.update_file_preview(eye_in_hand, marker_type, records)

    # ═══════════════════════════════════════════════════════
    # 设置对话框
    # ═══════════════════════════════════════════════════════

    def _show_settings_dialog(self):
        """
        设置对话框。
        包含：
        - 数据保存路径设置
        - 相机参数设置（曝光时间、增益、Gamma）
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)

        # ── 数据保存路径 ──
        path_group = QGroupBox("数据保存路径")
        path_layout = QHBoxLayout(path_group)

        self._save_path_edit = QLineEdit(self._save_base_dir)
        self._save_path_edit.setMinimumWidth(300)
        path_layout.addWidget(self._save_path_edit)

        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_save_path)
        path_layout.addWidget(btn_browse)

        layout.addWidget(path_group)

        # ── 相机参数 ──
        cam_group = QGroupBox("相机参数")
        cam_form = QFormLayout(cam_group)

        settings = self._camera.get_settings() if self._camera.is_connected() else {}
        self._settings_fields = {}

        for key, val in settings.items():
            le = QLineEdit(str(val))
            self._settings_fields[key] = le
            # 将英文键名转为可读的中文标签
            label_map = {
                "exposure_time_2d": "2D曝光时间(ms)",
                "exposure_time_3d": "3D曝光时间(ms)",
                "gain_2d": "2D增益",
                "gain_3d": "3D增益",
                "gamma_2d": "2D Gamma",
                "gamma_3d": "3D Gamma",
            }
            cam_form.addRow(label_map.get(key, key), le)

        layout.addWidget(cam_group)

        # ── 确定/取消按钮 ──
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_() == QDialog.Accepted:
            # 保存路径
            new_path = self._save_path_edit.text().strip()
            if new_path and os.path.isdir(os.path.dirname(new_path) or new_path):
                self._save_base_dir = new_path
                self._logger.info(f"保存路径已更新: {self._save_base_dir}")
                # 路径变更后重置会话
                self._reset_session()

            # 相机参数
            if self._camera.is_connected() and self._settings_fields:
                try:
                    if "exposure_time_2d" in self._settings_fields:
                        self._camera.set_exposure_2d(
                            float(self._settings_fields["exposure_time_2d"].text())
                        )
                    if "exposure_time_3d" in self._settings_fields:
                        self._camera.set_exposure_3d(
                            float(self._settings_fields["exposure_time_3d"].text())
                        )
                    if "gain_2d" in self._settings_fields:
                        self._camera.set_gain_2d(
                            float(self._settings_fields["gain_2d"].text())
                        )
                    if "gain_3d" in self._settings_fields:
                        self._camera.set_gain_3d(
                            float(self._settings_fields["gain_3d"].text())
                        )
                    if "gamma_2d" in self._settings_fields:
                        self._camera.set_gamma_2d(
                            float(self._settings_fields["gamma_2d"].text())
                        )
                    self._logger.success("相机参数已更新")
                except Exception as e:
                    self._logger.error(f"参数设置失败: {e}")

    def _browse_save_path(self):
        """弹出文件夹选择对话框，设置数据保存路径"""
        path = QFileDialog.getExistingDirectory(
            self, "选择数据保存目录", self._save_path_edit.text()
        )
        if path:
            self._save_path_edit.setText(path)

    # ═══════════════════════════════════════════════════════
    # 帮助对话框
    # ═══════════════════════════════════════════════════════

    def _show_help_dialog(self):
        """显示使用帮助对话框"""
        QMessageBox.information(
            self, "使用帮助",
            "手眼标定数据收集助手 V1.0\n\n"
            "操作步骤：\n"
            "1. 点击顶部「连接相机」按钮连接设备\n"
            "2. 选择标定模式和类型\n"
            "3. 移动机器人到目标位姿 → 点击「拍照」\n"
            "4. 点击「识别」检测标记物/标定板\n"
            "5. 补充/确认输入框数据后点击「保存」\n"
            "6. 重复步骤 3-5 直到采集 15-20 组\n"
            "7. 采集完成后用 HandEyeManager.exe 进行标定计算\n\n"
            "快捷键：\n"
            "Ctrl+S: 保存 | Ctrl+Z: 清除上一组\n"
            "F5: 刷新相机 | F11: 全屏切换\n\n"
            "输出目录可在「设置」中指定",
        )

    # ═══════════════════════════════════════════════════════
    # 窗口生命周期
    # ═══════════════════════════════════════════════════════

    def closeEvent(self, event):
        """
        窗口关闭事件。
        保存持久化设置、关闭相机预览流、保存备份、断开相机连接。
        """
        # 保存窗口几何信息
        self._settings.set_window_geometry(
            self.x(), self.y(), self.width(), self.height()
        )
        # 保存当前模式状态
        self._settings.set_last_mode(self._eye_in_hand, self._marker_type)
        # 保存当前路径
        self._settings.set_save_base_dir(self._save_base_dir)
        # 保存相机参数
        if self._camera.is_connected():
            self._settings.set_camera_params(self._camera.get_settings())
        # 持久化写入
        self._settings.save()

        if self._camera.is_connected():
            self._camera.stop_preview()
            self._data._save_backup()
            self._camera.shutdown()
        event.accept()
