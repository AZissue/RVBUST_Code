"""Read-only bounded preview; the histogram counts every ROI point."""
import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
    QLabel, QComboBox, QSpinBox, QCheckBox, QDialogButtonBox, QWidget)
from ui_v2.dialogs import localize_buttons
from ui_v2.postprocess.parameter_guard import ParameterGuard

class FilterPreview(QWidget):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._preview_data = data
        self.rejected = np.zeros(len(data['points']),dtype=bool)
        self.mark_removed = True
        self.setMinimumSize(420,300)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(),QColor('#444444'))
        points = self._preview_data['points']
        if not len(points):
            return
        low, high = points.min(axis=0), points.max(axis=0)
        scale = min((self.width()-24)/max(high[0]-low[0],1e-8),
                    (self.height()-24)/max(high[1]-low[1],1e-8))
        xy = (points-(low+high)/2)*scale+[self.width()/2,self.height()/2]
        for i, point in enumerate(xy):
            if self.rejected[i] and not self.mark_removed:
                continue
            color = QColor('#ff4646') if self.rejected[i] else QColor.fromRgbF(*self._preview_data['colors'][i])
            painter.setPen(QPen(color,2))
            painter.drawPoint(QPointF(*point))

class ColorFilterDialog(QDialog):
    def __init__(self, data, state=None, parent=None):
        super().__init__(parent)
        self._preview_data = data
        self.setWindowTitle('框内颜色过滤 · 去除黑边')
        self.setModal(True)
        self.resize(640,620)
        layout = QVBoxLayout(self)
        help_text = QLabel('只处理当前框内点，框外全部保留。低于下限或高于上限的点被剔除。\n'
            '去黑边可先将亮度下限设为40，再逐步调整。亮度=max(R,G,B)，0黑、255亮。\n'
            '框选沿视线投影，包含遮挡点；真实暗纹理也可能被选中，请先检查预览。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()
        self.metric_combo = QComboBox()
        for title,key in [('亮度（RGB最大值）','value'),('灰度（加权RGB）','gray'),
                          ('红色 R','red'),('绿色 G','green'),('蓝色 B','blue')]:
            self.metric_combo.addItem(title,key)
        form.addRow('过滤依据',self.metric_combo)
        self.low, self.high = QSpinBox(),QSpinBox()
        self._guard = ParameterGuard(self)
        for spin in (self.low,self.high):
            spin.setRange(0,255)
            spin.installEventFilter(self._guard)
            spin.setFocusPolicy(Qt.StrongFocus)
        form.addRow('保留范围下限',self.low)
        form.addRow('保留范围上限',self.high)
        layout.addLayout(form)
        self.mark = QCheckBox('标红待剔除点（取消勾选查看去除后的预览）')
        self.mark.setChecked(True)
        layout.addWidget(self.mark)
        self.preview = FilterPreview(data)
        layout.addWidget(self.preview,1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel('预览最多12,000个框内采样点；统计和实际处理使用全部原始点。'))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        localize_buttons(buttons)
        self.execute_button = buttons.button(QDialogButtonBox.Ok)
        self.execute_button.setText('应用框内颜色过滤')
        self.execute_button.setAutoDefault(False)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        state = state or {}
        self.metric_combo.setCurrentIndex(max(0,self.metric_combo.findData(state.get('metric','value'))))
        self.low.setValue(state.get('low',40))
        self.high.setValue(state.get('high',255))
        for control in (self.low,self.high):
            control.valueChanged.connect(self.refresh)
        self.metric_combo.currentIndexChanged.connect(self.refresh)
        self.mark.toggled.connect(self.refresh)
        self.refresh()

    def parameters(self):
        return dict(low=self.low.value(), high=self.high.value(), metric=self.metric_combo.currentData())

    def refresh(self, *_):
        params = self.parameters()
        low, high, metric = params['low'], params['high'], params['metric']
        valid = low <= high
        histogram = self._preview_data['histograms'][metric]
        removed = int(histogram[:low].sum()+histogram[high+1:].sum()) if valid else 0
        remaining = self._preview_data['total']-removed
        values = self._preview_data['values'][metric]
        self.preview.rejected = (values<low)|(values>high)
        self.preview.mark_removed = self.mark.isChecked()
        self.preview.update()
        self.execute_button.setEnabled(valid and removed>0 and remaining>0)
        self.summary.setText(('下限不能大于上限。' if not valid else
            f"框内 {self._preview_data['selected']:,} 点；待剔除 {removed:,} 点；结果保留 {remaining:,} 点。")+
            (' 没有匹配的待剔除点，请调整阈值。' if valid and removed==0 else '')+
            (' 保留结果为空，禁止执行。' if valid and remaining==0 else ''))

    def accept(self):
        self.refresh()
        if self.execute_button.isEnabled():
            super().accept()
