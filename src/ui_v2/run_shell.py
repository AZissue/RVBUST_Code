# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
ui_v2.run_shell —— 新 UI 空壳的离线演示入口。

用法（项目根目录）：
    python -m src.ui_v2.run_shell          # 或把 src 加入 sys.path 后：
    python src/ui_v2/run_shell.py

说明：
  - 不连接任何相机 / PyRVC / OpenGL，全部设备与流程数据均为 mock；
  - 用于评审交互与视觉：模式分流、步骤门控、质量门禁、时间线评估等
    均可通过界面操作触发 mock 回调演示；
  - 正式接入时删除本文件中的 mock 逻辑，把信号接到 CameraManager /
    Workflow 即可（接口清单见 ui_v2/README.md）。
"""

from __future__ import annotations

import os
import sys

# 保证 src 包可导入（与 main.py 保持一致）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from ui_v2 import GLOBAL_QSS, LauncherDialog, MainWindowShell
from ui_v2.widgets.device_table import DeviceInfo


# ------------------------------------------------------------------ mock 数据
def make_mock_devices():
    """mock 设备列表（空壳演示用，正式接入时由 SDK 枚举替换）。"""
    return [
        DeviceInfo(model="M2600R", serial="SN260001", ip="192.168.1.10",
                   online=True),
        DeviceInfo(model="M2600R", serial="SN260002", ip="192.168.1.11",
                   online=True),
        DeviceInfo(model="M2000", serial="SN200077", ip="192.168.1.12",
                   online=True),
        DeviceInfo(model="X1", serial="SNX10031", ip="192.168.1.13",
                   online=False),
    ]


# ------------------------------------------------------------------ mock 后端编排
def wire_mock_backend(win: MainWindowShell):
    """把工作区信号接到 mock 回调，演示完整状态流转（正式接入时整段删除）。"""

    ws_a = win.workspace_multi()
    ws_b = win.workspace_mobile()

    # ---- 模式 A ----
    def a_capture(sync: bool):
        win.show_loading("拍摄标定帧中（mock）")
        QTimer.singleShot(600, lambda: (
            win.hide_loading(),
            ws_a.on_capture_done(),
            ws_a.set_state("captured"),
            win.log("拍摄完成（mock），请检测标记物", "success"),
        ))
    ws_a.capture_requested.connect(a_capture)

    def a_detect(method: str):
        win.show_loading("检测标记物中（mock）")
        mock_counts = {cid: 12 - i * 3 for i, cid in
                       enumerate(ws_a._camera_grid.camera_ids())}
        if mock_counts:
            mock_counts[list(mock_counts)[-1]] = 0  # 演示红色「未看到标定板」
        QTimer.singleShot(600, lambda: (
            win.hide_loading(),
            ws_a.on_detect_done(mock_counts),
            ws_a.set_state("detected"),
            win.log("检测完成（mock）", "success"),
        ))
    ws_a.detect_requested.connect(a_detect)

    def a_calibrate():
        win.show_loading("计算外参中（mock）")
        pairs = [
            {"pair": "cam0-cam1", "rms_mm": 0.42, "inlier_ratio": 0.94,
             "level": "ok"},
            {"pair": "cam0-cam2", "rms_mm": 1.10, "inlier_ratio": 0.88,
             "level": "warn"},
        ]
        QTimer.singleShot(700, lambda: (
            win.hide_loading(),
            ws_a.on_calibrate_done(pairs, score=86, quality_passed=True),
            ws_a.set_state("calibrated"),
            win.log("外参计算完成（mock），质量门禁通过", "success"),
        ))
    ws_a.calibrate_requested.connect(a_calibrate)

    # 质量门禁通过 → 进入扫描 Tab 时锁定外参
    ws_a._tabs.currentChanged.connect(
        lambda i: ws_a.set_state("locked")
        if i == 1 and ws_a.current_state() == "calibrated" and ws_a._quality_passed
        else None)

    ws_a.capture_scan_requested.connect(
        lambda: win.log("拍摄扫描帧（mock）：帧分区标签已切换", "info")
        or [ws_a._camera_grid.card(c).set_frame_kind("扫描帧")
            for c in ws_a._camera_grid.camera_ids()])
    ws_a.stitch_save_requested.connect(
        lambda: win.log("应用外参拼接并保存 PLY（接口预留）", "info"))
    ws_a.batch_scan_requested.connect(
        lambda n: win.log(f"连续拍摄 {n} 次批量拼接（接口预留）", "info"))

    # ---- 模式 B ----
    state = {"n": 0}

    def b_capture():
        ws_b.set_state("capturing")
        win.show_loading("拍摄机位 → 自动检测 → 匹配评估（mock）")

        def _finish():
            win.hide_loading()
            state["n"] += 1
            n = state["n"]
            # 演示三种评估结果循环：绿 / 黄 / 红
            mock_eval = [
                (12, 0.94, 0.42, "ok", "重合度充足，可继续移动"),
                (8, 0.71, 0.85, "warn", "可继续，建议减小移动距离"),
                (3, 0.40, None, "fail", "配准失败，请重拍或微调位置后重试"),
            ][(n - 1) % 3]
            markers = [(0.2 + 0.1 * i, 0.3 + 0.08 * i, 100 + i, i < 6)
                       for i in range(mock_eval[0])]
            ws_b.on_capture_done()
            ws_b.on_detection_done(markers)
            ws_b.on_evaluation_done(*mock_eval)
            ws_b.set_state("chaining")
            if ws_b._station_count >= 4:
                ws_b.on_loop_closure_detected()
        QTimer.singleShot(900, _finish)
    ws_b.capture_station_requested.connect(b_capture)

    def b_undo():
        ws_b.on_undo_done()
        win.log("已撤销上一机位（mock）", "info")
    ws_b.undo_requested.connect(b_undo)

    ws_b.optimize_requested.connect(
        lambda: ws_b.on_optimize_done(before_mm=1.25, after_mm=0.38))
    ws_b.save_requested.connect(
        lambda: win.log("保存会话 + 点云 PLY + 误差报告（接口预留）", "info"))
    ws_b.recapture_requested.connect(
        lambda i: win.log(f"重拍机位 {i if i >= 0 else '当前'}（接口预留）", "info"))
    ws_b.delete_station_requested.connect(
        lambda i: win.log(f"删除机位 #{i}，后续链自动重算（接口预留）", "warn"))

    # ---- 顶部功能栏 ----
    win.save_session_requested.connect(
        lambda: win.log("保存会话（接口预留：scans/<mode>_session_时间戳/）", "info"))
    win.open_session_requested.connect(
        lambda: win.log("打开会话（接口预留）", "info"))


# ------------------------------------------------------------------ 入口
def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RVC 拼接工作站（UI 空壳）")
    app.setStyleSheet(GLOBAL_QSS)

    win = MainWindowShell()
    wire_mock_backend(win)

    launcher = LauncherDialog()
    launcher.set_devices(make_mock_devices())

    # 小窗信号（正式接入时接 SDK / CameraManager）
    launcher.refresh_requested.connect(
        lambda: launcher.set_devices(make_mock_devices()))
    launcher.auto_ip_requested.connect(
        lambda devs: win.log(f"自动设置 IP ×{len(devs)}（接口预留）", "info"))

    def on_connect(mode: str, devices: list):
        launcher.accept()
        win.set_mode(mode, devices)
        win.show()

    launcher.connect_requested.connect(on_connect)

    if launcher.exec() != QDialog.Accepted:
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
