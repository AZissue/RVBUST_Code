# -*- coding: utf-8 -*-
"""
ui_v2.widgets.camera_grid —— 模式 A 中央相机取景网格。

每台相机一张卡片：
  - 实时缩略图（拍完刷新）+ 相机名；
  - 标记数量角标；
  - 共视状态角标：绿「✓ 共视正常」/ 红「● 未看到标定板」（标定阶段硬提示）；
  - 帧分区标签：标定帧 / 扫描帧（不同标签色，互不覆盖）。

正式接入时缩略图渲染可替换为现有 ``camera_card.py`` 的 AspectRatioLabel
叠加逻辑（绿圈 + code 号），本壳仅保留布局与状态接口。
"""

from __future__ import annotations

from typing import Dict, List, Optional
from collections import deque
from time import monotonic

from PySide6.QtCore import Qt, QSize, Signal, QEvent
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget, QToolButton, QFileDialog,
)

from core.frame_data import FrameData
from ui_common.image_preview import AspectRatioLabel, numpy_to_qpixmap

from ..theme import (
    ACCENT, ACCENT_DIM, BG_CARD, BG_PANEL, BORDER, BORDER_HOVER,
    STATUS_ERR, STATUS_OK, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)
from .. import icons as ui_icons

FRAME_KIND_STYLE = {
    # 帧分区标签色：标定帧 / 扫描帧 互不覆盖
    "标定帧": ("#5C6BC0", "标定帧"),
    "扫描帧": (STATUS_OK, "扫描帧"),
}


