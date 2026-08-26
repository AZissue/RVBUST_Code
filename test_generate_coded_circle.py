# -*- coding: utf-8 -*-
"""
test_generate_coded_circle.py —— 编码圆生成工具（基础脚本）。

基于 RVC SDK 示例 ``Examples/Python/Utils/GenerateCodedCircle.py`` 的编码逻辑，
使用项目已有依赖（OpenCV / NumPy）绘制，生成可打印的编码圆标定板 PNG，
并可选生成 PDF（若环境中已安装 pycairo）。

生成的编码圆与 ``src/core/marker_detector.py`` 中 ``MarkerDetector`` 的默认参数
（N=8, r1_to_r0_ratio=2.0, r2_to_r0_ratio=3.0）兼容。
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
from typing import List, Optional, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# 编码逻辑（与 RVC SDK 示例一致）
# ---------------------------------------------------------------------------
def smallest_cyclic_binary(binary_str: str) -> str:
    """返回二进制字符串的所有循环移位中的最小字典序字符串。"""
    min_binary = binary_str
    n = len(binary_str)
    for i in range(1, n):
        shifted = binary_str[i:] + binary_str[:i]
        if shifted < min_binary:
            min_binary = shifted
    return min_binary


def generate_minimal_cyclic_permutations(n: int) -> List[str]:
    """生成长度为 n 的所有本质不同的循环二进制串（按最小循环移位归一化）。"""
    seen = set()
    for bits in itertools.product("01", repeat=n):
        binary_str = "".join(bits)
        seen.add(smallest_cyclic_binary(binary_str))
    return sorted(seen)


def generate_valid_codes(n: int) -> List[int]:
    """返回可用于编码圆的十进制 code 列表。

    去掉全 0（无法编码）和全 1（与中心圆无法区分）两个极端。
    """
    binaries = generate_minimal_cyclic_permutations(n)
    decimals = [int(b, 2) for b in binaries]
    decimals = sorted(decimals)
    # 去掉全 0 和全 1
    if len(decimals) >= 2:
        decimals = decimals[1:-1]
    return decimals


def decimal_to_binary_fixed_length(decimal_number: int, length: int) -> str:
    """把十进制数字转为定长二进制字符串，前面补 0。"""
    return format(decimal_number, f"0{length}b")


def decimal_list_to_binary(decimal_list: List[int], length: int) -> List[str]:
    """把十进制 code 列表批量转为二进制字符串列表。"""
    return [decimal_to_binary_fixed_length(d, length) for d in decimal_list]


# ---------------------------------------------------------------------------
# 绘图工具（OpenCV 实现）
# ---------------------------------------------------------------------------
def _mm_to_px(mm: float, dpi: int = 300) -> int:
    """毫米转像素（默认 300 DPI）。"""
    return int(round(mm / 25.4 * dpi))


def _draw_annular_sector(
    img: np.ndarray,
    cx: float,
    cy: float,
    r_inner: float,
    r_outer: float,
    start_angle: float,
    end_angle: float,
    color: Tuple[int, int, int],
    steps: int = 60,
) -> None:
    """在 img 上填充一个环形扇区（逆时针角度，0 指向右侧）。"""
    if r_inner < 0 or r_outer <= r_inner:
        return

    pts = []
    for i in range(steps + 1):
        t = start_angle + (end_angle - start_angle) * i / steps
        pts.append([cx + r_outer * math.cos(t), cy + r_outer * math.sin(t)])
    for i in range(steps + 1):
        t = end_angle - (end_angle - start_angle) * i / steps
        pts.append([cx + r_inner * math.cos(t), cy + r_inner * math.sin(t)])

    pts = np.array([pts], dtype=np.int32)
    cv2.fillPoly(img, pts, color)


def _calculate_angles(binary_code: str) -> List[Tuple[float, float]]:
    """把二进制串中为 1 的连续段转为角度区间列表。"""
    n = len(binary_code)
    step = 2 * math.pi / n
    angles = []
    i = 0
    while i < n:
        if binary_code[i] == "1":
            start = i
            while i < n and binary_code[i] == "1":
                i += 1
            angles.append((start * step, i * step))
        else:
            i += 1
    return angles


def draw_single_coded_circle(
    img: np.ndarray,
    decimal_code: int,
    binary_code: str,
    cx: float,
    cy: float,
    radius_px: float,
    r1_to_r0_ratio: float,
    r2_to_r0_ratio: float,
    r3_to_r0_ratio: float,
    r4_to_r0_ratio: float,
    draw_label: bool = True,
) -> None:
    """在 img 上绘制单个编码圆。

    视觉结构与 RVC SDK 示例一致：
      - 黑色正方形背景（边长 2 * r3 * radius）
      - 白色中心圆（半径 r0 = radius）
      - 在 r1~r2 环形区域内，按二进制 code 绘制白色扇区
      - 下方用黑色文字标注十进制 code
    """
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)

    # 黑色背景方块
    half = radius_px * r3_to_r0_ratio
    x0, y0 = int(cx - half), int(cy - half)
    x1, y1 = int(cx + half), int(cy + half)
    cv2.rectangle(img, (x0, y0), (x1, y1), BLACK, -1)

    # 白色中心圆
    cv2.circle(img, (int(cx), int(cy)), int(radius_px), WHITE, -1)

    # 编码扇区（二进制为 1 的位置在 r1~r2 画白色）
    for start_a, end_a in _calculate_angles(binary_code):
        _draw_annular_sector(
            img,
            cx,
            cy,
            radius_px * r1_to_r0_ratio,
            radius_px * r2_to_r0_ratio,
            start_a,
            end_a,
            WHITE,
        )

    # 十进制标签（人类可读，不影响检测）
    if draw_label:
        font_scale = max(0.3, radius_px * (r4_to_r0_ratio - r3_to_r0_ratio) / 30.0)
        thickness = max(1, int(font_scale * 1.5))
        text = str(decimal_code)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        tx, ty = int(cx - tw / 2), int(cy + radius_px * r4_to_r0_ratio + th)
        cv2.putText(img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, BLACK, thickness)


def _page_size_px(page_type: str, dpi: int) -> Tuple[int, int]:
    """返回页面尺寸（宽，高）像素。"""
    sizes_mm = {
        "A1": (594, 841),
        "A2": (420, 594),
        "A3": (297, 420),
        "A4": (210, 297),
        "A5": (148, 210),
        "A6": (105, 148),
    }
    w_mm, h_mm = sizes_mm.get(page_type.upper(), sizes_mm["A4"])
    return _mm_to_px(w_mm, dpi), _mm_to_px(h_mm, dpi)


def generate_page(
    codes: List[int],
    binaries: List[str],
    page_type: str = "A4",
    dpi: int = 300,
    radius_mm: float = 6.0,
    r1_to_r0_ratio: float = 2.0,
    r2_to_r0_ratio: float = 3.0,
    r3_to_r0_ratio: float = 4.0,
    r4_to_r0_ratio: float = 5.0,
    margin_mm: float = 5.0,
) -> np.ndarray:
    """把所有编码圆排列到一张白色页面上，返回 BGR 图像。"""
    width, height = _page_size_px(page_type, dpi)
    img = np.ones((height, width, 3), dtype=np.uint8) * 255

    radius_px = _mm_to_px(radius_mm, dpi)
    margin_px = _mm_to_px(margin_mm, dpi)
    cell = int(2 * radius_px * r4_to_r0_ratio)

    cols = max(1, (width - 2 * margin_px) // cell)
    rows = max(1, (height - 2 * margin_px) // cell)

    for idx, (dec, binary) in enumerate(zip(codes, binaries)):
        if idx >= cols * rows:
            break
        row = idx // cols
        col = idx % cols
        cx = margin_px + col * cell + cell / 2
        cy = margin_px + row * cell + cell / 2
        draw_single_coded_circle(
            img,
            dec,
            binary,
            cx,
            cy,
            radius_px,
            r1_to_r0_ratio,
            r2_to_r0_ratio,
            r3_to_r0_ratio,
            r4_to_r0_ratio,
        )
    return img


# ---------------------------------------------------------------------------
# PDF 输出（可选，依赖 pycairo）
# ---------------------------------------------------------------------------
def _try_generate_pdf(
    codes: List[int],
    binaries: List[str],
    output_path: str,
    page_type: str = "A4",
    radius_mm: float = 6.0,
    r1_to_r0_ratio: float = 2.0,
    r2_to_r0_ratio: float = 3.0,
    r3_to_r0_ratio: float = 4.0,
    r4_to_r0_ratio: float = 5.0,
    margin_mm: float = 5.0,
    dpi: int = 300,
) -> bool:
    """尝试用 pycairo 生成 PDF，返回是否成功。"""
    try:
        import cairo
    except ImportError:
        return False

    width, height = _page_size_px(page_type, dpi)
    surface = cairo.PDFSurface(output_path, width, height)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()

    radius_px = _mm_to_px(radius_mm, dpi)
    margin_px = _mm_to_px(margin_mm, dpi)
    cell = int(2 * radius_px * r4_to_r0_ratio)
    cols = max(1, (width - 2 * margin_px) // cell)
    rows = max(1, (height - 2 * margin_px) // cell)

    def draw_sector(cx, cy, inner, outer, start, end):
        ctx.set_source_rgb(1, 1, 1)
        ctx.new_sub_path()
        ctx.arc(cx, cy, outer, start, end)
        ctx.line_to(cx + inner * math.cos(end), cy + inner * math.sin(end))
        ctx.arc_negative(cx, cy, inner, end, start)
        ctx.close_path()
        ctx.fill()

    def calculate_degrees(code):
        n = len(code)
        step = 2 * math.pi / n
        result = []
        i = 0
        while i < n:
            if code[i] == "1":
                start = i
                while i < n and code[i] == "1":
                    i += 1
                result.append((start * step, i * step))
            else:
                i += 1
        return result

    for idx, (dec, binary) in enumerate(zip(codes, binaries)):
        if idx >= cols * rows:
            break
        row = idx // cols
        col = idx % cols
        cx = margin_px + col * cell + cell / 2
        cy = margin_px + row * cell + cell / 2

        # 黑色背景方块
        ctx.set_source_rgb(0, 0, 0)
        half = radius_px * r3_to_r0_ratio
        ctx.rectangle(cx - half, cy - half, 2 * half, 2 * half)
        ctx.fill()

        # 白色中心圆
        ctx.set_source_rgb(1, 1, 1)
        ctx.arc(cx, cy, radius_px, 0, 2 * math.pi)
        ctx.fill()

        # 编码扇区
        for start_a, end_a in calculate_degrees(binary):
            draw_sector(cx, cy, radius_px * r1_to_r0_ratio, radius_px * r2_to_r0_ratio, start_a, end_a)

        # 标签
        font_size = radius_px * (r4_to_r0_ratio - r3_to_r0_ratio)
        ctx.set_source_rgb(0, 0, 0)
        ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(font_size)
        ctx.move_to(cx - font_size, cy + radius_px * r4_to_r0_ratio)
        ctx.show_text(str(dec))

    surface.finish()
    return True


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成 RVC 兼容的编码圆标定板图片/PDF。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-n", "--sectors", type=int, default=8,
                        help="编码圆扇区数量 N（决定可编码数量）。")
    parser.add_argument("--r1", type=float, default=2.0, help="内环半径 / 中心圆半径。")
    parser.add_argument("--r2", type=float, default=3.0, help="编码环外半径 / 中心圆半径。")
    parser.add_argument("--r3", type=float, default=4.0, help="黑色背景方块半边长 / 中心圆半径。")
    parser.add_argument("--r4", type=float, default=5.0, help="标签位置 / 中心圆半径。")
    parser.add_argument("--radius", type=float, default=6.0,
                        help="中心圆半径，单位 mm（打印尺寸）。")
    parser.add_argument("--page", type=str, default="A4", choices=["A1", "A2", "A3", "A4", "A5", "A6"],
                        help="输出页面尺寸。")
    parser.add_argument("--dpi", type=int, default=300, help="输出分辨率 DPI。")
    parser.add_argument("--margin", type=float, default=5.0, help="页面边距，单位 mm。")
    parser.add_argument("--format", type=str, default="png", choices=["png", "pdf", "both"],
                        help="输出格式。")
    parser.add_argument("--codes", type=int, nargs="+", default=None,
                        help="只生成指定十进制 code（需与 N 兼容）。未指定则生成全部有效 code。")
    parser.add_argument("--max-codes", type=int, default=None,
                        help="最多生成多少个 code（用于快速测试）。")
    parser.add_argument("-o", "--output-dir", type=str, default="OutputCodedCircleData",
                        help="输出目录。")

    args = parser.parse_args(argv)

    # 1. 生成/筛选 code
    all_codes = generate_valid_codes(args.sectors)
    if args.codes is not None:
        codes = [c for c in args.codes if c in all_codes]
        invalid = set(args.codes) - set(all_codes)
        if invalid:
            print(f"[WARN] 以下 code 与 N={args.sectors} 不兼容，已跳过: {sorted(invalid)}")
    else:
        codes = all_codes

    if args.max_codes is not None:
        codes = codes[: args.max_codes]

    binaries = decimal_list_to_binary(codes, args.sectors)
    print(f"N={args.sectors}，有效编码圆总数={len(all_codes)}，本次生成={len(codes)}")

    os.makedirs(args.output_dir, exist_ok=True)

    # 2. 保存元数据
    meta = {
        "n": args.sectors,
        "r1_to_r0_ratio": args.r1,
        "r2_to_r0_ratio": args.r2,
        "r3_to_r0_ratio": args.r3,
        "r4_to_r0_ratio": args.r4,
        "radius_mm": args.radius,
        "page": args.page,
        "dpi": args.dpi,
        "margin_mm": args.margin,
        "codes": codes,
        "binaries": binaries,
    }
    meta_path = os.path.join(args.output_dir, "coded_circle_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"元数据已保存: {meta_path}")

    # 3. 生成 PNG
    if args.format in ("png", "both"):
        img = generate_page(
            codes,
            binaries,
            page_type=args.page,
            dpi=args.dpi,
            radius_mm=args.radius,
            r1_to_r0_ratio=args.r1,
            r2_to_r0_ratio=args.r2,
            r3_to_r0_ratio=args.r3,
            r4_to_r0_ratio=args.r4,
            margin_mm=args.margin,
        )
        png_path = os.path.join(args.output_dir, f"coded_circles_{args.page}_{args.dpi}dpi.png")
        cv2.imwrite(png_path, img)
        print(f"PNG 已保存: {png_path} ({img.shape[1]}x{img.shape[0]} px)")

    # 4. 生成 PDF（可选）
    if args.format in ("pdf", "both"):
        pdf_path = os.path.join(args.output_dir, f"coded_circles_{args.page}_{args.dpi}dpi.pdf")
        ok = _try_generate_pdf(
            codes,
            binaries,
            pdf_path,
            page_type=args.page,
            radius_mm=args.radius,
            r1_to_r0_ratio=args.r1,
            r2_to_r0_ratio=args.r2,
            r3_to_r0_ratio=args.r3,
            r4_to_r0_ratio=args.r4,
            margin_mm=args.margin,
            dpi=args.dpi,
        )
        if ok:
            print(f"PDF 已保存: {pdf_path}")
        else:
            print("[WARN] 未安装 pycairo，无法生成 PDF。可运行 `pip install pycairo` 后重试。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
