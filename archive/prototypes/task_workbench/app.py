"""Standalone MCC task-pane interaction prototype; all data are simulated."""
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from model import Workflow


class Preview(QWidget):
    def __init__(self):
        super().__init__()
        self.caption = '演练输入预览 · 无真实点云'
        self.setMinimumSize(280, 220)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#171a1f'))
        p.setPen(QPen(QColor('#2b3038'), 1))
        for x in range(0, self.width(), 32):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QColor('#aeb7c3'))
        p.drawText(self.rect(), Qt.AlignCenter, self.caption)
        p.end()


def button(text, slot):
    result = QPushButton(text)
    result.setMinimumHeight(34)
    result.clicked.connect(slot)
    return result


class Workbench(QMainWindow):
    def __init__(self):
        super().__init__()
        self.flow = Workflow()
        self.view_visible = {}
        self.focused = False
        self.token = None
        self.ticks = 0
        self.job_failed = False
        self.setWindowTitle('MCC SCAN STUDIO · 操作逻辑测试台（模拟）')
        self.resize(1366, 768)
        self.setMinimumSize(1000, 640)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        top = QHBoxLayout()
        brand = QLabel('MCC  /  SCAN STUDIO')
        brand.setObjectName('brand')
        top.addWidget(brand)
        top.addStretch()
        top.addWidget(QLabel('演练项目 · 未写入磁盘'))
        top.addWidget(button('保存说明', lambda: self.explain('原型不保存正式项目；关闭后演练结果丢弃。')))
        top.addWidget(button('导出说明', self.export_info))
        self.focus_button = button('专注视图', self.toggle_focus)
        top.addWidget(self.focus_button)
        outer.addLayout(top)
        banner = QLabel('交互原型 / 全部输入、进度与结果均为模拟 / 不连接设备、不执行配准、不写正式会话')
        banner.setObjectName('banner')
        outer.addWidget(banner)
        self.split = QSplitter()
        outer.addWidget(self.split, 1)

        self.left = QWidget()
        left = QVBoxLayout(self.left)
        left.addWidget(QLabel('项目数据'))
        left.addWidget(QLabel('行选择＝查看　输入＝参与计算　显示＝预览'))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['对象', '输入', '显示'])
        self.tree.setColumnWidth(0, 126)
        self.tree.setColumnWidth(1, 44)
        self.tree.setColumnWidth(2, 44)
        for i in range(1, 4):
            item = QTreeWidgetItem(self.tree, [f'机位 {i:03d}', '', ''])
            item.setCheckState(1, Qt.Unchecked)
            item.setCheckState(2, Qt.Checked)
            self.view_visible[item.text(0)] = True
        left.addWidget(self.tree)
        self.tree.currentItemChanged.connect(self.select_item)
        self.tree.itemChanged.connect(self.change_item)
        self.split.addWidget(self.left)

        center = QWidget()
        middle = QVBoxLayout(center)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('工作视图'))
        toolbar.addStretch()
        toolbar.addWidget(button('适配', lambda: self.set_preview('演练视图已适配；无真实几何数据')))
        middle.addLayout(toolbar)
        self.object_label = QLabel('查看对象：机位 001')
        middle.addWidget(self.object_label)
        self.preview = Preview()
        middle.addWidget(self.preview, 1)
        self.result_label = QLabel('候选：无  /  生成结果：0')
        middle.addWidget(self.result_label)
        self.split.addWidget(center)

        self.right = QWidget()
        right = QVBoxLayout(self.right)
        right.addWidget(QLabel('任务操作'))
        self.mode = QComboBox()
        self.mode.addItems(['离线拼接 · 首批交互验证', '多相机 · 迁移占位', '移动拼接 · 迁移占位', '转台 · 迁移占位', '机器人 · 迁移占位'])
        self.mode.currentIndexChanged.connect(self.change_mode)
        right.addWidget(self.mode)
        self.back_button = button('返回工具目录', lambda: self.pages.setCurrentIndex(0))
        right.addWidget(self.back_button)
        self.input_label = QLabel()
        self.input_label.setWordWrap(True)
        right.addWidget(self.input_label)
        self.pages = QStackedWidget()
        menu = QWidget()
        menu_layout = QVBoxLayout(menu)
        menu_layout.addWidget(QLabel('离线任务 / 输入 → 候选 → 检查 → 结果'))
        menu_layout.addWidget(button('进入配准任务', lambda: self.pages.setCurrentIndex(1)))
        menu_layout.addWidget(QLabel('从左侧勾选至少两项输入。\n单击数据行仅改变查看对象。'))
        menu_layout.addStretch()
        self.pages.addWidget(menu)
        form_widget = QWidget()
        form = QVBoxLayout(form_widget)
        form.addWidget(QLabel('配准候选 · 演练'))
        fields = QFormLayout()
        self.parameter = QDoubleSpinBox()
        self.parameter.setRange(.1, 100)
        self.parameter.setValue(1)
        self.parameter.setSuffix(' mm')
        self.parameter.valueChanged.connect(self.parameter_changed)
        fields.addRow('最大距离', self.parameter)
        form.addLayout(fields)
        form.addWidget(QLabel('输入或参数变化后，旧候选立即失效。\n返回目录保留参数草稿。'))
        self.fail_next = QCheckBox('本次演练失败，验证恢复路径')
        form.addWidget(self.fail_next)
        self.review = QCheckBox('我已检查候选（模拟），允许生成结果')
        self.review.toggled.connect(self.render)
        form.addWidget(self.review)
        form.addStretch()
        self.pages.addWidget(form_widget)
        placeholder = QLabel('此工作区尚未迁移。\n首批仅演练离线任务逻辑。')
        placeholder.setWordWrap(True)
        self.pages.addWidget(placeholder)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.pages)
        right.addWidget(scroll, 1)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        right.addWidget(self.reason)
        self.primary = button('计算候选（演练）', self.primary_action)
        self.primary.setObjectName('primary')
        self.primary.setMinimumHeight(40)
        right.addWidget(self.primary)
        self.split.addWidget(self.right)
        self.split.setSizes([280, 700, 350])
        self.left.setMinimumWidth(250)
        self.right.setMinimumWidth(300)

        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(150)
        bottom.addWidget(self.progress)
        self.stop_button = button('安全停止', self.stop)
        bottom.addWidget(self.stop_button)
        outer.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.pages.currentChanged.connect(self.render)
        self.setStyleSheet('''
            QWidget { background:#202329; color:#e2e5eb; font:13px "Microsoft YaHei"; }
            QPushButton, QComboBox, QDoubleSpinBox { background:#30353e; border:1px solid #606976; border-radius:4px; padding:6px; }
            QPushButton:hover { background:#404752; }
            QPushButton:focus, QComboBox:focus, QDoubleSpinBox:focus { border:2px solid #edc58b; }
            QPushButton:disabled { color:#a4acb8; background:#282c33; border-color:#454b56; }
            QPushButton#primary { background:#b72d3d; color:white; }
            QPushButton#primary:disabled { background:#58323b; color:#c6bbc0; }
            QLabel#brand { font-size:18px; font-weight:bold; }
            QLabel#banner { background:#3a3022; color:#f2d7a6; padding:8px; }
            QTreeWidget { background:#191d23; border:0; }
            QTreeWidget::item { min-height:32px; }
            QTreeWidget::item:selected { background:#4d3440; }
            QHeaderView::section { background:#30353e; padding:4px; }
            QScrollArea { border:0; }
        ''')
        self.render()

    def explain(self, text):
        QMessageBox.information(self, '演练说明', text)

    def export_info(self):
        self.explain(f'导出目标：{self.flow.selected}\n原型不执行文件导出。')

    def set_preview(self, text):
        self.preview.caption = text
        self.preview.update()

    def select_item(self, item, previous):
        if item:
            self.flow.select(item.text(0))
            self.object_label.setText(f'查看对象：{self.flow.selected}（不改变处理输入）')
            self.set_preview(f'{self.flow.selected} · 模拟查看 / 无真实点云')

    def change_item(self, item, column):
        if column == 1:
            self.flow.set_inputs([self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).checkState(1) == Qt.Checked])
            self.review.setChecked(False)
        elif column == 2:
            self.view_visible[item.text(0)] = item.checkState(2) == Qt.Checked
            names = [name for name, visible in self.view_visible.items() if visible]
            self.set_preview('模拟可见对象：' + '、'.join(names) if names else '全部对象已隐藏（处理输入不变）')
        self.render()

    def parameter_changed(self, value):
        self.flow.set_parameter(value)
        self.review.setChecked(False)
        self.render()

    def change_mode(self, index):
        self.pages.setCurrentIndex(0 if index == 0 else 2)
        self.render()

    def primary_action(self):
        if self.flow.busy:
            self.stop()
        elif self.flow.can_publish and self.review.isChecked():
            name = self.flow.publish()
            item = QTreeWidgetItem(self.tree, [name, '', ''])
            item.setCheckState(1, Qt.Unchecked)
            item.setCheckState(2, Qt.Checked)
            self.tree.setCurrentItem(item)
            self.review.setChecked(False)
        elif not self.flow.can_publish:
            self.token = self.flow.start()
            self.job_failed = self.fail_next.isChecked()
            self.ticks = 0
            self.timer.start()
        self.render()

    def tick(self):
        self.ticks += 1
        if self.ticks >= 8 or self.flow.stopping:
            self.timer.stop()
            self.flow.complete(self.token, failed=self.job_failed)
            if self.flow.can_publish:
                self.set_preview('模拟候选 · 请检查右侧输入与参数\n此预览不代表配准质量')
        self.render()

    def stop(self):
        self.flow.stop()
        self.render()

    def toggle_focus(self):
        self.focused = not self.focused
        self.left.setVisible(not self.focused)
        self.right.setVisible(not self.focused)
        self.focus_button.setText('退出专注视图' if self.focused else '专注视图')

    def render(self):
        self.input_label.setText(f'处理输入 {len(self.flow.inputs)} 项：' + '、'.join(self.flow.inputs))
        self.status.setText(self.flow.message)
        self.progress.setValue(min(self.ticks * 12, 96) if self.flow.busy else (100 if self.flow.can_publish else 0))
        self.stop_button.setVisible(self.flow.busy)
        self.stop_button.setEnabled(not self.flow.stopping)
        self.mode.setEnabled(not self.flow.busy)
        self.review.setEnabled(self.flow.can_publish)
        self.result_label.setText(f'候选：{"有效（模拟）" if self.flow.can_publish else "无 / 需重算"}  /  生成结果：{len(self.flow.results)}')
        reason = ''
        if self.mode.currentIndex() != 0 or self.pages.currentIndex() != 1:
            reason = '请进入离线配准任务；其他工作区尚未迁移。'
        elif len(self.flow.inputs) < 2:
            reason = '请勾选至少两项处理输入，不会自动使用全部数据。'
        elif self.flow.can_publish and not self.review.isChecked():
            reason = '请先检查候选并勾选确认。'
        self.reason.setText(reason)
        self.primary.setText('正在安全停止…' if self.flow.stopping else '安全停止' if self.flow.busy else '生成结果（演练）' if self.flow.can_publish else '计算候选（演练）')
        self.primary.setEnabled(not self.flow.stopping and (self.flow.busy or not reason))

    def closeEvent(self, event):
        if self.flow.busy:
            self.flow.message = '任务尚未结束，请安全停止后关闭。'
            self.render()
            event.ignore()
        else:
            event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = Workbench()
    window.show()
    sys.exit(app.exec())
