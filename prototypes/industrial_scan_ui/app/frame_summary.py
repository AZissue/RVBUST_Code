"""Compact production-style registration feedback, without invented metrics."""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

STATES = {'ok': ('#80d69b', '配准成功'), 'warn': ('#f1c86a', '需关注'),
          'fail': ('#ff7c82', '配准失败'), 'reference': ('#8fc6f0', '基准帧'),
          'idle': ('#9aa9b9', '未评估')}


def registration_state(layer):
    result = layer.registration or {}
    if result.get('is_reference'):
        return 'reference'
    if result.get('accepted') is False:
        return 'fail'
    if result.get('accepted') is True:
        return 'warn' if result.get('level') == 'warn' else 'ok'
    return 'idle'


class FrameQualityCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('frameQuality')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        self.title = QLabel('本帧评估 · 未选择')
        self.metrics = QLabel('共有圆 —　内点率 —　误差 —')
        self.suggestion = QLabel('选择帧查看拼接结果')
        self.suggestion.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.metrics)
        layout.addWidget(self.suggestion, 1)
        self.set_layer(None)

    def set_layer(self, layer):
        state = registration_state(layer) if layer is not None else 'idle'
        color, title = STATES[state]
        result = (layer.registration or {}) if layer is not None else {}
        self.title.setText('● '+title)
        self.title.setStyleSheet('color:'+color)
        shared, ratio, rms = (result.get(key) for key in ('shared_markers','inlier_ratio','rms_mm'))
        self.metrics.setText('共有圆 %s　内点率 %s　误差 %s' % (
            str(shared) if shared is not None else '—',
            f'{ratio:.0%}' if ratio is not None else '—',
            f'{rms:.3f} mm' if rms is not None else '—'))
        reference = result.get('reference_id')
        message = result.get('suggestion') or {
            'reference':'用作拼接基准，无帧间配准误差', 'idle':'尚无配准结果',
            'ok':'本帧已完成配准', 'warn':'请检查本帧配准结果',
            'fail':'请检查共有圆，重拍或重新配准'}[state]
        prefix = f'{layer.name} · ' if layer is not None else ''
        if reference is not None:
            prefix += f'参考帧 {reference} · '
        self.suggestion.setText(prefix+message)
        self.setStyleSheet(f'QFrame#frameQuality {{background:#29323b;border-left:3px solid {color};}}')
