# -*- coding: utf-8 -*-
"""
ui_v2.theme —— 设计系统常量 + 全局 QSS。

视觉规范（《docs/拼接软件UI重设计-AI提示词.md》第七节）：
  - 深色工业风；
  - 底色 #1E1F24 / 面板 #26272E / 卡片 #2E3038 / 边框 #3A3D46；
  - 主强调色 RVC 品牌红 #E53935（按钮 / 选中态）；
  - 状态色 绿 #4CAF50 / 黄 #FFC107 / 红 #F44336；
  - 间距 8px 基准，圆角 6px。
"""

# ---------------------------------------------------------------- 色彩 token
BG_WINDOW = "#1A1D23"     # 窗口底色：偏冷蓝灰，减少沉闷
BG_PANEL = "#23272F"      # 面板底色
BG_CARD = "#2B3039"       # 卡片底色：与面板形成明显层次
BG_INPUT = "#1E2229"    # 输入框微底色，在无边框卡片中可辨识
BORDER = "#3D4350"        # 边框：冷灰蓝，更柔和
BORDER_HOVER = "#4D535F"  # 悬停边框

ACCENT = "#D32F2F"        # RVC 品牌红（主强调）—— 降饱和，减少视觉疲劳
ACCENT_HOVER = "#E57373"
ACCENT_PRESSED = "#B71C1C"
ACCENT_DIM = "rgba(211, 47, 47, 0.16)"   # 选中态底色

TEXT_PRIMARY = "#E8EAED"
TEXT_SECONDARY = "#9AA0A8"
TEXT_MUTED = "#949BA3"

STATUS_OK = "#4CAF50"     # 绿
STATUS_WARN = "#FFB300"   # 黄 —— 提高深色背景对比度
STATUS_ERR = "#F44336"    # 红

RADIUS = "6px"
SPACE = 8                 # 8px 间距基准

# 相机分色调色板（3D 预览 / 卡片角标共用，占位阶段仅作常量）
CAMERA_PALETTE = [
    "#F0F0F0", "#29B6F6", "#FFA726", "#66BB6A", "#EC407A",
    "#FFEE58", "#AB47BC", "#26C6DA", "#EF5350",
]


