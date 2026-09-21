#!/usr/bin/env python3
"""第 12 回合任务 2 的界面自检：设置 / 工具 两个窗口

判据（用户反馈原文：「内容多的时候窗口也跟着变大，确认按钮被任务栏挡住」）：
  1. 窗口带最大化按钮（与主窗口一样可缩放）；
  2. 把窗口缩到一个不大的尺寸后，「确定 / 取消」仍在窗口内、且整体在屏幕工作区内；
  3. 内容装不下时出现纵向滚动条（说明是滚动，而不是把窗口撑大）。

用法：python .pair/tools/ui_check_012.py
输出：逐步 JSON + 截图到 .pair/shots/round12/
说明：UIA 把这两个 QDialog 挂在主窗口节点下面（不是桌面根），所以控件一律从
      主窗口的子树里找。
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

SHOTS = REPO_ROOT / ".pair" / "shots" / "round12"
EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_STYLE = -16
WS_MAXIMIZEBOX = 0x00010000
WS_THICKFRAME = 0x00040000

OK_TEXTS = {"OK", "确定"}
CANCEL_TEXTS = {"Cancel", "取消"}


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def top_windows(pid: int):
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_hwnd(pid: int, title: str, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, text in top_windows(pid):
            if text == title:
                return hwnd
        time.sleep(0.2)
    return None


def work_area():
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def resize(hwnd, w, h):
    left, top, _, _ = window_rect(hwnd)
    user32.MoveWindow(hwnd, left, top, w, h, True)
    time.sleep(0.8)



def shot(hwnd, name):
    if not hwnd:
        return None
    l, t, r, b = window_rect(hwnd)
    if r - l < 8 or b - t < 8:      # 窗口已销毁/被移出屏幕，别拿空图骗自己
        return None
    SHOTS.mkdir(parents=True, exist_ok=True)
    img = ImageGrab.grab(bbox=(l, t, r, b))
    path = SHOTS / f"{name}.png"
    img.save(path)
    return str(path)



def buttons_of(win):
    found = {}
    try:
        for ctrl in win.descendants(control_type="Button"):
            try:
                found.setdefault(ctrl.window_text(), ctrl.rectangle())
            except Exception:
                continue
    except Exception:
        pass
    return found


def has_vertical_scrollbar(win):
    try:
        for ctrl in win.descendants(control_type="ScrollBar"):
            try:
                r = ctrl.rectangle()
                if r.height() > r.width():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def find_dialog(mw, title, timeout=6.0):
    """UIA 把模态对话框挂在主窗口节点下，用 descendants 找（UIAWrapper 没有
    child_window，那是 WindowSpecification 的接口）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for ctrl in mw.descendants(control_type="Window"):
                if ctrl.window_text() == title:
                    return ctrl
        except Exception:
            pass
        time.sleep(0.3)
    return None


def rect_of(ctrl):
    try:
        r = ctrl.rectangle()
        return [r.left, r.top, r.right, r.bottom]
    except Exception:
        return None


def client_rect(hwnd):
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def overflow_px(win, hwnd):
    """页面内容底边超出窗口客户区底边多少像素（<=0 = 完整可见）。

    比「有没有滚动条」可靠：Qt 的滚动区在 UIA 里不一定暴露成 ScrollBar 控件，
    但控件坐标一定对。判据：溢出 > 0 的页面必须自己带滚动条，否则就是把用户
    的内容顶到窗外——正是这次要修的问题。
    """
    cr = client_rect(hwnd)
    if cr is None:
        return None
    cl, _ct, crr, cb = cr
    worst = None
    for c in win.descendants():
        r = rect_of(c)
        if r is None:
            continue
        x, y, w, h = r
        if w <= 0 or h <= 0:
            continue
        if x < cl or x + w > crr:      # 横向溢出（下拉弹层等）另算，不算高度
            continue
        worst = y + h if worst is None else max(worst, y + h)
    return None if worst is None else worst - cb


def _text(ctrl):
    try:
        return ctrl.window_text()
    except Exception:
        return ""


def select_item(ctrl):
    """选页用 UIA 的 SelectionItemPattern——不移动鼠标，也不会误点到「关闭」。"""
    try:
        ctrl.iface_selection_item.Select()
        return "select"
    except Exception as exc:
        return f"error: {exc}"


