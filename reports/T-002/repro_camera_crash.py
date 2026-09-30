#!/usr/bin/env python3
"""T-002 复现探针：连上真相机以后点「预览」/「拍照」会不会把程序弄崩。

人的原话：「在我连接相机之后再点击预览或者拍照会导致程序闪退」。

用法：python reports/T-002/repro_camera_crash.py [SN]
      SN 默认 I1GM112B652。
输出：逐步 JSON + 截图到 reports/T-002/。
退出码：0 = 全程存活（没复现）；1 = 进程死了（复现）；2 = 环境/流程问题。
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
    """按标题找顶层 HWND（post_click 要用它把屏幕坐标换算成客户区坐标）。"""
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
    """点按钮：优先 UIA InvokePattern——不动物理鼠标、也不看谁在最前面。
    （物理鼠标点会被前台窗口挡走，T-002 探针在这上面翻过车。）"""
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


def main() -> int:
    if not EXE.exists():
        say(error=f"exe not found: {EXE}")
        return 2

    global PROC
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    PROC = proc
    pid = proc.pid
    say(started=pid, sn=SN)

    mw = None
    deadline = time.time() + 45
    while time.time() < deadline:
        if proc.poll() is not None:
            say(error=f"exited early code={proc.returncode}")
            return 2
        try:
            mw = ui.main_window(pid)
            break
        except Exception:
            time.sleep(0.5)
    if mw is None:
        say(error="main window not found")
        return 2
    time.sleep(2.0)
    # 启动预扫描约 4 s；在它跑完之前点「连接」只会记一个 pending 请求，
    # 而设备对话框本身弹出后约 9 s 会自己关掉 —— 所以先等够，再点、再看、马上操作。
    time.sleep(11.0)

    # ── 连接 ──
    # 启动预扫描（~4 s）没跑完时点「连接」只会记一个 pending 请求，对话框不一定弹；
    # 所以「点 → 等 → 没弹再点」重试，别把启动竞态当成"相机不可用"。
    def find_device_dialog():
        for c in mw.descendants(control_type="Window"):
            try:
                if c.window_text() == "选择相机设备":
                    return c
            except Exception:
                continue
        return None

    dlg = None
    for attempt in range(4):
        if not click_text(mw, "连接"):
            say(error="找不到『连接』按钮")
            return 2
        say(step=f"clicked 连接 (attempt {attempt + 1})",
            shot=shot(f"cam_00_connect_clicked_{attempt + 1}"))
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                say(error="进程在选设备前就退了", exit_code=proc.poll())
                return 1
            dlg = find_device_dialog()
            if dlg is not None:
                break
            time.sleep(0.5)
        if dlg is not None:
            break
    if dlg is None:
        say(error="设备选择对话框没出现（没扫到相机？）",
            shot=shot("cam_01_no_dialog"))
        return 2
    say(step="device dialog up", shot=shot("cam_02_device_dialog"))

    # 设备表是 QTableWidget，UIA 不一定把它暴露成 ListItem——按**名字**扫所有控件。
    picked = None
    seen = []
    for c in dlg.descendants():
        try:
            txt = c.window_text()
        except Exception:
            continue
        if not txt:
            continue
        seen.append(txt[:30])
        if SN in txt:
            picked = c
            break
    if picked is None:
        say(error=f"设备列表里没有 {SN}", seen=seen[:40])
        return 2
    say(step=f"picked device row: {picked.window_text()!r}")
    dlg_hwnd = hwnd_by_title(pid, "选择相机设备")
    if dlg_hwnd:
        ui.post_click(picked, dlg_hwnd)
    else:
        picked.click_input()
    time.sleep(0.5)
    for label in ("确定", "连接", "OK"):
        if click_text(dlg, label, timeout=1.5):
            say(step=f"confirmed with {label}")
            break
    else:
        picked.double_click_input()
        say(step="double-clicked device row")

    # 等连上（状态灯文字会从"未连接"变掉）
    time.sleep(6.0)
    if proc.poll() is not None:
        say(step="died during connect", exit_code=proc.poll(),
            shot=shot("cam_03_died_connecting"))
        return 1
    say(step="connected (process alive)", shot=shot("cam_04_connected"))

    # ── 预览 ──
    if not click_text(mw, "预览"):
        say(error="找不到『预览』按钮")
        return 2
    say(step="clicked 预览")
    for i in range(24):                     # 最多 12 秒
        if proc.poll() is not None:
            say(step="DIED after 预览", exit_code=proc.poll(),
                after_s=round((i + 1) * 0.5, 1), shot=shot("cam_05_died_preview"))
            return 1
        time.sleep(0.5)
    say(step="预览 存活 12 秒", shot=shot("cam_06_preview_alive"))

    # ── 拍照 ──
    if not click_text(mw, "拍照"):
        say(error="找不到『拍照』按钮")
        return 2
    say(step="clicked 拍照")
    for i in range(24):
        if proc.poll() is not None:
            say(step="DIED after 拍照", exit_code=proc.poll(),
                after_s=round((i + 1) * 0.5, 1), shot=shot("cam_07_died_capture"))
            return 1
        time.sleep(0.5)
    say(step="拍照 存活 12 秒", shot=shot("cam_08_capture_alive"))
    say(result="NOT REPRODUCED (alive)")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        # 相机会被进程占着——探针结束必须把它收掉，否则下一次连接会失败。
        if PROC is not None and PROC.poll() is None:
            PROC.terminate()
            try:
                PROC.wait(timeout=6)
            except subprocess.TimeoutExpired:
                PROC.kill()
    sys.exit(code)
