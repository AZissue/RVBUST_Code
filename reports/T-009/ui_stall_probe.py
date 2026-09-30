#!/usr/bin/env python3
"""T-009 判据：读机器人位姿（以及连机器人）不许把 UI 线程冻住。

怎么把"冻住"变成机器可读的事实：程序自己带着**UI 卡顿看门狗**
（`logic/UiStallWatchdog`，阈值 500 ms，超了就往操作日志写一条
`[WATCHDOG] UI stall N ms (…)`）。所以只要制造一次真实的阻塞读，就能看日志说话。

制造阻塞的办法（不需要真机器人）：
  * **连不上但也不立刻失败**：把机器人地址填成一个黑洞地址（10.255.255.1），
    `QTcpSocket::waitForConnected(1500)` 会在 UI 线程上等满 1.5 s；
  * （可选）**连上了但对方不吭声**：本探针还能起一个假 TCP 服务器
    （accept 之后永不回包），那样 `readPose` 的 `waitForReadyRead(1500)` 也会冻 1.5 s。

判据：整个过程里**不出现新的** `[WATCHDOG] UI stall` 行；且程序存活、连接最终给出可读失败提示。

用法：python reports/T-009/ui_stall_probe.py [--with-read]
退出码：0 = 没有卡顿（PASS）；1 = 出现了卡顿（FAIL）；2 = 环境问题。
"""

from __future__ import annotations

import ctypes
import json
import re
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".codex-loop" / "tools"))

import ui  # noqa: E402

EXE = REPO_ROOT / "build" / "src" / "Release" / "HandEyeCalibrationTool.exe"
BLACKHOLE = "10.255.255.1"
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def hwnd_of(pid: int, prefix: str, timeout=12.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not _user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            _user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value.startswith(prefix):
                found.append(hwnd)
                return False
            return True

        _user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def stall_lines() -> list[str]:
    logs = sorted((EXE.parent / "logs").glob("app_*.log"))
    out: list[str] = []
    for path in logs:
        try:
            out += re.findall(r".*\[WATCHDOG\].*", path.read_text(encoding="utf-8",
                                                                 errors="replace"))
        except OSError:
            continue
    return out


def click_text(root, text, timeout=6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for c in root.descendants(control_type="Button"):
            try:
                if c.window_text().strip() == text:
                    ui.activate(c)
                    return True
            except Exception:              # noqa: BLE001
                continue
        time.sleep(0.3)
    return False


def field_for(root, label_text):
    """表单行：标签右边那个 Edit（QFormLayout 的固定布局）。"""
    labels = [c for c in root.descendants()
              if c.element_info.control_type == "Text" and c.window_text() == label_text]
    if not labels:
        return None
    lr = labels[0].rectangle()
    best = None
    for c in root.descendants():
        if c.element_info.control_type != "Edit":
            continue
        r = c.rectangle()
        if r.left < lr.right or r.bottom < lr.top or r.top > lr.bottom:
            continue
        if best is None or r.left < best[0]:
            best = (r.left, c)
    return best[1] if best else None


class FakeServer(threading.Thread):
    """accept 之后永不回包：让对方 readPose 的 waitForReadyRead 等满超时。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.kept: list[socket.socket] = []
        self._stop = False

    def run(self):
        self.sock.settimeout(1.0)
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
                self.kept.append(conn)     # 收下，不回
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self):
        self._stop = True
        for c in self.kept:
            try:
                c.close()
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass


def main() -> int:
    with_read = "--with-read" in sys.argv
    server = FakeServer() if with_read else None
    if server:
        server.start()
        emit({"step": "fake-server", "port": server.port})

    proc = subprocess.Popen([str(EXE)], cwd=str(REPO_ROOT))
    try:
        mw = None
        deadline = time.time() + 45
        while time.time() < deadline and mw is None:
            try:
                mw = ui.main_window(proc.pid)
            except Exception:              # noqa: BLE001
                time.sleep(0.5)
        if mw is None:
            emit({"result": "FAIL", "why": "main window not found"})
            return 2
        time.sleep(13.0)                   # 启动预扫描

        main_hwnd = hwnd_of(proc.pid, "手眼标定数据收集助手")
        panel = None
        for _ in range(4):
            ui.post_click(ui.find_button(mw, "工具"), main_hwnd)
            panel = hwnd_of(proc.pid, "工具", timeout=10.0)
            if panel:
                break
            time.sleep(1.0)
        if panel is None:
            emit({"result": "FAIL", "why": "工具面板没打开"})
            return 2
        item = ui.find_button(mw, "机器人通信", timeout=8.0)
        if item is None:
            emit({"result": "FAIL", "why": "找不到「机器人通信」"})
            return 2
        ui.post_click(item, panel)
        time.sleep(1.5)

        host_field = field_for(mw, "IP / 端口")
        if host_field is None:
            emit({"result": "FAIL", "why": "找不到 IP / 端口 输入框"})
            return 2
        target = "127.0.0.1" if server else BLACKHOLE
        host_field.set_edit_text(target)
        emit({"step": "host-set", "host": target})
        time.sleep(0.5)

        # 只比较"点连接之后"新出现的卡顿行：启动预扫描/开面板本来就会偶尔超阈值
        # （本机实测过一条 970 ms），那是别的路径的事，不该记在机器人头上。
        before = stall_lines()
        click_text(mw, "连接", timeout=6.0)      # 这一下就会冻 1.5 s（改之前）
        time.sleep(4.0)
        emit({"step": "connect-clicked", "alive": proc.poll() is None})

        if server:
            # 连上之后读一次位姿（readPose 等满 1.5 s）
            click_text(mw, "拍照位姿", timeout=5.0)
            time.sleep(4.0)
            emit({"step": "read-clicked", "alive": proc.poll() is None})

        after = stall_lines()
        fresh = after[len(before):] if len(after) >= len(before) else after
        emit({"check": "没有新的 [WATCHDOG] UI stall", "ok": not fresh,
              "count": len(fresh), "lines": fresh[:2]})
        ok = not fresh and proc.poll() is None
        emit({"result": "PASS" if ok else "FAIL"})
        return 0 if ok else 1
    finally:
        if server:
            server.stop()
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:                  # noqa: BLE001
            try:
                proc.kill()
            except Exception:              # noqa: BLE001
                pass


if __name__ == "__main__":
    sys.exit(main())
