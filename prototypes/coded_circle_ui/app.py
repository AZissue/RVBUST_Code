# -*- coding: utf-8 -*-
"""
coded_circle_ui.app —— 编码圆标定板生成器 UI。

布局：
  - 左侧：参数面板（N / 半径 / 比例 / 页面 / DPI / 边距 / 输出格式 / 目录）
  - 右侧：实时预览 + 生成按钮 + 状态日志
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import cv2
import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTextEdit, QVBoxLayout,
    QWidget,
)

# 引入主项目 ui_v2 主题
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
try:
    from ui_v2 import GLOBAL_QSS
    HAS_THEME = True
except Exception as e:
    print(f"ui_v2 主题加载失败: {e}")
    HAS_THEME = False
    GLOBAL_QSS = ""

from generator import (
    CodedCircleParams,
    generate_preview,
    generate_full_board,
    save_board,
    generate_valid_codes,
)


class CodedCircleGeneratorUI(QMainWindow):
    """编码圆生成器主窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编码圆标定板生成器")
        self.resize(1200, 800)
        self._params = CodedCircleParams()
        self._setup_ui()
        self._schedule_preview()

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # ---- 左侧面板 ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_widget = QWidget()
        left_lo = QVBoxLayout(left_widget)
        left_lo.setSpacing(12)
        left_lo.setContentsMargins(4, 4, 4, 4)
        left_lo.setAlignment(Qt.AlignTop)

        left_lo.addWidget(self._build_param_group())
        left_lo.addWidget(self._build_page_group())
        left_lo.addWidget(self._build_output_group())
        left_lo.addStretch(1)

        left_scroll.setWidget(left_widget)
        splitter.addWidget(left_scroll)
        splitter.setSizes([360, 840])

        # ---- 右侧面板 ----
        right = QWidget()
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(0, 0, 0, 0)
        right_lo.setSpacing(12)

        self._preview_label = QLabel("预览区域")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setMinimumSize(400, 300)
        self._preview_label.setStyleSheet("background-color: #1E1F24; color: #9AA0A8;")
        self._preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_lo.addWidget(self._preview_label, 1)

        self._info_label = QLabel("等待生成预览...")
        self._info_label.setStyleSheet("color: #9AA0A8; font-size: 12px;")
        right_lo.addWidget(self._info_label)

        btn_row = QHBoxLayout()
        self._btn_generate = QPushButton("生成标定板")
        self._btn_generate.setObjectName("primary")
        self._btn_generate.setMinimumHeight(36)
        self._btn_generate.clicked.connect(self._on_generate)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_generate)
        right_lo.addLayout(btn_row)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("运行日志...")
        right_lo.addWidget(self._log)

        splitter.addWidget(right)

    def _build_param_group(self) -> QGroupBox:
        group = QGroupBox("编码圆参数")
        lo = QVBoxLayout(group)
        lo.setSpacing(10)

        self._spin_n = QSpinBox()
        self._spin_n.setRange(4, 16)
        self._spin_n.setValue(self._params.n)
        self._spin_n.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("扇区数 N", self._spin_n))

        self._spin_radius = QDoubleSpinBox()
        self._spin_radius.setRange(1.0, 50.0)
        self._spin_radius.setDecimals(1)
        self._spin_radius.setValue(self._params.radius_mm)
        self._spin_radius.setSuffix(" mm")
        self._spin_radius.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("中心圆半径", self._spin_radius))

        self._spin_r1 = QDoubleSpinBox()
        self._spin_r1.setRange(1.0, 10.0)
        self._spin_r1.setDecimals(2)
        self._spin_r1.setValue(self._params.r1_to_r0_ratio)
        self._spin_r1.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("r1/r0", self._spin_r1))

        self._spin_r2 = QDoubleSpinBox()
        self._spin_r2.setRange(1.0, 15.0)
        self._spin_r2.setDecimals(2)
        self._spin_r2.setValue(self._params.r2_to_r0_ratio)
        self._spin_r2.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("r2/r0", self._spin_r2))

        self._spin_r3 = QDoubleSpinBox()
        self._spin_r3.setRange(1.0, 20.0)
        self._spin_r3.setDecimals(2)
        self._spin_r3.setValue(self._params.r3_to_r0_ratio)
        self._spin_r3.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("r3/r0", self._spin_r3))

        self._spin_r4 = QDoubleSpinBox()
        self._spin_r4.setRange(1.0, 25.0)
        self._spin_r4.setDecimals(2)
        self._spin_r4.setValue(self._params.r4_to_r0_ratio)
        self._spin_r4.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("r4/r0", self._spin_r4))

        return group

    def _build_page_group(self) -> QGroupBox:
        group = QGroupBox("页面设置")
        lo = QVBoxLayout(group)
        lo.setSpacing(10)

        self._combo_page = QComboBox()
        for p in ["A1", "A2", "A3", "A4", "A5", "A6"]:
            self._combo_page.addItem(p, p)
        self._combo_page.setCurrentText(self._params.page_type)
        self._combo_page.currentTextChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("页面尺寸", self._combo_page))

        self._spin_dpi = QSpinBox()
        self._spin_dpi.setRange(72, 1200)
        self._spin_dpi.setValue(self._params.dpi)
        self._spin_dpi.setSuffix(" dpi")
        self._spin_dpi.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("打印 DPI", self._spin_dpi))

        self._spin_margin = QDoubleSpinBox()
        self._spin_margin.setRange(0.0, 50.0)
        self._spin_margin.setDecimals(1)
        self._spin_margin.setValue(self._params.margin_mm)
        self._spin_margin.setSuffix(" mm")
        self._spin_margin.valueChanged.connect(self._on_param_changed)
        lo.addLayout(self._labeled_row("页面边距", self._spin_margin))

        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("输出")
        lo = QVBoxLayout(group)
        lo.setSpacing(10)

        self._combo_format = QComboBox()
        self._combo_format.addItem("PNG 图片", "png")
        self._combo_format.addItem("PDF 文档", "pdf")
        self._combo_format.addItem("PNG + PDF", "both")
        lo.addLayout(self._labeled_row("输出格式", self._combo_format))

        dir_row = QHBoxLayout()
        self._edit_output = QLineEdit("OutputCodedCircleData")
        self._edit_output.setReadOnly(True)
        btn_browse = QPushButton("浏览...")
        btn_browse.setObjectName("secondary")
        btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(self._edit_output, 1)
        dir_row.addWidget(btn_browse)
        lo.addLayout(self._labeled_row("输出目录", dir_row))

        return group

    def _labeled_row(self, text: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(text)
        lbl.setMinimumWidth(90)
        row.addWidget(lbl)
        if isinstance(widget, QHBoxLayout):
            row.addLayout(widget, 1)
        else:
            row.addWidget(widget, 1)
        return row

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    def _on_param_changed(self):
        self._params.n = self._spin_n.value()
        self._params.radius_mm = self._spin_radius.value()
        self._params.r1_to_r0_ratio = self._spin_r1.value()
        self._params.r2_to_r0_ratio = self._spin_r2.value()
        self._params.r3_to_r0_ratio = self._spin_r3.value()
        self._params.r4_to_r0_ratio = self._spin_r4.value()
        self._params.page_type = self._combo_page.currentText()
        self._params.dpi = self._spin_dpi.value()
        self._params.margin_mm = self._spin_margin.value()
        self._schedule_preview()

    def _schedule_preview(self):
        # 简单防抖：参数连续变化时只生成最后一次预览
        if not hasattr(self, "_preview_timer"):
            self._preview_timer = QTimer(self)
            self._preview_timer.setSingleShot(True)
            self._preview_timer.timeout.connect(self._update_preview)
        self._preview_timer.stop()
        self._preview_timer.start(200)

    def _update_preview(self):
        try:
            preview, info = generate_preview(self._params, max_codes=6, preview_width=560)
            self._set_preview_image(preview)
            total = info["total_codes"]
            self._info_label.setText(
                f"当前 N={self._params.n}，可用编码圆数量：{total} 个 | "
                f"预览渲染 {info['preview_codes']} 个 | "
                f"页面 {info['page_px'][0]}×{info['page_px'][1]} px"
            )
        except Exception as e:
            self._log.append(f"预览生成失败: {e}")

    def _set_preview_image(self, img_bgr: np.ndarray):
        h, w, c = img_bgr.shape
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        self._preview_label.setPixmap(
            pixmap.scaled(self._preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_preview()

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self._edit_output.text())
        if path:
            self._edit_output.setText(path)

    def _on_generate(self):
        output_dir = self._edit_output.text().strip() or "OutputCodedCircleData"
        fmt = self._combo_format.currentData()
        try:
            self._log.append("开始生成完整标定板...")
            all_codes = generate_valid_codes(self._params.n)
            img, codes, binaries = generate_full_board(self._params, codes=None)
            saved = save_board(img, codes, binaries, self._params, output_dir, fmt)
            self._log.append(f"生成完成：{len(codes)} 个编码圆（可用 {len(all_codes)} 个）")
            for p in saved:
                self._log.append(f"  → {p}")
            QMessageBox.information(self, "生成完成", f"已保存到：\n{output_dir}")
        except Exception as e:
            self._log.append(f"生成失败: {e}")
            QMessageBox.critical(self, "错误", f"生成失败: {e}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main(argv: Optional[list] = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    if HAS_THEME:
        app.setStyleSheet(GLOBAL_QSS)
    win = CodedCircleGeneratorUI()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
