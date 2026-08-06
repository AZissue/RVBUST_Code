# -*- coding: utf-8 -*-
"""ui_v2 空壳离屏冒烟测试（QT_QPA_PLATFORM=offscreen，不开真实窗口）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PySide6.QtWidgets import QApplication

from ui_v2 import GLOBAL_QSS, LauncherDialog, MainWindowShell
from ui_v2.widgets.device_table import DeviceInfo
from ui_v2.widgets.station_timeline import StationNodeData


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"  ok: {name}")


def main():
    app = QApplication([])
    app.setStyleSheet(GLOBAL_QSS)

    # ---------- LauncherDialog ----------
    dlg = LauncherDialog()
    dlg.set_devices([
        DeviceInfo(model="M2600R", serial="SN1", ip="192.168.1.10", online=True),
        DeviceInfo(model="M2600R", serial="SN2", ip="192.168.1.11", online=True),
        DeviceInfo(model="X1", serial="SN3", ip="192.168.1.12", online=False),
    ])
    check("默认模式为多相机", dlg.selected_mode() == LauncherDialog.MODE_MULTI_CAM)
    check("未选设备时连接禁用", not dlg._btn_connect.isEnabled())

    # 勾选 2 台 → 多相机模式可连接
    dlg._table._devices[0].checked = True
    dlg._table._devices[1].checked = True
    dlg._refresh_connect_state()
    check("多相机选 2 台可连接", dlg._btn_connect.isEnabled())

    # 切到单相机模式：多选被清空，选 2 台提示不可连接
    dlg._set_mode(LauncherDialog.MODE_MOBILE_CHAIN)
    check("切模式清空多选", len(dlg.selected_devices()) == 0)
    dlg._table._devices[0].checked = True
    dlg._table._devices[1].checked = True
    dlg._refresh_connect_state()
    check("单相机选 2 台禁止连接", not dlg._btn_connect.isEnabled())
    dlg._table._devices[1].checked = False
    dlg._refresh_connect_state()
    check("单相机选 1 台可连接", dlg._btn_connect.isEnabled())

    # 搜索过滤
    dlg._table.apply_filter("M2600")
    hidden = [dlg._table.isRowHidden(r) for r in range(3)]
    check("搜索过滤生效（X1 被隐藏）", hidden == [False, False, True])

    # ---------- MainWindowShell ----------
    win = MainWindowShell()
    devices = dlg.selected_devices()
    win.set_mode(LauncherDialog.MODE_MOBILE_CHAIN, devices)
    check("模式 B 工作区切换", win._stack.currentWidget() is win.workspace_mobile())
    win.set_mode(LauncherDialog.MODE_MULTI_CAM, devices * 2)
    check("模式 A 工作区切换", win._stack.currentWidget() is win.workspace_multi())

    # 模式 A 状态机门控
    ws_a = win.workspace_multi()
    check("A 初始 connected", ws_a.current_state() == "connected")
    check("A 拍摄可用", ws_a._btn_capture.isEnabled())
    check("A 检测禁用（未拍摄）", not ws_a._btn_detect.isEnabled())
    ws_a.set_state("captured")
    check("A 检测可用", ws_a._btn_detect.isEnabled())
    ws_a.set_state("detected")
    check("A 计算外参可用", ws_a._btn_calibrate.isEnabled())
    ws_a.on_calibrate_done(
        [{"pair": "cam0-cam1", "rms_mm": 0.42, "inlier_ratio": 0.94, "level": "ok"}],
        score=90, quality_passed=True)
    ws_a.set_state("calibrated")
    check("A 质量门禁通过但扫描仍待锁定", not ws_a._btn_stitch_save.isEnabled())
    ws_a.set_state("locked")
    check("A 锁定后扫描可用", ws_a._btn_stitch_save.isEnabled())
    check("A 撤板横幅显示", not ws_a._lock_banner.isHidden())
    # 质量门禁失败场景
    ws_a.on_calibrate_done(
        [{"pair": "cam0-cam1", "rms_mm": 2.10, "inlier_ratio": 0.5, "level": "fail"}],
        score=30, quality_passed=False)
    ws_a.set_state("calibrated")
    check("A 门禁失败禁扫描", not ws_a._btn_scan_capture.isEnabled())

    # 模式 B 状态机与评估入链
    ws_b = win.workspace_mobile()
    win.set_mode(LauncherDialog.MODE_MOBILE_CHAIN, devices[:1])
    check("B 初始 connected", ws_b.current_state() == "connected")
    check("B 拍摄可用", ws_b._btn_capture.isEnabled())
    check("B 撤销禁用（无机位）", not ws_b._btn_undo.isEnabled())

    ws_b.on_detection_done([(0.3, 0.3, 101, True), (0.5, 0.5, 102, False)])
    ws_b.on_evaluation_done(12, 0.94, 0.42, "ok", "重合度充足，可继续移动")
    check("B 评估通过入链 1 机位", ws_b._station_count == 1)
    ws_b.on_evaluation_done(3, 0.40, None, "fail", "配准失败，请重拍")
    check("B 评估失败拒绝入链", ws_b._station_count == 1)
    check("B 撤销可用", ws_b._btn_undo.isEnabled())
    ws_b.on_undo_done()
    check("B 撤销后链清空", ws_b._station_count == 0)
    ws_b.on_loop_closure_detected()
    check("B 闭环提示显示", not ws_b._timeline._btn_loop.isHidden())
    ws_b.on_optimize_done(1.25, 0.38)
    check("B 优化后闭环提示隐藏", ws_b._timeline._btn_loop.isHidden())

    # 术语检查：模式 B 界面文案不得出现标定术语
    banned = ("参考相机", "pair", "RMS", "标定")
    texts = [ws_b._btn_capture.text(), ws_b._btn_undo.text(),
             ws_b._btn_save.text(), ws_b._stats_label.text(),
             ws_b._eval_card._head.text()]
    joined = " ".join(texts)
    check("模式 B 文案无标定术语", not any(b in joined for b in banned))

    # 主窗口日志/遮罩/状态栏
    win.log("冒烟测试日志", "info")
    check("日志面板写入", "冒烟测试日志" in win._log_panel._text.toPlainText())
    win.show_loading("测试")
    win.hide_loading()

    print("\n全部冒烟检查通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
