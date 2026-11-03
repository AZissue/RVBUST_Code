"""Probe controls shared by the reusable analysis dialog."""
import math
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QCheckBox, QSizePolicy


def reference_text(stats):
    """Density-based starting points only; never populate processing controls."""
    spacing = stats.get('p50', 0)
    if not math.isfinite(spacing) or spacing <= 0:
        return '暂无可靠参考值：有效点不足或重复点过多，请先检查点云。'
    voxel = 1.5 * spacing
    distance = 3 * spacing
    sampling_value = f'{voxel:.2f} mm' if .01 <= voxel <= 100000 else '超出可设置范围，请检查尺度'
    icp_voxel = f'{voxel:.3f} mm' if .001 <= voxel <= 1000 else '超出可设置范围，请检查尺度'
    icp_distance = f'{distance:.3f} mm' if .001 <= distance <= 1000 else '超出可设置范围，请检查尺度'
    lines = [f'下采样 · 体素尺寸：{sampling_value}',
             f'ICP · 计算体素：{icp_voxel}',
             f'ICP · 最大对应距离：{icp_distance}',
             f'下采样可试 {spacing:.4g}～{2*spacing:.4g} mm；越大点越少、细节越少。',
             f'ICP对应距离可试 {distance:.4g}～{5*spacing:.4g} mm，仅适用于已粗略对齐的点云。',
             '估算方式：体素取典型点间距的1.5倍，ICP最大对应距离取3倍；不跟随检测重合判定距离变化。',
             '以上按当前点间距估算，需在处理窗口手动设置。单份点云不能判断两帧错位或最佳ICP参数。']
    if not (.001 <= voxel <= 1000 and .001 <= distance <= 1000):
        lines.append('ICP参考值超出当前参数窗口范围（0.001～1000 mm），请检查数据单位和尺度，不要直接照填。')
    if stats.get('ratio') is None or stats['ratio'] >= 3:
        lines.append('点密度差异较大或存在重复点，以上全局参考值应分区域复核。')
    return '\n'.join(lines)


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
        lines = [f"有效点数：{s['count']:,}", f"尺寸（X × Y × Z）：{bbox} mm",
                 f"{'抽样估计' if s['estimated'] else '全量查询'} {s['samples']:,} 点 · 耗时 {report['seconds']:.2f}s"]
        if 'p50' in s:
            lines += [f"典型点间距：{s['p50']:.4g} mm（中位数）",
                      f"平均点间距：{s['mean']:.4g} mm",
                      f"90%的最近邻距离 ≤ {s['p90']:.4g} mm",
                      f"95%的最近邻距离 ≤ {s['p95']:.4g} mm"]
            if s['ratio'] is None or s['ratio'] >= 3:
                lines.append('密度提示：点分布差异较大或存在重复点，可分区域检查点云分布。')
            else:
                lines.append(f"点间距差异：{s['ratio']:.2f}倍（90%分位值÷典型值；越大越不均匀）")
        else:
            lines.append(s['reason'])
        lines.append(f"本次重合判定距离：{report['tau']:.4g} mm（仅用于本次检测）")
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
