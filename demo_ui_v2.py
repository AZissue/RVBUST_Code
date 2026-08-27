# -*- coding: utf-8 -*-
"""
demo_ui_v2.py —— ui_v2 可视化演示外壳（无需相机 / 无需 RVC SDK）。

运行方式：
    "D:/Program Files/Anaconda/envs/rvc/python.exe" demo_ui_v2.py

说明：
    - 使用 ui_v2 的 LauncherDialog + MainWindowShell；
    - 用 MockBackendBridge 替代真实 core 模块，自动生成合成预览图、
      标定结果、机位评估数据；
    - 演示两种工作模式：多相机外参标定 / 单相机移动拼接；
    - 所有耗时操作使用 QTimer 模拟 0.5-1.5s 延迟，展示加载遮罩效果。
"""

from __future__ import annotations

import math
import os
import random
import sys
from datetime import datetime
from typing import Dict, List, Optional, Set

# 让 src 包可导入
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# 是否在离屏模式下生成截图
SCREENSHOT_MODE = "--screenshot" in sys.argv or os.environ.get("DEMO_SCREENSHOT") == "1"
if SCREENSHOT_MODE:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog

from ui_v2 import GLOBAL_QSS, LauncherDialog, MainWindowShell
from ui_v2.widgets.device_table import DeviceInfo
from version import get_version

# 截图/演示默认模式：multi / mobile / turntable
if "--mode=turntable" in sys.argv:
    DEMO_MODE = LauncherDialog.MODE_TURNTABLE
elif "--mode=mobile" in sys.argv:
    DEMO_MODE = LauncherDialog.MODE_MOBILE_CHAIN
else:
    DEMO_MODE = LauncherDialog.MODE_MULTI_CAM


# ---------------------------------------------------------------------------
# 合成图像生成
# ---------------------------------------------------------------------------

def _random_color(base: int, variance: int) -> int:
    return max(0, min(255, base + random.randint(-variance, variance)))


def make_synthetic_image(
    width: int = 640,
    height: int = 480,
    camera_index: int = 0,
    markers: Optional[List[Dict]] = None,
    marker_color: QColor = QColor("#4CAF50"),
) -> np.ndarray:
    """生成一张带暗色工业背景 + 标定板 + 标记点的合成 uint8 BGR 图。"""
    # 深色渐变背景
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / height
        r = int(30 + t * 20 + random.randint(-3, 3))
        g = int(32 + t * 18 + random.randint(-3, 3))
        b = int(38 + t * 15 + random.randint(-3, 3))
        img[y, :] = (b, g, r)

    # 随机画一个灰色标定板区域
    board_w, board_h = width // 2, height // 2
    bx = (width - board_w) // 2 + random.randint(-20, 20)
    by = (height - board_h) // 2 + random.randint(-20, 20)
    cv_color = (200, 200, 200)
    img[by : by + board_h, bx : bx + board_w] = cv_color

    # 为每台相机加点色调区分
    tint = [(0, 0, 0), (20, 0, 0), (0, 20, 0), (0, 0, 20)][camera_index % 4]
    img = np.clip(img.astype(int) + tint, 0, 255).astype(np.uint8)

    # 绘制标记点
    if markers is None:
        # 默认生成 5-10 个随机绿色标记
        n = random.randint(5, 10)
        markers = []
        for i in range(n):
            mx = bx + 30 + int((board_w - 60) * random.random())
            my = by + 30 + int((board_h - 60) * random.random())
            markers.append({"x": mx, "y": my, "code": 100 + i})

    for m in markers:
        x, y = int(m["x"]), int(m["y"])
        if 0 <= x < width and 0 <= y < height:
            # 绿色圆环
            for dy in range(-8, 9):
                for dx in range(-8, 9):
                    dist = math.hypot(dx, dy)
                    if 6 <= dist <= 8:
                        py, px = y + dy, x + dx
                        if 0 <= px < width and 0 <= py < height:
                            img[py, px] = (marker_color.blue(), marker_color.green(), marker_color.red())
            # 中心点
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    py, px = y + dy, x + dx
                    if 0 <= px < width and 0 <= py < height:
                        img[py, px] = (255, 255, 255)

    return img


