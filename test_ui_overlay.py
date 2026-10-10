# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
test_ui_overlay.py —— AspectRatioLabel 标记叠加绘制回归测试（离屏）。

背景（2026-10-10）：转台 2D 预览"识别圆心没有显示"。根因是标记圈预渲染
在原图尺寸缓存层、半径 4 原图像素，全分辨率图像（2448×2048）缩到预览
大小时亚像素化（<1px），肉眼不可见。现改为 paintEvent 内按显示坐标
绘制（半径 5 屏幕像素，与图像缩放无关）。本测试用离屏 grab 断言两色
圈在期望位置可见，防止回归。

验证：
  [1] 红圈（valid_3d=False）在期望位置可见
  [2] 绿圈（valid_3d=True）在期望位置可见
  [3] clear_markers 后圈消失

无 PySide6 环境：跳过。Qt teardown 退出码 127 属已知噪音。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

print("=" * 60)
print("AspectRatioLabel 标记叠加绘制测试（离屏）")
print("=" * 60)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPixmap, QColor
except ImportError:
    print("\n[!] 未安装 PySide6，跳过")
    sys.exit(0)

from ui.camera_card import AspectRatioLabel  # noqa: E402

_app = QApplication.instance() or QApplication([])

IMG_W, IMG_H = 2448, 2048
LAB_W, LAB_H = 640, 480
MARKERS = [
    {'x': 1900.0 / IMG_W, 'y': 730.0 / IMG_H, 'code': 15, 'valid_3d': False},
    {'x': 500.0 / IMG_W, 'y': 1300.0 / IMG_H, 'code': 29, 'valid_3d': True},
]

passed = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        print("\n测试失败：" + name)
        sys.exit(1)
    passed.append(name)


lab = AspectRatioLabel(ratio=4.0 / 3.0)
img = QPixmap(IMG_W, IMG_H)
img.fill(QColor(60, 60, 60))
lab.setPixmap(img)
lab.set_markers(MARKERS)
lab.resize(LAB_W, LAB_H)
lab.show()
_app.processEvents()
grab = lab.grab().toImage()

scale = min(LAB_W / IMG_W, LAB_H / IMG_H)
sw, sh = int(IMG_W * scale), int(IMG_H * scale)
ox, oy = (LAB_W - sw) // 2, (LAB_H - sh) // 2


def count_hits(px: float, py: float, want: str) -> int:
    cx, cy = int(ox + px * scale), int(oy + py * scale)
    hits = 0
    for dy in range(-6, 7):
        for dx in range(-6, 7):
            c = grab.pixelColor(cx + dx, cy + dy)
            if want == "red" and c.red() > 200 and c.green() < 100 and c.blue() < 100:
                hits += 1
            elif want == "green" and c.green() > 180 and c.red() < 80:
                hits += 1
    return hits


print("\n[1] 红圈（3D 无效）可见")
hits_red = count_hits(1900.0, 730.0, "red")
check("红圈命中像素充足（≥8）", hits_red >= 8, f"命中 {hits_red}")

print("\n[2] 绿圈（3D 有效）可见")
hits_green = count_hits(500.0, 1300.0, "green")
check("绿圈命中像素充足（≥8）", hits_green >= 8, f"命中 {hits_green}")

print("\n[3] clear_markers 后圈消失")
lab.clear_markers()
_app.processEvents()
grab2 = lab.grab().toImage()


def total_color(want: str) -> int:
    n = 0
    for yy in range(0, grab2.height(), 2):
        for xx in range(0, grab2.width(), 2):
            c = grab2.pixelColor(xx, yy)
            if want == "red" and c.red() > 200 and c.green() < 100 and c.blue() < 100:
                n += 1
            elif want == "green" and c.green() > 180 and c.red() < 80:
                n += 1
    return n


check("clear 后红圈消失", total_color("red") == 0, f"残留 {total_color('red')}")
check("clear 后绿圈消失", total_color("green") == 0, f"残留 {total_color('green')}")

print("\n" + "=" * 60)
print(f"全部 {len(passed)} 项断言通过")
print("=" * 60)
