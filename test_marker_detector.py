# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
test_marker_detector.py —— MarkerDetector 多尺度检测回退测试（无 GUI、无需相机）。

背景（2026-09 现场 bug）：RVC-I540 全分辨率 2448×2048 拍摄时，
DetectCodedCircleMarker 对画面中的编码圆返回 0 个；降采样到 0.5~0.75x 后
可稳定检出（圆心按 1/scale 反推，实测偏差 <0.3px，不影响配准精度）。
根因是 SDK 检测器对标记像素尺度敏感（全分辨率下 r0≈17px 超出其有效窗口），
N / r1_to_r0_ratio / r2_to_r0_ratio 三个参数本身无误。

验证：
  [1] 大标记场景（r0=71px）：1.0x 未检出时 detect() 必须经回退检出全部 4 个，
      坐标为全分辨率坐标系（与放置中心偏差在容差内）
  [2] 常规场景（1.0x 可检出）：detect() 必须直接使用全分辨率结果，
      坐标与原始 SDK 检测结果一致（不发生任何缩放）
  [3] 回退阶梯的坐标反推：1.0x 失败时坐标按 1/scale 换算回全分辨率

无 PyRVC 环境：跳过检测类断言（detect 按设计返回空列表）。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "prototypes", "coded_circle_ui"))

print("=" * 60)
print("MarkerDetector 多尺度检测回退测试")
print("=" * 60)

import cv2  # noqa: E402

from core.marker_detector import MarkerDetector  # noqa: E402

try:
    import PyRVC as RVC
except ImportError:
    RVC = None

from generator import CodedCircleParams, draw_single_coded_circle  # noqa: E402

# 场景中的标记放置位置（全分辨率坐标）与编码
SCENE_MARKERS = [
    (15, (600, 500)),
    (29, (1800, 600)),
    (45, (700, 1500)),
    (111, (1800, 1500)),
]
COORD_TOL_PX = 3.0  # 回退尺度拟合圆心反推后的最大允许偏差（像素）


def make_scene(r0_px: float, width: int, height: int,
               positions=None) -> np.ndarray:
    """合成编码圆场景：亮灰背景 + 白色卡片 + 硬边编码圆（模拟打印标记）。"""
    params = CodedCircleParams()
    img = np.full((height, width, 3), 110, np.uint8)
    for (code, (cx, cy)) in positions:
        half = int(r0_px * params.r4_to_r0_ratio + 30)
        cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half), (255, 255, 255), -1)
        draw_single_coded_circle(img, code, format(code, "08b"), cx, cy, r0_px, params,
                                 draw_label=False)
    return img


def sdk_detect(image: np.ndarray):
    """直接用 SDK 在指定图像上检测，返回 {code: (x, y)}。"""
    mt = RVC.CodedCircleMarkerType()
    mt.N = 8
    mt.r1_to_r0_ratio = 2.0
    mt.r2_to_r0_ratio = 3.0
    return {m.code: (float(m.x), float(m.y)) for m in RVC.DetectCodedCircleMarker(image, mt)}


if RVC is None:
    print("\n[!] 未安装 PyRVC，跳过检测断言（无 SDK 环境 detect 返回空列表属预期行为）")
    sys.exit(0)

passed = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        print("\n测试失败：" + name)
        sys.exit(1)
    passed.append(name)


# ------------------------------------------------------------------
# [1] 大标记场景：1.0x 失效 → 回退必须恢复
# ------------------------------------------------------------------
print("\n[1] 大标记场景（r0=71px @ 2448×2048）多尺度回退")
scene_big = make_scene(r0_px=71.0, width=2448, height=2048, positions=SCENE_MARKERS)
direct_big = sdk_detect(scene_big)
check("前置: 1.0x 直接检测确实返回 0（场景复现 bug）", len(direct_big) == 0,
      f"实际 {len(direct_big)} 个")

detector = MarkerDetector()
result = detector.detect(scene_big)
codes = sorted(m['code'] for m in result)
expected = sorted(c for c, _ in SCENE_MARKERS)
check("detect() 经回退检出全部 4 个标记", codes == expected, f"实际 {codes}")

worst = 0.0
by_code = {m['code']: m for m in result}
for code, (cx, cy) in SCENE_MARKERS:
    dx = by_code[code]['x'] - cx
    dy = by_code[code]['y'] - cy
    worst = max(worst, float(np.hypot(dx, dy)))
check("坐标已反推回全分辨率系（偏差 ≤3px）", worst <= COORD_TOL_PX, f"最大偏差 {worst:.2f}px")

# ------------------------------------------------------------------
# [2] 常规场景：1.0x 可用 → 不得降级（精度优先）
# ------------------------------------------------------------------
print("\n[2] 常规场景（1.0x 可检出）使用全分辨率结果")
NORMAL_MARKERS = [(15, (200, 150)), (29, (600, 180)), (45, (220, 450)), (111, (580, 430))]
scene_normal = make_scene(r0_px=20.0, width=800, height=600, positions=NORMAL_MARKERS)
scene_normal = cv2.GaussianBlur(scene_normal, (3, 3), 0)  # 模拟相机光学抗混叠
direct_normal = sdk_detect(scene_normal)
check("前置: 1.0x 直接检测可检出标记", len(direct_normal) == len(NORMAL_MARKERS),
      f"实际 {len(direct_normal)} 个")

detector2 = MarkerDetector()
result2 = detector2.detect(scene_normal)
check("检出数量一致", len(result2) == len(direct_normal), f"实际 {len(result2)} 个")
max_diff = 0.0
for m in result2:
    x0, y0 = direct_normal[m['code']]
    max_diff = max(max_diff, abs(m['x'] - x0), abs(m['y'] - y0))
check("坐标与 1.0x 原始结果完全一致（未做缩放）", max_diff < 1e-6, f"最大差异 {max_diff:.2e}")

# ------------------------------------------------------------------
# [3] 回退尺度的坐标反推正确性（对照 SDK 在 0.75x 图上的拟合中心）
# ------------------------------------------------------------------
print("\n[3] 回退坐标反推与 SDK 子尺度拟合中心一致")
small = cv2.resize(scene_big, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
small_result = sdk_detect(small)
by_code3 = {m['code']: m for m in result}
max_back_err = 0.0
for code, (sx, sy) in small_result.items():
    if code in by_code3:
        max_back_err = max(max_back_err,
                           abs(by_code3[code]['x'] - sx / 0.75),
                           abs(by_code3[code]['y'] - sy / 0.75))
check("0.75x 拟合中心 ×1/0.75 与 detect() 返回坐标一致", max_back_err < 1e-6,
      f"最大差异 {max_back_err:.2e}")

print("\n" + "=" * 60)
print(f"全部 {len(passed)} 项断言通过")
print("=" * 60)