def make_full_frame_image(width: int = 1440, height: int = 1080) -> np.ndarray:
    """生成一张占满整个画面的测试图（无深色边框），用于验证 cover 铺满效果。"""
    img = np.full((height, width, 3), 180, dtype=np.uint8)
    # 加一些色调变化和角标，让画面有内容可辨
    for y in range(height):
        t = y / height
        img[y, :, 0] = np.clip(180 - t * 30, 0, 255).astype(np.uint8)
        img[y, :, 1] = np.clip(180 - t * 20, 0, 255).astype(np.uint8)
        img[y, :, 2] = np.clip(180 - t * 10, 0, 255).astype(np.uint8)
    # 画几个绿色圆点作为标记
    import math
    n = 8
    for i in range(n):
        x = int(width * (0.15 + 0.7 * i / max(1, n - 1)))
        y = int(height * (0.2 + 0.6 * (i % 3) / 2.0))
        for dy in range(-10, 11):
            for dx in range(-10, 11):
                if 8 <= math.hypot(dx, dy) <= 10:
                    py, px = y + dy, x + dx
                    if 0 <= px < width and 0 <= py < height:
                        img[py, px] = (0, 255, 0)
    return img


def numpy_to_qpixmap(arr: np.ndarray) -> QPixmap:
    """BGR uint8 numpy 数组 → QPixmap。"""
    if arr is None or arr.size == 0:
        return QPixmap()
    h, w = arr.shape[:2]
    # OpenCV 默认 BGR，QImage 需要 RGB
    rgb = arr[..., ::-1] if arr.shape[2] == 3 else arr
    image = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(image)


# ---------------------------------------------------------------------------
# 模拟后端
# ---------------------------------------------------------------------------

