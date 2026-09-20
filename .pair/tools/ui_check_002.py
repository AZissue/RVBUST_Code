#!/usr/bin/env python3
"""真机验收脚本（turn 002）：像素→3D 的「在线/离线」+ 主 2D 视窗冻结/恢复。

用法：python .pair/tools/ui_check_002.py <pid> <数据文件夹>

逐步打印状态（JSON），并把关键画面存成截图，判定仍由 Codex 做。
"""

from __future__ import annotations

import json
import re
import sys
import time
import ctypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402
from PIL import ImageGrab, Image  # noqa: E402

REPORTS = REPO_ROOT / ".pair" / "reports"
POINT_RE = re.compile(r"^-?\d+\.\d{3}, -?\d+\.\d{3}, -?\d+\.\d{3}$")


def main() -> int:
    pid = int(sys.argv[1])
    folder = sys.argv[2]
    main_window = ui.main_window(pid)
    hwnd = ui._top_hwnd(pid)
    user32 = ctypes.WinDLL("user32")

    def all_ctl(ctype):
        out = []
        for ctrl in main_window.descendants():
            try:
                if ctrl.element_info.control_type == ctype:
                    out.append(ctrl)
            except Exception:
                continue
        return out

    def by_text(ctype, text):
        return [c for c in all_ctl(ctype) if c.window_text() == text]

    def field_for(label_text):
        labels = by_text("Text", label_text)
        if not labels:
            return None
        lab = labels[0].rectangle()
        best = None
        for ctrl in all_ctl("Edit"):
            rect = ctrl.rectangle()
            if rect.left < lab.right:
                continue
            if rect.bottom < lab.top or rect.top > lab.bottom:
                continue
            if best is None or rect.left < best[0]:
                best = (rect.left, ctrl)
        return best[1] if best else None

    def find_panel():
        windows = by_text("Window", "工具")
        return windows[0] if windows else None

    def open_panel():
        if find_panel() is None:
            ui.post_click(ui.find_button(main_window, "工具"), hwnd)
            deadline = time.time() + 5
            while time.time() < deadline and find_panel() is None:
                time.sleep(0.2)
        return find_panel()

    def select_tool(name):
        items = by_text("ListItem", name)
        if not items:
            raise RuntimeError(f"工具列表里没有 {name}")
        ui.post_click(items[0], hwnd)
        marker = "像素坐标" if name == "像素→3D" else "点 1 (x y z)"
        deadline = time.time() + 6
        while time.time() < deadline and not field_for(marker):
            time.sleep(0.2)
        if not field_for(marker):
            raise RuntimeError(f"切到 {name} 失败（没看到 {marker}）")
        return items[0].rectangle().top

    def shot(tag, crop=None):
        rect = main_window.rectangle()
        image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        path = REPORTS / f"002-{tag}.png"
        image.save(path)
        return path

    def view2d_brightness():
        """主 2D 视窗中心区域的平均亮度：实时图是纯黑，冻结文件图偏灰。"""
        rect = main_window.rectangle()
        image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        w, h = image.size
        crop = image.crop((int(w * 0.06), int(h * 0.25), int(w * 0.24), int(h * 0.55)))
        gray = crop.convert("L")
        pixels = list(gray.getdata())
        return round(sum(pixels) / max(1, len(pixels)), 2)

    def result_text():
        for ctrl in all_ctl("Text"):
            if POINT_RE.match(ctrl.window_text()):
                return ctrl.window_text()
        return ""

    print(json.dumps({"step": "panel-open", "ok": open_panel() is not None,
                      "brightness": view2d_brightness()}, ensure_ascii=False))

    select_tool("像素→3D")
    time.sleep(0.5)
    combos = [c for c in all_ctl("ComboBox") if c.rectangle().left > 850]
    print(json.dumps({"step": "mode-switch", "texts": [c.window_text() for c in combos]},
                     ensure_ascii=False))

    live_before = view2d_brightness()
    dir_field = field_for("数据文件夹")
    dir_field.set_edit_text(folder)          # 判据 7：打字也要刷新图像列表
    time.sleep(1.2)
    print(json.dumps({
        "step": "offline-folder",
        "dir": dir_field.window_text(),
        "image_combo": [c.window_text() for c in combos],
        "brightness_live_before": live_before,
        "brightness_after_freeze": view2d_brightness(),
        "shot": shot("offline-frozen").name,
    }, ensure_ascii=False))

    pixel_field = field_for("像素坐标")
    pixel_field.set_edit_text("5, 7")
    calc = sorted([c for c in by_text("Button", "计算")
                   if c.rectangle().top > pixel_field.rectangle().top],
                  key=lambda c: c.rectangle().top)[0]
    ui.post_click(calc, hwnd)
    time.sleep(0.6)
    print(json.dumps({"step": "typed-pixel", "result": result_text()}, ensure_ascii=False))

    # 主 2D 视窗上左键点击 → 像素坐标应当被填回输入框并重算
    rect = main_window.rectangle()
    click_x = rect.left + int((rect.right - rect.left) * 0.15)
    click_y = rect.top + int((rect.bottom - rect.top) * 0.45)
    # Posted clicks are swallowed by Qt's click-to-activate when the window is
    # not foreground, so bring the main window to the front first.
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    ui.click_at(hwnd, click_x, click_y)
    time.sleep(0.8)
    shown = pixel_field.window_text()
    print(json.dumps({"step": "click-main-2d", "pixel_field": shown,
                      "result": result_text()}, ensure_ascii=False))
    index = None
    if POINT_RE.match(result_text()):
        parts = [float(v) for v in result_text().split(",")]
        index = round(parts[0] - 0.125)
        print(json.dumps({"step": "index-check", "index_from_result": index,
                          "pixel_field_numeric": shown}, ensure_ascii=False))

    # 切到另一个工具页：主 2D 视窗应当恢复实时/采集图（回到纯黑）
    select_tool("欧氏距离")
    time.sleep(0.8)
    print(json.dumps({"step": "switch-tool-away",
                      "brightness": view2d_brightness(),
                      "shot": shot("after-switch-tool").name}, ensure_ascii=False))

    # 关掉工具面板
    close_btn = by_text("Button", "关闭")
    if close_btn:
        ui.post_click(close_btn[0], hwnd)
    time.sleep(0.8)
    print(json.dumps({"step": "panel-closed", "brightness": view2d_brightness(),
                      "shot": shot("after-close").name}, ensure_ascii=False))

    # 重新打开：主 2D 视窗不应再被冻结
    open_panel()
    time.sleep(0.8)
    print(json.dumps({"step": "panel-reopened", "brightness": view2d_brightness(),
                      "shot": shot("after-reopen").name}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
