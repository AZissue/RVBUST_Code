# -*- coding: utf-8 -*-
"""
coded_circle_ui.generator —— 编码圆标定板生成核心逻辑。

与 RVC SDK 示例 ``Examples/Python/Utils/GenerateCodedCircle.py`` 保持一致的
编码/几何定义，纯 OpenCV + NumPy 实现，不依赖 PyRVC。
"""

from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class CodedCircleParams:
    """编码圆生成参数。"""

    n: int = 8
    r1_to_r0_ratio: float = 2.0
    r2_to_r0_ratio: float = 3.0
    r3_to_r0_ratio: float = 4.0
    r4_to_r0_ratio: float = 5.0
    radius_mm: float = 6.0
    scale: float = 1.0
    page_type: str = "A4"
    dpi: int = 300
    margin_mm: float = 5.0

    def clone(self) -> "CodedCircleParams":
        return CodedCircleParams(
            n=self.n,
            r1_to_r0_ratio=self.r1_to_r0_ratio,
            r2_to_r0_ratio=self.r2_to_r0_ratio,
            r3_to_r0_ratio=self.r3_to_r0_ratio,
            r4_to_r0_ratio=self.r4_to_r0_ratio,
            radius_mm=self.radius_mm,
            scale=self.scale,
            page_type=self.page_type,
            dpi=self.dpi,
            margin_mm=self.margin_mm,
        )

    @property
    def effective_radius_mm(self) -> float:
        """经全局缩放后的有效中心圆半径。"""
        return self.radius_mm * self.scale


# ---------------------------------------------------------------------------
# 编码逻辑
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
    """生成长度为 n 的所有本质不同的循环二进制串。"""
    seen = set()
    for bits in itertools.product("01", repeat=n):
        binary_str = "".join(bits)
        seen.add(smallest_cyclic_binary(binary_str))
    return sorted(seen)


def generate_valid_codes(n: int) -> List[int]:
    """返回可用于编码圆的十进制 code 列表（去掉全 0 / 全 1）。"""
    binaries = generate_minimal_cyclic_permutations(n)
    decimals = [int(b, 2) for b in binaries]
    decimals = sorted(decimals)
    if len(decimals) >= 2:
        decimals = decimals[1:-1]
    return decimals


def decimal_to_binary_fixed_length(decimal_number: int, length: int) -> str:
    return format(decimal_number, f"0{length}b")


# ---------------------------------------------------------------------------
# 绘图工具
# ---------------------------------------------------------------------------
def _mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm / 25.4 * dpi))


def _page_size_px(page_type: str, dpi: int) -> Tuple[int, int]:
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
    params: CodedCircleParams,
    draw_label: bool = True,
) -> None:
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)

    half = radius_px * params.r3_to_r0_ratio
    x0, y0 = int(cx - half), int(cy - half)
    x1, y1 = int(cx + half), int(cy + half)
    cv2.rectangle(img, (x0, y0), (x1, y1), BLACK, -1)

    cv2.circle(img, (int(cx), int(cy)), int(radius_px), WHITE, -1)

    for start_a, end_a in _calculate_angles(binary_code):
        _draw_annular_sector(
            img,
            cx,
            cy,
            radius_px * params.r1_to_r0_ratio,
            radius_px * params.r2_to_r0_ratio,
            start_a,
            end_a,
            WHITE,
        )

    if draw_label:
        font_scale = max(0.3, radius_px * (params.r4_to_r0_ratio - params.r3_to_r0_ratio) / 30.0)
        thickness = max(1, int(font_scale * 1.5))
        text = str(decimal_code)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        tx = int(cx - tw / 2)
        ty = int(cy + radius_px * params.r4_to_r0_ratio + th)
        cv2.putText(img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, BLACK, thickness)


