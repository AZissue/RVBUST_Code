"""Probe controls shared by the reusable analysis dialog."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QCheckBox, QSizePolicy


class ProbePanel(QGroupBox):
    analyze = Signal()

    def __init__(self, parent=None):
        super().__init__('点云探针', parent)
        layout = QVBoxLayout(self)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0, 1e8)
        self.threshold.setDecimals(6)
        self.threshold.setSpecialValueText('自动：典型点间距的3倍')
        self.threshold.setSuffix(' mm')
        self.threshold.setToolTip('两份点云中，点与最近点的距离不超过此值，就计为重合。数值越大，判定越宽松；设为0使用自动值。')
        self.confirmed = QCheckBox('确认各来源点云已对齐，且坐标单位均为毫米')
        self.button = QPushButton('分析当前点云')
        self.button.clicked.connect(self.analyze)
        self.text = QLabel('点击后只读分析；不会自动处理点云。')
        self.text.setTextFormat(Qt.PlainText)
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(QLabel('重合判定距离（0表示自动）'))
        for widget in (self.threshold, self.confirmed, self.button, self.text):
            layout.addWidget(widget)
        hint = QLabel('检测结果会显示在左侧数据属性中，供后续处理时自行参考。不会填入或修改任何处理参数。\n重合比例表示有多少点在另一份点云附近，不等于表面面积重合比例；重合部分的点间距离也不能作为工件测量精度。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def reset(self):
        self.text.setText('点击分析当前点云。')
        self.confirmed.setChecked(False)

    def show_report(self, report):
        s = report['spacing']
        bbox = ' × '.join(f'{v:.4g}' for v in s['bbox'])
        lines = [f"有效点数：{s['count']:,}；点云尺寸（X × Y × Z）：{bbox} mm",
                 f"{'抽样估计' if s['estimated'] else '全量查询'}；样本 {s['samples']:,}；总耗时 {report['seconds']:.3f}s"]
        if 'p50' in s:
            lines += [f"典型点间距：{s['p50']:.6g} mm（最近邻距离的中位数）；平均点间距：{s['mean']:.6g} mm",
                      f"90%的点最近邻距离不超过：{s['p90']:.6g} mm；95%不超过：{s['p95']:.6g} mm"]
            if s['ratio'] is None or s['ratio'] >= 3:
                lines.append('密度提示：点分布差异较大或存在重复点，可分区域检查点云分布。')
            else:
                lines.append(f"密度参考：较大点间距约为典型值的{s['ratio']:.2f}倍（90%分位值÷中位数，越大表示间距差异越明显）。")
        else:
            lines.append(s['reason'])
        lines.append(f"重合判定距离：{report['tau']:.6g} mm（距离不超过此值的点计为重合）")
        if report.get('reason'):
            lines.append('来源点云重合比例暂不可计算：'+report['reason'])
        for a, b, row in report['directions']:
            if 'coverage' not in row:
                lines.append(f'{a}→{b}：不可计算：{row["reason"]}')
                continue
            lines.append(f"{a} → {b}：前者有{row['coverage']:.2%}的点在后者附近；样本 {row['samples']:,}（{'估计' if row['estimated'] else '全量'}）")
            if row['median'] is None:
                lines.append('  此判定距离内没有重合点，无法统计距离。')
            else:
                lines.append(f"  重合部分的最近点距离：典型值 {row['median']:.6g} mm；均方根距离 {row['rms']:.6g} mm（较大距离影响更明显）；95%不超过 {row['p95']:.6g} mm")
        rates = [r['coverage'] for _, _, r in report['directions'] if 'coverage' in r]
        if rates:
            import statistics
            lines.append(f'各方向重合比例汇总：最低 {min(rates):.2%}；典型值（中位数） {statistics.median(rates):.2%}（每个方向同等权重）')
        self.text.setText('\n'.join(lines))