class CameraCard(QFrame):
    """单相机取景卡片。

    信号：
        clicked(str)                  点击卡片（选中该相机）。
        preview_toggled(str, bool)    单相机 2D 预览开关。
        capture_requested(str)        单相机 3D 拍摄。
        detect_requested(str)         单相机检测标记。
    """

    clicked = Signal(str)
    preview_toggled = Signal(str, bool)
    capture_requested = Signal(str)
    detect_requested = Signal(str)
    focus_requested = Signal(str)

    def __init__(self, camera_id: str, title: Optional[str] = None, parent=None, *, preview_factory=None):
        super().__init__(parent)
        self.camera_id = camera_id
        self._current_frame: Optional[FrameData] = None
        self._arrival_times = deque(maxlen=20)

        self.setStyleSheet(
            f"CameraCard {{ background-color: {BG_CARD};"
            f" border: none; border-radius: 6px; }}")
        self.setMinimumSize(300, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(4)

        # 标题行：相机名 + 帧分区标签
        title_row = QHBoxLayout()
        cam_icon = QLabel()
        cam_icon.setPixmap(ui_icons.pixmap("camera", TEXT_SECONDARY, 14))
        cam_icon.setFixedSize(16, 16)
        title_row.addWidget(cam_icon)
        self._name = QLabel(title or camera_id)
        self._name.setStyleSheet(
            f"font-weight: 600; color: {TEXT_PRIMARY};")
        self._name.setMinimumWidth(65)
        self._name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_row.addWidget(self._name, 1)
        self._kind = QLabel("")
        self._kind.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        title_row.addWidget(self._kind)
        self._quick_actions = QWidget()
        quick = QHBoxLayout(self._quick_actions)
        quick.setContentsMargins(0, 0, 0, 0)
        quick.setSpacing(2)
        for title, glyph, callback in (
                ('保存当前2D图像', 'camera', self._save_image),
                ('放大 / 返回', 'maximize', lambda: self.focus_requested.emit(self.camera_id))):
            button = QToolButton()
            button.setToolTip(title)
            ui_icons.apply(button, glyph, TEXT_SECONDARY, 14)
            button.clicked.connect(callback)
            if glyph == 'camera':
                self._save_button = button
                button.setEnabled(False)
            quick.addWidget(button)
        self._freeze = QToolButton()
        self._freeze.setText('锁')
        self._freeze.setCheckable(True)
        self._freeze.setEnabled(False)
        self._freeze.setToolTip('冻结显示；后台采集继续，解锁后显示最新帧')
        self._freeze.toggled.connect(self._freeze_changed)
        quick.addWidget(self._freeze)
        title_row.addWidget(self._quick_actions)
        self._quick_actions.hide()
        lo.addLayout(title_row)

        # 缩略图占位（4:3，宽度随卡片水平铺满，保持比例）
        self._thumb = (preview_factory or AspectRatioLabel)(ratio=4.0 / 3.0)
        self._thumb.setMinimumSize(260, 180)
        self._thumb.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        lo.addWidget(self._thumb, 1)
        self._thumb.installEventFilter(self)
        self._overview_meta = QHBoxLayout()
        self._overview_meta.setContentsMargins(0, 0, 0, 0)
        lo.addLayout(self._overview_meta)
        self._image_info = QLabel('等待图像')
        self._image_info.setStyleSheet('color:#999999;font-size:11px;background:transparent;')
        self._image_info.hide()

        # 底部角标 + 单相机控制按钮
        bottom = QHBoxLayout()
        self._bottom = bottom
        self._marker_badge = QLabel("标记: —")
        self._marker_badge.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px;"
            f" background-color: {BG_PANEL}; border-radius: 4px; padding: 3px 8px;")
        bottom.addWidget(self._marker_badge)
        bottom.addStretch(1)

        self._covis_badge = QLabel("")
        self._covis_badge.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        bottom.addWidget(self._covis_badge)
        bottom.addSpacing(6)

        # 单相机控制按钮（图标 + 文字，紧凑排列）
        btn_style = (
            f"QPushButton {{"
            f"  background-color: {BG_PANEL};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 4px;"
            f"  padding: 4px 10px;"
            f"  color: {TEXT_SECONDARY};"
            f"  font-size: 12px;"
            f"  min-width: 60px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {BG_CARD};"
            f"  border-color: {BORDER_HOVER};"
            f"  color: {TEXT_PRIMARY};"
            f"}}"
            f"QPushButton:pressed {{ background-color: #3E424E; }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: #2E313A; }}"
            f"QPushButton:checked {{"
            f"  background-color: {ACCENT_DIM};"
            f"  border-color: {ACCENT};"
            f"  color: {ACCENT};"
            f"  font-weight: 600;"
            f"}}"
        )

        self._btn_preview = QPushButton("2D预览")
        self._btn_preview.setCheckable(True)
        self._btn_preview.setStyleSheet(btn_style)
        self._btn_preview.setFixedHeight(30)
        self._btn_preview.setIconSize(QSize(16, 16))
        ui_icons.apply(self._btn_preview, "video", TEXT_SECONDARY, 16)
        self._btn_preview.toggled.connect(self._on_preview_toggled)
        bottom.addWidget(self._btn_preview)

        self._btn_capture = QPushButton("3D拍")
        self._btn_capture.setStyleSheet(btn_style)
        self._btn_capture.setFixedHeight(30)
        self._btn_capture.setIconSize(QSize(16, 16))
        ui_icons.apply(self._btn_capture, "camera", TEXT_SECONDARY, 16)
        self._btn_capture.clicked.connect(
            lambda: self.capture_requested.emit(self.camera_id))
        bottom.addWidget(self._btn_capture)

        self._btn_detect = QPushButton("检测")
        self._btn_detect.setStyleSheet(btn_style)
        self._btn_detect.setFixedHeight(30)
        self._btn_detect.setIconSize(QSize(16, 16))
        ui_icons.apply(self._btn_detect, "detect", TEXT_SECONDARY, 16)
        self._btn_detect.clicked.connect(
            lambda: self.detect_requested.emit(self.camera_id))
        bottom.addWidget(self._btn_detect)

        bottom.setSpacing(8)
        lo.addLayout(bottom)

    # ------------------------------------------------------------ 公共接口
    def set_thumbnail(self, pixmap: Optional[QPixmap]):
        """刷新缩略图（拍摄完成后调用）。"""
        if pixmap is None:
            self._thumb.clear_image()
            return
        if not self._freeze.isChecked():
            self._thumb.setPixmap(pixmap)

    def set_marker_overlay(self, markers: list):
        """Display an explicit normalized overlay supplied by a controller."""
        if not self._freeze.isChecked():
            self._thumb.set_markers(markers)

    def set_compact_preview(self):
        """Read-only overview cards for displaying multiple images together."""
        self.setMinimumSize(200, 170)
        self._thumb.setMinimumSize(180, 70)
        for button in (self._btn_preview, self._btn_capture, self._btn_detect):
            button.hide()

    def set_overview(self, enabled):
        """Compact production overview retaining every per-camera action."""
        buttons = (self._btn_preview, self._btn_capture, self._btn_detect)
        if enabled:
            if not hasattr(self, '_overview_original'):
                self._overview_original = (self.minimumSize(), self.maximumSize(),
                    self._thumb.minimumSize(), [(b.text(), b.styleSheet()) for b in buttons])
                self._overview_chrome = (self.styleSheet(), self._thumb.styleSheet())
                self._overview_name = self._name.text()
            self._name.setText(self._overview_name if self._overview_name.startswith(self.camera_id)
                               else f'{self.camera_id} · {self._overview_name}')
            self.setStyleSheet('CameraCard {background:#292929;border:0;border-radius:3px;}')
            self._thumb.setStyleSheet('background:#202020;border:0;')
            self._quick_actions.show()
            self._image_info.show()
            self.setMinimumSize(230, 190)
            self._thumb.setMinimumSize(180, 80)
            if self._overview_meta.count() == 0:
                self._bottom.removeWidget(self._marker_badge)
                self._bottom.removeWidget(self._covis_badge)
                self._overview_meta.addWidget(self._marker_badge)
                self._overview_meta.addStretch(1)
                self._overview_meta.addWidget(self._covis_badge)
            if self._overview_meta.indexOf(self._image_info) < 0:
                self._overview_meta.addWidget(self._image_info)
            self._thumb.setToolTip('双击画面放大此相机，再次双击返回全部相机')
            for button, text in zip(buttons, ('预览', '拍摄', '检测')):
                button.setText(text)
                button.setStyleSheet(button.styleSheet() + ' QPushButton {min-width:0px;padding:3px 4px;font-size:11px;}')
        elif hasattr(self, '_overview_original'):
            minimum, maximum, thumb, styles = self._overview_original
            self.setMinimumSize(minimum)
            self.setMaximumSize(maximum)
            self._thumb.setMinimumSize(thumb)
            for button, (text, style) in zip(buttons, styles):
                button.setText(text)
                button.setStyleSheet(style)
            self._overview_meta.removeWidget(self._marker_badge)
            self._overview_meta.removeWidget(self._covis_badge)
            while self._overview_meta.count():
                self._overview_meta.takeAt(0)
            self._bottom.insertWidget(0, self._marker_badge)
            self._bottom.insertWidget(2, self._covis_badge)
            self._thumb.setToolTip('')
            self._quick_actions.hide()
            self._image_info.hide()
            self._freeze.setChecked(False)
            self.setStyleSheet(self._overview_chrome[0])
            self._thumb.setStyleSheet(self._overview_chrome[1])
            self._name.setText(self._overview_name)
            del self._overview_name
            del self._overview_chrome
            del self._overview_original

    def eventFilter(self, watched, event):
        if watched is self._thumb and event.type() == QEvent.MouseButtonDblClick and hasattr(self, '_overview_original'):
            self.focus_requested.emit(self.camera_id)
            return True
        return super().eventFilter(watched, event)

    def set_calibration_status(self, text: str, success: bool):
        self._covis_badge.setText(text)
        color = STATUS_OK if success else STATUS_ERR
        self._covis_badge.setStyleSheet(f'color:{color};font-size:12px;font-weight:600;')

    def set_frame(self, frame: Optional[FrameData], markers: Optional[list] = None, *, arrival=True):
        """由 FrameData 更新缩略图与标记叠加，并保留当前帧供检测使用。"""
        self._current_frame = frame
        if frame is None or frame.image_np is None:
            self._save_button.setEnabled(False)
            self._freeze.setEnabled(False)
            self._freeze.blockSignals(True)
            self._freeze.setChecked(False)
            self._freeze.blockSignals(False)
            self._image_info.setText('等待图像')
            self._arrival_times.clear()
            self._thumb.clear_image()
            return
        self._save_button.setEnabled(True)
        self._freeze.setEnabled(True)
        if arrival and self._btn_preview.isChecked():
            self._arrival_times.append(monotonic())
        height, width = frame.image_np.shape[:2]
        self._image_info.setText(f'{width} × {height} · {self.preview_rate_text()}')
        if self._freeze.isChecked():
            return
        pixmap = numpy_to_qpixmap(frame.image_np)
        self._thumb.setPixmap(pixmap)

        # AspectRatioLabel 期望归一化坐标 [0,1] 与 x/y/code/valid_3d 字段，
        # 而 frame.markers 中的编码圆只含 x_2d/y_2d，标定板含 x/y/x_2d/y_2d，
        # 因此需要统一转换。markers 缺省优先取 frame.markers_all（含 3D
        # 无效标记，红圈显示），无全量列表时回退过滤后的 frame.markers。
        markers = (markers if markers is not None
                   else (frame.markers_all or frame.markers))
        h, w = frame.image_np.shape[:2]
        is_board = frame.board_pattern_name is not None
        overlay = []
        for m in markers or []:
            px = m.get('x_2d', m.get('x', 0.0))
            py = m.get('y_2d', m.get('y', 0.0))
            has_3d = 'x_3d' in m
            overlay.append({
                'x': float(px) / w if w > 0 else 0.0,
                'y': float(py) / h if h > 0 else 0.0,
                'code': m.get('code', '?'),
                'valid_3d': has_3d,
                'marker_type': 'board' if is_board else 'coded',
            })
        self._thumb.set_markers(overlay)

    def preview_rate_text(self):
        if self._freeze.isChecked():
            return '已冻结'
        if not self._btn_preview.isChecked():
            return '静帧'
        if len(self._arrival_times) < 2:
            return '预览中'
        if monotonic() - self._arrival_times[-1] > 2:
            return '等待新帧'
        elapsed = self._arrival_times[-1] - self._arrival_times[0]
        return f'{(len(self._arrival_times)-1)/max(.001, elapsed):.1f} FPS'

    def _freeze_changed(self, frozen):
        if not frozen:
            self.set_frame(self._current_frame, arrival=False)

    def _save_image(self):
        pixmap = getattr(self._thumb, '_pixmap', None)
        if pixmap is None or pixmap.isNull():
            return
        path, _ = QFileDialog.getSaveFileName(self, '保存当前2D图像', f'{self.camera_id}.png', 'PNG 图像 (*.png)')
        if path and not pixmap.save(path, 'PNG'):
            from ..dialogs import ChineseMessageBox
            ChineseMessageBox.warning(self, '保存失败', '无法写入图像，请检查路径及目录权限。')

    def current_frame(self) -> Optional[FrameData]:
        """返回当前卡片持有的最新帧（预览/拍摄/检测用）。"""
        return self._current_frame

    def set_marker_count(self, count: Optional[int]):
        """更新标记数量角标。"""
        if count is None:
            self._marker_badge.setText("标记: —")
            return
        self._marker_badge.setText(f"标记: {count}")
        color = STATUS_OK if count > 0 else STATUS_ERR
        self._marker_badge.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 600;"
            f" background-color: {BG_PANEL}; border-radius: 4px; padding: 3px 8px;")

    def set_covis_status(self, ok: Optional[bool]):
        """共视状态角标（标定阶段硬提示）。

        ok=True  → 绿「✓ 共视正常」
        ok=False → 红「● 未看到标定板」
        ok=None  → 清空
        """
        if ok is None:
            self._covis_badge.setText("")
        elif ok:
            self._covis_badge.setText("✓ 共视正常")
            self._covis_badge.setStyleSheet(
                f"color: {STATUS_OK}; font-size: 12px; font-weight: 600;")
        else:
            self._covis_badge.setText("● 未看到标定板")
            self._covis_badge.setStyleSheet(
                f"color: {STATUS_ERR}; font-size: 12px; font-weight: 600;")

    def set_frame_kind(self, kind: Optional[str]):
        """帧分区标签：'标定帧' / '扫描帧' / None。"""
        if kind in FRAME_KIND_STYLE:
            color, text = FRAME_KIND_STYLE[kind]
            self._kind.setText(text)
            self._kind.setStyleSheet(
                f"color: {color}; font-size: 12px; font-weight: 600;")
        else:
            self._kind.setText("")

    def set_title(self, title: str):
        self._name.setText(title)

    def set_controls_enabled(self, enabled: bool):
        """设置单相机控制按钮可用性。"""
        self._btn_capture.setEnabled(enabled)
        self._btn_detect.setEnabled(enabled)
        if not enabled:
            self._btn_preview.setChecked(False)
        self._btn_preview.setEnabled(enabled)

    def set_preview_checked(self, checked: bool):
        """同步 2D 预览按钮勾选状态（不触发 toggled 信号）。"""
        if self._btn_preview.isChecked() != checked:
            self._arrival_times.clear()
        self._btn_preview.blockSignals(True)
        self._btn_preview.setChecked(checked)
        self._btn_preview.blockSignals(False)
        self._update_preview_icon(checked)

    def _on_preview_toggled(self, checked: bool):
        """2D 预览按钮切换：同步图标颜色并向上转发信号。"""
        self._update_preview_icon(checked)
        self._arrival_times.clear()
        self.preview_toggled.emit(self.camera_id, checked)

    def _update_preview_icon(self, checked: bool):
        """根据勾选状态更新预览按钮图标颜色。"""
        color = ACCENT if checked else TEXT_SECONDARY
        ui_icons.apply(self._btn_preview, "video", color, 16)

    def mousePressEvent(self, event):
        self.clicked.emit(self.camera_id)
        super().mousePressEvent(event)