# ---------------------------------------------------------------- 全局 QSS
GLOBAL_QSS = f"""
/* ============ 基础 ============ */
QMainWindow, QDialog {{ background-color: {BG_WINDOW}; }}
QWidget {{
    background-color: {BG_WINDOW};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QLabel#dimLabel {{ color: {TEXT_SECONDARY}; }}
QLabel#mutedLabel {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#sectionTitle {{
    font-size: 14px; font-weight: 600; color: {TEXT_PRIMARY};
    padding: 2px 0;
}}

/* ============ 按钮 ============ */
QPushButton {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 7px 16px;
    color: {TEXT_PRIMARY};
    min-height: 28px;
}}
QPushButton:hover {{ background-color: #363943; border-color: {BORDER_HOVER}; }}
QPushButton:pressed {{ background-color: #3E424E; }}
QPushButton:disabled {{
    background-color: {BG_PANEL}; color: {TEXT_MUTED}; border-color: #2E313A;
}}

QPushButton#primary {{
    background-color: {ACCENT}; border-color: {ACCENT}; color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background-color: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{
    background-color: #5A2A28; border-color: #5A2A28; color: #B08080;
}}

QPushButton#danger {{
    background: transparent;
    border: 1px solid {STATUS_ERR};
    color: {STATUS_ERR};
}}
QPushButton#danger:hover {{
    background-color: rgba(244, 67, 54, 0.12);
    border-color: {STATUS_ERR};
}}
QPushButton#danger:pressed {{ background-color: rgba(244, 67, 54, 0.20); }}
QPushButton#danger:disabled {{
    background: transparent; color: {TEXT_MUTED}; border-color: #2E313A;
}}

QPushButton#secondary {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    color: {TEXT_PRIMARY};
}}
QPushButton#secondary:hover {{
    background-color: {BG_CARD};
    border-color: {BORDER_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton#secondary:pressed {{ background-color: #3E424E; }}
QPushButton#secondary:disabled {{
    background-color: {BG_PANEL}; color: {TEXT_MUTED}; border-color: #2E313A;
}}

QPushButton#bigAction {{
    background-color: {ACCENT}; border-color: {ACCENT}; color: #FFFFFF;
    font-size: 16px; font-weight: 700; padding: 12px 24px; min-height: 44px;
}}
QPushButton#bigAction:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#bigAction:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#bigAction:disabled {{
    background-color: #5A2A28; border-color: #5A2A28; color: #B08080;
}}

/* ============ 工具按钮 ============ */
QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: {RADIUS}; padding: 6px 12px; color: {TEXT_SECONDARY};
}}
QToolButton:hover {{ background-color: {BG_CARD}; color: {TEXT_PRIMARY}; }}
QToolButton:checked {{
    background-color: {ACCENT_DIM}; color: {ACCENT};
    border-color: {ACCENT};
}}

/* ============ 输入控件 ============ */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 5px 10px;
    min-height: 26px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

QRadioButton, QCheckBox {{ spacing: 8px; }}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 2px solid {BORDER}; border-radius: {RADIUS};
    background-color: {BG_INPUT};
}}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
    border-color: {BORDER_HOVER};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {ACCENT};
    background-color: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    border-color: {ACCENT};
    background-color: {ACCENT};
    image: none;
}}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{
    border-color: #2E313A;
    background-color: {BG_PANEL};
}}

/* ============ 分组 / 卡片 ============ */
QGroupBox {{
    background-color: {BG_PANEL};
    border: none;
    border-radius: {RADIUS};
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: {TEXT_SECONDARY};
}}

/* ============ 表格 ============ */
QTableWidget, QTableView {{
    background-color: {BG_PANEL};
    alternate-background-color: #2A2C34;
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    gridline-color: #30333C;
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: {BG_CARD};
    padding: 6px 8px;
    border: 1px solid {BORDER_HOVER};
    border-left: none;
    color: {TEXT_PRIMARY};
    font-weight: 600;
}}
QHeaderView::section:first {{
    border-left: 1px solid {BORDER_HOVER};
}}

/* ============ Tab ============ */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: {RADIUS}; }}
QTabBar::tab {{
    background: {BG_PANEL}; color: {TEXT_SECONDARY};
    padding: 6px 16px; border-top-left-radius: {RADIUS};
    border-top-right-radius: {RADIUS};
}}
QTabBar::tab:selected {{ background: {BG_CARD}; color: {ACCENT}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT_PRIMARY}; }}

/* ============ 列表 ============ */
QListWidget {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER};
    border-radius: {RADIUS};
    outline: none;
}}
QListWidget::item {{
    padding: 6px 8px; border-radius: 4px;
    border-left: 3px solid transparent;
    outline: none;
}}
QListWidget::item:selected {{
    background-color: {ACCENT_DIM}; color: {TEXT_PRIMARY};
    border-left: 3px solid {ACCENT};
}}
QListWidget::item:hover {{ background-color: {BG_CARD}; }}

/* ============ Splitter / 滚动条 ============ */
QSplitter::handle {{ background-color: #26282F; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QSplitter::handle:hover {{ background-color: {ACCENT}; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {BORDER_HOVER}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 5px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {BORDER_HOVER}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ============ 进度条 / 工具提示 ============ */
QProgressBar {{
    background-color: {BG_INPUT}; border: 1px solid {BORDER};
    border-radius: {RADIUS}; text-align: center; color: {TEXT_PRIMARY};
    min-height: 14px; max-height: 14px;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 5px; }}

QToolTip {{
    background-color: {BG_CARD}; color: {TEXT_PRIMARY};
    border: 1px solid {BORDER}; padding: 4px 8px;
}}

QStatusBar {{ background-color: {BG_PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}

QDockWidget {{ color: {TEXT_SECONDARY}; titlebar-close-icon: none; }}
QPlainTextEdit {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER};
    border-radius: {RADIUS};
    font-family: "Consolas", "Courier New", monospace; font-size: 12px;
}}
"""
