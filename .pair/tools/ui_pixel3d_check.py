#!/usr/bin/env python3
"""真机验收：驱动正在运行的 GUI 走一遍「像素→3D」离线取点，回读界面上的原始结果。

复用上一版留下的 `.codex-loop/tools/ui.py`（UIA 助手：优先用 InvokePattern /
posted mouse messages，不动物理鼠标）。

用法：
    python .pair/tools/ui_pixel3d_check.py <pid> <数据文件夹> "5, 7" ["1000, 1000" ...]

每个像素打印一段 JSON：界面上的结果行、提示行、以及当前页可见的全部文字控制
（带矩形），判定（对真值）由 Codex 做——脚本只负责取原始值，不做判断。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402


def controls(root, ctype=None, text=None):
    out = []
    for ctrl in root.descendants():
        try:
            info = ctrl.element_info
            if ctype is not None and info.control_type != ctype:
                continue
            name = ctrl.window_text()
        except Exception:
            continue
        if text is not None and name != text:
            continue
        out.append((name, ctrl))
    return out


def field_for(root, label_text):
    """表单行：标签右边的那个 Edit（QFormLayout 的固定布局）。"""
    labels = [c for _, c in controls(root, "Text", label_text)]
    if not labels:
        raise RuntimeError(f"找不到标签：{label_text}")
    label_rect = labels[0].rectangle()
    best = None
    for _, ctrl in controls(root, "Edit"):
        rect = ctrl.rectangle()
        if rect.left < label_rect.right:
            continue
        if rect.bottom < label_rect.top or rect.top > label_rect.bottom:
            continue
        if best is None or rect.left < best[0]:
            best = (rect.left, ctrl)
    if best is None:
        raise RuntimeError(f"找不到 {label_text} 的输入框")
    return best[1]


def panel_visible_texts(root, panel_rect):
    rows = []
    for name, ctrl in controls(root, "Text"):
        rect = ctrl.rectangle()
        if (rect.left >= panel_rect.left and rect.top >= panel_rect.top
                and rect.right <= panel_rect.right
                and rect.bottom <= panel_rect.bottom):
            rows.append({"text": name, "top": rect.top})
    return sorted(rows, key=lambda r: (r["top"], r["text"]))


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    pid = int(sys.argv[1])
    folder = sys.argv[2]
    pixels = sys.argv[3:]

    main_window = ui.main_window(pid)
    hwnd = ui._top_hwnd(pid)

    def post(ctrl):
        return ui.post_click(ctrl, hwnd)

    # 1) 工具面板：已经开着就用，没开就点「工具」按钮。
    panels = [c for name, c in controls(main_window, "Window", "工具")]
    if not panels:
        post(ui.find_button(main_window, "工具"))
        deadline = time.time() + 5
        while time.time() < deadline and not panels:
            panels = [c for name, c in controls(main_window, "Window", "工具")]
            time.sleep(0.2)
    if not panels:
        raise RuntimeError("工具面板没有打开")
    panel = panels[0]
    print(json.dumps({"step": "panel-open"}, ensure_ascii=False))

    # 2) 选中左侧「像素→3D」条目（页面靠 currentRowChanged 切换，必须真点一下）。
    post(ui.find_button(main_window, "像素→3D"))
    deadline = time.time() + 5
    while time.time() < deadline and not controls(main_window, "Text", "像素坐标"):
        time.sleep(0.2)
    if not controls(main_window, "Text", "像素坐标"):
        raise RuntimeError("像素→3D 页面没有切出来")
    print(json.dumps({"step": "select-tool", "tool": "像素→3D"}, ensure_ascii=False))

    # 3) 填数据文件夹，等图像下拉框自动选中第一张 png。
    field_for(main_window, "数据文件夹").set_edit_text(folder)
    print(json.dumps({"step": "set-folder", "value": folder}, ensure_ascii=False))
    time.sleep(1.0)

    pixel_field = field_for(main_window, "像素坐标")
    pixel_top = pixel_field.rectangle().top
    # 「计算」按钮是像素输入行**下方**的那个（上面还有别的工具页的同名按钮）。
    buttons = [c for _, c in controls(main_window, "Button", "计算")
               if c.rectangle().top > pixel_top]
    if not buttons:
        raise RuntimeError("找不到「计算」按钮")
    calc = sorted(buttons, key=lambda c: c.rectangle().top)[0]
    panel_rect = panel.rectangle()

    for pixel in pixels:
        pixel_field.set_edit_text(pixel)
        post(calc)
        time.sleep(0.6)
        print(json.dumps({
            "step": "query",
            "pixel": pixel,
            "visible_texts": panel_visible_texts(main_window, panel_rect),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