class CameraGrid(QScrollArea):
    """相机卡片网格（响应式列数，N 台相机水平平铺）。

    信号：
        card_clicked(str)  点击某张卡片。
    """

    card_clicked = Signal(str)
    focus_changed = Signal(str)
    database_focus_requested = Signal()
    frames_changed = Signal()
    CARD_WIDTH = 300
    CARD_HEIGHT = 270
    H_SPACING = 8
    V_SPACING = 8

    def __init__(self, parent=None, *, preview_factory=None):
        super().__init__(parent)
        self._preview_factory = preview_factory
        self._cards: Dict[str, CameraCard] = {}
        self._titles: Dict[str, str] = {}
        self._last_cols: Optional[int] = None
        self._overview = False
        self._focused_id = None
        self._database_card = None
        self._layout_columns = 0

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(self.H_SPACING)
        self._grid.setVerticalSpacing(self.V_SPACING)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setWidget(self._container)

    # ------------------------------------------------------------ 公共接口
    def set_cameras(self, camera_ids: List[str], titles: Optional[Dict[str, str]] = None):
        """重建网格（连接设备变化时调用）。

        titles: {camera_id: 显示名称}，未提供时显示 camera_id。
        """
        self.show_database_frame(None)
        for card in self._cards.values():
            self._grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards.clear()
        self._titles = dict(titles or {})
        self._focused_id = None

        for cid in camera_ids:
            card = CameraCard(cid, title=self._titles.get(cid, cid), preview_factory=self._preview_factory)
            card.clicked.connect(self.card_clicked)
            card.focus_requested.connect(self.focus_camera)
            self._cards[cid] = card
            if self._overview:
                card.set_overview(True)
        self._last_cols = None
        self._relayout()
        self.focus_changed.emit('')
        self.frames_changed.emit()

    def set_overview(self, enabled):
        if self._overview == enabled:
            return
        self.show_database_frame(None)
        self._overview = enabled
        self._focused_id = None
        self._grid.setAlignment(Qt.AlignTop if enabled else Qt.AlignTop | Qt.AlignLeft)
        self.CARD_WIDTH = 245 if enabled else type(self).CARD_WIDTH
        for card in self._cards.values():
            card.show()
            card.set_overview(enabled)
            if not enabled and card.current_frame() is not None:
                card.set_frame(card.current_frame())
        self._last_cols = None
        self._relayout()
        self.focus_changed.emit('')

    def focus_camera(self, camera_id=None):
        if not self._overview or self._database_card is not None:
            return
        self._focused_id = camera_id if camera_id in self._cards and self._focused_id != camera_id else None
        for cid, card in self._cards.items():
            card.setVisible(self._focused_id is None or cid == self._focused_id)
        self._last_cols = None
        self._relayout()
        self.focus_changed.emit(self._focused_id or '')

    def show_database_frame(self, frame):
        """Read-only archive display in the shared 2D area; never replace live frames."""
        if self._database_card is not None:
            self._grid.removeWidget(self._database_card)
            self._database_card.hide()
            self._database_card.deleteLater()
            self._database_card = None
        if frame is not None:
            card = CameraCard(frame.camera_name, title=f'{frame.camera_name} · DB 帧 {frame.frame_id:03d}',
                              preview_factory=self._preview_factory)
            card.set_overview(True)
            card.focus_requested.connect(lambda _: self.database_focus_requested.emit())
            card.set_frame(frame)
            card.set_marker_count(len(frame.markers_all or frame.markers))
            card.set_frame_kind(None)
            card._kind.setText('只读')
            card._name.setToolTip('DB历史帧；点击“返回工作视图”恢复实时相机画面')
            card._thumb.setToolTip('DB历史帧预览；点击“返回工作视图”恢复实时相机画面')
            for button in (card._btn_preview, card._btn_capture, card._btn_detect):
                button.hide()
            self._database_card = card
        for cid, card in self._cards.items():
            card.setVisible(frame is None and (self._focused_id is None or cid == self._focused_id))
        self._last_cols = None
        self._relayout()

    def set_marker_pair(self, reference_id, accepted=None):
        from ui_common.industrial_scene.marker_display import classify_markers
        reference_card = self.card(reference_id)
        reference = reference_card.current_frame() if reference_card else None
        reference_markers = (reference.markers_all or reference.markers) if reference is not None else None
        for cid, card in self._cards.items():
            frame = card.current_frame()
            if frame is None or frame.image_np is None:
                continue
            height, width = frame.image_np.shape[:2]
            display = classify_markers(frame.markers_all or frame.markers,
                reference_markers if cid != reference_id else None, registration_accepted=accepted)
            card.set_marker_overlay([dict(x=row.xy[0]/max(1,width), y=row.xy[1]/max(1,height),
                code=row.code, valid_3d=row.xyz is not None, display_color=row.color) for row in display.rows])

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()

    def set_layout_columns(self, columns):
        self._layout_columns = max(0, min(4, int(columns)))
        self._last_cols = None
        self._relayout()

    def _relayout(self):
        """根据当前 viewport 宽度计算列数并重新排布卡片，列宽水平铺满。

        仅当列数真正变化时才移除/重加卡片，避免拖动 splitter 或窗口
        缩放时频繁全量 relayout 造成卡顿。
        """
        cards = ([self._database_card] if self._database_card is not None else
                 [card for cid, card in self._cards.items() if self._focused_id is None or cid == self._focused_id])
        n = len(cards)
        if n == 0:
            return

        viewport_w = self.viewport().width()
        # 每个卡片最小占用宽度 = 卡片最小宽 + 水平间距
        col_unit = self.CARD_WIDTH + self.H_SPACING
        cols = max(1, viewport_w // col_unit)
        cols = min(cols, n)
        if self._overview:
            # Choose the arrangement by actual image area. In a narrow joint
            # view, two cameras stack; in a wide 2D view they sit side by side.
            ratios = [card.current_frame().image_np.shape[1] / card.current_frame().image_np.shape[0]
                for card in cards if card.current_frame() is not None and card.current_frame().image_np is not None]
            ratio = sum(ratios)/len(ratios) if ratios else 4/3
            available_h = max(1, self.viewport().height()-8)
            best = (-1, 1, 210)
            max_cols = min(n, max(1, (viewport_w-8+self.H_SPACING)//(230+self.H_SPACING)))
            candidates = [min(max_cols, self._layout_columns)] if self._layout_columns else range(1, max_cols+1)
            for candidate in candidates:
                rows = (n+candidate-1)//candidate
                width = (viewport_w-8-(candidate-1)*self.H_SPACING)/candidate
                height = max(210, (available_h-(rows-1)*self.V_SPACING)//rows)
                image_h = max(1, min(height-100, (width-12)/ratio))
                score = image_h*image_h*ratio*n*min(1, available_h/(rows*height+(rows-1)*self.V_SPACING))
                if score > best[0]:
                    best = (score, candidate, height)
            _, cols, height = best
            for card in cards:
                card.setFixedHeight(height)

        if cols == self._last_cols:
            # 列数未变，QGridLayout 的 stretch 会让卡片自动均分宽度，
            # 无需移除并重排所有卡片。
            return

        # 清空布局
        for card in self._cards.values():
            self._grid.removeWidget(card)
        # 重置列拉伸（先清零，再为当前列数设置均分）
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)
        # 重新按行添加
        for i, card in enumerate(cards):
            self._grid.addWidget(card, i // cols, i % cols)
        # 当前使用的列均分可用宽度
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

        self._last_cols = cols

    def card(self, camera_id: str) -> Optional[CameraCard]:
        return self._cards.get(camera_id)

    def camera_ids(self) -> List[str]:
        return list(self._cards.keys())

    def set_frame(self, camera_id: str, frame: Optional[FrameData],
                  markers: Optional[list] = None):
        """更新指定相机卡片的帧与标记叠加。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_frame(frame, markers)
            if self._overview:
                self._relayout()
            self.frames_changed.emit()

    def set_marker_count(self, camera_id: str, count: Optional[int]):
        """更新指定相机卡片的标记数量角标。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_marker_count(count)

    def set_covis_status(self, camera_id: str, ok: Optional[bool]):
        """更新指定相机卡片的共视状态角标。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_covis_status(ok)

    def set_frame_kind(self, camera_id: str, kind: Optional[str]):
        """更新指定相机卡片的帧分区标签。"""
        card = self._cards.get(camera_id)
        if card is not None:
            card.set_frame_kind(kind)
