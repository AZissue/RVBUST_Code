#!/usr/bin/env python3
"""T-002 判据：3D 视窗里那条「识别后可点击场景中的点选择填充」提示**不再出现在视窗**，
而是进「操作日志」。

路径：连真机相机 → 预览 → 拍照 → 识别（产生 3D 标记，原逻辑此刻才显示那条提示）。
判定：把窗口里所有含该文案的控件按 x 分成两区——
  * x < 「操作日志」标题的 x  ⇒ 落在视窗区（老行为）⇒ 失败
  * x >= 那一列              ⇒ 落在日志面板 ⇒ 通过

用法：python reports/T-002/probe_pickhint.py [SN]
退出码：0 = 通过（文案只在日志里 / 视窗里没有）；1 = 失败；2 = 环境问题。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import ui  # noqa: E402
from PIL import ImageGrab  # noqa: E402

OUT = REPO_ROOT / "reports" / "T-002"
EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
SN = sys.argv[1] if len(sys.argv) > 1 else "I1GM112B652"
HINT = "识别后可点击场景中的点选择填充"
PROC: subprocess.Popen | None = None


def say(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def shot(name: str):
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.png"
        ImageGrab.grab().save(path)
        return str(path)
    except Exception as exc:  # noqa: BLE001
        return f"(shot failed: {exc})"


def hwnd_by_title(pid: int, title: str, timeout=6.0):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value == title:
                    found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def click_text(root, text, timeout=8.0) -> bool:
    """优先 UIA InvokePattern——不动物理鼠标、也不看谁在最前面。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for c in root.descendants(control_type="Button"):
            if c.window_text().strip() == text:
                try:
                    ui.activate(c)
                    return True
                except Exception:
                    try:
                        c.click_input()
                        return True
                    except Exception:
                        pass
        time.sleep(0.3)
    return False


def find_text_node(mw, text):
    for c in mw.descendants():
        try:
            if c.window_text().strip() == text:
                return c
        except Exception:
            continue
    return None


def hint_nodes(mw):
    out = []
    for c in mw.descendants():
        try:
            t = c.window_text()
        except Exception:
            continue
        if HINT in t:
            try:
                r = c.rectangle()
            except Exception:
                continue
            out.append({"type": c.element_info.control_type, "left": r.left,
                        "top": r.top, "text": t[:80]})
    return out


def main() -> int:
    global PROC
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    PROC = proc

    mw = None
    deadline = time.time() + 45
    while time.time() < deadline:
        if proc.poll() is not None:
            say(error=f"exited early code={proc.returncode}")
            return 2
        try:
            mw = ui.main_window(proc.pid)
            break
        except Exception:
            time.sleep(0.5)
    if mw is None:
        say(error="main window not found")
        return 2
    # 启动预扫描约 4 s；太早点「连接」只会记 pending，而对话框弹出后约 9 s 会自己关掉。
    time.sleep(13.0)

    # 启动预扫描没跑完时点「连接」不一定弹框——重试，别把启动竞态当成相机不可用。
    dlg = None
    for attempt in range(4):
        if not click_text(mw, "连接"):
            say(error="找不到『连接』按钮")
            return 2
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                say(error="进程退出", exit_code=proc.poll())
                return 2
            for c in mw.descendants(control_type="Window"):
                if c.window_text() == "选择相机设备":
                    dlg = c
                    break
            if dlg:
                break
            time.sleep(0.5)
        if dlg:
            break
        say(step=f"device dialog not up yet (attempt {attempt + 1})")
    if not dlg:
        say(error="设备对话框没出现")
        return 2
    row = None
    for c in dlg.descendants():
        try:
            if SN in c.window_text():
                row = c
                break
        except Exception:
            continue
    if row is None:
        say(error=f"设备列表里没有 {SN}")
        return 2
    dlg_hwnd = hwnd_by_title(proc.pid, "选择相机设备")
    if dlg_hwnd:
        ui.post_click(row, dlg_hwnd)
    else:
        row.click_input()
    time.sleep(0.5)
    for label in ("确定", "连接", "OK"):
        if click_text(dlg, label, timeout=1.5):
            break
    time.sleep(6.0)
    if proc.poll() is not None:
        say(error="连接阶段进程退出", exit_code=proc.poll())
        return 2
    say(step="connected")

    click_text(mw, "预览")
    time.sleep(5.0)
    click_text(mw, "拍照")
    time.sleep(6.0)
    if proc.poll() is not None:
        say(error="拍照阶段进程退出", exit_code=proc.poll())
        return 2
    click_text(mw, "识别")
    time.sleep(6.0)
    if proc.poll() is not None:
        say(error="识别阶段进程退出", exit_code=proc.poll())
        return 2
    say(step="captured + recognised", shot=shot("pickhint_after_recognise"))

    log_label = find_text_node(mw, "操作日志")
    log_left = None
    if log_label is not None:
        try:
            log_left = log_label.rectangle().left
        except Exception:
            log_left = None
    nodes = hint_nodes(mw)
    say(step="hint occurrences", log_left=log_left, nodes=nodes)

    if log_left is None:
        say(error="找不到『操作日志』标题，无法分区分流")
        return 2
    in_view = [n for n in nodes if n["left"] < log_left]
    in_log = [n for n in nodes if n["left"] >= log_left]
    say(result=("FAIL: 提示仍在视窗里" if in_view else "PASS: 视窗里没有该提示"),
        in_view=len(in_view), in_log=len(in_log))
    return 1 if in_view else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        if PROC is not None and PROC.poll() is None:
            PROC.terminate()
            try:
                PROC.wait(timeout=6)
            except subprocess.TimeoutExpired:
                PROC.kill()
    sys.exit(code)
