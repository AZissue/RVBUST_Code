# -*- coding: utf-8 -*-
"""
标量场管理（Scalar Field）—— CloudCompare 式标量场支持。

功能：
  - 为点云附加一个或多个 float32 标量数组
  - 自动计算 min/max 做归一化
  - 支持多种颜色映射（viridis、jet、hot、CoolWarm）
  - 与 OpenGL 渲染管线联动：标量场 → RGBA 顶点色
"""

from __future__ import annotations

import numpy as np

from typing import Dict, List, Optional, Tuple


# ── 颜色映射表（256 级，可直接上传为 1D texture） ──

_COLOR_MAPS: Dict[str, np.ndarray] = {}


def _build_viridis() -> np.ndarray:
    """Matplotlib viridis（感知均匀，默认推荐）。"""
    t = np.linspace(0, 1, 256)
    # 简化版分段多项式
    r = np.clip(-0.001 + 0.089 * t + 0.588 * t**2 + 0.284 * t**3, 0, 1)
    g = np.clip(0.026 + 0.755 * t + 0.142 * t**2 + 0.041 * t**3, 0, 1)
    b = np.clip(0.302 + 0.655 * t - 0.025 * t**2 + 0.032 * t**3, 0, 1)
    return np.stack([r, g, b, np.ones_like(t)], axis=1).astype(np.float32)


def _build_jet() -> np.ndarray:
    """Jet（传统彩虹，对比度高）。"""
    t = np.linspace(0, 1, 256)
    r = np.clip(1.5 - 4 * np.abs(t - 0.75), 0, 1)
    g = np.clip(1.5 - 4 * np.abs(t - 0.5), 0, 1)
    b = np.clip(1.5 - 4 * np.abs(t - 0.25), 0, 1)
    return np.stack([r, g, b, np.ones_like(t)], axis=1).astype(np.float32)


def _build_hot() -> np.ndarray:
    """Hot（黑-红-黄-白，适合强度）。"""
    t = np.linspace(0, 1, 256)
    r = np.clip(3 * t, 0, 1)
    g = np.clip(3 * (t - 0.333), 0, 1)
    b = np.clip(3 * (t - 0.667), 0, 1)
    return np.stack([r, g, b, np.ones_like(t)], axis=1).astype(np.float32)


def _build_coolwarm() -> np.ndarray:
    """CoolWarm（蓝-白-红，适合有符号数据）。"""
    t = np.linspace(0, 1, 256)
    r = np.clip(0.23 + 0.77 * t, 0, 1)
    g = np.clip(0.93 - 0.5 * np.abs(t - 0.5) * 2, 0, 1)
    b = np.clip(0.97 - 0.77 * t, 0, 1)
    return np.stack([r, g, b, np.ones_like(t)], axis=1).astype(np.float32)


def get_color_map(name: str) -> np.ndarray:
    """获取指定颜色映射（256×4 float32 RGBA）。"""
    if name not in _COLOR_MAPS:
        builders = {
            "viridis": _build_viridis,
            "jet": _build_jet,
            "hot": _build_hot,
            "coolwarm": _build_coolwarm,
        }
        if name not in builders:
            name = "viridis"
        _COLOR_MAPS[name] = builders[name]()
    return _COLOR_MAPS[name]


# ── 标量场类 ──

class ScalarField:
    """单一点云标量场。"""

    def __init__(self, name: str, values: np.ndarray):
        assert values.ndim == 1 and values.dtype == np.float32
        self.name = name
        self.values = values  # (N,)
        self._vmin = float(np.nanmin(values))
        self._vmax = float(np.nanmax(values))
        self.color_map = "viridis"
        self.saturation = 1.0
        self.visible = True

    @property
    def vmin(self) -> float:
        return self._vmin

    @vmin.setter
    def vmin(self, v: float):
        self._vmin = v

    @property
    def vmax(self) -> float:
        return self._vmax

    @vmax.setter
    def vmax(self, v: float):
        self._vmax = v

    def normalized(self) -> np.ndarray:
        """返回 [0,1] 归一化数组。"""
        rng = self._vmax - self._vmin
        if rng < 1e-12:
            return np.zeros_like(self.values)
        return np.clip((self.values - self._vmin) / rng, 0, 1)

    def to_rgba(self, color_map: Optional[str] = None) -> np.ndarray:
        """标量值 → RGBA (N,4) float32。"""
        cmap = get_color_map(color_map or self.color_map)
        norm = self.normalized()
        idx = (norm * 255).astype(np.uint8)
        return cmap[idx]


class ScalarFieldManager:
    """管理一个点云的全部标量场。"""

    def __init__(self):
        self._fields: Dict[str, ScalarField] = {}
        self.active_name: Optional[str] = None

    def add(self, field: ScalarField) -> None:
        self._fields[field.name] = field
        if self.active_name is None:
            self.active_name = field.name

    def remove(self, name: str) -> None:
        if name in self._fields:
            del self._fields[name]
            if self.active_name == name:
                self.active_name = next(iter(self._fields), None)

    def get(self, name: str) -> Optional[ScalarField]:
        return self._fields.get(name)

    def list_names(self) -> List[str]:
        return list(self._fields.keys())

    def active_field(self) -> Optional[ScalarField]:
        return self._fields.get(self.active_name) if self.active_name else None

    def set_range(self, name: str, vmin: float, vmax: float) -> None:
        f = self._fields.get(name)
        if f:
            f.vmin = vmin
            f.vmax = vmax
