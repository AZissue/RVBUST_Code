# -*- coding: utf-8 -*-
"""
UI 图标管理器（assets/icons/ 自定义图标加载）。

用户把自己的 PNG / SVG 图标放到项目根 ``assets/icons/`` 目录
（文件名规范见该目录 README.md），程序自动加载；
**没有对应文件的位置保持 emoji 文本兜底**，只提供部分图标也能正常工作。

核心接口：
  - icons_dir()                → assets/icons 目录路径
  - has_icon(name)             → 图标文件是否存在
  - get_icon(name)             → QIcon（无文件返回空 QIcon）
  - icon_text(name, fallback)  → 有图标时剥离开头 emoji 的纯文本，无图标返回原文本
  - apply_icon(widget, name)   → 有文件则 setIcon + setIconSize
  - make_group_box(name, title) → 创建带图标标题的 QGroupBox（记录图标信息）
  - apply_group_icon(group)    → setLayout 后把图标标题行插入布局顶部
  - reload_icons()             → 清空缓存（运行时替换文件后热刷新）
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QGroupBox, QBoxLayout, QFormLayout, QHBoxLayout, QLabel,
)

# 支持的图标格式（.png 优先，其次 .svg）
_ICON_EXTS = (".png", ".svg")

# 图标缓存：name → QIcon / bool（同名图标只加载一次）
_icon_cache: dict = {}
_has_cache: dict = {}

# 剥离开头 emoji：行首连续的非单词字符（emoji / 符号 / 空格）
_LEADING_EMOJI_RE = re.compile(r"^[^\w]+")


def icons_dir() -> Path:
    """返回 assets/icons 目录路径（从 src/ui/icons.py 上溯两级到项目根）。"""
    return Path(__file__).resolve().parents[2] / "assets" / "icons"


def _find_icon_file(name: str) -> Path | None:
    """按扩展名优先级查找图标文件，找不到返回 None。"""
    base = icons_dir()
    for ext in _ICON_EXTS:
        p = base / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def has_icon(name: str) -> bool:
    """该图标文件是否存在（结果缓存，reload_icons() 后重查）。"""
    if name not in _has_cache:
        _has_cache[name] = _find_icon_file(name) is not None
    return _has_cache[name]


def get_icon(name: str) -> QIcon:
    """加载 assets/icons/{name}.png（或 .svg）返回 QIcon；文件不存在返回空 QIcon()。"""
    if name not in _icon_cache:
        path = _find_icon_file(name)
        icon = QIcon(str(path)) if path is not None else QIcon()
        if icon.isNull():  # 文件不存在或加载失败，统一为空图标
            icon = QIcon()
        _icon_cache[name] = icon
    return _icon_cache[name]


def strip_emoji(text: str) -> str:
    """去掉文本开头的 emoji / 符号及紧随的空格（"📸 拍摄" → "拍摄"）。"""
    return _LEADING_EMOJI_RE.sub("", text)


def icon_text(name: str, fallback_text: str) -> str:
    """有图标文件时返回去掉开头 emoji 的纯文本（避免图标+emoji 重复），
    无文件时返回原文本（含 emoji 兜底）。"""
    if has_icon(name):
        return strip_emoji(fallback_text)
    return fallback_text


def apply_icon(widget, name: str, size: int = 16):
    """便捷方法：有图标文件则 widget.setIcon(get_icon(name)) + setIconSize。"""
    if has_icon(name):
        widget.setIcon(get_icon(name))
        widget.setIconSize(QSize(size, size))


# 分组框图标标题行中标题文字的样式（与 STYLESHEET 中 QGroupBox::title 一致）
_GROUP_TITLE_STYLE = (
    "color: #2979FF; font-weight: bold; font-size: 9pt; "
    "background: transparent; border: none;"
)

# 分组框图标标题行中图标 QLabel 的 objectName（测试 / 样式定位用）
GROUP_ICON_LABEL_NAME = "groupIconLabel"


def make_group_box(icon_name: str, title: str) -> QGroupBox:
    """创建带图标标题的 QGroupBox（配合 apply_group_icon 使用）。

    QGroupBox 原生标题不支持图标，故拆成两步：
      1. make_group_box() 创建分组框并记录图标名 / 剥离 emoji 的标题文本
         （有图标文件时不设 title；无文件时 setTitle 含 emoji 原文兜底）；
      2. 调用方 setLayout 之后调用 apply_group_icon() 把标题行插入布局顶部。
    """
    group = QGroupBox()
    group.setProperty("iconName", icon_name)
    group.setProperty("iconTitle", strip_emoji(title))
    if not has_icon(icon_name):
        group.setTitle(title)  # 无图标文件：emoji 标题兜底，与旧行为一致
    return group


def apply_group_icon(group: QGroupBox, icon_name: str = "", size: int = 16):
    """在 group 已有 layout 顶部插入「图标 + 加粗标题」行（setLayout 之后调用）。

    图标文件缺失时不做任何事（make_group_box 已 setTitle emoji 兜底）。
    适用于垂直布局（QVBoxLayout / QFormLayout）。"""
    icon_name = icon_name or str(group.property("iconName") or "")
    if not has_icon(icon_name):
        return
    layout = group.layout()
    if layout is None:
        return
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 2)
    row.setSpacing(4)
    lbl_icon = QLabel(group)
    lbl_icon.setObjectName(GROUP_ICON_LABEL_NAME)
    lbl_icon.setFixedSize(size, size)
    lbl_icon.setStyleSheet("background: transparent; border: none;")
    lbl_icon.setPixmap(get_icon(icon_name).pixmap(size, size))
    row.addWidget(lbl_icon)
    lbl_title = QLabel(str(group.property("iconTitle") or ""), group)
    lbl_title.setStyleSheet(_GROUP_TITLE_STYLE)
    row.addWidget(lbl_title)
    row.addStretch(1)
    if isinstance(layout, QFormLayout):
        layout.insertRow(0, row)          # 跨两列插入到首行
    elif isinstance(layout, QBoxLayout):
        layout.insertLayout(0, row)       # QVBoxLayout：插入到顶部
    else:
        layout.addItem(row)


def reload_icons():
    """清空缓存（用户运行时替换图标文件后可热刷新）。"""
    _icon_cache.clear()
    _has_cache.clear()
