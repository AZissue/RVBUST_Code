"""
全局资源定义：配色系统、字体规范、QSS 辅助函数。
整个 UI 主题的唯一信息源，避免各处散落硬编码的颜色值。
"""

# ═══════════════════════════════════════════════════════════════
# 配色系统（天蓝色主题 #1677FF）
# ═══════════════════════════════════════════════════════════════

# 主色 — 天蓝色（按钮、选中态、标题栏、强调边框、进度条）
PRIMARY = "#1677FF"
PRIMARY_HOVER = "#4096FF"    # 悬停态：比主色稍亮
PRIMARY_CLICK = "#0958D9"    # 点击态：比主色稍暗
PRIMARY_LIGHT = "#E6F7FF"    # 浅蓝辅助色（卡片背景、选中态背景、输入框聚焦背景）

# 背景色
BG_MAIN = "#FFFFFF"          # 页面整体背景（白色）
BG_CARD = "#F5F5F5"          # 卡片/数据区背景（浅灰）
BG_DARK_2D = "#000000"       # 2D 图像显示区背景（纯黑）
BG_DARK_3D = "#1A1A1A"       # 3D 点云显示区背景（深灰）

# 边框色
BORDER_DEFAULT = "#D9D9D9"   # 默认边框/分割线（浅灰）
BORDER_FOCUS = "#1677FF"     # 聚焦态边框（天蓝色）

# 文字色
TEXT_TITLE = "#262626"       # 一级标题/按钮文字（近黑）
TEXT_BODY = "#434343"        # 二级标题/输入框文字（深灰）
TEXT_HINT = "#8C8C8C"        # 说明文字/占位符（中灰）

# 状态色
SUCCESS = "#52C41A"          # 成功提示/有效数据指示灯（绿色）
WARNING = "#FAAD14"          # 注意事项/警告提示（橙色）
ERROR = "#F5222D"            # 错误提示/无效数据指示灯（红色）
ERROR_BG = "#FFF2F0"         # 错误背景（浅红）

# ═══════════════════════════════════════════════════════════════
# 字体规范
# ═══════════════════════════════════════════════════════════════

FONT_FAMILY = "Microsoft YaHei"   # 优先使用微软雅黑（Windows 无衬线）
FONT_H1 = 18                       # H1 字号：软件名称、窗口标题
FONT_H2 = 16                       # H2 字号：卡片标题、模式标签
FONT_BODY = 14                     # 正文：输入框、按钮、普通说明
FONT_HINT = 12                     # 辅助：小字说明、日志、状态提示

# ═══════════════════════════════════════════════════════════════
# 尺寸与视觉效果
# ═══════════════════════════════════════════════════════════════

RECOMMENDED_COUNT = 15             # 推荐采集数据组数
BORDER_RADIUS = 8                  # 统一圆角（所有卡片/按钮/输入框）
CARD_SHADOW = "0 2px 8px rgba(0, 0, 0, 0.08)"       # 卡片阴影
BTN_SHADOW = "0 2px 4px rgba(22, 119, 255, 0.2)"     # 按钮阴影
ACTIVE_SHADOW = "0 4px 12px rgba(22, 119, 255, 0.15)" # 激活窗口阴影


# ═══════════════════════════════════════════════════════════════
# QSS（Qt Style Sheet）辅助函数
# ═══════════════════════════════════════════════════════════════

def global_stylesheet():
    """全局 QSS 样式表，应用于整个 QApplication"""
    return f"""
    * {{
        font-family: "{FONT_FAMILY}";
        font-size: {FONT_BODY}px;
    }}
    QMainWindow {{
        background-color: {BG_MAIN};
    }}
    QToolTip {{
        background-color: {BG_CARD};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: {FONT_HINT}px;
        color: {TEXT_BODY};
    }}
    QProgressBar {{
        border: none;
        background-color: {BORDER_DEFAULT};
        border-radius: 3px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {PRIMARY};
        border-radius: 3px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QSplitter::handle {{
        background-color: {BORDER_DEFAULT};
        width: 2px;
    }}
    """


