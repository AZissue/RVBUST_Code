#!/usr/bin/env python3
"""真机验收（turn 003）：冻结必须跟「像素→3D 页」绑定——5 条状态转换。

主 2D 视窗中心平均亮度：实时/采集图 = 0.0，被离线图冻结 ≈ 35.7。
真实鼠标点击（posted click 会被 Qt 的 click-to-activate 吞掉）。

用法：python .pair/tools/ui_check_003.py <pid> <数据文件夹>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

FOLDER = ""


def main() -> int:
    global FOLDER
    pid = int(sys.argv[1])
    FOLDER = sys.argv[2]
    main_window = ui.main_window(pid)
    hwnd = ui._top_hwnd(pid)

    def ctls(ctype, text=None):
        out = []
        for ctrl in main_window.descendants():
            try:
                if ctrl.element_info.control_type != ctype:
                    continue
                name = ctrl.window_text()
            except Exception:
                continue
            if text is None or name == text:
                out.append(ctrl)
        return out

    def panel_open():
        return bool(ctls("Window", "工具"))

    def brightness(tag):
        rect = main_window.rectangle()
        image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        image.save(REPO_ROOT / ".pair" / "reports" / f"003-{tag}.png")
        crop = image.convert("L").crop((100, 300, 500, 700))
        data = list(crop.getdata())
        return round(sum(data) / max(1, len(data)), 2)

    def open_panel():
        if not panel_open():
            ui.find_button(main_window, "工具").click_input()
            deadline = time.time() + 6
            while time.time() < deadline and not panel_open():
                time.sleep(0.2)
        if not panel_open():
            raise RuntimeError("工具面板没有打开")

    def close_panel():
        buttons = [c for c in ctls("Button", "关闭") if c.rectangle().top > 60]
        if not buttons:
            raise RuntimeError("找不到面板的关闭按钮")
        buttons[0].iface_invoke.Invoke()
        deadline = time.time() + 6
        while time.time() < deadline and panel_open():
            time.sleep(0.2)
        if panel_open():
            raise RuntimeError("面板没有关掉")

    def select_tool(name, marker):
        ctls("ListItem", name)[0].click_input()
        deadline = time.time() + 6
        while time.time() < deadline and not ctls("Text", marker):
            time.sleep(0.2)
        if not ctls("Text", marker):
            raise RuntimeError(f"切到 {name} 失败")
        time.sleep(0.5)

    def field_for(label_text):
        labels = ctls("Text", label_text)
        if not labels:
            return None
        lab = labels[0].rectangle()
        best = None
        for ctrl in ctls("Edit"):
            rect = ctrl.rectangle()
            if rect.left < lab.right:
                continue
            if rect.bottom < lab.top or rect.top > lab.bottom:
                continue
            if best is None or rect.left < best[0]:
                best = (rect.left, ctrl)
        return best[1] if best else None

    report = {"0-no-panel": brightness("no-panel")}

    open_panel()
    select_tool("欧氏距离", "点 1 (x y z)")
    report["1-panel-open-other-page"] = brightness("open-other-page")

    select_tool("像素→3D", "像素坐标")
    field_for("数据文件夹").set_edit_text(FOLDER)
    time.sleep(1.5)
    report["2-pixel3d-offline"] = brightness("pixel3d-offline")

    select_tool("欧氏距离", "点 1 (x y z)")
    report["3-switch-away"] = brightness("switch-away")

    select_tool("像素→3D", "像素坐标")
    report["4-switch-back"] = brightness("switch-back")

    select_tool("欧氏距离", "点 1 (x y z)")   # 复现回归场景：停在别的页再关
    close_panel()
    report["5-closed-on-other-page"] = brightness("closed-on-other-page")

    open_panel()
    time.sleep(1.0)
    report["6-reopened-on-other-page"] = brightness("reopened-on-other-page")

    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