def generate_page(
    codes: List[int],
    binaries: List[str],
    params: CodedCircleParams,
) -> np.ndarray:
    """把所有编码圆排列到一张页面上，返回 BGR 图像。"""
    width, height = _page_size_px(params.page_type, params.dpi)
    img = np.ones((height, width, 3), dtype=np.uint8) * 255

    radius_px = _mm_to_px(params.effective_radius_mm, params.dpi)
    margin_px = _mm_to_px(params.margin_mm, params.dpi)
    cell = int(2 * radius_px * params.r4_to_r0_ratio)
    if cell <= 0:
        return img

    cols = max(1, (width - 2 * margin_px) // cell)
    rows = max(1, (height - 2 * margin_px) // cell)

    for idx, (dec, binary) in enumerate(zip(codes, binaries)):
        if idx >= cols * rows:
            break
        row = idx // cols
        col = idx % cols
        cx = margin_px + col * cell + cell / 2
        cy = margin_px + row * cell + cell / 2
        draw_single_coded_circle(img, dec, binary, cx, cy, radius_px, params)
    return img


def generate_preview(
    params: CodedCircleParams,
    preview_width: int = 600,
    max_preview_codes: Optional[int] = None,
) -> Tuple[np.ndarray, dict]:
    """生成低分辨率预览图及信息字典。

    预览直接基于当前页面设置生成完整标定板，再缩放到 preview_width，
    因此预览图与导出的 PNG/PDF 在排布、数量和页面尺寸上完全一致。
    """
    all_codes = generate_valid_codes(params.n)
    img, codes, binaries = generate_full_board(params, codes=None, max_codes=max_preview_codes)

    # 等比例缩放到预览宽度
    if img.shape[1] > preview_width:
        resize_scale = preview_width / img.shape[1]
        new_h = int(img.shape[0] * resize_scale)
        preview = cv2.resize(img, (preview_width, new_h), interpolation=cv2.INTER_AREA)
    else:
        preview = img.copy()

    info = {
        "total_codes": len(all_codes),
        "preview_codes": len(codes),
        "page_px": (img.shape[1], img.shape[0]),
        "preview_px": (preview.shape[1], preview.shape[0]),
        "effective_radius_mm": params.effective_radius_mm,
    }
    return preview, info


def generate_full_board(
    params: CodedCircleParams,
    codes: Optional[List[int]] = None,
    max_codes: Optional[int] = None,
) -> Tuple[np.ndarray, List[int], List[str]]:
    """生成完整标定板图像。"""
    all_codes = generate_valid_codes(params.n)
    if codes is not None:
        codes = [c for c in codes if c in all_codes]
        if not codes:
            codes = all_codes
    else:
        codes = all_codes
    if max_codes is not None:
        codes = codes[:max_codes]
    binaries = [decimal_to_binary_fixed_length(c, params.n) for c in codes]
    img = generate_page(codes, binaries, params)
    return img, codes, binaries


def _format_save_error(path: str, exc: Exception) -> str:
    """把文件保存异常转换为用户友好的中文提示。"""
    name = os.path.basename(path)
    # errno 13 = Permission denied, errno 32 = Sharing violation (Windows)
    if isinstance(exc, PermissionError) or (
        isinstance(exc, OSError) and getattr(exc, "errno", None) in (13, 32)
    ):
        return (
            f"无法写入 {name}：文件可能被其他程序占用或没有写入权限。\n"
            f"请先关闭已打开的 {name}，或更换输出目录后再试。"
        )
    return f"保存 {name} 失败：{exc}"


def save_board(
    img: np.ndarray,
    codes: List[int],
    binaries: List[str],
    params: CodedCircleParams,
    output_dir: str,
    fmt: str = "png",
) -> List[str]:
    """保存标定板图片与元数据，返回保存的文件路径列表。"""
    os.makedirs(output_dir, exist_ok=True)
    saved = []

    base_name = f"coded_circles_{params.page_type}_{params.dpi}dpi"

    meta = {
        "n": params.n,
        "r1_to_r0_ratio": params.r1_to_r0_ratio,
        "r2_to_r0_ratio": params.r2_to_r0_ratio,
        "r3_to_r0_ratio": params.r3_to_r0_ratio,
        "r4_to_r0_ratio": params.r4_to_r0_ratio,
        "radius_mm": params.radius_mm,
        "scale": params.scale,
        "effective_radius_mm": params.effective_radius_mm,
        "page_type": params.page_type,
        "dpi": params.dpi,
        "margin_mm": params.margin_mm,
        "codes": codes,
        "binaries": binaries,
    }
    meta_path = os.path.join(output_dir, "coded_circle_meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        saved.append(meta_path)
    except Exception as e:
        raise RuntimeError(_format_save_error(meta_path, e)) from e

    if fmt in ("png", "both"):
        png_path = os.path.join(output_dir, f"{base_name}.png")
        try:
            if not cv2.imwrite(png_path, img):
                raise OSError(f"cv2.imwrite 返回失败，路径：{png_path}")
            saved.append(png_path)
        except Exception as e:
            raise RuntimeError(_format_save_error(png_path, e)) from e

    if fmt in ("pdf", "both"):
        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        try:
            _try_generate_pdf(codes, binaries, pdf_path, params)
            saved.append(pdf_path)
        except Exception as e:
            raise RuntimeError(_format_save_error(pdf_path, e)) from e

    return saved


def _try_generate_pdf(
    codes: List[int],
    binaries: List[str],
    output_path: str,
    params: CodedCircleParams,
) -> bool:
    try:
        import cairo
    except ImportError:
        raise RuntimeError(
            "生成 PDF 需要 pycairo 库。请安装：pip install pycairo"
        ) from None

    try:
        width, height = _page_size_px(params.page_type, params.dpi)
        surface = cairo.PDFSurface(output_path, width, height)
        ctx = cairo.Context(surface)
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()

        radius_px = _mm_to_px(params.effective_radius_mm, params.dpi)
        margin_px = _mm_to_px(params.margin_mm, params.dpi)
        cell = int(2 * radius_px * params.r4_to_r0_ratio)
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

            ctx.set_source_rgb(0, 0, 0)
            half = radius_px * params.r3_to_r0_ratio
            ctx.rectangle(cx - half, cy - half, 2 * half, 2 * half)
            ctx.fill()

            ctx.set_source_rgb(1, 1, 1)
            ctx.arc(cx, cy, radius_px, 0, 2 * math.pi)
            ctx.fill()

            for start_a, end_a in calculate_degrees(binary):
                draw_sector(cx, cy, radius_px * params.r1_to_r0_ratio, radius_px * params.r2_to_r0_ratio, start_a, end_a)

            font_size = radius_px * (params.r4_to_r0_ratio - params.r3_to_r0_ratio)
            ctx.set_source_rgb(0, 0, 0)
            ctx.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(font_size)
            ctx.move_to(cx - font_size, cy + radius_px * params.r4_to_r0_ratio)
            ctx.show_text(str(dec))

        surface.finish()
    except (PermissionError, OSError) as e:
        raise RuntimeError(
            "无法写入 PDF：文件可能被其他程序占用或没有写入权限。\n"
            "请先关闭已打开的 PDF，或更换输出目录后再试。"
        ) from e
    except Exception as e:
        raise RuntimeError(f"生成 PDF 失败：{e}") from e
    return True
