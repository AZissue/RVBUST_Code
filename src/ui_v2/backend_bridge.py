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
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMessageBox

from core.camera_manager import CameraManager
from core.fixed_multi_cam_workflow import FixedMultiCamWorkflow
from core.mobile_chain_workflow import MobileChainWorkflow
from core.marker_detector import MarkerDetector
from core.calibration_engine import CalibrationEngine
from core.stitch_engine import StitchEngine
from core.point_cloud_processor import PointCloudProcessor
from core.offline_session import OfflineSession
from core.utils import logger
from ui.camera_card import numpy_to_qpixmap

from .launcher_dialog import LauncherDialog
from .main_window import MainWindowShell
from .widgets.device_table import DeviceInfo


class BackendBridge(QObject):
    """ui_v2 与 core 模块的桥接器。"""

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

        # 模式 B 实时取景定时器
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._on_preview_tick)
        self._preview_camera_id: Optional[str] = None

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
        ws.reference_changed.connect(self._on_multi_reference_changed)
        ws.step_back_requested.connect(self._on_multi_step_back)

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

    def _wire_main_window(self):
        """接线主窗口。"""
        self.shell.save_session_requested.connect(self._on_save_session)
        self.shell.open_session_requested.connect(self._on_open_session)
        self.shell.postprocess_applied.connect(self._on_postprocess_applied)

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

    def _on_device_manager_reopened(self, mode: str, devices: List[DeviceInfo]):
        """设备管理小窗确认：断开旧设备 → 连接新设备 → 切换工作区。"""
        self.shell.show_loading("正在连接设备...")
        # 断开旧设备
        self.camera_manager.disconnect_all()

        # 连接新设备
        def _connect():
            results = []
            for dev in devices:
                idx = dev.backend_ref if isinstance(dev.backend_ref, int) else 0
                camera_id = f"cam{len(self.camera_manager.camera_ids)}"
                self.camera_manager.add_camera(camera_id)
                ok, msg = self.camera_manager.connect(camera_id, idx)
                results.append((camera_id, ok, msg))
            return results

        def _done(results, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"连接设备异常: {error}", "error")
                return
            ok_count = sum(1 for _, ok, _ in results if ok)
            for cid, ok, msg in results:
                level = "success" if ok else "warn"
                self.shell.log(f"相机 {cid}: {msg}", level)
            self.shell.log(f"设备连接完成: {ok_count}/{len(results)} 台成功", "info")
            # 切换工作区
            self.shell.set_mode(mode, devices)
            self._current_mode = mode
            # 模式 B 需要初始化链式拼接会话
            if mode == LauncherDialog.MODE_MOBILE_CHAIN:
                ok, msg = self.mobile_workflow.start_chaining()
                self.shell.log(msg, "success" if ok else "warn")

        self._run_background(_connect, _done)

    # ------------------------------------------------------------------
    # 模式 A（多相机外参标定）
    # ------------------------------------------------------------------
    def _on_multi_capture(self, sync: bool):
        """拍摄标定帧。"""
        preview_cam = self._pause_2d_preview()
        self.shell.show_loading("正在拍摄标定帧...")
        def _work():
            return self.camera_manager.capture_all(sync=sync)
        def _done(frames, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            if error:
                self.shell.log(f"拍摄失败: {error}", "error")
                return
            if not frames:
                self.shell.log("拍摄失败：无已连接相机", "warn")
                return
            # 更新工作流标定帧
            for cid, frame in frames.items():
                self.fixed_workflow.add_calibration_frame(frame)
            ws = self.shell.workspace_multi()
            # 更新各相机卡片预览
            for cid, frame in frames.items():
                ws.camera_grid().set_frame(cid, frame)
            ws.on_capture_done()
            ws.set_state("captured")
            self.shell.log(f"拍摄完成: {len(frames)} 台相机", "success")
        self._run_background(_work, _done)

    def _on_multi_detect(self, method: str):
        """检测标记物。"""
        self.shell.show_loading("正在检测标记物...")
        def _work():
            marker_counts = {}
            for cid, frame in self.fixed_workflow.frames_calib.items():
                markers = self.marker_detector.detect_3d(
                    frame.image_np,
                    pointmap=frame.pointmap,
                    rvc_image=frame.rvc_image,
                    offline_ply_path=frame.offline_pointmap_path,
                )
                frame.markers = markers
                marker_counts[cid] = len(markers)
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
            score = 100 if ok else 50
            ws = self.shell.workspace_multi()
            # 设置参考相机，viewer 中参考相机显示为白色
            ws.viewer().set_reference(self.calibration_engine.reference_id)
            ws.on_calibrate_done(pairs, score, ok)
            if ok:
                ws.set_state("calibrated")
                self.shell.log(f"标定完成: {msg}", "success")
            else:
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
        """加载外参。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self.shell, "加载外参", "", "JSON 文件 (*.json)")
        if path:
            ok, msg = self.fixed_workflow.load_calibration(path)
            self.shell.log(msg, "success" if ok else "error")
            if ok:
                self.shell.workspace_multi().set_state("locked")

    def _on_multi_capture_scan(self):
        """拍摄扫描帧。"""
        preview_cam = self._pause_2d_preview()
        self.shell.show_loading("正在拍摄扫描帧...")
        def _work():
            return self.camera_manager.capture_all(sync=True)
        def _done(frames, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            if error:
                self.shell.log(f"扫描拍摄失败: {error}", "error")
                return
            ws = self.shell.workspace_multi()
            for cid, frame in frames.items():
                self.fixed_workflow.add_scan_frame(frame)
                ws.camera_grid().set_frame(cid, frame)
                ws.camera_grid().set_frame_kind(cid, "扫描帧")
            self.shell.log(f"扫描帧拍摄完成: {len(frames)} 台相机", "success")
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
                # 保存
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

    def _on_multi_reference_changed(self, camera_id: str):
        """参考相机变更。"""
        self.calibration_engine.reference_id = camera_id
        self.shell.workspace_multi().viewer().set_reference(camera_id)
        self.shell.log(f"参考相机: {camera_id}", "info")

    def _on_multi_step_back(self, index: int):
        """步骤回退。"""
        self.shell.log(f"步骤回退到: {index}", "info")
        # TODO: 根据步骤索引重置工作流状态

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
        frame = self.camera_manager.capture_2d_preview(self._preview_camera_id)
        if frame is None or frame.image_np is None:
            return
        pixmap = numpy_to_qpixmap(frame.image_np)
        if pixmap is not None:
            self.shell.workspace_mobile().live_view().set_frame(pixmap)

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

    def _on_mobile_capture_station(self):
        """拍摄机位（自动配准）。"""
        preview_cam = self._pause_2d_preview()
        self.shell.show_loading("正在拍摄机位...")
        def _work():
            return self.mobile_workflow.capture_station()
        def _done(result, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            if error:
                self.shell.log(f"拍摄异常: {error}", "error")
                return
            ok, msg, evaluation = result
            ws = self.shell.workspace_mobile()
            if evaluation:
                ws.on_evaluation_done(
                    evaluation.get('common_markers', 0),
                    evaluation.get('inlier_ratio', 0.0),
                    evaluation.get('rms_mm'),
                    'ok' if evaluation.get('success') else 'fail',
                    evaluation.get('suggestion', ''),
                )
            if ok:
                self.shell.log(f"机位配准成功: {msg}", "success")
                # 刷新 3D 拼接
                merged = self.mobile_workflow.get_merged_pointcloud()
                if merged is not None:
                    ws.viewer().set_pointcloud_merged(merged)
            else:
                self.shell.log(f"机位配准失败: {msg}", "warn")
        self._run_background(_work, _done)

    def _on_mobile_undo(self):
        """撤销上一机位。"""
        ok, msg = self.mobile_workflow.undo_last_station()
        self.shell.log(msg, "info" if ok else "warn")
        self.shell.workspace_mobile().on_undo_done()

    def _on_mobile_recapture(self, index: int):
        """重拍指定机位。"""
        preview_cam = self._pause_2d_preview()
        station_id = f"station_{index}"
        self.shell.show_loading(f"正在重拍 {station_id}...")

        def _work():
            return self.mobile_workflow.recapture_station(station_id)

        def _done(result, error):
            self.shell.hide_loading()
            self._resume_2d_preview(preview_cam)
            if error:
                self.shell.log(f"重拍异常: {error}", "error")
                return
            ok, msg, evaluation = result
            ws = self.shell.workspace_mobile()
            if evaluation:
                ws.on_evaluation_done(
                    evaluation.get('common_markers', 0),
                    evaluation.get('inlier_ratio', 0.0),
                    evaluation.get('rms_mm'),
                    'ok' if evaluation.get('success') else 'fail',
                    evaluation.get('suggestion', ''),
                )
            if ok:
                self.shell.log(f"重拍成功: {msg}", "success")
                merged = self.mobile_workflow.get_merged_pointcloud()
                if merged is not None:
                    ws.viewer().set_pointcloud_merged(merged)
            else:
                self.shell.log(f"重拍失败: {msg}", "warn")

        self._run_background(_work, _done)

    def _on_mobile_delete_station(self, index: int):
        """删除指定机位。"""
        station_id = f"station_{index}"
        ok, msg = self.mobile_workflow.delete_station(station_id)
        self.shell.log(msg, "success" if ok else "warn")
        if ok:
            ws = self.shell.workspace_mobile()
            ws.on_undo_done()
            merged = self.mobile_workflow.get_merged_pointcloud()
            if merged is not None:
                ws.viewer().set_pointcloud_merged(merged)

    def _on_mobile_optimize(self):
        """全局优化。"""
        self.shell.show_loading("正在全局优化...")
        def _work():
            return self.mobile_workflow.optimize_global()
        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"优化异常: {error}", "error")
                return
            ok, msg = result
            self.shell.log(msg, "success" if ok else "warn")
            if ok:
                ws = self.shell.workspace_mobile()
                ws.on_optimize_done(0.0, 0.0)  # TODO: 传入实际误差
        self._run_background(_work, _done)

    def _on_mobile_save(self):
        """保存拼接数据。"""
        report = self.mobile_workflow.get_error_report()
        if report:
            self.shell.log(f"会话已保存: {report.get('n_nodes', 0)} 机位", "success")
        else:
            self.shell.log("无会话数据可保存", "warn")

    # ------------------------------------------------------------------
    # 主窗口
    # ------------------------------------------------------------------
    def _on_save_session(self):
        """保存当前会话（标定帧 + 扫描帧 + 外参）。"""
        self.shell.show_loading("正在保存会话...")

        def _work():
            if self._current_mode == LauncherDialog.MODE_MULTI_CAM:
                return self._save_fixed_session()
            else:
                return self._save_mobile_session()

        def _done(result, error):
            self.shell.hide_loading()
            if error:
                self.shell.log(f"保存会话失败: {error}", "error")
                return
            ok, msg = result
            self.shell.log(msg, "success" if ok else "warn")
            if ok:
                self.shell.set_dirty(False)

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
            self._load_session_into_workflow(session, frames)
            self.shell.log(f"会话加载完成: {path}（{len(frames)} 台相机）", "success")

        self._run_background(_work, _done)

    def _load_session_into_workflow(self, session: OfflineSession,
                                    frames: Dict[str, List[FrameData]]):
        """把加载的会话帧回填到当前工作流与 UI。"""
        if self._current_mode == LauncherDialog.MODE_MULTI_CAM:
            # 取每台相机的最新帧作为标定帧
            latest = {cid: flist[-1] for cid, flist in frames.items() if flist}
            for cid, frame in latest.items():
                self.fixed_workflow.add_calibration_frame(frame)
            ws = self.shell.workspace_multi()
            ws.camera_grid().set_cameras(list(latest.keys()))
            for cid, frame in latest.items():
                ws.camera_grid().set_frame(cid, frame, frame.markers)
            ws.set_state("captured")
        else:
            # 模式 B：加载会话暂不恢复时间线，仅记录
            self.shell.log("模式 B 会话加载：已加载帧数据，时间线恢复待实现", "info")

    def _on_postprocess_applied(self, params: dict):
        """后处理参数应用。"""
        crop_radius = params.get("crop_radius_mm", 0.0)
        voxel = params.get("voxel_mm", 0.0)
        outlier_nb = params.get("outlier_neighbors", 0)

        self.processor.crop_mode = "sphere" if crop_radius > 0 else "none"
        self.processor.crop_radius = crop_radius if crop_radius > 0 else 500.0
        self.processor.enable_voxel_downsample = voxel > 0
        self.processor.voxel_size = voxel if voxel > 0 else 0.5
        self.processor.enable_outlier_removal = outlier_nb > 0
        self.processor.outlier_nb_neighbors = outlier_nb if outlier_nb > 0 else 20

        self.shell.log(
            f"后处理参数已应用: 裁切={crop_radius:.2f}mm, "
            f"下采样={voxel:.2f}mm, 离群点邻域={outlier_nb}", "info")

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
        # 等待所有后台任务结束，避免 QThread 运行期间被销毁
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait(3000)
        self._workers.clear()
        self.camera_manager.shutdown()
