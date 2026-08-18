# -*- coding: utf-8 -*-
"""
ui_v2.widgets.live_view_panel —— 模式 B 实时取景面板（占位）。

中央上部单相机实时画面，**拍摄后自动执行检测**（核心需求：
不提供手动「检测」按钮，检测/匹配由工作流自动触发，UI 只负责叠加呈现）：
  1. 检测编码圆 → 绿框 + code 号叠加；
  2. 与上一机位的共有标记 → 蓝色圆圈高亮；
  3. 上一机位标记在当前视野中的位置 → 半透明蓝圈引导提示。

正式接入时替换为 camera_card.AspectRatioLabel 的叠加渲染
（绿圈 + code 文字已有实现），本壳保留布局、状态与叠加数据接口。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
)

from ..theme import (
    ACCENT, BG_PANEL, BORDER, STATUS_OK, TEXT_MUTED, TEXT_SECONDARY,
)
from .. import icons as ui_icons

# 一个标记的叠加描述：(x, y, code, shared)
#   x, y    归一化坐标 0~1（相对画面）
#   code    编码圆 code 号
#   shared  是否为与上一机位的共有标记（蓝圈高亮）
MarkerOverlay = Tuple[float, float, int, bool]


class _CoverLabel(QLabel):
    """自适应铺满的 2D 预览标签（background-size: cover，居中裁剪）。

    在 QLabel 原生绘制基础上，保留原始 pixmap，每次尺寸变化时按 cover
    模式缩放到当前控件尺寸再交给 QLabel 居中显示，避免自定义 paintEvent
    与样式表/高分屏绘制冲突。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._orig_pixmap: Optional[QPixmap] = None
        self.setAlignment(Qt.AlignCenter)
        self.setScaledContents(False)
        self.setStyleSheet(f"background-color: {BG_PANEL}; border: none;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(220)

    def setPixmap(self, pixmap: Optional[QPixmap]):  # noqa: N802
        self._orig_pixmap = pixmap
        self._refresh_scaled()

    def clear(self):
        self._orig_pixmap = None
        super().setPixmap(QPixmap())

    def setText(self, text: str):
        """占位提示：无实时帧时显示检测统计。"""
        self._orig_pixmap = None
        super().setPixmap(QPixmap())
        super().setText(text)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._refresh_scaled()

    def _refresh_scaled(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull():
            return
        wgt_w, wgt_h = self.width(), self.height()
        if wgt_w <= 0 or wgt_h <= 0:
            return
        pm_w, pm_h = self._orig_pixmap.width(), self._orig_pixmap.height()
        if pm_w <= 0 or pm_h <= 0:
            return
        # cover 缩放：取宽高比中较大的缩放因子，让图像填满控件
        scale = max(wgt_w / pm_w, wgt_h / pm_h)
        target_w = int(pm_w * scale)
        target_h = int(pm_h * scale)
        # 使用 Smooth 插值，按高分屏 DPR 自动处理
        scaled = self._orig_pixmap.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        super().setPixmap(scaled)


class LiveViewPanel(QFrame):
    """实时取景占位面板（自动检测叠加接口预留）。

    信号：
        mode_toggled(bool)  「自动/手动」开关切换（默认自动；
                            手动模式才显示原有手动 pair 标定面板，作为兜底）。
    """

    mode_toggled = Signal(bool)  # True=自动

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_mode = True
        self._current_pixmap: Optional[QPixmap] = None

        self.setStyleSheet(
            f"LiveViewPanel {{ background-color: {BG_PANEL};"
            f" border: none; border-radius: 6px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部条：标题 + 自动/手动开关 ----
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        video_icon = QLabel()
        video_icon.setPixmap(ui_icons.pixmap("video", TEXT_SECONDARY, 15))
        video_icon.setFixedSize(18, 18)
        bar.addWidget(video_icon)
        title = QLabel("实时取景（自动检测）")
        title.setStyleSheet(f"font-weight: 600; color: {TEXT_SECONDARY};")
        bar.addWidget(title)
        bar.addStretch(1)

        self._auto_hint = QLabel("自动检测已开启")
        self._auto_hint.setStyleSheet(f"color: {STATUS_OK}; font-size: 11px;")
        bar.addWidget(self._auto_hint)

        self._mode_btn = QToolButton()
        self._mode_btn.setText("自动 ▾")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setChecked(True)
        self._mode_btn.setToolTip(
            "默认自动：拍摄后自动检测/匹配/评估。\n"
            "手动模式仅作高级用户兜底（显示手动标定面板）。")
        self._mode_btn.toggled.connect(self._on_mode_toggled)
        bar.addWidget(self._mode_btn)
        root.addLayout(bar)

        # ---- 画面占位区 ----
        self._canvas = _CoverLabel()
        root.addWidget(self._canvas, 1)

        # ---- 底部提示条：共有标记引导 ----
        self._guide = QLabel("")
        self._guide.setAlignment(Qt.AlignCenter)
        self._guide.setStyleSheet(
            f"color: #64B5F6; font-size: 11px; padding: 4px;")
        self._guide.hide()
        root.addWidget(self._guide)

    # ------------------------------------------------------------ 公共接口
    def set_frame(self, pixmap: Optional[QPixmap]):
        """刷新实时画面。

        # TODO(BACKEND): 相机帧 → QPixmap（复用 camera_card.numpy_to_qpixmap）
        """
        self._current_pixmap = pixmap
        self._canvas.setPixmap(pixmap)

    def _refresh_frame(self):
        """按当前画布尺寸重新缩放帧（窗口最大化/拉伸时铺满）。"""
        self._canvas.setPixmap(self._current_pixmap)

    def set_detection_overlay(self, markers: Sequence[MarkerOverlay]):
        """叠加检测结果（拍摄后由工作流自动检测并调用，无手动检测入口）。

        # TODO(BACKEND): 工作流检测结果 → 绿框 + code 号 / 共有标记蓝圈
        """
        total = len(markers)
        shared = sum(1 for m in markers if m[3])
        # 若当前无图像，先用占位文字提示检测数量；有图像时保留画面，
        # 仅通过底部 guide 显示统计，避免 setText 把已拍摄的 2D 图像覆盖掉。
        if not total:
            self._guide.hide()
            return
        if self._current_pixmap is None or self._current_pixmap.isNull():
            self._canvas.setText(
                f"实时画面区（占位）\n\n检测到 {total} 个编码圆，"
                f"其中共有标记 {shared} 个")
        if shared:
            self._guide.setText(
                f"上一机位共有标记 {shared} 个（蓝圈）— "
                "保持这些区域在视野内可提高重合度")
            self._guide.show()
        else:
            self._guide.setText(f"检测到 {total} 个编码圆")
            self._guide.show()

    def clear_overlay(self):
        """清空叠加（移动相机/重拍时调用）。"""
        self._guide.hide()

    def is_auto_mode(self) -> bool:
        return self._auto_mode

    # ------------------------------------------------------------ 内部
    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._refresh_frame()

    def _on_mode_toggled(self, checked: bool):
        self._auto_mode = checked
        self._mode_btn.setText("自动 ▾" if checked else "手动 ▾")
        self._auto_hint.setText("自动检测已开启" if checked else "手动模式（兜底）")
        self._auto_hint.setStyleSheet(
            f"color: {STATUS_OK if checked else ACCENT}; font-size: 11px;")
        self.mode_toggled.emit(checked)
