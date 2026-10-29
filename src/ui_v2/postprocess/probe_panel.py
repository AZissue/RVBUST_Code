"""Probe controls shared by the reusable analysis dialog."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QCheckBox, QSizePolicy


class ProbePanel(QGroupBox):
    analyze = Signal()
    adopt = Signal(float)

    def __init__(self, parent=None):
        super().__init__('点云探针', parent)
        layout = QVBoxLayout(self)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0, 1e8)
        self.threshold.setDecimals(6)
        self.threshold.setSpecialValueText('自动：3×P50')
        self.threshold.setSuffix(' mm (τ)')
        self.confirmed = QCheckBox('确认来源结果已配准至同一毫米坐标系')
        self.button = QPushButton('分析当前点云')
        self.button.clicked.connect(self.analyze)
        self.text = QLabel('点击后只读分析；不会自动处理点云。')
        self.text.setTextFormat(Qt.PlainText)
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.apply = QPushButton('采用为体素尺寸')
        self.apply.setEnabled(False)
        self.apply.clicked.connect(lambda: self.adopt.emit(self.voxel))
        for widget in (self.threshold, self.confirmed, self.button, self.text, self.apply):
            layout.addWidget(widget)
        hint = QLabel('阈值 τ 下的点覆盖重合率，不是面积重合率，也不是拼接绝对精度；重合区 RMS 不代表整个表面的精度。Mesh 实验参考：法向邻域可从 3–5×P50 起步；点间距不能确定 Poisson 深度或保证封装质量。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def reset(self):
        self.text.setText('点击分析当前点云。')
        self.apply.setEnabled(False)
        self.confirmed.setChecked(False)

    def show_report(self, report):
        s = report['spacing']
        bbox = ' × '.join(f'{v:.4g}' for v in s['bbox'])
        lines = [f"有效点 {s['count']:,}；包围盒 {bbox} mm",
                 f"{'抽样估计' if s['estimated'] else '全量查询'}；样本 {s['samples']:,}；总耗时 {report['seconds']:.3f}s"]
        if 'p50' in s:
            lines += [f"P50 {s['p50']:.6g} mm；算术平均 {s['mean']:.6g} mm",
                      f"P90 {s['p90']:.6g}；P95 {s['p95']:.6g} mm；P90/P50 {s['ratio']}",
                      f"体素起始 {s['voxel']:.6g} mm；范围 {s['voxel_range']} mm"]
            self.voxel = s['voxel']
            self.apply.setEnabled(self.voxel > 0)
            if s['ratio'] is None or s['ratio'] >= 3:
                lines.append('密度严重不均或重复点：不要对全场景盲目使用同一体素。')
        else:
            lines.append(s['reason'])
        lines.append(f"当前阈值 τ：{report['tau']:.6g} mm")
        if report.get('reason'):
            lines.append('重合度不可计算：'+report['reason'])
        for a, b, row in report['directions']:
            if 'coverage' not in row:
                lines.append(f'{a}→{b}：不可计算：{row["reason"]}')
                continue
            lines.append(f"{a}→{b}：{row['coverage']:.2%}；重合区中位/RMS/P95 {row['median']}/{row['rms']}/{row['p95']} mm；样本 {row['samples']}（{'估计' if row['estimated'] else '全量'}）")
        rates = [r['coverage'] for _, _, r in report['directions'] if 'coverage' in r]
        if rates:
            import statistics
            lines.append(f'各方向等权：最低 {min(rates):.2%}；中位数 {statistics.median(rates):.2%}')
        self.text.setText('\n'.join(lines))