def primary_button_style():
    """主要按钮 QSS：天蓝色填充 + 白色文字，用于「保存」等核心操作"""
    return f"""
    QPushButton {{
        background-color: {PRIMARY};
        color: #FFFFFF;
        border: none;
        border-radius: {BORDER_RADIUS}px;
        padding: 0 24px;
        font-size: {FONT_BODY}px;
        font-weight: 500;
        height: 40px;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_CLICK};
    }}
    QPushButton:disabled {{
        opacity: 0.5;
    }}
    """


def secondary_button_style():
    """次要按钮 QSS：白底灰边黑字，用于「上一张」「下一张」等"""
    return f"""
    QPushButton {{
        background-color: {BG_MAIN};
        color: {TEXT_BODY};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {BORDER_RADIUS}px;
        padding: 0 24px;
        font-size: {FONT_BODY}px;
        font-weight: 500;
        height: 40px;
    }}
    QPushButton:hover {{
        background-color: {BG_CARD};
    }}
    QPushButton:disabled {{
        opacity: 0.5;
    }}
    """


def secondary_emphasis_button_style():
    """次要强调按钮：白底蓝边蓝字，用于「重拍」等"""
    return f"""
    QPushButton {{
        background-color: {BG_MAIN};
        color: {PRIMARY};
        border: 1px solid {PRIMARY};
        border-radius: {BORDER_RADIUS}px;
        padding: 0 24px;
        font-size: {FONT_BODY}px;
        font-weight: 500;
        height: 40px;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY_LIGHT};
    }}
    QPushButton:disabled {{
        opacity: 0.5;
    }}
    """


def danger_button_style():
    """危险按钮 QSS：白底红边红字，用于「清空所有」"""
    return f"""
    QPushButton {{
        background-color: {BG_MAIN};
        color: {ERROR};
        border: 1px solid {ERROR};
        border-radius: {BORDER_RADIUS}px;
        padding: 0 24px;
        font-size: {FONT_BODY}px;
        font-weight: 500;
        height: 40px;
    }}
    QPushButton:hover {{
        background-color: {ERROR_BG};
    }}
    QPushButton:disabled {{
        opacity: 0.5;
    }}
    """


def input_style():
    """输入框默认 QSS：白底灰边"""
    return f"""
    QLineEdit {{
        background-color: {BG_MAIN};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: 6px;
        padding: 6px 12px;
        color: {TEXT_BODY};
        font-size: {FONT_BODY}px;
        height: 32px;
    }}
    QLineEdit:focus {{
        border: 1px solid {BORDER_FOCUS};
        background-color: {PRIMARY_LIGHT};
    }}
    """


def input_error_style():
    """输入框错误态 QSS：白底红边"""
    return f"""
    QLineEdit {{
        background-color: {BG_MAIN};
        border: 1px solid {ERROR};
        border-radius: 6px;
        padding: 6px 12px;
        color: {TEXT_BODY};
        font-size: {FONT_BODY}px;
        height: 32px;
    }}
    """


def toggle_selected_style():
    """切换按钮选中态：蓝色填充白色文字"""
    return f"""
    QPushButton {{
        background-color: {PRIMARY};
        color: #FFFFFF;
        border: none;
        border-radius: {BORDER_RADIUS}px;
        font-size: {FONT_BODY}px;
        font-weight: 500;
        height: 32px;
        min-width: 80px;
    }}
    """


def toggle_unselected_style():
    """切换按钮未选中态：灰底深字，悬停变浅蓝"""
    return f"""
    QPushButton {{
        background-color: {BG_CARD};
        color: {TEXT_BODY};
        border: none;
        border-radius: {BORDER_RADIUS}px;
        font-size: {FONT_BODY}px;
        font-weight: 400;
        height: 32px;
        min-width: 80px;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY_LIGHT};
    }}
    """