def check_dialog(pid, mw, title, small_w, small_h):
    hwnd = find_hwnd(pid, title)
    if hwnd is None:
        return {"title": title, "found": False}

    dlg = find_dialog(mw, title)
    if dlg is None:
        return {"title": title, "found": True, "uia_error": "dialog node not found"}

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    res = {
        "title": title,
        "found": True,
        "maximize_box": bool(style & WS_MAXIMIZEBOX),
        "thick_frame": bool(style & WS_THICKFRAME),
        "shot_before": shot(hwnd, f"{title}_before"),
        "scrollbar_before": has_vertical_scrollbar(dlg),
    }

    resize(hwnd, small_w, small_h)
    l, t, r, b = window_rect(hwnd)
    wa = work_area()
    res.update({
        "requested": [small_w, small_h],
        "actual": [r - l, b - t],
        "inside_work_area": t >= wa[1] and b <= wa[3],
        "shot_small": shot(hwnd, f"{title}_small"),
    })

    btns = buttons_of(dlg)
    res["button_texts"] = sorted(btns)
    ok = next((btns[x] for x in OK_TEXTS if x in btns), None)
    cancel = next((btns[x] for x in CANCEL_TEXTS if x in btns), None)
    last = cancel or ok
    if last is not None:
        res["ok_button"] = rect_of_rect(ok)
        res["cancel_button"] = rect_of_rect(cancel)
        # 判据 2：底部那行按钮必须整个在窗口内，且不越过工作区下沿（任务栏）
        res["buttons_inside_window"] = t <= last.top and last.bottom <= b
        res["buttons_above_taskbar"] = last.bottom <= wa[3]
    res["scrollbar_after_shrink"] = has_vertical_scrollbar(dlg)
    res["overflow_px"] = overflow_px(dlg, hwnd)
    # 判据 3：缩到小尺寸后，内容要么完整可见，要么由滚动条接住
    ov = res["overflow_px"]
    res["content_ok"] = ov is None or ov <= 0 or res["scrollbar_after_shrink"]
    return res


def rect_of_rect(r):
    return None if r is None else [r.left, r.top, r.right, r.bottom]


def main() -> int:
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2

    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    pid = proc.pid
    say(started=pid)

    try:
        mw = None
        deadline = time.time() + 40
        while time.time() < deadline:
            if proc.poll() is not None:
                say(error=f"process exited early, code={proc.returncode}")
                return 3
            try:
                mw = ui.main_window(pid)
                break
            except Exception:
                time.sleep(0.5)
        if mw is None:
            say(error="main window not found", top=[t for _, t in top_windows(pid)])
            return 3
        time.sleep(1.5)

        out = {}
        main_hwnd = find_hwnd(pid, "手眼标定数据收集助手 V1.0")
        out["main_window"] = {
            "maximize_box": bool(user32.GetWindowLongW(main_hwnd, GWL_STYLE)
                                 & WS_MAXIMIZEBOX)}

        # ── 设置 ──
        ui.click(mw, "设置")
        time.sleep(1.2)
        out["settings"] = check_dialog(pid, mw, "设置", 560, 400)
        hwnd = find_hwnd(pid, "设置")
        if hwnd:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
            time.sleep(1.0)

        # ── 工具 ──
        ui.click(mw, "工具")
        time.sleep(1.5)
        out["tools"] = check_dialog(pid, mw, "工具", 660, 460)

        # 逐页看滚动：左列表 15 个条目，缩到最小尺寸后切一遍，看每页是否自己滚动
        # （页面自己滚 = 窗口不会再被内容撑大）。
        tool_hwnd = find_hwnd(pid, "工具")
        try:
            dlg = find_dialog(mw, "工具")
            # 15 个条目在原尺寸下才都被 UIA 枚举出来（窗口一小，Qt 只暴露可见项）
            sweep = {}
            items = [c for c in dlg.descendants(control_type="ListItem")
                     if _text(c)]
            out["tool_page_count"] = len(items)
            # 1) 默认尺寸下逐页切换，确认每页都能打开
            for ctrl in items:
                sweep[_text(ctrl)] = {"select": select_item(ctrl)}
                time.sleep(0.25)
            out["tool_page_sweep"] = sweep

            # 2) 缩到最小尺寸：窗口不许被内容撑大，每页内容要么完整可见、
            #    要么由页面自己的滚动条接住
            resize(tool_hwnd, 640, 440)
            time.sleep(0.6)
            l, t, r, b = window_rect(tool_hwnd)
            out["tools"]["actual_min"] = [r - l, b - t]
            at_min = {}
            for ctrl in dlg.descendants(control_type="ListItem"):
                name = _text(ctrl)
                if not name:
                    continue
                select_item(ctrl)
                time.sleep(0.25)
                ov = overflow_px(dlg, tool_hwnd)
                scrolls = has_vertical_scrollbar(dlg)
                at_min[name] = {
                    "overflow_px": ov,
                    "scrollbar": scrolls,
                    "ok": ov is None or ov <= 0 or scrolls,
                }
            out["tools"]["pages_at_min"] = at_min
            out["tools"]["bad_pages"] = [k for k, v in at_min.items() if not v["ok"]]
            out["tools"]["scrolling_pages"] = [k for k, v in at_min.items() if v["scrollbar"]]
            l, t, r, b = window_rect(tool_hwnd)
            out["tools"]["actual_after_sweep"] = [r - l, b - t]
            out["tools"]["shot_list"] = shot(tool_hwnd, "工具_最小尺寸")
        except Exception as exc:
            out["tool_pages_error"] = str(exc)

        # 关掉工具窗口，确认程序仍能正常收尾
        if tool_hwnd:
            user32.PostMessageW(tool_hwnd, 0x0010, 0, 0)
            time.sleep(0.8)

        say(**out)
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
