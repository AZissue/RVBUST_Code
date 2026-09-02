# -*- coding: utf-8 -*-
"""
ui_v2.backend_bridge —— ui_v2 空壳与现有 core 模块的桥接器。

职责：
  - 把 LauncherDialog / MultiCamWorkspace / MobileChainWorkspace 的 Qt 信号
    接到现有 core 模块（CameraManager / FixedMultiCamWorkflow / MobileChainWorkflow）；
  - 把控件替换为成熟组件（EmbeddedPointCloudViewer / camera_card 等）；
  - 处理 QThread 后台执行与主线程 UI 更新的线程切换。

使用方式：
  bridge = BackendBridge(main_window_shell)
  bridge.wire_all()
"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox

from core.camera_manager import CameraManager
from core.fixed_multi_cam_workflow import FixedMultiCamWorkflow
from core.mobile_chain_workflow import MobileChainWorkflow
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.point_cloud_processor import PointCloudProcessor
from core.offline_session import OfflineSession
from core.frame_data import FrameData
from core.utils import logger
from ui.camera_card import numpy_to_qpixmap

from .launcher_dialog import LauncherDialog
from .main_window import MainWindowShell
from .widgets.device_table import DeviceInfo


class BackendBridge(QObject):
    """ui_v2 与 core 模块的桥接器。"""

    connection_finished = Signal(bool, str)
    """设备连接完成信号：(success, message)。"""

    def __init__(self, shell: MainWindowShell):
        super().__init__()
        self.shell = shell

        # core 模块
        self.camera_manager = CameraManager()
        self.marker_detector = MarkerDetector()
        self.calibration_engine = CalibrationEngine()
        self.stitch_engine = StitchEngine()
        self.processor = PointCloudProcessor()

        # 工作流
        self.fixed_workflow = FixedMultiCamWorkflow(
            self.camera_manager, self.marker_detector,
            self.calibration_engine, self.stitch_engine, self.processor)
        self.mobile_workflow = MobileChainWorkflow(
            self.camera_manager, self.marker_detector,
            self.calibration_engine, self.stitch_engine, self.processor)

        # 当前模式
        self._current_mode = LauncherDialog.MODE_MULTI_CAM

        # 标记物检测器共享状态锁（set_marker_type / detect_3d 非线程安全）
        self._detect_lock = threading.Lock()

        # 模式 B 实时取景定时器
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._on_preview_tick)
        self._preview_camera_id: Optional[str] = None

        # 模式 A 单相机卡片 2D 预览定时器
        self._card_preview_timer = QTimer(self)
        self._card_preview_timer.timeout.connect(self._on_card_preview_tick)
        self._card_preview_active: Set[str] = set()

        # 后台任务引用保护：防止 QThread 运行期间被 Python GC 销毁
        self._workers: List[WorkerThread] = []

        # 初始化 RVC 系统
        ok, msg = self.camera_manager.initialize()
        if ok:
            logger.info("RVC 系统初始化成功")
        else:
            logger.warning(f"RVC 系统初始化失败: {msg}")

    # ------------------------------------------------------------------
    # 接线入口
    # ------------------------------------------------------------------
    def wire_all(self):
        """连接所有信号到后端。"""
        self._wire_launcher()
        self._wire_multi_cam_workspace()
        self._wire_mobile_chain_workspace()
        self._wire_main_window()

    def _wire_launcher(self):
        """接线启动小窗。"""
        # LauncherDialog 由 MainWindowShell.open_device_manager 创建，
        # 这里只接线 MainWindowShell 的设备管理重开信号
        self.shell.device_manager_reopened.connect(self._on_device_manager_reopened)

    def _wire_multi_cam_workspace(self):
        """接线模式 A（多相机外参标定）。"""
        ws = self.shell.workspace_multi()
        ws.capture_requested.connect(self._on_multi_capture)
        ws.detect_requested.connect(self._on_multi_detect)
        ws.calibrate_requested.connect(self._on_multi_calibrate)
        ws.save_extrinsics_requested.connect(self._on_multi_save_extrinsics)
        ws.load_extrinsics_requested.connect(self._on_multi_load_extrinsics)
        ws.capture_scan_requested.connect(self._on_multi_capture_scan)
        ws.stitch_save_requested.connect(self._on_multi_stitch_save)
        ws.batch_scan_requested.connect(self._on_multi_batch_scan)
        ws.reference_changed.connect(self._on_multi_reference_changed)
        ws.step_back_requested.connect(self._on_multi_step_back)
        ws.card_preview_toggled.connect(self._on_card_preview_toggled)
        ws.card_capture_requested.connect(self._on_card_capture)
        ws.card_detect_requested.connect(self._on_card_detect)

    def _wire_mobile_chain_workspace(self):
        """接线模式 B（单相机移动链式）。"""
        ws = self.shell.workspace_mobile()
        ws.capture_station_requested.connect(self._on_mobile_capture_station)
        ws.preview_toggled.connect(self._on_mobile_preview_toggled)
        ws.undo_requested.connect(self._on_mobile_undo)
        ws.recapture_requested.connect(self._on_mobile_recapture)
        ws.delete_station_requested.connect(self._on_mobile_delete_station)
        ws.optimize_requested.connect(self._on_mobile_optimize)
        ws.save_requested.connect(self._on_mobile_save)
        ws.offline_load_requested.connect(self._on_mobile_offline_load)
        ws.station_selected.connect(self._on_mobile_station_selected)

    def _wire_main_window(self):
        """接线主窗口。"""
        self.shell.save_session_requested.connect(self._on_save_session)
        self.shell.open_session_requested.connect(self._on_open_session)
        self.shell.param_debug_requested.connect(self._on_param_debug)

    # ------------------------------------------------------------------
    # 参数调试：打开官方 RVCManager
    # ------------------------------------------------------------------
    def _on_param_debug(self):
        """断开当前已连接相机，打开 RVC 官方调试工具 RVCManager。

        自动按默认安装路径查找 D/C 盘；找不到时弹窗提示并允许用户
        自定义选择 RVCManager.exe 路径。
        """
        # 1. 断开当前已连接相机
        try:
            connected_ids = self.camera_manager.get_connected_ids()
            if connected_ids:
                self.camera_manager.disconnect_all()
                self.shell.log(
                    f"已断开 {len(connected_ids)} 台相机，准备打开 RVCManager", "info")
            else:
                self.shell.log("当前无在线相机，直接打开 RVCManager", "info")
        except Exception as e:
            self.shell.log(f"断开相机时出错: {e}", "warn")

        # 2. 查找默认安装路径
        candidates = [
            r"D:\Program Files\RVBUST\RVC\RVCManager\RVCManager.exe",
            r"C:\Program Files\RVBUST\RVC\RVCManager\RVCManager.exe",
        ]
        executable: Optional[str] = None
        for path in candidates:
            if os.path.isfile(path):
                executable = path
                break

        # 3. 找不到则弹窗提示并让用户自定义路径
        if executable is None:
            self.shell.log("未在默认路径找到 RVCManager.exe", "warn")
            reply = QMessageBox.question(
                self.shell,
                "未找到 RVCManager",
                "未在以下默认路径找到 RVCManager.exe：\n"
                "D:\\Program Files\\RVBUST\\RVC\\RVCManager\\RVCManager.exe\n"
                "C:\\Program Files\\RVBUST\\RVC\\RVCManager\\RVCManager.exe\n\n"
                "是否手动指定 RVCManager.exe 路径？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                self.shell.log("已取消打开 RVCManager", "info")
                return

            default_dir = r"C:\Program Files\RVBUST\RVC\RVCManager"
            if not os.path.isdir(default_dir):
                default_dir = r"C:\\"
            executable, _ = QFileDialog.getOpenFileName(
                self.shell,
                "选择 RVCManager.exe",
                default_dir,
                "可执行文件 (*.exe)",
            )
            if not executable:
                self.shell.log("未选择 RVCManager.exe，已取消", "info")
                return
            if os.path.basename(executable) != "RVCManager.exe":
                QMessageBox.warning(
                    self.shell,
                    "路径无效",
                    "请选择 RVCManager.exe 官方调试工具。",
                )
                self.shell.log(f"选择的文件不是 RVCManager.exe: {executable}", "warn")
                return

        # 4. 打开官方调试工具
        try:
            subprocess.Popen([executable], shell=False)
            self.shell.log(f"已启动 RVCManager: {executable}", "success")
        except Exception as e:
            self.shell.log(f"启动 RVCManager 失败: {e}", "error")
            QMessageBox.critical(
                self.shell,
                "启动失败",
                f"无法启动 RVCManager：\n{e}\n\n"
                f"请检查路径是否正确或尝试以管理员身份运行。",
            )

    # ------------------------------------------------------------------
    # 连接失败诊断与提示
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_connection_failure(
        results: List[Tuple[str, bool, str]],
        real_devices: List[DeviceInfo],
        required: int,
        total_count: Optional[int] = None,
    ) -> Tuple[str, str]:
        """根据连接结果构造用户友好的失败原因和排查建议。

        Args:
            total_count: 总设备数（含测试相机）。为 None 时取 len(results)。

        Returns:
            (reason, details) 分别用于弹窗标题下方的正文和详细说明。
        """
        ok_count = sum(1 for _, ok, _ in results if ok)
        total_count = total_count if total_count is not None else len(results)
        failures = [(cid, msg) for cid, ok, msg in results if not ok]

        # 1. 设备总数不足（含只选测试相机但数量不够）
        if total_count < required:
            if not real_devices:
                return (
                    f"当前仅选择了 {total_count} 台测试相机（仅用于 UI 布局预览），"
                    f"该模式需要至少 {required} 台设备。",
                    "调试 UI 时可选择多台测试相机进入；"
                    "正式使用请检查真实 RVC 相机是否已上电、网线/USB 是否连接正常，"
                    "然后点击「刷新」重新枚举设备并勾选真实相机。",
                )
            return (
                f"该模式需要至少 {required} 台设备，当前仅 {total_count} 台。",
                "请继续勾选更多设备，或检查真实相机的连接状态。",
            )

        # 2. 有真实设备但全部连接失败
        if ok_count == 0 and failures:
            msgs = "\n".join(f"  • {cid}: {msg}" for cid, msg in failures)
            busy = any("占用" in msg or "RVCManager" in msg for _, msg in failures)
            if busy:
                reason = "所有真实相机均连接失败，检测到相机可能被占用。"
                details = (
                    f"失败详情：\n{msgs}\n\n"
                    "常见原因与解决方法：\n"
                    "  1. RVCManager 或其他调试工具正在占用相机："
                    "请关闭 RVCManager 后再点击「连接设备」。\n"
                    "  2. 本软件已连接过该相机：请尝试点击「设备管理」重新进入小窗连接。\n"
                    "  3. 相机被其他程序占用：请检查任务管理器，结束相关进程后重试。"
                )
            else:
                reason = "所有真实相机均连接失败。"
                details = (
                    f"失败详情：\n{msgs}\n\n"
                    "常见原因与解决方法：\n"
                    "  1. 相机未上电或网线/USB 松动：请检查物理连接。\n"
                    "  2. 相机 IP 不在同一网段：请点击「自动设置 IP」。\n"
                    "  3. 防火墙或杀毒软件拦截：请临时关闭后重试。"
                )
            return reason, details

        # 3. 部分成功但真实相机数量不足
        msgs = "\n".join(f"  • {cid}: {msg}" for cid, msg in failures)
        return (
            f"该模式需要至少 {required} 台设备，当前 {total_count} 台已选择，"
            f"但仅 {ok_count} 台真实相机成功连接。",
            f"失败详情：\n{msgs}\n\n"
            "当前仍可用测试相机进入工作区调试 UI；"
            "正式拍摄/标定请检查失败相机的连接状态，排除被占用或网络问题后重试。",
        )

    def _show_connection_error(self, title: str, reason: str, details: str):
        """弹出带排查建议的连接失败提示框。"""
        msg_box = QMessageBox(self.shell)
        msg_box.setWindowTitle(title)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText(reason)
        msg_box.setInformativeText(details)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    def _show_debug_mode_notice(
        self, mode_name: str, real_ok_count: int, test_count: int
    ):
        """提示当前以测试相机为主进入调试模式，正式功能需要真实相机。"""
        self.shell.log(
            f"{mode_name} 以调试模式进入：真实相机 {real_ok_count} 台，"
            f"测试设备 {test_count} 台", "warn")
        msg_box = QMessageBox(self.shell)
        msg_box.setWindowTitle(f"{mode_name} — 调试模式")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(
            f"当前已使用 {test_count} 台测试相机进入 {mode_name} 工作区。\n"
            f"真实相机成功连接 {real_ok_count} 台。")
        msg_box.setInformativeText(
            "测试相机仅用于 UI 布局调试：\n"
            "  • 可以正常查看界面布局、操作流程和大部分交互；\n"
            "  • 拍摄、标定、拼接等依赖真实数据的功能会失败或无结果；\n"
            "  • 正式使用时请连接真实 RVC 相机。\n\n"
            "如果刚用过「参数调试」打开 RVCManager，请关闭 RVCManager 后"
            "重新连接真实相机。")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    # ------------------------------------------------------------------
    # 设备管理（LauncherDialog）
    # ------------------------------------------------------------------
    def enumerate_devices(self) -> List[DeviceInfo]:
        """枚举所有 RVC 设备并返回 DeviceInfo 列表。"""
        device_infos = []
        for i, dev in enumerate(self.camera_manager.find_devices()):
            try:
                ret, info = dev.GetDeviceInfo()
                if ret:
                    device_infos.append(DeviceInfo(
                        model=info.name,
                        serial=info.sn,
                        ip=getattr(info, 'ip', ''),
                        online=True,
                        backend_ref=i,
                    ))
            except Exception:
                pass
        return device_infos

    @staticmethod
    def get_ordered_devices(devices: List[DeviceInfo]) -> List[DeviceInfo]:
        """对齐 backend 连接顺序：真实设备在前，测试/虚拟设备在后。

        LauncherDialog 返回的勾选顺序是用户点击顺序；camera_id 分配必须
        与 backend 的 ordered_devices（real + test）一致，否则卡片标题与
        实际视频帧错位。
        """
        real = [d for d in devices if isinstance(d.backend_ref, int)]
        test = [d for d in devices if not isinstance(d.backend_ref, int)]
        return real + test

    def auto_configure_network(self, devices: List[DeviceInfo],
                               on_finished=None):
        """对勾选设备自动配置 IP；未勾选则对所有 GigE 设备配置（后台执行）。

        Args:
            devices: 勾选设备列表；空列表表示所有 GigE 设备。
            on_finished: 完成回调，签名为 (results, error)，可选。
        """
        indices = [d.backend_ref for d in devices
                   if isinstance(d.backend_ref, int)]
        target_desc = f"选中 {len(indices)} 台" if indices else "所有 GigE"
        self.shell.log(f"开始对 {target_desc} 设备进行自动 IP 配置...", "info")

        def _work():
            return self.camera_manager.auto_configure_network(indices)

        def _done(results, error):
            if error:
                self.shell.log(f"自动配置 IP 失败: {error}", "error")
            else:
                for idx, ok, msg in results:
                    level = "success" if ok else "warn"
                    self.shell.log(f"[{idx}] {msg}", level)
            if on_finished is not None:
                on_finished(results, error)

        self._run_background(_work, _done)

    def _on_device_manager_reopened(
        self, mode: str, devices: List[DeviceInfo], show_loading: bool = True
    ):
        """设备管理小窗确认：断开旧设备 → 连接新设备 → 切换工作区。

        Args:
            show_loading: 是否在主窗口显示 loading 遮罩。
                          主程序新流程会在 launcher 小窗上先显示遮罩，
                          因此调用时传入 False。
        """
        if show_loading:
            self.shell.show_loading("正在连接设备...")
        # 清空旧相机注册表（避免多次进入设备管理后 camera_id 递增错乱）
        self.camera_manager.clear()

        # 区分真实设备与测试/虚拟设备
        real_devices = [d for d in devices if isinstance(d.backend_ref, int)]
        test_devices = [d for d in devices if not isinstance(d.backend_ref, int)]
        ordered_devices = real_devices + test_devices

        # 连接新设备
        def _connect():
            results = []
            for dev in ordered_devices:
                camera_id = f"cam{len(self.camera_manager.camera_ids)}"
                self.camera_manager.add_camera(camera_id)
                if dev in test_devices:
                    # 测试设备仅占用 camera_id，不连接真实相机
                    results.append((camera_id, False, "测试设备（仅布局）"))
                    continue
                idx = dev.backend_ref  # type: ignore[union-attr]
                ok, msg = self.camera_manager.connect(camera_id, idx)
                results.append((camera_id, ok, msg))
            return results

        def _done(results, error):
            if error:
                if show_loading:
                    self.shell.hide_loading()
                self.connection_finished.emit(False, f"连接设备异常: {error}")
                self.shell.log(f"连接设备异常: {error}", "error")
                self._show_connection_error(
                    "连接设备异常",
                    f"连接过程中发生异常：{error}",
                    details="请检查相机是否上电、网络是否正常，或尝试重新插拔相机后重试。")
                return
            ok_count = sum(1 for _, ok, _ in results if ok)
            total_count = len(results)
            real_count = len(real_devices)
            test_count = len(test_devices)
            for cid, ok, msg in results:
                level = "success" if ok else "warn"
                self.shell.log(f"相机 {cid}: {msg}", level)
            self.shell.log(
                f"设备连接完成: {ok_count}/{real_count} 台真实相机成功，"
                f"测试设备 {test_count} 台", "info")
            self._current_mode = mode

            # 若用户勾选了真实相机但全部连接失败，阻断进入工作区并给出排查建议
            if real_count > 0 and ok_count == 0:
                reason, details = self._classify_connection_failure(
                    results, real_devices, required=1,
                    total_count=real_count)
                self.shell.log(
                    "所有真实相机连接失败，未进入工作区", "error")
                if show_loading:
                    self.shell.hide_loading()
                self._show_connection_error(
                    "相机连接失败", reason, details)
                self.connection_finished.emit(
                    False, "所有真实相机连接失败")
                return

            if mode == LauncherDialog.MODE_MULTI_CAM:
                # 模式 A：多相机外参标定要求至少 2 台设备（真实或测试均可进入 UI）
                if total_count < 2:
                    reason, details = self._classify_connection_failure(
                        results, real_devices, required=2,
                        total_count=total_count)
                    self.shell.log(
                        f"多相机外参标定需要至少 2 台设备，当前仅 {total_count} 台",
                        "error")
                    if show_loading:
                        self.shell.hide_loading()
                    self._show_connection_error(
                        "无法进入多相机外参标定", reason, details)
                    self.connection_finished.emit(
                        False,
                        f"多相机外参标定需要至少 2 台设备，当前 {total_count} 台")
                    return
                if ok_count < 2 and test_count > 0:
                    self._show_debug_mode_notice(
                        "多相机外参标定", ok_count, test_count)
                # 参考相机选第一台真实连接成功的相机，fallback 到 cam0
                reference_id = next(
                    (cid for cid, ok, _ in results if ok), "cam0")
                ok, msg = self.fixed_workflow.start_calibration(reference_id)
                self.shell.log(msg, "success" if ok else "warn")
                self._on_multi_reference_changed(reference_id)
                self.shell.workspace_multi().set_state("connected")
            elif mode == LauncherDialog.MODE_MOBILE_CHAIN:
                # 模式 B：单相机移动拼接要求至少 1 台设备
                if total_count < 1:
                    reason, details = self._classify_connection_failure(
                        results, real_devices, required=1,
                        total_count=total_count)
                    self.shell.log(
                        "单相机移动拼接需要至少 1 台设备", "error")
                    if show_loading:
                        self.shell.hide_loading()
                    self._show_connection_error(
                        "无法进入单相机移动拼接", reason, details)
                    self.connection_finished.emit(
                        False, "单相机移动拼接需要至少 1 台设备")
                    return
                if ok_count < 1 and test_count > 0:
                    self._show_debug_mode_notice(
                        "单相机移动拼接", ok_count, test_count)
                # 模式 B 需要初始化链式拼接会话
                ok, msg = self.mobile_workflow.start_chaining()
                self.shell.log(msg, "success" if ok else "warn")
                self.shell.workspace_mobile().set_state("connected")
            elif mode == LauncherDialog.MODE_TURNTABLE:
                # 模式 C：转台要求至少 1 台设备（真实或测试均可进入 UI）
                if total_count < 1:
                    reason, details = self._classify_connection_failure(
                        results, real_devices, required=1,
                        total_count=total_count)
                    self.shell.log(
                        "转台 360° 拼接需要至少 1 台设备", "error")
                    if show_loading:
                        self.shell.hide_loading()
                    self._show_connection_error(
                        "无法进入转台 360° 拼接", reason, details)
                    self.connection_finished.emit(
                        False, "转台 360° 拼接需要至少 1 台设备")
                    return
                if ok_count < 1 and test_count > 0:
                    self._show_debug_mode_notice(
                        "转台 360° 拼接", ok_count, test_count)
                # 转台工作区接入主程序共享的相机管理器
                self.shell.workspace_turntable().set_camera_manager(
                    self.camera_manager, self.marker_detector)
                self.shell.workspace_turntable().set_state("connected")
            if show_loading:
                self.shell.hide_loading()
            self.connection_finished.emit(
                True,
                f"设备连接完成: {ok_count}/{real_count} 台真实相机成功"
                f"（测试设备 {test_count} 台）")

        self._run_background(_connect, _done)

    # ------------------------------------------------------------------
    # 模式 A（多相机外参标定）
    # ------------------------------------------------------------------
    def _on_multi_capture(self, sync: bool):
        """拍摄标定帧；若已处于扫描/锁定阶段，则先重置为重新标定。"""
        ws = self.shell.workspace_multi()

        # locked 状态下点击「重新标定」：先回到标定阶段并清空旧结果
        if ws.current_state() == "locked":
            ref_id = self.calibration_engine.reference_id or ws.current_reference_id() or "cam0"
            ok, msg = self.fixed_workflow.start_calibration(ref_id)
            if not ok:
                self.shell.log(f"重新标定失败: {msg}", "error")
                return
            ws.clear_calibration_results()
            ws.viewer().clear_all()
            ws.viewer().set_reference(None)
            ws.set_state("connected")
            self.shell.log("已回到标定阶段，请重新拍摄标定帧", "info")

        preview_cam = self._pause_2d_preview()
        active_cards = self._pause_card_preview()
        self.shell.show_loading("正在拍摄标定帧...")
        def _work():
            return self.camera_manager.capture_all(sync=sync)
        def _done(frames, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            self._resume_card_preview(active_cards)
            if error:
                self.shell.log(f"拍摄失败: {error}", "error")
                return
            if not frames:
                self.shell.log("拍摄失败：无已连接相机", "warn")
                return
            # 更新工作流标定帧
            ws = self.shell.workspace_multi()
            all_ok = True
            for cid, frame in frames.items():
                ok, msg = self.fixed_workflow.add_calibration_frame(frame)
                if not ok:
                    all_ok = False
                    self.shell.log(f"添加标定帧失败 ({cid}): {msg}", "warn")
            if not all_ok:
                self.shell.log("部分标定帧未加入工作流，请检查状态", "warn")
                return
            # 更新各相机卡片预览
            for cid, frame in frames.items():
                ws.camera_grid().set_frame(cid, frame)
            ws.on_capture_done()
            ws.set_state("captured")
            self.shell.set_dirty(True)
            self.shell.log(f"拍摄完成: {len(frames)} 台相机", "success")
        self._run_background(_work, _done)

    def _on_multi_detect(self, method: str):
        """检测标记物（串行执行，避免共享 MarkerDetector 线程竞态）。"""
        marker_type = self._map_detect_method(method)
        self.shell.show_loading("正在检测标记物...")

        def _detect_one(cid_frame):
            cid, frame = cid_frame
            with self._detect_lock:
                self.marker_detector.set_marker_type(marker_type)
                markers = self.marker_detector.detect_3d(
                    frame.image_np,
                    pointmap=frame.pointmap,
                    rvc_image=frame.rvc_image,
                    offline_ply_path=frame.offline_pointmap_path,
                )
            frame.markers = markers
            return cid, len(markers)

        def _work():
            frames = list(self.fixed_workflow.frames_calib.items())
            marker_counts = {}
            for cid, frame in frames:
                cid_out, count = _detect_one((cid, frame))
                marker_counts[cid_out] = count
            return marker_counts
        def _done(marker_counts, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"检测失败: {error}", "error")
                return
            ws = self.shell.workspace_multi()
            # 更新各相机卡片的标记数量与共视状态
            grid = ws.camera_grid()
            for cid, count in marker_counts.items():
                grid.set_marker_count(cid, count)
                grid.set_covis_status(cid, count > 0)
                frame = self.fixed_workflow.frames_calib.get(cid)
                if frame is not None:
                    grid.set_frame(cid, frame, frame.markers)
            ws.on_detect_done(marker_counts)
            ws.set_state("detected")
            self.shell.set_dirty(True)
            total = sum(marker_counts.values())
            self.shell.log(f"检测完成: 共 {total} 个标记", "success")
        self._run_background(_work, _done)

    def _on_multi_calibrate(self):
        """计算外参。"""
        self.shell.show_loading("正在计算外参...")
        def _work():
            ok, msg = self.fixed_workflow.calibrate()
            pairs = []
            for (ref, cam), res in self.calibration_engine.pair_results.items():
                if res.get('success'):
                    pairs.append({
                        'pair': f"{cam}→{ref}",
                        'rms_mm': res['rms_mm'],
                        'inlier_ratio': res['inlier_ratio'],
                        'level': 'ok' if res['rms_mm'] < 0.5 else 'warn' if res['rms_mm'] < 1.5 else 'fail',
                    })
            return ok, msg, pairs
        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"标定异常: {error}", "error")
                return
            ok, msg, pairs = result
            # 质量评分：基于最大 RMS 与最小内点率加权，0~100
            if not ok or not pairs:
                score = 0
            else:
                max_rms = max(p['rms_mm'] for p in pairs)
                min_inlier = min(p['inlier_ratio'] for p in pairs)
                rms_score = max(0.0, 100.0 - max_rms * 25.0)
                score = int(min(100.0, rms_score * (0.5 + 0.5 * min_inlier)))
            ws = self.shell.workspace_multi()
            # 设置参考相机，viewer 中参考相机显示为白色
            ws.viewer().set_reference(self.calibration_engine.reference_id)
            ws.on_calibrate_done(pairs, score, ok)
            self.shell.set_dirty(True)
            if ok:
                ok_scan, msg_scan = self.fixed_workflow.start_scanning()
                if ok_scan:
                    ws.set_state("locked")
                    self.shell.log(f"标定完成: {msg} | {msg_scan}", "success")
                else:
                    ws.set_state("calibrated")
                    self.shell.log(f"标定完成但无法进入扫描: {msg_scan}", "warn")
            else:
                ws.set_state("calibrated")
                self.shell.log(f"标定质量不达标: {msg}", "warn")
        self._run_background(_work, _done)

    def _on_multi_save_extrinsics(self):
        """保存外参。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self.shell, "保存外参", "calibration.json", "JSON 文件 (*.json)")
        if path:
            ok, msg = self.fixed_workflow.save_calibration(path)
            self.shell.log(msg, "success" if ok else "error")

    def _on_multi_load_extrinsics(self):
        """加载外参并直接进入扫描阶段。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self.shell, "加载外参", "", "JSON 文件 (*.json)")
        if not path:
            return
        ok, msg = self.fixed_workflow.load_calibration(path)
        self.shell.log(msg, "success" if ok else "error")
        if not ok:
            return

        ws = self.shell.workspace_multi()
        ref_id = self.fixed_workflow.reference_id
        ws.viewer().set_reference(ref_id)

        # 回填标定结果表格，使用户知道加载了哪些 pair
        pairs = []
        for (ref, cam), res in self.calibration_engine.pair_results.items():
            if res.get('success'):
                pairs.append({
                    'pair': f"{cam}→{ref}",
                    'rms_mm': res['rms_mm'],
                    'inlier_ratio': res['inlier_ratio'],
                    'level': 'ok' if res['rms_mm'] < 0.5 else 'warn' if res['rms_mm'] < 1.5 else 'fail',
                })
        ws.on_calibrate_done(pairs, score=100, quality_passed=True)

        ok_scan, msg_scan = self.fixed_workflow.start_scanning()
        if ok_scan:
            ws.set_state("locked")
            self.shell.set_dirty(True)
            self.shell.log(f"外参已加载并进入扫描阶段: {msg_scan}", "success")
        else:
            ws.set_state("calibrated")
            self.shell.set_dirty(True)
            self.shell.log(f"外参已加载但无法进入扫描: {msg_scan}", "warn")

    def _on_multi_capture_scan(self):
        """拍摄扫描帧。"""
        preview_cam = self._pause_2d_preview()
        active_cards = self._pause_card_preview()
        self.shell.show_loading("正在拍摄扫描帧...")
        def _work():
            return self.camera_manager.capture_all(sync=True)
        def _done(frames, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            self._resume_card_preview(active_cards)
            if error:
                self.shell.log(f"扫描拍摄失败: {error}", "error")
                return
            ws = self.shell.workspace_multi()
            all_ok = True
            for cid, frame in frames.items():
                ok, msg = self.fixed_workflow.add_scan_frame(frame)
                if ok:
                    ws.camera_grid().set_frame(cid, frame)
                    ws.camera_grid().set_frame_kind(cid, "扫描帧")
                else:
                    all_ok = False
                    self.shell.log(f"添加扫描帧失败 ({cid}): {msg}", "warn")
            if all_ok:
                self.shell.set_dirty(True)
                self.shell.log(f"扫描帧拍摄完成: {len(frames)} 台相机", "success")
            else:
                self.shell.log("部分扫描帧未加入工作流", "warn")
        self._run_background(_work, _done)

    def _on_multi_stitch_save(self):
        """拼接并保存。"""
        self.shell.show_loading("正在拼接点云...")
        def _work():
            ok, msg, merged = self.fixed_workflow.stitch()
            return ok, msg, merged
        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"拼接异常: {error}", "error")
                return
            ok, msg, merged = result
            if ok and merged is not None:
                # 更新 3D 查看器
                ws = self.shell.workspace_multi()
                ws.viewer().set_pointcloud_merged(merged)
                self.shell.log(f"拼接完成: {len(merged.points)} 点", "success")
                # 在主线程弹窗保存
                from PySide6.QtWidgets import QFileDialog
                path, _ = QFileDialog.getSaveFileName(
                    self.shell, "保存点云", "merged.ply", "PLY 文件 (*.ply)")
                if path:
                    import open3d as o3d
                    o3d.io.write_point_cloud(path, merged)
                    self.shell.log(f"点云已保存: {path}", "success")
            else:
                self.shell.log(f"拼接失败: {msg}", "error")
        self._run_background(_work, _done)

    def _on_multi_batch_scan(self, n: int):
        """批量拼接保存：连续拍摄 n 次扫描帧并拼接保存。"""
        preview_cam = self._pause_2d_preview()
        active_cards = self._pause_card_preview()
        self.shell.show_loading(f"批量扫描拼接 ({n} 次)...")

        def _work():
            saved_paths = []
            for i in range(n):
                frames = self.camera_manager.capture_all(sync=True)
                if not frames:
                    return False, f"第 {i+1}/{n} 次拍摄失败：无已连接相机", saved_paths
                for cid, frame in frames.items():
                    ok, msg = self.fixed_workflow.add_scan_frame(frame)
                    if not ok:
                        return False, f"第 {i+1}/{n} 次添加扫描帧失败 ({cid}): {msg}", saved_paths
                ok, msg, merged = self.fixed_workflow.stitch()
                if not ok or merged is None:
                    return False, f"第 {i+1}/{n} 次拼接失败: {msg}", saved_paths
                import open3d as o3d
                path = os.path.join(
                    os.path.abspath("offline_data"),
                    f"batch_scan_{i+1:03d}.ply")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                o3d.io.write_point_cloud(path, merged)
                saved_paths.append(path)
            return True, f"批量扫描完成，共保存 {len(saved_paths)} 帧", saved_paths

        def _done(result, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            self._resume_card_preview(active_cards)
            if error:
                self.shell.log(f"批量扫描异常: {error}", "error")
                return
            ok, msg, paths = result
            if ok:
                self.shell.set_dirty(True)
            self.shell.log(msg, "success" if ok else "error")
            if paths:
                self.shell.log(f"保存路径: {paths[0]} 等", "info")

        self._run_background(_work, _done)

    def _on_multi_reference_changed(self, camera_id: str):
        """参考相机变更。

        若已标定/扫描阶段切换参考相机，历史标定/扫描数据会失效，需要重置
        工作流并清空 UI 结果，提示用户重新拍摄。
        """
        ws = self.shell.workspace_multi()
        state = self.fixed_workflow.get_state()
        if state in (self.fixed_workflow.STATE_CALIBRATING,
                     self.fixed_workflow.STATE_CALIBRATED,
                     self.fixed_workflow.STATE_SCANNING):
            self.fixed_workflow.reset()
            ok, msg = self.fixed_workflow.start_calibration(camera_id)
            if not ok:
                self.shell.log(f"切换参考相机失败: {msg}", "error")
                return
            ws.clear_calibration_results()
            ws.viewer().clear_all()
            ws.set_state("connected")
            self.shell.log(
                f"参考相机已切换为 {camera_id}，历史标定/扫描数据已清空，"
                "请重新拍摄标定帧", "info")
        else:
            self.shell.log(f"参考相机: {camera_id}", "info")
        self.calibration_engine.reference_id = camera_id
        ws.viewer().set_reference(camera_id)

    def _on_multi_step_back(self, index: int):
        """步骤回退。"""
        self.shell.log(f"步骤回退到: {index}", "info")
        # TODO: 根据步骤索引重置工作流状态

    def _on_card_preview_toggled(self, camera_id: str, enabled: bool):
        """单相机卡片 2D 预览开关。多卡同时预览时自动降频以减轻 SDK 负担。"""
        if enabled:
            if not self.camera_manager.is_connected(camera_id):
                self.shell.log(f"相机 {camera_id} 未连接，无法预览", "warn")
                self._set_card_preview_checked(camera_id, False)
                return
            self._card_preview_active.add(camera_id)
            # 多卡预览时自动降频：>2 卡 → 5fps，否则 10fps
            interval = 200 if len(self._card_preview_active) > 2 else 100
            if not self._card_preview_timer.isActive():
                self._card_preview_timer.start(interval)
            elif self._card_preview_timer.interval() != interval:
                self._card_preview_timer.setInterval(interval)
            self.shell.log(f"开始 2D 预览: {camera_id}", "info")
        else:
            self._card_preview_active.discard(camera_id)
            if not self._card_preview_active:
                self._card_preview_timer.stop()
            else:
                interval = 200 if len(self._card_preview_active) > 2 else 100
                self._card_preview_timer.setInterval(interval)
            self.shell.log(f"停止 2D 预览: {camera_id}", "info")

    def _on_card_preview_tick(self):
        """刷新所有处于 2D 预览状态的相机卡片。"""
        ws = self.shell.workspace_multi()
        for camera_id in list(self._card_preview_active):
            try:
                if not self.camera_manager.is_connected(camera_id):
                    self._card_preview_active.discard(camera_id)
                    self._set_card_preview_checked(camera_id, False)
                    continue
                frame = self.camera_manager.capture_2d_preview(camera_id)
                if frame is not None and frame.image_np is not None:
                    ws.camera_grid().set_frame(camera_id, frame)
            except Exception as e:
                logger.warning(f"2D 预览刷新异常 ({camera_id}): {e}")

    def _set_card_preview_checked(self, camera_id: str, checked: bool):
        """同步卡片上 2D 预览按钮的勾选状态。"""
        ws = self.shell.workspace_multi()
        card = ws.camera_grid().card(camera_id)
        if card is not None:
            card.set_preview_checked(checked)

    def _pause_card_preview(self) -> Set[str]:
        """暂停所有卡片 2D 预览，返回之前处于预览状态的 camera_id 集合。"""
        active = set(self._card_preview_active)
        if active:
            self._card_preview_timer.stop()
            self._card_preview_active.clear()
            for cid in active:
                self._set_card_preview_checked(cid, False)
            logger.info(f"已暂停卡片 2D 预览: {active}")
        return active

    def _resume_card_preview(self, active: Set[str]):
        """恢复之前暂停的卡片 2D 预览。"""
        if not active:
            return
        for cid in active:
            if self.camera_manager.is_connected(cid):
                self._card_preview_active.add(cid)
                self._set_card_preview_checked(cid, True)
        if self._card_preview_active:
            interval = 200 if len(self._card_preview_active) > 2 else 100
            self._card_preview_timer.start(interval)
            logger.info(f"已恢复卡片 2D 预览: {self._card_preview_active}")

    def _on_card_capture(self, camera_id: str):
        """单相机卡片 3D 拍摄。

        注意：RVC SDK 同一相机句柄上 2D 预览与 3D 拍摄互斥，拍摄前必须
        停止所有 2D 预览（卡片预览定时器 + 移动工作站预览定时器），拍摄
        结束后恢复其他相机的预览。
        """
        if not self.camera_manager.is_connected(camera_id):
            self.shell.log(f"拍摄失败: 相机 {camera_id} 未连接", "warn")
            return

        # 1. 停止卡片 2D 预览
        was_card_preview_active = camera_id in self._card_preview_active
        if was_card_preview_active:
            self._card_preview_active.discard(camera_id)
            self._set_card_preview_checked(camera_id, False)
        # 即使本机未开预览，也暂停整个卡片预览定时器，防止并发 2D/3D 冲突
        card_timer_was_running = self._card_preview_timer.isActive()
        if card_timer_was_running:
            self._card_preview_timer.stop()

        # 2. 暂停移动工作站实时取景（若正在运行）
        mobile_preview_cam = self._pause_2d_preview()

        self.shell.show_loading(f"正在拍摄 {camera_id}...")

        def _work():
            return self.camera_manager.capture(camera_id)

        def _done(frame, error):
            self.shell.hide_loading()
            # 恢复移动工作站预览
            self._resume_2d_preview(mobile_preview_cam)
            # 失败路径：恢复本机卡片预览勾选
            if error or frame is None:
                if was_card_preview_active:
                    self._card_preview_active.add(camera_id)
                    self._set_card_preview_checked(camera_id, True)
            # 恢复其他相机的卡片预览定时器
            if self._card_preview_active and card_timer_was_running:
                self._card_preview_timer.start(200 if len(self._card_preview_active) > 2 else 100)

            if error:
                self.shell.log(f"拍摄失败 ({camera_id}): {error}", "error")
                return
            if frame is None:
                self.shell.log(f"拍摄失败 ({camera_id}): 无数据", "warn")
                return
            ws = self.shell.workspace_multi()
            ok, msg = self.fixed_workflow.add_calibration_frame(frame)
            if not ok:
                self.shell.log(f"添加标定帧失败 ({camera_id}): {msg}", "warn")
            ws.camera_grid().set_frame(camera_id, frame)
            ws.camera_grid().set_frame_kind(camera_id, "标定帧")
            # 把单相机点云刷新到 3D 查看器（叠加显示）
            try:
                pcd = frame.load_pointcloud_o3d()
                if pcd is not None and len(pcd.points) > 0:
                    pts_arr = np.asarray(pcd.points)
                    n_total = len(pts_arr)
                    n_invalid = int((~np.isfinite(pts_arr).all(axis=1)).sum())
                    ws.viewer().set_pointcloud(camera_id, pcd)
                    self.shell.log(
                        f"点云已加载 ({camera_id}): {n_total} 点"
                        f"{f' (含 {n_invalid} 个无效点)' if n_invalid else ''}",
                        "info")
                else:
                    self.shell.log(f"点云为空 ({camera_id})", "warn")
            except Exception as e:
                self.shell.log(f"加载点云失败 ({camera_id}): {e}", "warn")
            # 如果已有标定帧，允许继续检测/计算，但不自动推进状态
            if ws.current_state() == "connected":
                ws.set_state("captured")
            self.shell.set_dirty(True)
            self.shell.log(f"拍摄完成 ({camera_id})", "success")

        self._run_background(_work, _done)

    def _on_card_detect(self, camera_id: str):
        """单相机卡片检测标记物。"""
        ws = self.shell.workspace_multi()
        card = ws.camera_grid().card(camera_id)
        if card is None:
            return
        frame = card.current_frame()

        # 若当前只有 2D 预览帧（无点云），先拍摄 3D 帧再检测
        if frame is None or frame.pointmap is None:
            self.shell.log(f"{camera_id} 无 3D 帧，先执行 3D 拍摄再检测", "info")
            self._capture_then_detect(camera_id)
            return

        self._run_detect_on_frame(camera_id, frame)

    def _capture_then_detect(self, camera_id: str):
        """先 3D 拍摄再对单相机卡片执行检测。"""
        if not self.camera_manager.is_connected(camera_id):
            self.shell.log(f"检测失败: 相机 {camera_id} 未连接", "warn")
            return
        # 停止该卡 2D 预览
        if camera_id in self._card_preview_active:
            self._card_preview_active.discard(camera_id)
            self._set_card_preview_checked(camera_id, False)
            if not self._card_preview_active:
                self._card_preview_timer.stop()

        self.shell.show_loading(f"正在拍摄并检测 {camera_id}...")

        def _work():
            return self.camera_manager.capture(camera_id)

        def _done(frame, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"拍摄失败 ({camera_id}): {error}", "error")
                return
            if frame is None:
                self.shell.log(f"拍摄失败 ({camera_id}): 无数据", "warn")
                return
            ws = self.shell.workspace_multi()
            ok, msg = self.fixed_workflow.add_calibration_frame(frame)
            if not ok:
                self.shell.log(f"添加标定帧失败 ({camera_id}): {msg}", "warn")
            ws.camera_grid().set_frame(camera_id, frame)
            ws.camera_grid().set_frame_kind(camera_id, "标定帧")
            if ws.current_state() == "connected":
                ws.set_state("captured")
            self.shell.set_dirty(True)
            self._run_detect_on_frame(camera_id, frame)

        self._run_background(_work, _done)

    def _run_detect_on_frame(self, camera_id: str, frame: FrameData):
        """对已有 3D 帧执行标记物检测并回填 UI。"""
        ws = self.shell.workspace_multi()
        method = ws.current_detect_method()
        self.marker_detector.set_marker_type(self._map_detect_method(method))

        self.shell.show_loading(f"正在检测 {camera_id}...")

        def _work():
            markers = self.marker_detector.detect_3d(
                frame.image_np,
                pointmap=frame.pointmap,
                rvc_image=frame.rvc_image,
                offline_ply_path=frame.offline_pointmap_path,
            )
            return markers

        def _done(markers, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"检测失败 ({camera_id}): {error}", "error")
                return
            frame.markers = markers
            count = len(markers)
            grid = ws.camera_grid()
            grid.set_frame(camera_id, frame, markers)
            grid.set_marker_count(camera_id, count)
            grid.set_covis_status(camera_id, count > 0)
            self.shell.log(f"检测完成 ({camera_id}): {count} 个标记", "success")

        self._run_background(_work, _done)

    def _map_detect_method(self, method: str) -> str:
        """把 UI 检测方式映射到 MarkerDetector 内部类型。"""
        if method == "calib_board":
            return "asymmetric_grid"
        return method or "coded_circle"

    # ------------------------------------------------------------------
    # 模式 B（单相机移动链式）
    # ------------------------------------------------------------------
    def _on_mobile_preview_toggled(self, enabled: bool):
        """实时取景开关。"""
        if not enabled:
            self._preview_timer.stop()
            self.shell.workspace_mobile().live_view().set_frame(None)
            self.shell.log("已停止实时取景", "info")
            return
        # 找到已连接的物理相机（模式 B 只有一台）
        connected = self.camera_manager.get_connected_ids()
        if not connected:
            self.shell.log("没有已连接相机，无法取景", "warn")
            self.shell.workspace_mobile()._btn_preview.setChecked(False)
            return
        self._preview_camera_id = connected[0]
        self._preview_timer.start(100)  # 10 fps
        self.shell.log(f"开始实时取景: {self._preview_camera_id}", "info")

    def _on_preview_tick(self):
        """定时抓取 2D 预览帧并更新 LiveViewPanel。"""
        if self._preview_camera_id is None:
            return
        try:
            frame = self.camera_manager.capture_2d_preview(self._preview_camera_id)
            if frame is None or frame.image_np is None:
                return
            pixmap = numpy_to_qpixmap(frame.image_np)
            if pixmap is not None:
                self.shell.workspace_mobile().live_view().set_frame(pixmap)
        except Exception as e:
            logger.warning(f"实时取景异常 ({self._preview_camera_id}): {e}")

    def _pause_2d_preview(self) -> Optional[str]:
        """暂停持续 2D 预览，返回之前正在预览的 camera_id（如无则 None）。

        RVC SDK 不允许同一 X2/X1 句柄上并发执行 Capture2D 与 Capture（3D）：
        M2600C 等三目相机的彩色 Extra 相机处于 2D 预览流时，直接调用 3D 拍摄
        会导致驱动状态冲突/崩溃。所有 3D 拍摄入口必须先调用本方法。
        """
        if not self._preview_timer.isActive():
            return None
        camera_id = self._preview_camera_id
        self._preview_timer.stop()
        # 同步 UI 按钮状态（避免用户以为预览仍在运行）
        ws = self.shell.workspace_mobile()
        if ws._btn_preview.isChecked():
            ws._btn_preview.setChecked(False)
        logger.info(f"已暂停 2D 预览（准备 3D 拍摄）: {camera_id}")
        return camera_id

    def _resume_2d_preview(self, camera_id: Optional[str]):
        """恢复之前暂停的 2D 预览。"""
        if camera_id is None:
            return
        connected = self.camera_manager.get_connected_ids()
        if camera_id not in connected:
            return
        self._preview_camera_id = camera_id
        self._preview_timer.start(100)
        ws = self.shell.workspace_mobile()
        if not ws._btn_preview.isChecked():
            ws._btn_preview.setChecked(True)
        logger.info(f"已恢复 2D 预览: {camera_id}")

    def _update_mobile_live_view(self, station_id: str):
        """把指定机位的 2D 图像与检测标记刷新到 LiveViewPanel。"""
        sm = self.mobile_workflow.station_manager
        if sm is None:
            return
        frame = sm.get_frame(station_id)
        if frame is None or frame.image_np is None:
            return
        pixmap = numpy_to_qpixmap(frame.image_np)
        if pixmap is None:
            return
        ws = self.shell.workspace_mobile()
        ws.live_view().set_frame(pixmap)
        # 标记叠加（归一化坐标）
        h, w = frame.image_np.shape[:2]
        if h > 0 and w > 0:
            markers = [
                (m.get('x_2d', m.get('x', 0)) / w,
                 m.get('y_2d', m.get('y', 0)) / h,
                 int(m.get('code', 0)),
                 False)
                for m in frame.markers
            ]
            ws.live_view().set_detection_overlay(markers)

    def _refresh_mobile_frame_to_ui(self, frame: FrameData):
        """把任意 FrameData 的 2D 图像与 3D 点云刷新到模式 B UI。

        用于配准失败帧：该帧已从 station_manager 删除，但 evaluation 中仍附带，
        需要直接由 frame 刷新，而不是通过 station_id 查询。
        """
        if frame is None or frame.image_np is None:
            return
        ws = self.shell.workspace_mobile()

        # 2D 画面
        pixmap = numpy_to_qpixmap(frame.image_np)
        if pixmap is not None:
            ws.live_view().set_frame(pixmap)
        # 标记叠加（归一化坐标）
        h, w = frame.image_np.shape[:2]
        if h > 0 and w > 0:
            markers = [
                (m.get('x_2d', m.get('x', 0)) / w,
                 m.get('y_2d', m.get('y', 0)) / h,
                 int(m.get('code', 0)),
                 False)
                for m in frame.markers
            ]
            ws.live_view().set_detection_overlay(markers)

        # 3D 点云（单帧预览）
        try:
            pcd = frame.load_pointcloud_o3d()
            if pcd is not None and len(pcd.points) > 0:
                ws.viewer().set_pointcloud_merged(pcd)
                self.shell.log(
                    f"单帧点云已加载: {len(pcd.points)} 点", "info")
        except Exception as e:
            self.shell.log(f"加载单帧点云失败: {e}", "warn")

    def _refresh_mobile_live_view_to_latest(self):
        """刷新 LiveViewPanel 为最新机位（撤销/删除后调用）。"""
        sm = self.mobile_workflow.station_manager
        if sm is None:
            return
        station_ids = sm.get_station_ids()
        if not station_ids:
            ws = self.shell.workspace_mobile()
            ws.live_view().set_frame(None)
            ws.live_view().set_detection_overlay([])
            return
        self._update_mobile_live_view(station_ids[-1])

    def _station_id_from_timeline_index(self, index: int) -> Tuple[Optional[str], int]:
        """把时间线索引映射为后端真实的 station_id。

        index 为 1-based 时间线索引；-1 表示当前/最新机位。
        返回 (station_id, timeline_index)。station_id 为 None 表示不存在。
        """
        ws = self.shell.workspace_mobile()
        stations = self.mobile_workflow.get_station_list()
        n = len(stations)
        if n == 0:
            return None, index
        if index == -1:
            timeline_index = n
        elif 1 <= index <= n:
            timeline_index = index
        else:
            return None, index
        # 优先用时间线节点上保存的 backend_ref，失败再按列表顺序回退
        station_id = ws.get_station_id(timeline_index)
        if station_id is None and stations:
            station_id = stations[timeline_index - 1].get('station_id')
        return station_id, timeline_index

    def _on_mobile_capture_station(self):
        """拍摄机位（自动配准）。"""
        preview_cam = self._pause_2d_preview()
        ws = self.shell.workspace_mobile()
        ws.set_state("capturing")
        self.shell.show_loading("正在拍摄机位...")
        def _work():
            ok, msg, evaluation = self.mobile_workflow.capture_station()
            # 拼接合并是耗时操作，放到后台线程执行
            merged = None
            if ok:
                merged = self.mobile_workflow.get_merged_pointcloud()
            return ok, msg, evaluation, merged

        def _done(result, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            if error:
                ws.set_state("chaining")
                self.shell.log(f"拍摄异常: {error}", "error")
                return
            ok, msg, evaluation, merged = result
            if evaluation:
                ws.on_evaluation_done(
                    evaluation.get('common_markers', 0),
                    evaluation.get('inlier_ratio', 0.0),
                    evaluation.get('rms_mm'),
                    'ok' if evaluation.get('success') else 'fail',
                    evaluation.get('suggestion', ''),
                    backend_ref=evaluation.get('station_id'),
                )
                # 无论配准成败，都先把当前帧的 2D/3D 数据显示出来
                # （失败帧已从 station_manager 删除， evaluation 中附带 frame）
                frame = evaluation.get('frame')
                station_id = evaluation.get('station_id')
                if frame is not None:
                    self._refresh_mobile_frame_to_ui(frame)
                elif station_id:
                    self._update_mobile_live_view(station_id)
            else:
                ws.set_state("chaining")
            if ok:
                self.shell.log(f"机位配准成功: {msg}", "success")
                self.shell.set_dirty(True)
                # 刷新 3D 拼接（已在后台计算好）
                if merged is not None:
                    ws.viewer().set_pointcloud_merged(merged)
            else:
                self.shell.log(f"机位配准失败: {msg}", "warn")
        self._run_background(_work, _done)

    def _on_mobile_undo(self):
        """撤销上一机位（合并点云在后台计算）。"""
        ws = self.shell.workspace_mobile()
        self.shell.show_loading("正在撤销...")

        def _work():
            ok, msg = self.mobile_workflow.undo_last_station()
            merged = None
            if ok:
                merged = self.mobile_workflow.get_merged_pointcloud()
            return ok, msg, merged

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"撤销异常: {error}", "error")
                return
            ok, msg, merged = result
            self.shell.log(msg, "info" if ok else "warn")
            if ok:
                self.shell.set_dirty(True)
                ws.on_undo_done()
                self._refresh_mobile_live_view_to_latest()
                if merged is not None:
                    ws.viewer().set_pointcloud_merged(merged)

        self._run_background(_work, _done)

    def _on_mobile_recapture(self, index: int):
        """重拍指定机位（index 为时间线索引，-1 表示当前/最新机位）。"""
        preview_cam = self._pause_2d_preview()
        ws = self.shell.workspace_mobile()

        # 时间线索引 → 后端机位 ID（考虑拍废删除导致的错位）
        station_id, timeline_index = self._station_id_from_timeline_index(index)
        if station_id is None:
            self._resume_2d_preview(preview_cam)
            self.shell.log("重拍失败: 指定机位不存在", "warn")
            return

        # 若目标为已固定的参考机位，先询问是否重置整条链并重新拍摄
        reset_for_reference = False
        if (self.mobile_workflow._chain_stitcher is not None and
                station_id == self.mobile_workflow._chain_stitcher._reference_id and
                len(self.mobile_workflow._chain_stitcher.nodes) > 1):
            reply = QMessageBox.question(
                self.shell, "重拍参考机位",
                "参考机位已固定，重拍将清空整条链并回到初始状态。\n是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)
            if reply != QMessageBox.Yes:
                self._resume_2d_preview(preview_cam)
                self.shell.log("已取消重拍参考机位", "info")
                return
            ok, msg = self.mobile_workflow.reset_chain()
            if not ok:
                self._resume_2d_preview(preview_cam)
                self.shell.log(f"重拍失败: {msg}", "warn")
                return
            ws.reset_session()
            reset_for_reference = True
            timeline_index = 1  # 重置后拍摄的是新的 #1

        ws.set_state("capturing")
        self.shell.show_loading(f"正在重拍 #{timeline_index}...")

        def _work():
            if reset_for_reference:
                ok, msg, evaluation = self.mobile_workflow.capture_station()
            else:
                ok, msg, evaluation = self.mobile_workflow.recapture_station(station_id)
            # 拼接合并是耗时操作，放到后台线程执行
            merged = None
            if ok:
                merged = self.mobile_workflow.get_merged_pointcloud()
            return ok, msg, evaluation, merged

        def _done(result, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            if error:
                ws.set_state("chaining")
                self.shell.log(f"重拍异常: {error}", "error")
                return
            ok, msg, evaluation, merged = result
            if evaluation:
                level = 'ok' if evaluation.get('success') else 'fail'
                if reset_for_reference:
                    # 重置后按新机位入链
                    ws.on_evaluation_done(
                        evaluation.get('common_markers', 0),
                        evaluation.get('inlier_ratio', 0.0),
                        evaluation.get('rms_mm'),
                        level,
                        evaluation.get('suggestion', ''),
                        backend_ref=evaluation.get('station_id'),
                    )
                else:
                    # 非参考机位重拍会删除旧机位并在链尾插入新机位，
                    # 直接用后端机位列表重建时间线，避免索引错位
                    ws.set_stations(self.mobile_workflow.get_station_evaluations())
                    ws.set_evaluation(
                        evaluation.get('common_markers', 0),
                        evaluation.get('inlier_ratio', 0.0),
                        evaluation.get('rms_mm'),
                        level,
                        evaluation.get('suggestion', ''),
                    )
                # 无论重拍成败，都先刷新当前帧 2D/3D
                frame = evaluation.get('frame')
                new_station_id = evaluation.get('station_id')
                if frame is not None:
                    self._refresh_mobile_frame_to_ui(frame)
                elif new_station_id:
                    self._update_mobile_live_view(new_station_id)
            else:
                ws.set_state("chaining")
            if ok:
                self.shell.log(f"重拍成功: {msg}", "success")
                self.shell.set_dirty(True)
                # 刷新 3D 拼接（已在后台计算好）
                if merged is not None:
                    ws.viewer().set_pointcloud_merged(merged)
            else:
                self.shell.log(f"重拍失败: {msg}", "warn")

        self._run_background(_work, _done)

    def _on_mobile_delete_station(self, index: int):
        """删除指定机位（index 为时间线索引）。"""
        station_id, _ = self._station_id_from_timeline_index(index)
        if station_id is None:
            self.shell.log("删除失败: 指定机位不存在", "warn")
            return

        ok, msg = self.mobile_workflow.delete_station(station_id)
        # 参考机位已固定：需要二次确认是否重置整条链
        if not ok and "参考机位已固定" in msg:
            reply = QMessageBox.question(
                self.shell, "删除参考机位",
                "参考机位已固定，删除将清空整条链并回到初始状态。\n是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)
            if reply != QMessageBox.Yes:
                self.shell.log("已取消删除参考机位", "info")
                return
            ok, msg = self.mobile_workflow.reset_chain()

        self.shell.log(msg, "success" if ok else "warn")
        if not ok:
            return
        self.shell.set_dirty(True)
        ws = self.shell.workspace_mobile()
        # 按后端当前机位列表重建时间线，避免误清整条链
        evaluations = self.mobile_workflow.get_station_evaluations()
        ws.set_stations(evaluations)
        self._refresh_mobile_live_view_to_latest()

        # 拼接合并是耗时操作，放到后台线程执行
        self.shell.show_loading("正在刷新拼接点云...")

        def _work():
            return self.mobile_workflow.get_merged_pointcloud()

        def _done(merged, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"刷新点云失败: {error}", "error")
                return
            if merged is not None:
                ws.viewer().set_pointcloud_merged(merged)

        self._run_background(_work, _done)

    def _on_mobile_station_selected(self, index: int):
        """时间线选中机位：在 2D 实时取景区显示该机位图像。"""
        station_id, _ = self._station_id_from_timeline_index(index)
        if station_id is None:
            return
        self._update_mobile_live_view(station_id)

    def _on_mobile_optimize(self):
        """全局优化（拼接合并点云在后台计算）。"""
        self.shell.show_loading("正在全局优化...")
        def _work():
            ok, msg, before_mm, after_mm = self.mobile_workflow.optimize_global()
            # 拼接合并是耗时操作，放到后台线程执行
            merged = None
            if ok:
                merged = self.mobile_workflow.get_merged_pointcloud()
            return ok, msg, before_mm, after_mm, merged

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"优化异常: {error}", "error")
                return
            ok, msg, before_mm, after_mm, merged = result
            self.shell.log(msg, "success" if ok else "warn")
            if ok:
                self.shell.set_dirty(True)
                ws = self.shell.workspace_mobile()
                ws.on_optimize_done(before_mm, after_mm)
                # 刷新 3D 拼接（已在后台计算好）
                if merged is not None:
                    ws.viewer().set_pointcloud_merged(merged)
        self._run_background(_work, _done)

    def _on_mobile_save(self):
        """保存拼接数据：合并点云 PLY + 误差报告 JSON。"""
        self.shell.show_loading("正在保存拼接数据...")

        def _work():
            report = self.mobile_workflow.get_error_report()
            if not report:
                return False, "无机位数据可保存", None
            session_dir = report.get('session_dir')
            if not session_dir:
                return False, "会话目录未知，无法保存", None
            os.makedirs(session_dir, exist_ok=True)

            merged = self.mobile_workflow.get_merged_pointcloud()
            ply_path = os.path.join(session_dir, "merged.ply")
            if merged is not None:
                import open3d as o3d
                o3d.io.write_point_cloud(ply_path, merged)
            else:
                ply_path = None

            json_path = os.path.join(session_dir, "error_report.json")
            import json
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

            return True, f"会话已保存: {session_dir}", {
                "session_dir": session_dir,
                "ply_path": ply_path,
                "json_path": json_path,
            }

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"保存失败: {error}", "error")
                return
            ok, msg, paths = result
            self.shell.log(msg, "success" if ok else "warn")
            if ok and paths:
                if paths.get("ply_path"):
                    self.shell.log(f"点云: {paths['ply_path']}", "info")
                self.shell.log(f"报告: {paths['json_path']}", "info")

        self._run_background(_work, _done)

    def _on_mobile_offline_load(self):
        """离线加载单相机站位会话目录并自动拼接。"""
        from PySide6.QtWidgets import QFileDialog

        base = self.mobile_workflow.session_dir or "offline_data/stations"
        session_dir = QFileDialog.getExistingDirectory(
            self.shell, "选择单相机会话目录", base)
        if not session_dir:
            return

        self.shell.show_loading("正在离线加载会话...")

        def _work():
            ok, msg = self.mobile_workflow.load_session_dir(session_dir)
            if not ok:
                return False, msg, None, None
            evaluations = self.mobile_workflow.get_station_evaluations()
            merged = self.mobile_workflow.get_merged_pointcloud()
            report = self.mobile_workflow.get_error_report()
            return True, msg, evaluations, (merged, report)

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"离线加载失败: {error}", "error")
                return
            ok, msg, evaluations, data = result
            self.shell.log(msg, "success" if ok else "warn")
            if not ok or not evaluations:
                return

            ws = self.shell.workspace_mobile()
            ws.reset_session()
            ws.set_stations(evaluations)
            ws.set_state("chaining" if len(evaluations) < 3 else "ready")
            self.shell.set_dirty(True)

            merged, report = data
            if merged is not None:
                ws.viewer().set_pointcloud_merged(merged)
                self.shell.log(
                    f"合并点云已显示: {len(merged.points)} 点", "info")
            if report:
                self.shell.log(
                    f"节点 {report.get('n_nodes', 0)} 边 {report.get('n_edges', 0)} "
                    f"累计误差 {report.get('cum_rms_mm', 0):.3f}mm", "info")

        self._run_background(_work, _done)

    # ------------------------------------------------------------------
    # 主窗口
    # ------------------------------------------------------------------
    def _on_save_session(self):
        """保存当前会话（标定帧 + 扫描帧 + 外参）。"""
        self.shell.show_loading("正在保存会话...")

        def _work():
            if self._current_mode == LauncherDialog.MODE_MULTI_CAM:
                return self._save_fixed_session()
            if self._current_mode == LauncherDialog.MODE_TURNTABLE:
                return self._save_turntable_session()
            return self._save_mobile_session()

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"保存会话失败: {error}", "error")
                self.shell.session_save_finished.emit(False, str(error))
                return
            ok, msg = result
            self.shell.log(msg, "success" if ok else "warn")
            if ok:
                self.shell.set_dirty(False)
            self.shell.session_save_finished.emit(ok, msg)

        self._run_background(_work, _done)

    def _save_fixed_session(self) -> Tuple[bool, str]:
        """保存多相机模式会话。"""
        session = OfflineSession()
        session.create_new("offline_data")
        # 保存标定帧
        for cid, frame in self.fixed_workflow.frames_calib.items():
            session.add_frame(cid, frame)
        # 保存扫描帧（使用递增 frame_id 避免覆盖）
        scan_frames = self.fixed_workflow.frames_scan
        if scan_frames:
            max_id = 0
            for flist in session.frames.values():
                for f in flist:
                    max_id = max(max_id, f.frame_id)
            for cid, frame in scan_frames.items():
                frame.frame_id = max_id + 1
                session.add_frame(cid, frame)
        session.save_all()
        return True, f"会话已保存: {session.session_dir}"

    def _save_mobile_session(self) -> Tuple[bool, str]:
        """保存单相机移动拼接会话。"""
        report = self.mobile_workflow.get_error_report()
        if not report:
            return False, "无机位数据可保存"
        # StationManager 已在拍摄时存盘，这里只返回会话路径
        return True, f"移动拼接会话已保存: {report.get('session_dir', 'unknown')}"

    def _save_turntable_session(self) -> Tuple[bool, str]:
        """保存转台 360° 拼接会话（序列帧 + 标定元数据）。"""
        import json
        ws = self.shell.workspace_turntable()
        session = ws.session
        frames = session.get_all_frames()
        if not frames:
            return False, "无转台帧数据可保存"

        offline = OfflineSession()
        offline.create_new("offline_data")
        for frame in frames:
            cam_id = getattr(frame, "camera_name", None) or "cam0"
            offline.add_frame(cam_id, frame)

        meta = {
            "mode": "turntable",
            "step_count": session.step_count(),
            "total_steps_needed": session.total_steps_needed(),
            "current_step": session.current_step,
        }
        calib = session.calib
        if calib.is_calibrated():
            meta["angle_deg"] = float(np.degrees(calib.angle_rad))
            meta["axis"] = (
                calib.axis.tolist() if calib.axis is not None else None)
            meta["center"] = (
                calib.center.tolist() if calib.center is not None else None)

        try:
            meta_path = os.path.join(offline.session_dir, "turntable_meta.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存转台元数据失败: {e}")

        offline.save_all()
        return True, f"转台会话已保存: {offline.session_dir}"

    def _on_open_session(self):
        """打开离线会话并加载帧。"""
        from PySide6.QtWidgets import QFileDialog
        base = os.path.abspath("offline_data")
        os.makedirs(base, exist_ok=True)
        path = QFileDialog.getExistingDirectory(
            self.shell, "选择会话目录", base)
        if not path:
            return
        self.shell.show_loading("正在加载会话...")

        def _work():
            session = OfflineSession()
            frames = session.load_session(path)
            return session, frames

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"加载会话失败: {error}", "error")
                return
            session, frames = result
            self._load_session_into_workflow(session, frames, path)

        self._run_background(_work, _done)

    def _load_session_into_workflow(self, session: OfflineSession,
                                    frames: Dict[str, List[FrameData]],
                                    path: str):
        """把加载的会话帧回填到当前工作流与 UI。"""
        if self._current_mode == LauncherDialog.MODE_MULTI_CAM:
            # 取每台相机的最新帧作为标定帧
            latest = {cid: flist[-1] for cid, flist in frames.items() if flist}
            if not latest:
                self.shell.log("会话为空，无标定帧可加载", "warn")
                return

            # 确保工作流处于标定阶段；先 reset 再 start，避免历史状态干扰
            self.fixed_workflow.reset()
            ref_id = self.fixed_workflow.reference_id
            if ref_id not in latest:
                ref_id = sorted(latest.keys())[0]
            ok, msg = self.fixed_workflow.start_calibration(ref_id)
            if not ok:
                self.shell.log(f"加载会话失败: {msg}", "error")
                return

            failed = []
            for cid, frame in latest.items():
                ok, msg = self.fixed_workflow.add_calibration_frame(frame)
                if not ok:
                    failed.append(cid)
                    self.shell.log(f"加载 {cid} 标定帧失败: {msg}", "warn")

            if failed:
                self.shell.log(
                    f"部分相机标定帧未加载: {failed}，已回到连接状态", "warn")
                self.shell.workspace_multi().set_state("connected")
                return

            ws = self.shell.workspace_multi()
            ws.reset_camera_grid(list(latest.keys()), enable_controls=False)
            for cid, frame in latest.items():
                ws.camera_grid().set_frame(cid, frame, frame.markers)
            ws.set_state("captured")
            self.shell.set_dirty(True)
            self.shell.log(
                f"会话加载完成: {len(latest)} 台相机标定帧已恢复", "success")
        elif self._current_mode == LauncherDialog.MODE_MOBILE_CHAIN:
            # 模式 B：加载会话暂不恢复时间线，仅记录
            self.shell.log(
                f"模式 B（单相机移动拼接）会话已读取 {len(frames)} 台相机数据，"
                "时间线恢复待实现", "warn")
        else:
            # 模式 C：当前未实现会话恢复
            self.shell.log(
                "模式 C（转台 360° 拼接）暂不支持从会话恢复数据，"
                "请重新拍摄/标定", "warn")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _run_background(self, work, on_done):
        """后台执行 work()，完成后主线程回调 on_done(result, error)。"""
        from ui.worker_thread import WorkerThread
        worker = WorkerThread(work)
        self._workers.append(worker)

        def _wrapped_done(result, error):
            if worker in self._workers:
                self._workers.remove(worker)
            on_done(result, error)

        worker.finished.connect(_wrapped_done)
        worker.start()

    def cleanup(self):
        """清理资源（关闭窗口时调用）。"""
        # 停止实时取景
        self._preview_timer.stop()
        self._card_preview_timer.stop()
        self._card_preview_active.clear()
        # 等待所有后台任务结束，避免 QThread 运行期间被销毁
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait(3000)
        self._workers.clear()
        self.camera_manager.shutdown()
