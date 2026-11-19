"""Shared offline-capable recognition settings for all industrial workspaces."""
import copy
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox,
                              QGroupBox, QLabel, QPushButton, QLayout, QScrollArea, QCheckBox,
                              QSpinBox, QDoubleSpinBox)
from core.feature_masks import WorkpieceMaskSettings
from core.feature_settings import FEATURE_SETTING_LIMITS, FeatureSettings
from core.calib_board_detector import DEFAULT_BOARD_SPECS
from core.marker_detector import MARKER_TYPE_UNENCODED_CIRCLE, CircleParameters
from ..feature_recognition import FEATURE_RECOGNITION


class RecognitionParameters(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = None
        self.mode = None
        self._loaded = None
        self._edited = False
        self._loading = False
        self._revision = 0
        self._search_cancel = None
        self._search_result = None
        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(250)
        self.apply_timer.timeout.connect(self._apply)
        self._catalog = copy.deepcopy(DEFAULT_BOARD_SPECS)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(8)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(6)
        self.marker_type = QComboBox()
        self.marker_type.addItem('编码圆', 'coded_circle')
        self.marker_type.addItem('非对称圆标定板', 'asymmetric_grid')
        form.addRow('识别类型', self.marker_type)
        layout.addLayout(form)
        self.feature_group = QGroupBox('① 特征匹配区域（ROI）')
        roi_layout = QVBoxLayout(self.feature_group)
        self.roi_label = QLabel('整幅图像')
        self.roi_label.setWordWrap(True)
        self.draw_roi = QPushButton('绘制匹配 ROI…')
        self.draw_roi.setToolTip('使用选中的原始帧图像绘制，未选中时使用最近一帧。')
        self.clear_roi = QPushButton('恢复整图')
        roi_layout.addWidget(self.roi_label)
        roi_layout.addWidget(self.draw_roi)
        roi_layout.addWidget(self.clear_roi)
        self.draw_roi.clicked.connect(self._draw_feature_roi)
        self.clear_roi.clicked.connect(self._clear_feature_roi)
        layout.addWidget(self.feature_group)
        self.workpiece_group = QGroupBox('② 工件区域与二值化掩膜')
        mask_layout = QFormLayout(self.workpiece_group)
        self.workpiece_label = QLabel('工件区域未限定')
        self.workpiece_label.setWordWrap(True)
        self.draw_workpiece_roi = QPushButton('绘制工件 ROI…')
        self.clear_workpiece_roi = QPushButton('清除工件框')
        self.mask_enabled = QCheckBox('用二值化掩膜筛选特征点')
        self.mask_polarity = QComboBox()
        self.mask_polarity.addItem('亮工件 / 暗背景', 'bright')
        self.mask_polarity.addItem('暗工件 / 亮背景', 'dark')
        self.mask_threshold = QSpinBox()
        self.mask_threshold.setRange(-1, 255)
        self.mask_threshold.setSpecialValueText('自动 Otsu')
        self.mask_threshold.setKeyboardTracking(False)
        self.mask_threshold.setToolTip('自动按两个 ROI 的重叠区域计算阈值，或输入 0～255 手动调整。')
        self.mask_overlay = QCheckBox('在原始 2D 图像上显示掩膜')
        mask_note = QLabel('青框是匹配范围，橙框是工件范围。开启掩膜后，绿色区域参与匹配，红色区域被排除。')
        mask_note.setWordWrap(True)
        for control in (self.workpiece_label, self.draw_workpiece_roi, self.clear_workpiece_roi, self.mask_enabled):
            mask_layout.addRow(control)
        mask_layout.addRow('工件明暗', self.mask_polarity)
        mask_layout.addRow('二值化阈值', self.mask_threshold)
        mask_layout.addRow(self.mask_overlay)
        mask_layout.addRow(mask_note)
        self.draw_workpiece_roi.clicked.connect(self._draw_workpiece_roi)
        self.clear_workpiece_roi.clicked.connect(self._clear_workpiece_roi)
        self.mask_enabled.toggled.connect(self._apply_workpiece_mask)
        self.mask_polarity.currentIndexChanged.connect(self._apply_workpiece_mask)
        self.mask_threshold.valueChanged.connect(self._apply_workpiece_mask)
        self.mask_overlay.toggled.connect(self._toggle_mask_overlay)
        layout.addWidget(self.workpiece_group)
        self.feature_tuning = QGroupBox('2D 检测与 3D 配准')
        tuning_form = QFormLayout(self.feature_tuning)
        tuning_hint = QLabel('匹配点少：先框住工件，再试提高检测细节。转角太大：补拍有重叠的中间角度。')
        tuning_hint.setWordWrap(True)
        tuning_form.addRow(tuning_hint)
        fields = (
            ('image_size', '检测细节', ' px', '数值越高，保留的图像细节越多。工件小或纹理少时可调高，计算也会更慢。'),
            ('max_keypoints', '每帧最多找点', '', '工件上找点太少时可调高。建议先用 ROI 框住工件，避免背景占用点数。'),
            ('match_score', '图像匹配严格度', '', '调高会过滤低分匹配，但也会减少候选点。调低后请检查是否出现错配。'),
            ('depth_jump', '允许的深度落差', ' mm', '调小可避开轮廓和背景交界。调大只会放宽连续性检查，无法补出缺失的深度。'),
            ('tolerance', '允许的对齐误差', ' mm', '两点对齐后相距不超过此值才计为内点。放宽会更容易通过，也可能接纳错配。'),
            ('inlier_percent', '至少多少点对齐', ' %', '在有有效深度的匹配里，至少要有这个比例对齐，同时至少需要 6 对。'),
        )
        self.feature_fields = {}
        for key, label, suffix, hint in fields:
            low, high, step = FEATURE_SETTING_LIMITS[key]
            spin = QSpinBox() if isinstance(low, int) else QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setSuffix(suffix)
            spin.setToolTip(hint)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._apply_feature_settings)
            caption = QLabel(label)
            caption.setToolTip(hint)
            caption.setBuddy(spin)
            tuning_form.addRow(caption, spin)
            self.feature_fields[key] = spin
        self.reset_feature_tuning = QPushButton('恢复默认参数')
        self.reset_feature_tuning.clicked.connect(self._reset_feature_settings)
        tuning_form.addRow(self.reset_feature_tuning)
        layout.addWidget(self.feature_tuning)
        self.circle_group = QGroupBox('编码圆')
        circle = QFormLayout(self.circle_group)
        circle.setContentsMargins(8, 14, 8, 8)
        circle.setVerticalSpacing(6)
        self.circle_n = QSpinBox()
        self.circle_n.setRange(1, 32)
        self.circle_r1 = QDoubleSpinBox()
        self.circle_r2 = QDoubleSpinBox()
        for spin in (self.circle_r1, self.circle_r2):
            spin.setRange(.01, 20.)
            spin.setDecimals(2)
            spin.setSingleStep(.1)
        for label, spin in (('N', self.circle_n), ('r1 / r0', self.circle_r1), ('r2 / r0', self.circle_r2)):
            spin.setKeyboardTracking(False)
            circle.addRow(label, spin)
            spin.valueChanged.connect(self._changed)
            spin.lineEdit().textEdited.connect(self._validate_input)
        self.circle_n.setToolTip('整数 N：1～32。')
        for spin in (self.circle_r1, self.circle_r2):
            spin.setToolTip('有限正数，最大20；r2/r0 必须大于 r1/r0。')
        self.auto_button = QPushButton('自动识别')
        self.auto_button.setToolTip('在当前原始图像上搜索有限整数候选；按亮度变化前后稳定检出的编码圆数量选择。')
        self.auto_button.clicked.connect(self._auto_detect)
        circle.addRow(self.auto_button)
        layout.addWidget(self.circle_group)
        self.unencoded_group = QGroupBox('普通圆点 / 圆环')
        unencoded = QFormLayout(self.unencoded_group)
        self.dot_polarity = QComboBox()
        self.dot_polarity.addItem('黑圆点 / 浅色背景', 'dark')
        self.dot_polarity.addItem('白圆点 / 深色背景', 'light')
        self.dot_polarity.currentIndexChanged.connect(self._changed)
        unencoded.addRow('圆点极性', self.dot_polarity)
        self.dot_threshold = QSpinBox()
        self.dot_threshold.setRange(-1, 255)
        self.dot_threshold.setSpecialValueText('自动 Otsu')
        unencoded.addRow('灰度阈值', self.dot_threshold)
        self.dot_min_radius = QDoubleSpinBox()
        self.dot_max_radius = QDoubleSpinBox()
        self.dot_circularity = QDoubleSpinBox()
        for label, spin, low, high in (
            ('最小半径（像素）', self.dot_min_radius, 1, 999),
            ('最大半径（像素）', self.dot_max_radius, 2, 1000),
            ('最小圆度', self.dot_circularity, .1, 1),
        ):
            spin.setRange(low, high)
            unencoded.addRow(label, spin)
        self.dot_fields = dict(threshold=self.dot_threshold, min_radius=self.dot_min_radius,
                               max_radius=self.dot_max_radius, circularity=self.dot_circularity)
        for spin in self.dot_fields.values():
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._changed)
        self.dot_auto_button = QPushButton('自动设置')
        self.dot_auto_button.setToolTip('使用当前原始帧的图像和有序点云搜索参数，优先保留稳定的 3D 圆心。')
        self.dot_auto_button.clicked.connect(self._auto_detect)
        unencoded.addRow(self.dot_auto_button)
        layout.addWidget(self.unencoded_group)
        self.board_group = QGroupBox('非对称圆标定板')
        board = QFormLayout(self.board_group)
        board.setContentsMargins(8, 14, 8, 8)
        board.setVerticalSpacing(6)
        board.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.board_spec = QComboBox()
        self.board_spec.setMinimumContentsLength(10)
        self.board_spec.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.board_spec.setToolTip('优先选择板上实际行列数；自动模式会逐一尝试全部规格。')
        self.board_details = QLabel()
        self.board_details.setWordWrap(True)
        board.addRow('规格', self.board_spec)
        board.addRow(self.board_details)
        self.board_group.setToolTip('规格按行 × 列显示；圆心间距由三维数据自动估计。')
        layout.addWidget(self.board_group)
        layout.addStretch()
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.status = QLabel('识别参数可在未连接相机时设置。')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.marker_type.currentIndexChanged.connect(self._changed)
        self.board_spec.currentIndexChanged.connect(self._changed)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self._update_groups()
        self.setEnabled(False)

    def bind(self, bridge, mode):
        self._cancel_search()
        self.apply_timer.stop()
        self._revision += 1
        self.bridge = bridge if hasattr(bridge, 'recognition') else None
        self.mode = mode
        self._loaded = None
        self._edited = False
        index = self.marker_type.findData(MARKER_TYPE_UNENCODED_CIRCLE)
        with QSignalBlocker(self.marker_type):
            if mode in ('mobile_chain', 'turntable') and index < 0:
                self.marker_type.addItem('普通圆点 / 圆环（几何匹配）', MARKER_TYPE_UNENCODED_CIRCLE)
            elif mode not in ('mobile_chain', 'turntable') and index >= 0:
                self.marker_type.removeItem(index)
            feature = self.marker_type.findData(FEATURE_RECOGNITION)
            supported = mode == 'mobile_chain' and getattr(getattr(bridge, 'shell', None),
                                                           'feature_recognition_enabled', False)
            if supported and feature < 0:
                self.marker_type.addItem('SuperPoint + LightGlue（2D 特征）', FEATURE_RECOGNITION)
            elif not supported and feature >= 0:
                self.marker_type.removeItem(feature)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        self.apply_timer.stop()
        self._cancel_search()
        self._revision += 1
        self._edited = False
        self._loaded = None
        super().hideEvent(event)

    def refresh(self):
        ready = bool(self.bridge and not getattr(self.bridge, '_cleaned', False)
                     and self.bridge._current_mode == self.mode)
        self.setEnabled(ready)
        if not ready:
            self.apply_timer.stop()
            self._cancel_search()
            return
        config = self.bridge.recognition.config(self.mode)
        if config != self._loaded and not self._edited:
            self._load(config)
        idle = self.bridge.can_change_workspace()
        for control in (self.marker_type, self.board_spec, self.circle_n, self.circle_r1, self.circle_r2,
                        self.dot_polarity, *self.dot_fields.values()):
            control.setEnabled(idle and self._search_cancel is None)
        self.auto_button.setEnabled(idle or self._search_cancel is not None)
        self.dot_auto_button.setEnabled(idle or self._search_cancel is not None)
        if config['marker_type'] == FEATURE_RECOGNITION:
            roi = self.bridge.stitching.feature_roi()
            text = ('整幅图像' if roi is None else
                    '已框选：横向 %.0f%%–%.0f%%，纵向 %.0f%%–%.0f%%' %
                    (roi[0]*100, roi[2]*100, roi[1]*100, roi[3]*100))
            self.roi_label.setText(text)
            self.draw_roi.setEnabled(idle)
            self.clear_roi.setEnabled(idle and roi is not None)
            stitch = self.bridge.stitching
            workpiece = stitch.workpiece_roi()
            self.workpiece_label.setText('工件区域未限定' if workpiece is None else
                '已框选：横向 %.0f%%–%.0f%%，纵向 %.0f%%–%.0f%%' %
                (workpiece[0]*100, workpiece[2]*100, workpiece[1]*100, workpiece[3]*100))
            self.draw_workpiece_roi.setEnabled(idle)
            self.clear_workpiece_roi.setEnabled(idle and workpiece is not None)
            mask = stitch.workpiece_mask()
            self.mask_enabled.setEnabled(idle)
            self.mask_polarity.setEnabled(idle)
            self.mask_threshold.setEnabled(idle)
            with QSignalBlocker(self.mask_enabled), QSignalBlocker(self.mask_polarity), QSignalBlocker(self.mask_threshold), QSignalBlocker(self.mask_overlay):
                self.mask_enabled.setChecked(mask.enabled)
                self.mask_polarity.setCurrentIndex(self.mask_polarity.findData(mask.polarity))
                if self.mask_threshold.value() != mask.threshold:
                    self.mask_threshold.setValue(mask.threshold)
                self.mask_overlay.setChecked(stitch.show_feature_mask())
            settings = self.bridge.stitching.feature_settings()
            self.feature_tuning.setEnabled(idle)
            for key, spin in self.feature_fields.items():
                if spin.value() != getattr(settings, key):
                    with QSignalBlocker(spin):
                        spin.setValue(getattr(settings, key))
            self.reset_feature_tuning.setEnabled(settings != FeatureSettings())

    def _draw_workpiece_roi(self):
        self.bridge.stitching.configure_feature_roi(workpiece=True)
        self.refresh()

    def _clear_workpiece_roi(self):
        self.bridge.stitching.set_workpiece_roi(None)
        self.refresh()

    def _apply_workpiece_mask(self):
        if self.bridge is None or self.marker_type.currentData() != FEATURE_RECOGNITION:
            return
        settings = WorkpieceMaskSettings(enabled=self.mask_enabled.isChecked(),
            polarity=self.mask_polarity.currentData(), threshold=self.mask_threshold.value())
        self.bridge.stitching.set_workpiece_mask(settings)
        self.refresh()

    def _toggle_mask_overlay(self, enabled):
        if self.bridge is not None and self.marker_type.currentData() == FEATURE_RECOGNITION:
            self.bridge.stitching.set_show_feature_mask(enabled)
            self.refresh()

    def _apply_feature_settings(self):
        if self.bridge is not None and self.marker_type.currentData() == FEATURE_RECOGNITION:
            settings = FeatureSettings(**{key: spin.value() for key, spin in self.feature_fields.items()})
            self.bridge.stitching.set_feature_settings(settings)
            self.refresh()

    def _reset_feature_settings(self):
        self.bridge.stitching.set_feature_settings(FeatureSettings())
        self.refresh()

    def _draw_feature_roi(self):
        self.bridge.stitching.configure_feature_roi()
        self.refresh()

    def _clear_feature_roi(self):
        self.bridge.stitching.set_feature_roi(None)
        self.refresh()

    def _load(self, config):
        self._loading = True
        for spec in config['boards']:
            if spec not in self._catalog:
                self._catalog.append(copy.deepcopy(spec))
        with QSignalBlocker(self.marker_type), QSignalBlocker(self.board_spec):
            self.marker_type.setCurrentIndex(self.marker_type.findData(config['marker_type']))
            self.board_spec.clear()
            self.board_spec.addItem('自动识别全部规格', copy.deepcopy(self._catalog))
            for spec in self._catalog:
                self.board_spec.addItem(f"{spec['rows']} × {spec['cols']}", [copy.deepcopy(spec)])
            selected = next((i for i in range(self.board_spec.count())
                             if self.board_spec.itemData(i) == config['boards']), None)
            if selected is None:
                self.board_spec.addItem('当前配置的规格组合', copy.deepcopy(config['boards']))
                selected = self.board_spec.count() - 1
            self.board_spec.setCurrentIndex(selected)
        n, r1, r2 = config['circle']
        for spin, value in zip((self.circle_n, self.circle_r1, self.circle_r2), (n, r1, r2)):
            spin.setValue(value)
        dot_params = CircleParameters(**config.get('unencoded', {}))
        self.dot_polarity.setCurrentIndex(self.dot_polarity.findData(dot_params.polarity))
        for key, spin in self.dot_fields.items():
            spin.setValue(getattr(dot_params, key))
        self._loaded = copy.deepcopy(config)
        self._edited = False
        self._loading = False
        self._update_groups()
        self.status.setText(
            '拍摄后仅后台缓存 2D 匹配，蓝点表示待 3D 验证。点击「执行拼接」进行配准和合并。'
            if config['marker_type'] == FEATURE_RECOGNITION else '修改后自动应用；无需连接相机。')

    def _update_groups(self):
        board = self.marker_type.currentData() == 'asymmetric_grid'
        dots = self.marker_type.currentData() == MARKER_TYPE_UNENCODED_CIRCLE
        self.circle_group.setVisible(not board and not dots and self.marker_type.currentData() != FEATURE_RECOGNITION)
        features = self.marker_type.currentData() == FEATURE_RECOGNITION
        self.feature_group.setVisible(features)
        self.feature_tuning.setVisible(features)
        self.workpiece_group.setVisible(features)
        self.board_group.setVisible(board)
        self.unencoded_group.setVisible(dots)
        specs = self.board_spec.currentData() or []
        details = '\n'.join(f"{spec['rows']} × {spec['cols']} · {spec['rows'] * spec['cols']} 圆心" for spec in specs)
        self.board_details.setToolTip(details)
        self.board_details.setText(details if len(specs) == 1 else
                                   f"自动尝试 {len(specs)} 种规格：" + ' / '.join(
                                       f"{s['rows']}×{s['cols']}" for s in specs))

    def _changed(self, *_):
        if self._loading or self._loaded is None:
            return
        self._revision += 1
        self._cancel_search()
        self._edited = True
        self._update_groups()
        if self.marker_type.currentData() == FEATURE_RECOGNITION or self._loaded['marker_type'] == FEATURE_RECOGNITION:
            self.apply_timer.stop()
            self._apply()
            return
        self.status.setText('正在等待参数自动应用…')
        self.apply_timer.start()

    def _apply(self):
        if not self.bridge or not self._edited or getattr(self.bridge, '_cleaned', False):
            return
        if not self._validate_input():
            return
        # A change in the legacy controls must not silently overwrite new settings.
        if self.bridge.recognition.config(self.mode) != self._loaded:
            self._edited = False
            self._search_result = None
            self.refresh()
            self.status.setText('识别配置已在其他入口变化，已重新读取；请重新修改。')
            return
        config = self._loaded
        search_result, self._search_result = self._search_result, None
        if search_result is not None:
            try:
                self.bridge.recognition.validate_search_source(self.mode, search_result['source'])
            except ValueError as exc:
                self._load(config)
                self.status.setText(str(exc))
                return
        circle = [self.circle_n.value(), self.circle_r1.value(), self.circle_r2.value()]
        for index, spin in enumerate((self.circle_r1, self.circle_r2), 1):
            if circle[index] == round(config['circle'][index], spin.decimals()):
                circle[index] = config['circle'][index]
        if self.marker_type.currentData() != 'coded_circle':
            circle = config['circle']
        dots = None
        if self.marker_type.currentData() == MARKER_TYPE_UNENCODED_CIRCLE:
            dots = dict(config.get('unencoded', {}), **{key: spin.value() for key, spin in self.dot_fields.items()})
            dots['polarity'] = self.dot_polarity.currentData()
        try:
            self.bridge.recognition.configure(self.mode, self.marker_type.currentData(),
                                              self.board_spec.currentData(), config['gamma'],
                                              circle=circle, **({'unencoded': dots} if dots is not None else {}))
        except ValueError as exc:
            if search_result is not None:
                self._load(config)
            self.status.setText(str(exc))
            return
        self._edited = False
        self.refresh()
        if search_result and 'unencoded' in search_result:
            self.status.setText(f"已应用参数，稳定检出 {search_result['stable_count']} 个有效 3D 圆心。")
        elif self.marker_type.currentData() != FEATURE_RECOGNITION:
            self.status.setText('已自动应用；原始帧将按新参数后台识别。')

    def _validate_input(self, *_):
        if self.marker_type.currentData() == 'coded_circle' and not all(
                spin.hasAcceptableInput() for spin in (self.circle_n, self.circle_r1, self.circle_r2)):
            self.apply_timer.stop()
            self.status.setText('输入无效：N 为 1～32 整数，半径比例为 0～20 内的正数。')
            return False
        return True

    def _cancel_search(self):
        self._search_result = None
        if self._search_cancel is not None:
            self._search_cancel.set()
            self._search_cancel = None
        if hasattr(self, 'auto_button'):
            self.auto_button.setText('自动识别')
            self.dot_auto_button.setText('自动设置')

    def _auto_detect(self):
        if self._search_cancel is not None:
            self._cancel_search()
            self._revision += 1
            self.status.setText('自动识别已取消，手动参数保持不变。')
            return
        if not self.bridge or self._edited:
            self.status.setText('请等待手动参数自动应用，或修正无效参数后重试。')
            return
        revision, mode = self._revision, self.mode
        dots = self.marker_type.currentData() == MARKER_TYPE_UNENCODED_CIRCLE
        button = self.dot_auto_button if dots else self.auto_button
        label = button.text()
        def done(result, error):
            if revision != self._revision or mode != self.mode:
                return
            self._search_cancel = None
            button.setText(label)
            if error:
                self.refresh()
                self.status.setText(str(error))
                return
            self._loading = True
            if dots:
                parameters = result['unencoded']
                self.dot_polarity.setCurrentIndex(self.dot_polarity.findData(parameters['polarity']))
                for key, spin in self.dot_fields.items():
                    spin.setValue(parameters[key])
            else:
                for spin, value in zip((self.circle_n, self.circle_r1, self.circle_r2), result['circle']):
                    spin.setValue(value)
            self._loading = False
            self._changed()
            self._search_result = result
            marker = '个有效 3D 圆心' if dots else '个编码圆'
            self.status.setText(f"稳定检出 {result['stable_count']} {marker}，正在应用参数…")
        try:
            self._search_cancel = self.bridge.recognition.search_current(mode, done)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        button.setText('取消' + label)
        self.status.setText('正在搜索极性、灰度和半径，比较 3D 圆心稳定性…' if dots else
                            '正在搜索整数参数，比较不同亮度下的稳定检出…')
        self.refresh()
