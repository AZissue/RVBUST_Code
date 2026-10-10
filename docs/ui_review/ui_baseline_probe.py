# -*- coding: utf-8 -*-
"""改前基线截图探针（@lead，一次性，不入库）—— 量化"UI 设计语言未复刻"的程度。

跑法（rvc 环境）：
  unset PYTHONPATH
  "D:/Program Files/Anaconda/envs/rvc/python.exe" <此文件>
"""
from __future__ import annotations

import os
import sys

OFFSCREEN = "--visible" not in sys.argv
if OFFSCREEN:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO = "D:/RVC_SRC/Python/MultiCameraCalibration"
OUT = os.path.join(REPO, "docs", "ui_review")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "prototypes", "robot_handeye_transform", "app"))
os.chdir(os.path.join(REPO, "prototypes", "robot_handeye_transform"))

from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QLabel  # noqa: E402


def metrics(img):
    """采样式度量：中位亮度 V、浅底像素占比、四角/中心像素。"""
    w, h = img.width(), img.height()
    lums, light, n = [], 0, 0
    for y in range(2, h - 2, max(1, h // 60)):
        for x in range(2, w - 2, max(1, w // 60)):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            lums.append(max(r, g, b))
            if min(r, g, b) > 200:
                light += 1
            n += 1
    lums.sort()
    pts = {}
    for name, (x, y) in {"tl": (5, 5), "tr": (w - 6, 5), "bl": (5, h - 6),
                         "br": (w - 6, h - 6), "ctr": (w // 2, h // 2)}.items():
        c = img.pixelColor(x, y)
        pts[name] = "#%02X%02X%02X" % (c.red(), c.green(), c.blue())
    return {"median_V": lums[len(lums) // 2], "light_ratio": round(light / max(n, 1), 3),
            "corner_center": pts}


def sample(widget, label):
    img = widget.grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    print("  [widget] %-22s %dx%d  center=#%02X%02X%02X" % (
        label, img.width(), img.height(), c.red(), c.green(), c.blue()))


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    print("Qt platform =", app.platformName(), "| app.font().family() =", app.font().family())

    import host as host_mod
    h = host_mod.RobotHandEyeHost()
    h.resize(1400, 850)
    h.show()
    for _ in range(4):
        app.processEvents()

    p1 = os.path.join(OUT, "baseline_before_qss.png")
    img = h.grab().toImage()
    print("== BEFORE（源码现状：宿主无 setStyleSheet）==")
    print(" ", metrics(img))
    img.save(p1)
    sample(h.workspace.panel, "ControlPanel")
    grps = h.workspace.panel.findChildren(QGroupBox)
    if grps:
        sample(grps[0], "QGroupBox[0]")
    btns = [b for b in h.workspace.panel.findChildren(QPushButton)]
    if btns:
        sample(btns[0], "QPushButton[0] px=" + str(btns[0].text()))
    sample(h.log_box, "host log QPlainTextEdit")

    from ui_v2.theme import GLOBAL_QSS, BG_WINDOW, BG_PANEL
    app.setStyleSheet(GLOBAL_QSS)
    for _ in range(4):
        app.processEvents()
    img2 = h.grab().toImage()
    print("== AFTER（探针内仅追加 app.setStyleSheet(GLOBAL_QSS)，源码未改）==")
    print(" ", metrics(img2))
    img2.save(os.path.join(OUT, "baseline_after_qss_preview.png"))
    sample(h.workspace.panel, "ControlPanel")
    if grps:
        sample(grps[0], "QGroupBox[0]")
    sample(h.log_box, "host log QPlainTextEdit")
    print("token 参照: BG_WINDOW=%s BG_PANEL=%s" % (BG_WINDOW, BG_PANEL))
    print("输出:", p1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
