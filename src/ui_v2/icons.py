# -*- coding: utf-8 -*-
"""
ui_v2.icons —— 空壳 UI 专用图标库（手绘线性 SVG，无外部文件依赖）。

风格约定：
  - 24×24 viewBox，1.8px 描边，圆角线帽/连接；
  - 单色描边（fill=none），颜色由 {c} 占位符注入，可随主题/状态着色；
  - 工业软件风格：几何、克制、无渐变无装饰。

接口：
  pixmap(name, color=None, size=16) -> QPixmap
  icon(name, color=None, size=16)   -> QIcon
  apply(button, name, color=None, size=16)  给按钮设置图标
  ICONS                             全部可用图标名
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import TEXT_SECONDARY

# ------------------------------------------------------------------ SVG 图元
# 占位符 {c} = 描边颜色；实心小点用 fill="{c}" stroke="none"
_BODIES = {
    # 单相机（机身 + 镜头）
    "camera":
        '<path d="M4 7h3l2-2h6l2 2h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4'
        'a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z"/>'
        '<circle cx="12" cy="12.5" r="3.5"/>',
    # 多相机（龙门架三联机位）
    "camera_multi":
        '<path d="M2 5.5h20"/>'
        '<rect x="4" y="5.5" width="4" height="6" rx="1"/>'
        '<rect x="10" y="5.5" width="4" height="6" rx="1"/>'
        '<rect x="16" y="5.5" width="4" height="6" rx="1"/>'
        '<circle cx="6" cy="15" r="1.8"/><circle cx="12" cy="15" r="1.8"/>'
        '<circle cx="18" cy="15" r="1.8"/>'
        '<path d="M4 20h16"/>',
    # 链式（双环链节）
    "chain":
        '<path d="M10 13.5a4.24 4.24 0 0 1-6 0l-1.5-1.5a4.24 4.24 0 0 1 6-6'
        'L10 7.5"/>'
        '<path d="M14 10.5a4.24 4.24 0 0 1 6 0l1.5 1.5a4.24 4.24 0 0 1-6 6'
        'L14 16.5"/>',
    # 搜索
    "search":
        '<circle cx="11" cy="11" r="6.5"/><path d="M20.5 20.5 16 16"/>',
    # 刷新（单箭头弧）
    "refresh":
        '<path d="M20 12a8 8 0 1 1-2.35-5.65"/><path d="M20.5 3v4.2h-4.2"/>',
    # 闪电（自动设置IP）
    "bolt":
        '<path d="M13 2 5 13.5h5.5L10 22l8-11.5h-5.5z"/>',
    # 网口（GigE 网络配置）
    "network":
        '<rect x="3" y="7" width="18" height="12" rx="2"/>'
        '<path d="M7 11.5v4M10.3 11.5v4M13.7 11.5v4M17 11.5v4"/>',
    # 齿轮（设备管理）
    "gear":
        '<circle cx="12" cy="12" r="3.2"/>'
        '<path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3'
        'M5 5l2.1 2.1M16.9 16.9 19 19M19 5l-2.1 2.1M7.1 16.9 5 19"/>',
    # 模式切换（双向箭头）
    "swap":
        '<path d="M4 8h13M13 4l4 4-4 4"/><path d="M20 16H7M11 12l-4 4 4 4"/>',
    # 保存（磁盘）
    "save":
        '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5'
        'a2 2 0 0 1 2-2z"/><path d="M8 3v5h7V3"/><path d="M8 21v-7h8v7"/>',
    # 打开会话（文件夹）
    "folder_open":
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8'
        'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 11h18"/>',
    # 后处理（漏斗滤波）
    "filter":
        '<path d="M3 4.5h18l-7 8.5v5.5l-4 2v-7.5z"/>',
    # 日志（终端）
    "terminal":
        '<rect x="2.5" y="4" width="19" height="16" rx="2"/>'
        '<path d="M7 9l3 3-3 3M12.5 15H17"/>',
    # 帮助
    "help":
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M9.5 9.2a2.6 2.6 0 0 1 5.1.7c0 1.7-2.6 2.1-2.6 3.8"/>'
        '<circle cx="12" cy="17.2" r="0.7" fill="{c}" stroke="none"/>',
    # 检测（取景框 + 中心点）
    "detect":
        '<path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3'
        'M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"/>'
        '<circle cx="12" cy="12" r="2.5"/>',
    # 标定（三轴坐标系）
    "calibrate":
        '<path d="M12 13V3M12 3 9.5 5.5M12 3l2.5 2.5"/>'
        '<path d="M12 13l9 5M21 18l-3.5.5M21 18l-.5-3.5"/>'
        '<path d="M12 13l-9 5M3 18l3.5.5M3 18l.5-3.5"/>'
        '<circle cx="12" cy="13" r="1" fill="{c}" stroke="none"/>',
    # 拼接（拼图块）
    "stitch":
        '<path d="M4 5h5a2.2 2.2 0 1 1 4.4 0H20v5a2.2 2.2 0 1 1 0 4.4V20'
        'h-5.6a2.2 2.2 0 1 0-4.4 0H4v-5.6a2.2 2.2 0 1 0 0-4.4z"/>',
    # 锁定（外参锁定）
    "lock":
        '<rect x="5" y="11" width="14" height="9.5" rx="2"/>'
        '<path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>'
        '<circle cx="12" cy="15.7" r="1.1" fill="{c}" stroke="none"/>',
    # 机位（定位针）
    "pin":
        '<path d="M12 21.5s-6.5-5.6-6.5-10.5a6.5 6.5 0 0 1 13 0'
        'c0 4.9-6.5 10.5-6.5 10.5z"/><circle cx="12" cy="10.8" r="2.3"/>',
    # 撤销
    "undo":
        '<path d="M8.5 5 4 9.5 8.5 14"/>'
        '<path d="M4 9.5h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    # 删除（回收站）
    "trash":
        '<path d="M4 6.5h16M9.5 6.5V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v1.5'
        'M6.5 6.5l1 13a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4l1-13"/>'
        '<path d="M10 10.5v6.5M14 10.5v6.5"/>',
    # 闭环（双箭头循环）
    "loop":
        '<path d="M4.5 12a7.5 7.5 0 0 1 13.4-4.7M19.5 12a7.5 7.5 0 0 1-13.4 4.7"/>'
        '<path d="M18.5 3.2v4h-4M5.5 20.8v-4h4"/>',
    # 3D（立方体）
    "cube":
        '<path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z"/>'
        '<path d="M12 12l8.5-5M12 12v9.5M12 12 3.5 7"/>',
    # 重置视角（准星）
    "reset_view":
        '<circle cx="12" cy="12" r="7"/>'
        '<path d="M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22"/>'
        '<circle cx="12" cy="12" r="1.1" fill="{c}" stroke="none"/>',
    # 最大化（外扩角标）
    "maximize":
        '<path d="M9 3.5H3.5V9M15 3.5h5.5V9M20.5 15v5.5H15M3.5 15v5.5H9"/>'
        '<path d="M3.5 3.5 9.2 9.2M20.5 3.5 14.8 9.2M20.5 20.5 14.8 14.8'
        'M3.5 20.5 9.2 14.8"/>',
    # 批量（图层堆叠）
    "layers":
        '<path d="M12 3l9 4.5-9 4.5L3 7.5z"/>'
        '<path d="M3.8 12.2 12 16.5l8.2-4.3M3.8 16.7 12 21l8.2-4.3"/>',
    # 实时取景（摄像机）
    "video":
        '<rect x="2.5" y="6.5" width="13" height="11" rx="2"/>'
        '<path d="M15.5 10.5 21.5 7v10l-6-3.5"/>',
    # 右箭头（连接设备）
    "arrow_right":
        '<path d="M4 12h15M13.5 6.5 19 12l-5.5 5.5"/>',
}

ICONS = tuple(_BODIES.keys())

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{c}" stroke-width="1.8" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)

_RENDER_SCALE = 2  # 2x 超采样，高分屏清晰


# ------------------------------------------------------------------ 公共接口
@lru_cache(maxsize=512)
def pixmap(name: str, color: Optional[str] = None, size: int = 16) -> QPixmap:
    """渲染图标为 QPixmap（带缓存，2x 超采样）。

    参数：
        name   图标名（见 ICONS）
        color  描边颜色（默认主题次要文本色；主按钮用 "#FFFFFF"）
        size   逻辑像素边长
    """
    if name not in _BODIES:
        raise KeyError(f"未知图标: {name}（可用：{', '.join(ICONS)}）")
    color = color or TEXT_SECONDARY
    svg = _SVG_TEMPLATE.format(c=color, body=_BODIES[name].format(c=color))

    pm = QPixmap(size * _RENDER_SCALE, size * _RENDER_SCALE)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(_RENDER_SCALE)
    return pm


def icon(name: str, color: Optional[str] = None, size: int = 16) -> QIcon:
    """渲染图标为 QIcon。"""
    return QIcon(pixmap(name, color, size))


def apply(button, name: str, color: Optional[str] = None, size: int = 16):
    """给 QPushButton / QToolButton 设置图标。"""
    button.setIcon(icon(name, color, size))
    button.setIconSize(QSize(size, size))