class MockBackendBridge:
    """ui_v2 的模拟后端：不依赖 RVC SDK，用合成数据驱动 UI。"""

    def __init__(self, shell: MainWindowShell):
        self.shell = shell
        self._devices: List[DeviceInfo] = []
        self._camera_ids: List[str] = []
        self._current_mode: str = LauncherDialog.MODE_MULTI_CAM
        self._multi_state: int = 0  # 0=connected, 1=captured, 2=detected, 3=calibrated, 4=locked
        self._mobile_station_count: int = 0
        self._card_preview_active: Set[str] = set()
        # 与真实 BackendBridge 保持接口兼容（转台模式会注入这些对象）
        self.camera_manager = None
        self.marker_detector = None

    # ------------------------------------------------------------------
    # 接线
    # ------------------------------------------------------------------
    def wire_all(self):
        self.shell.device_manager_reopened.connect(self._on_device_manager_reopened)

        ws_a = self.shell.workspace_multi()
        ws_a.capture_requested.connect(self._on_multi_capture)
        ws_a.detect_requested.connect(self._on_multi_detect)
        ws_a.calibrate_requested.connect(self._on_multi_calibrate)
        ws_a.save_extrinsics_requested.connect(self._on_multi_save_extrinsics)
        ws_a.load_extrinsics_requested.connect(self._on_multi_load_extrinsics)
        ws_a.capture_scan_requested.connect(self._on_multi_capture_scan)
        ws_a.stitch_save_requested.connect(self._on_multi_stitch_save)
        ws_a.batch_scan_requested.connect(self._on_multi_batch_scan)
        ws_a.reference_changed.connect(self._on_multi_reference_changed)
        ws_a.step_back_requested.connect(self._on_multi_step_back)
        ws_a.card_preview_toggled.connect(self._on_card_preview_toggled)
        ws_a.card_capture_requested.connect(self._on_card_capture)
        ws_a.card_detect_requested.connect(self._on_card_detect)

        ws_b = self.shell.workspace_mobile()
        ws_b.capture_station_requested.connect(self._on_mobile_capture_station)
        ws_b.preview_toggled.connect(self._on_mobile_preview_toggled)
        ws_b.undo_requested.connect(self._on_mobile_undo)
        ws_b.recapture_requested.connect(self._on_mobile_recapture)
        ws_b.delete_station_requested.connect(self._on_mobile_delete_station)
        ws_b.optimize_requested.connect(self._on_mobile_optimize)
        ws_b.save_requested.connect(self._on_mobile_save)
        ws_b.station_selected.connect(self._on_mobile_station_selected)

        self.shell.save_session_requested.connect(self._on_save_session)
        self.shell.open_session_requested.connect(self._on_open_session)
        self.shell.postprocess_applied.connect(self._on_postprocess_applied)

    # ------------------------------------------------------------------
    # 设备管理
    # ------------------------------------------------------------------
    def enumerate_devices(self) -> List[DeviceInfo]:
        return make_mock_devices()

    def _on_device_manager_reopened(self, mode: str, devices: List[DeviceInfo]):
        self.shell.show_loading("正在连接设备...")
        self._devices = list(devices)
        self._camera_ids = [f"cam{i}" for i in range(len(devices))]
        self._current_mode = mode

        def _done():
            if mode == LauncherDialog.MODE_MULTI_CAM:
                self.shell.workspace_multi().set_state("connected")
                self._multi_state = 0
                self.shell.log(f"已进入多相机模式（{len(devices)} 台设备）", "success")
            elif mode == LauncherDialog.MODE_MOBILE_CHAIN:
                self.shell.workspace_mobile().set_state("connected")
                self._mobile_station_count = 0
                self.shell.log("已进入单相机移动拼接模式", "success")
            else:
                self.shell.workspace_turntable().set_state("connected")
                self.shell.log("已进入转台 360° 拼接模式", "success")
            self.shell.hide_loading()

        QTimer.singleShot(1200, _done)

    # ------------------------------------------------------------------
    # 模式 A：多相机外参标定
    # ------------------------------------------------------------------
    def _on_multi_capture(self, sync: bool):
        self.shell.show_loading("正在拍摄标定帧...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_multi()
            for i, cid in enumerate(self._camera_ids):
                img = make_synthetic_image(camera_index=i)
                ws.camera_grid().set_frame(cid, _frame_from_image(img))
                ws.camera_grid().set_frame_kind(cid, "标定帧")
            ws.on_capture_done()
            ws.set_state("captured")
            self._multi_state = 1
            self.shell.set_dirty(True)
            self.shell.log(f"拍摄完成: {len(self._camera_ids)} 台相机", "success")

        QTimer.singleShot(1000, _done)

    def _on_multi_detect(self, method: str):
        self.shell.show_loading("正在检测标记物...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_multi()
            counts = {}
            for i, cid in enumerate(self._camera_ids):
                # 随机标记数，但保证大部分相机能看到
                count = random.randint(4, 12) if i != 2 else random.randint(0, 3)
                counts[cid] = count
                ws.camera_grid().set_marker_count(cid, count)
                ws.camera_grid().set_covis_status(cid, count > 0)
                # 重新刷新帧以显示标记叠加
                img = make_synthetic_image(camera_index=i)
                markers = [{"x": 200 + j * 40, "y": 180 + j * 30, "code": 100 + j} for j in range(count)]
                ws.camera_grid().set_frame(cid, _frame_from_image(img), markers)
            ws.on_detect_done(counts)
            ws.set_state("detected")
            self._multi_state = 2
            self.shell.log(f"检测完成: 共 {sum(counts.values())} 个标记", "success")

        QTimer.singleShot(1200, _done)

    def _on_multi_calibrate(self):
        self.shell.show_loading("正在计算外参...")

        def _done():
            self.shell.hide_loading()
            ref = self._camera_ids[0]
            pairs = []
            for cid in self._camera_ids[1:]:
                rms = round(random.uniform(0.15, 0.55), 2)
                inlier = round(random.uniform(0.82, 0.98), 2)
                level = "ok" if rms < 0.35 else "warn" if rms < 0.5 else "fail"
                pairs.append({"pair": f"{cid}->{ref}", "rms_mm": rms, "inlier_ratio": inlier, "level": level})

            ok = all(p["level"] != "fail" for p in pairs)
            score = int(min(100, max(0, 100 - max(p["rms_mm"] for p in pairs) * 40)))
            ws = self.shell.workspace_multi()
            ws.viewer().set_reference(ref)
            ws.on_calibrate_done(pairs, score, ok)
            if ok:
                ws.set_state("locked")
                self._multi_state = 4
                self.shell.log("外参已锁定，可进入扫描阶段", "success")
            else:
                ws.set_state("calibrated")
                self._multi_state = 3
                self.shell.log("标定完成，但部分 pair 质量不达标", "warn")
            self.shell.set_dirty(True)

        QTimer.singleShot(1500, _done)

    def _on_multi_save_extrinsics(self):
        self.shell.log("外参已保存（演示）", "success")

    def _on_multi_load_extrinsics(self):
        self.shell.show_loading("正在加载外参...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_multi()
            pairs = [
                {"pair": f"cam1->cam0", "rms_mm": 0.21, "inlier_ratio": 0.95, "level": "ok"},
                {"pair": f"cam2->cam0", "rms_mm": 0.33, "inlier_ratio": 0.91, "level": "ok"},
                {"pair": f"cam3->cam0", "rms_mm": 0.28, "inlier_ratio": 0.93, "level": "ok"},
            ]
            ws.viewer().set_reference("cam0")
            ws.on_calibrate_done(pairs, 95, True)
            ws.set_state("locked")
            self._multi_state = 4
            self.shell.log("外参已加载并进入扫描阶段", "success")
            self.shell.set_dirty(True)

        QTimer.singleShot(800, _done)

    def _on_multi_capture_scan(self):
        self.shell.show_loading("正在拍摄扫描帧...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_multi()
            for i, cid in enumerate(self._camera_ids):
                img = make_synthetic_image(camera_index=i, marker_color=QColor("#29B6F6"))
                ws.camera_grid().set_frame(cid, _frame_from_image(img))
                ws.camera_grid().set_frame_kind(cid, "扫描帧")
            self.shell.log("扫描帧拍摄完成", "success")

        QTimer.singleShot(1000, _done)

    def _on_multi_stitch_save(self):
        self.shell.show_loading("正在拼接点云...")

        def _done():
            self.shell.hide_loading()
            self.shell.log("拼接完成：12,580 点（演示数据）", "success")

        QTimer.singleShot(1200, _done)

    def _on_multi_batch_scan(self, n: int):
        self.shell.show_loading(f"批量扫描拼接 ({n} 次)...")

        def _done():
            self.shell.hide_loading()
            self.shell.log(f"批量扫描完成，共保存 {n} 帧", "success")

        QTimer.singleShot(1500, _done)

    def _on_multi_reference_changed(self, camera_id: str):
        self.shell.log(f"参考相机: {camera_id}", "info")

    def _on_multi_step_back(self, index: int):
        self.shell.log(f"请求回退到步骤 {index}（演示中仅记录）", "info")

    def _on_card_preview_toggled(self, camera_id: str, enabled: bool):
        ws = self.shell.workspace_multi()
        if enabled:
            self._card_preview_active.add(camera_id)
            self.shell.log(f"开始 2D 预览: {camera_id}", "info")
            # 模拟一次刷新
            idx = self._camera_ids.index(camera_id)
            img = make_synthetic_image(camera_index=idx)
            ws.camera_grid().set_frame(camera_id, _frame_from_image(img))
        else:
            self._card_preview_active.discard(camera_id)
            self.shell.log(f"停止 2D 预览: {camera_id}", "info")

    def _on_card_capture(self, camera_id: str):
        self.shell.show_loading(f"正在拍摄 {camera_id}...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_multi()
            idx = self._camera_ids.index(camera_id)
            img = make_synthetic_image(camera_index=idx)
            ws.camera_grid().set_frame(camera_id, _frame_from_image(img))
            ws.camera_grid().set_frame_kind(camera_id, "标定帧")
            if ws.current_state() == "connected":
                ws.set_state("captured")
                self._multi_state = 1
            self.shell.log(f"拍摄完成 ({camera_id})", "success")

        QTimer.singleShot(800, _done)

    def _on_card_detect(self, camera_id: str):
        self.shell.show_loading(f"正在检测 {camera_id}...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_multi()
            count = random.randint(5, 10)
            idx = self._camera_ids.index(camera_id)
            img = make_synthetic_image(camera_index=idx)
            markers = [{"x": 200 + j * 40, "y": 180 + j * 30, "code": 100 + j} for j in range(count)]
            ws.camera_grid().set_frame(camera_id, _frame_from_image(img), markers)
            ws.camera_grid().set_marker_count(camera_id, count)
            ws.camera_grid().set_covis_status(camera_id, count > 0)
            self.shell.log(f"检测完成 ({camera_id}): {count} 个标记", "success")

        QTimer.singleShot(800, _done)

    # ------------------------------------------------------------------
    # 模式 B：单相机移动链式
    # ------------------------------------------------------------------
    def _on_mobile_preview_toggled(self, enabled: bool):
        ws = self.shell.workspace_mobile()
        if enabled:
            self.shell.log("开始实时取景", "info")
            img = make_full_frame_image(1440, 1080)
            ws.live_view().set_frame(numpy_to_qpixmap(img))
        else:
            self.shell.log("已停止实时取景", "info")
            ws.live_view().set_frame(None)

    def _on_mobile_capture_station(self):
        self.shell.show_loading("正在拍摄机位...")
        ws = self.shell.workspace_mobile()
        ws.set_state("capturing")

        def _done():
            self.shell.hide_loading()
            self._mobile_station_count += 1
            shared = random.randint(3, 15)
            inlier = round(random.uniform(0.40, 0.98), 2)
            rms = round(random.uniform(0.10, 0.80), 2) if inlier > 0.6 else None

            if inlier >= 0.75 and rms is not None and rms < 0.50:
                level = "ok"
                suggestion = "重合度充足，可继续移动到下一机位"
            elif inlier >= 0.55:
                level = "warn"
                suggestion = "可继续，建议减小移动距离"
            else:
                level = "fail"
                suggestion = "配准失败，请重拍或微调位置后重试"
                rms = None

            ws.on_evaluation_done(shared, inlier, rms, level, suggestion)
            ws.set_state("chaining")

            # 刷新实时取景为当前帧
            img = make_full_frame_image(1440, 1080)
            markers = [
                {"x": 360 + j * 80, "y": 320 + j * 65, "code": 100 + j}
                for j in range(shared)
            ]
            ws.live_view().set_frame(numpy_to_qpixmap(img))
            ws.live_view().set_detection_overlay(
                [(m["x"] / 1440, m["y"] / 1080, m["code"], False) for m in markers]
            )

            if level == "ok":
                self.shell.log(f"机位 #{self._mobile_station_count} 配准成功", "success")
            elif level == "warn":
                self.shell.log(f"机位 #{self._mobile_station_count} 谨慎通过", "warn")
            else:
                self.shell.log(f"机位 #{self._mobile_station_count} 配准失败", "error")

            # 随机触发闭环提示
            if self._mobile_station_count >= 4 and random.random() > 0.5:
                ws.on_loop_closure_detected()
                self.shell.log("发现闭环，可执行全局优化", "warn")

            self.shell.set_dirty(True)

        QTimer.singleShot(1200, _done)

    def _on_mobile_undo(self):
        if self._mobile_station_count > 0:
            self._mobile_station_count -= 1
            ws = self.shell.workspace_mobile()
            ws.on_undo_done()
            self.shell.log("已撤销上一机位", "info")

    def _on_mobile_recapture(self, index: int):
        self.shell.show_loading("正在重拍...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_mobile()
            shared = random.randint(6, 14)
            inlier = round(random.uniform(0.75, 0.95), 2)
            rms = round(random.uniform(0.10, 0.40), 2)
            ws.on_recapture_done(
                index if index > 0 else self._mobile_station_count,
                shared, inlier, rms, "ok", "重拍成功，重合度良好"
            )
            self.shell.log("重拍完成", "success")

        QTimer.singleShot(1000, _done)

    def _on_mobile_delete_station(self, index: int):
        ws = self.shell.workspace_mobile()
        ws._timeline.remove_station(index)
        self._mobile_station_count = ws._timeline.station_count()
        ws._recompute_stats()
        self.shell.log(f"已删除机位 #{index}", "info")

    def _on_mobile_optimize(self):
        self.shell.show_loading("正在全局优化...")

        def _done():
            self.shell.hide_loading()
            ws = self.shell.workspace_mobile()
            ws.on_optimize_done(1.25, 0.38)
            self.shell.log("全局优化完成：误差 1.25mm → 0.38mm", "success")

        QTimer.singleShot(1500, _done)

    def _on_mobile_save(self):
        self.shell.log("拼接数据已保存（演示）", "success")

    def _on_mobile_station_selected(self, index: int):
        self.shell.log(f"选中机位 #{index}", "info")

    # ------------------------------------------------------------------
    # 主窗口通用
    # ------------------------------------------------------------------
    def _on_save_session(self):
        self.shell.log("会话已保存（演示）", "success")
        self.shell.set_dirty(False)

    def _on_open_session(self):
        self.shell.log("打开会话（演示中仅记录）", "info")

    def _on_postprocess_applied(self, params: dict):
        self.shell.log(f"后处理参数已应用: {params}", "info")


def _frame_from_image(image_np: np.ndarray):
    """构造一个最小 FrameData 对象供 camera_grid.set_frame 使用。"""
    class _Frame:
        def __init__(self, img):
            self.image_np = img
            self.markers = []
    return _Frame(image_np)


def make_mock_devices() -> List[DeviceInfo]:
    """生成演示用设备列表。"""
    return [
        DeviceInfo(model="M2600R", serial="SN-2024A", ip="192.168.1.10", online=True, backend_ref=0),
        DeviceInfo(model="M2600R", serial="SN-2024B", ip="192.168.1.11", online=True, backend_ref=1),
        DeviceInfo(model="X1", serial="SN-2024C", ip="192.168.1.12", online=False, backend_ref=2),
        DeviceInfo(model="M2000", serial="SN-2024D", ip="192.168.1.13", online=True, backend_ref=3),
    ]


# ---------------------------------------------------------------------------
# 截图辅助（离屏模式用）
# ---------------------------------------------------------------------------

SCREENSHOT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_demo_screenshots")


def screenshot_dir() -> str:
    if DEMO_MODE == LauncherDialog.MODE_MOBILE_CHAIN:
        sub = "mobile"
    elif DEMO_MODE == LauncherDialog.MODE_TURNTABLE:
        sub = "turntable"
    else:
        sub = "multi"
    path = os.path.join(SCREENSHOT_ROOT, sub)
    os.makedirs(path, exist_ok=True)
    return path


def grab_widget(widget, filename: str):
    """抓取控件并保存为 PNG（按当前演示模式分子目录）。"""
    directory = screenshot_dir()
    pixmap = widget.grab()
    path = os.path.join(directory, filename)
    pixmap.save(path)
    print(f"[screenshot] {path}")
    return path


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _load_fallback_font() -> str:
    """尝试加载系统中文字体；返回优先使用的字体家族名。"""
    candidates = [
        ("Noto Sans SC", "C:/Windows/fonts/NotoSansSC-VF.ttf"),
        ("Microsoft YaHei", "C:/Windows/fonts/msyh.ttc"),
        ("Microsoft YaHei", "C:/Windows/fonts/msyhbd.ttc"),
        ("SimHei", "C:/Windows/fonts/simhei.ttf"),
    ]
    for family, path in candidates:
        if os.path.exists(path):
            fid = QFontDatabase.addApplicationFont(path)
            if fid != -1:
                print(f"[demo] 加载字体: {path}")
                return family
    return "Microsoft YaHei"


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RVC 拼接工作站 - UI 演示")

    # 强制使用可渲染中文的字体（尤其离屏截图模式）
    font_family = _load_fallback_font()
    app.setFont(QFont(font_family, 10))
    # 在全局 QSS 后追加字体覆盖，确保优先级最高
    app.setStyleSheet(GLOBAL_QSS + f"""
        QWidget {{ font-family: "{font_family}", "Segoe UI", sans-serif; }}
    """)

    # 启动小窗
    launcher = LauncherDialog()
    launcher.set_devices(make_mock_devices())

    # 先切换模式（会清空勾选），再按模式预勾选设备
    launcher._set_mode(DEMO_MODE)
    if DEMO_MODE == LauncherDialog.MODE_MULTI_CAM:
        launcher._table._devices[0].checked = True
        launcher._table._devices[1].checked = True
    else:
        # 单相机移动拼接 / 转台 360° 拼接均只需 1 台
        launcher._table._devices[0].checked = True
    launcher._refresh_connect_state()

    # 创建主窗口（不显示）
    main_window = MainWindowShell()
    bridge = MockBackendBridge(main_window)
    bridge.wire_all()
    main_window.set_backend_bridge(bridge)

    def on_connect(mode: str, devices: list):
        # 与真实主程序一致：先渲染目标工作区 + loading，再后台连接
        main_window.set_mode(mode, devices)
        main_window.show()
        main_window.show_loading("正在连接相机...")
        bridge._on_device_manager_reopened(mode, devices)
        launcher.accept()

    launcher.connect_requested.connect(on_connect)
    launcher.auto_ip_requested.connect(
        lambda devs: main_window.log(f"自动设置 IP ×{len(devs)}（演示）", "info")
    )

    if SCREENSHOT_MODE:
        # 离屏截图模式：不阻塞在 launcher.exec()，直接 show 并截图后进入主窗口
        print(f"[demo] 截图模式启动，输出目录: {screenshot_dir()}")
        launcher.show()
        grab_widget(launcher, "00_launcher.png")
        mode = launcher.selected_mode()
        devices = launcher.selected_devices()
        on_connect(mode, devices)
        launcher.close()
    else:
        if launcher.exec() != QDialog.Accepted:
            return 0
        mode = launcher.selected_mode()
        devices = launcher.selected_devices()

    # on_connect 中已完成 set_mode / show / loading，这里只需设置标题
    main_window.setWindowTitle(
        f"RVC 拼接工作站 — {LauncherDialog.MODE_NAMES[mode]} {get_version()} [DEMO]")

    if SCREENSHOT_MODE:
        # 截图模式使用较大窗口，确保能看到 2D 预览 cover 铺满效果
        main_window.resize(1920, 1080)
        _run_screenshot_sequence(app, main_window, bridge, mode)
    else:
        # 演示自动进入第一步：多相机模式自动拍一张，单相机模式提示取景
        if mode == LauncherDialog.MODE_MULTI_CAM:
            QTimer.singleShot(800, lambda: bridge._on_multi_capture(True))
        elif mode == LauncherDialog.MODE_MOBILE_CHAIN:
            main_window.log("请点击「开始取景」后拍摄机位", "info")
        else:
            main_window.log("转台模式：请初始化 RVC 并连接相机后开始拍摄", "info")

    return app.exec()


def _run_screenshot_sequence(app: QApplication, main_window: MainWindowShell,
                             bridge: MockBackendBridge, mode: str):
    """离屏截图模式：自动执行操作序列并保存关键界面截图。"""
    print(f"[demo] 截图序列开始，输出目录: {screenshot_dir()}")

    steps: List[tuple] = []

    def wait(ms: int):
        return ("wait", ms)

    def shot(name: str):
        return ("shot", name)

    def act(fn):
        return ("act", fn)

    if mode == LauncherDialog.MODE_MULTI_CAM:
        steps = [
            wait(1500),  # 等待设备连接/模式切换完成
            shot("01_multi_connected.png"),
            act(lambda: bridge._on_multi_capture(True)),
            wait(1200),
            shot("02_multi_captured.png"),
            act(lambda: bridge._on_multi_detect("coded_circle")),
            wait(1300),
            shot("03_multi_detected.png"),
            act(lambda: bridge._on_multi_calibrate()),
            wait(1600),
            shot("04_multi_locked.png"),
            act(lambda: bridge._on_multi_capture_scan()),
            wait(1100),
            shot("05_multi_scan.png"),
            act(lambda: main_window._btn_log.setChecked(True)),
            wait(200),
            shot("06_multi_log_open.png"),
            act(lambda: main_window._btn_log.setChecked(False)),
            wait(200),
        ]
    else:
        steps = [
            wait(1500),  # 等待设备连接/模式切换完成
            shot("01_mobile_connected.png"),
            act(lambda: bridge._on_mobile_preview_toggled(True)),
            wait(300),
            shot("02_mobile_preview.png"),
            act(lambda: bridge._on_mobile_capture_station()),
            wait(1300),
            shot("03_mobile_station1.png"),
            act(lambda: bridge._on_mobile_capture_station()),
            wait(1300),
            shot("04_mobile_station2.png"),
            act(lambda: bridge._on_mobile_capture_station()),
            wait(1300),
            shot("05_mobile_station3_warn.png"),
        ]

    def _run_step(index: int):
        if index >= len(steps):
            print("[demo] 截图序列完成，即将退出")
            QTimer.singleShot(500, app.quit)
            return
        kind, value = steps[index]
        if kind == "wait":
            QTimer.singleShot(value, lambda: _run_step(index + 1))
        elif kind == "shot":
            grab_widget(main_window, value)
            QTimer.singleShot(100, lambda: _run_step(index + 1))
        elif kind == "act":
            value()
            QTimer.singleShot(50, lambda: _run_step(index + 1))

    QTimer.singleShot(500, lambda: _run_step(0))


if __name__ == "__main__":
    sys.exit(main())
