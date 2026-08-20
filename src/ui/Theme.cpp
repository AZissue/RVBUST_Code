#include "Theme.h"

#include <QApplication>
#include <QDir>
#include <QFont>
#include <QFontDatabase>
#include <QPalette>
#include <QStyleFactory>

#include <QtNodes/ConnectionStyle>
#include <QtNodes/GraphicsViewStyle>
#include <QtNodes/NodeStyle>
#include <QtNodes/StyleCollection>

namespace rvc::Theme {
namespace {

Mode g_mode = Mode::Dark;
QString g_uiFont;    // registerFonts 后解析
QString g_monoFont;

// 按 fallback 链挑第一个可用字体族
QString pickFamily(const QStringList& chain)
{
    const QStringList available = QFontDatabase::families();
    for (const QString& f : chain) {
        if (available.contains(f))
            return f;
    }
    return chain.last();
}

} // namespace

void setMode(Mode m)
{
    // 亮色主题预留：Mode::Light 暂未实现（设计系统 dark-first，亮色按反演派生）
    g_mode = m;
}

Mode mode()
{
    return g_mode;
}

void registerFonts()
{
    // 部署时 CMake 会把 resources/fonts 拷到 exe 目录 fonts/ 下
    const QDir fontsDir(QCoreApplication::applicationDirPath() + QStringLiteral("/fonts"));
    const QStringList ttf = fontsDir.entryList({QStringLiteral("*.ttf")}, QDir::Files);
    for (const QString& f : ttf)
        QFontDatabase::addApplicationFont(fontsDir.absoluteFilePath(f));

    g_uiFont = pickFamily({QStringLiteral("Geist"), QStringLiteral("Inter"),
                           QStringLiteral("Segoe UI"), QStringLiteral("system-ui")});
    g_monoFont = pickFamily({QStringLiteral("JetBrains Mono"), QStringLiteral("Fira Code"),
                             QStringLiteral("Consolas")});
}

QString uiFontFamily()
{
    return g_uiFont.isEmpty() ? QStringLiteral("Segoe UI") : g_uiFont;
}

QString monoFontFamily()
{
    return g_monoFont.isEmpty() ? QStringLiteral("Consolas") : g_monoFont;
}

QString appStyleSheet()
{
    using namespace Color;
    const QString ui = uiFontFamily();
    const QString mono = monoFontFamily();

    // 全部颜色引用 token 常量，无裸 hex
    QString qss;
    qss += QStringLiteral(
        // ---- 基础 ----
        "QMainWindow, QDialog { background: %1; color: %2; }"
        "QMainWindow#innerMainWindow { background: %5; border: none; }"
        "QWidget { color: %2; font-family: \"%3\"; }"
        "#titleBar { background: %5; border: none; border-bottom: 1px solid %6; }"
        "#titleLabel { color: %2; font-size: 12px; font-weight: 500; }"
        "QToolButton[class=\"title-button\"] { background: transparent; color: %4; border: none; border-radius: 0; font-size: 14px; font-family: \"Segoe UI\", \"Microsoft YaHei\", sans-serif; }"
        "QToolButton[class=\"title-button\"]:hover { background: %7; color: %2; }"
        "QToolButton[class=\"title-button\"]:pressed { background: %8; color: %2; }"
        "QToolButton[class=\"title-button\"]#closeBtn:hover { background: %16; color: #FFFFFF; }"
        // ---- Dock ----
        "QDockWidget { color: %4; font-size: 11px; font-weight: 600; }"
        "QDockWidget::title { background: %5; padding: 6px 8px; border-bottom: 1px solid %6; text-align: left; }"
        "QDockWidget::close-button, QDockWidget::float-button { background: transparent; border: none; padding: 2px; }"
        "QDockWidget::close-button:hover, QDockWidget::float-button:hover { background: %7; }"
        // ---- 菜单栏 / 菜单 ----
        "QMenuBar { background: %5; color: %2; border: none; border-bottom: 1px solid %6; padding: 0px; }"
        "QMenuBar::item { padding: 4px 8px; background: transparent; margin: 0px; }"
        "QMenuBar::item:selected { background: %7; }"
        "QMenu { background: %5; color: %2; border: 1px solid %6; padding: 4px; }"
        "QMenu::item { padding: 4px 24px 4px 12px; }"
        "QMenu::item:selected { background: %7; }"
        "QMenu::separator { height: 1px; background: %6; margin: 4px 8px; }"
        // ---- 工具栏 ----
        "QToolBar { background: %5; border: none; border-bottom: 1px solid %6; spacing: 4px; padding: 4px; }"
        "QToolBar::separator { width: 1px; background: %6; margin: 2px 4px; }"
        // ---- 按钮三层级：Secondary 默认 / Primary（琥珀，每区域至多一个）/ Ghost ----
        "QPushButton { background: %7; color: %2; border: 1px solid %6; border-radius: 6px; padding: 8px 16px; font-family: \"%3\"; }"
        "QPushButton:hover { background: %8; border-color: %9; }"
        "QPushButton:pressed { background: %8; }"
        "QPushButton:disabled { color: %10; background: %5; }"
        "QPushButton[class=\"primary\"] { background: %11; color: #FFFFFF; border: 1px solid %11; font-weight: 600; }"
        "QPushButton[class=\"primary\"]:hover { background: %12; border-color: %12; }"
        "QPushButton[class=\"primary\"]:pressed { background: %13; }"
        "QPushButton[class=\"primary\"]:disabled { background: %14; color: %10; border-color: %14; }"
        // Ghost（工具栏/视窗工具条图标按钮）
        "QToolButton { background: transparent; color: %4; border: none; border-radius: 6px; padding: 4px 8px; }"
        "QToolButton:hover { background: %7; color: %2; }"
        "QToolButton:pressed, QToolButton:checked { background: %8; color: %2; }"
        // 工具栏中的 Primary（琥珀填充，每个区域至多一个：运行按钮）
        "QToolButton[class=\"primary\"] { background: %11; color: #FFFFFF; border: 1px solid %11; font-weight: 600; padding: 4px 16px; }"
        "QToolButton[class=\"primary\"]:hover { background: %12; border-color: %12; }"
        "QToolButton[class=\"primary\"]:pressed { background: %13; }"
        "QToolButton[class=\"primary\"]:disabled { background: %14; color: %10; border-color: %14; }"
        // ---- 输入控件（1px 边框常显，focus = accent 边框近似双层环）----
        "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: %5; color: %2; border: 1px solid %6; border-radius: 6px; padding: 4px 8px; selection-background-color: %14; selection-color: %11; }"
        "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid %11; }"
        "QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: %10; background: %1; }"
        "QLineEdit[placeholderText] { color: %2; }"
        "QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button { width: 16px; background: %7; border-left: 1px solid %6; }"
        "QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: %8; }"
        "QComboBox::drop-down { width: 20px; border-left: 1px solid %6; background: %7; }"
        "QComboBox QAbstractItemView { background: %5; color: %2; border: 1px solid %6; selection-background-color: %7; }"
        // ---- CheckBox ----
        "QCheckBox { color: %2; spacing: 6px; }"
        "QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid %6; border-radius: 3px; background: %5; }"
        "QCheckBox::indicator:hover { border-color: %9; }"
        "QCheckBox::indicator:checked { background: %11; border-color: %11; }"
        // ---- 列表/树（工具箱：分类可折叠，模块项可拖拽）----
        "QListWidget, QTreeWidget, QTreeView { background: %1; color: %2; border: none; outline: none; }"
        "QListWidget::item, QTreeWidget::item, QTreeView::item { padding: 4px 8px; border-radius: 6px; }"
        "QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover { background: %7; }"
        "QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected { background: %14; color: %11; }"
        "QTreeWidget::branch { background: transparent; border: none; }"
        // ---- Tab（active 用 accent 下划线 + accent 字，不用填充）----
        "QTabWidget::pane { border: 1px solid %6; background: %1; }"
        "QTabBar::tab { background: transparent; color: %4; padding: 6px 12px; border-bottom: 2px solid transparent; }"
        "QTabBar::tab:hover { color: %2; }"
        "QTabBar::tab:selected { color: %11; border-bottom: 2px solid %11; }"
        // ---- 表格（结果表：行 hover，选中 = accent-muted 底 + accent 字）----
        "QTableWidget { background: %1; color: %2; gridline-color: %6; border: none; selection-background-color: %14; selection-color: %11; }"
        "QTableWidget::item { padding: 2px 8px; border: none; }"
        "QTableWidget::item:hover { background: %7; }"
        "QHeaderView::section { background: %5; color: %4; border: none; border-bottom: 1px solid %6; padding: 4px 8px; font-weight: 600; font-size: 11px; }"
        // ---- 日志（mono 字体，surface-0 底）----
        "QPlainTextEdit, QTextEdit { background: %1; color: %4; border: none; font-family: \"%15\"; font-size: 12px; }"
        // ---- 状态栏 ----
        "QStatusBar { background: %1; color: %4; border-top: 1px solid %6; }"
        "QStatusBar::item { border: none; }"
        // ---- ToolTip（弹层允许阴影，Qt 侧用深色底即可）----
        "QToolTip { background: %7; color: %2; border: 1px solid %9; padding: 4px 8px; }"
        // ---- 滚动条（细、surface-2 滑块、无箭头占位）----
        "QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }"
        "QScrollBar::handle:vertical { background: %7; border-radius: 4px; min-height: 24px; }"
        "QScrollBar::handle:vertical:hover { background: %8; }"
        "QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }"
        "QScrollBar::handle:horizontal { background: %7; border-radius: 4px; min-width: 24px; }"
        "QScrollBar::handle:horizontal:hover { background: %8; }"
        "QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }"
        "QScrollBar::add-page, QScrollBar::sub-page { background: none; }"
        // ---- 分隔条 ----
        "QSplitter::handle { background: %6; }"
        "QSplitter::handle:horizontal { width: 1px; }"
        "QSplitter::handle:vertical { height: 1px; }"
        // ---- 分组框/标签 ----
        "QLabel { background: transparent; }"
        "QGroupBox { border: 1px solid %6; border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; color: %4; }"
        // ROI 弹窗参数组：去掉边框，标题改 caption 样式
        "QGroupBox#roiParamGroup { border: none; margin-top: 12px; padding-top: 0px; }"
        "QGroupBox#roiParamGroup::title { subcontrol-origin: margin; left: 0px; top: -2px; color: %4; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; }"
        // ---- 流程画布（QtNodes GraphicsView）----
        "QGraphicsView { background: %1; border: none; }"
        // ---- 分隔条已在上文覆盖 ----
        )
            .arg(Surface0)    // %1
            .arg(InkPrimary)  // %2
            .arg(ui)          // %3
            .arg(InkSecondary)// %4
            .arg(Surface1)    // %5
            .arg(Border)      // %6
            .arg(Surface2)    // %7
            .arg(Surface3)    // %8
            .arg(BorderHover) // %9
            .arg(InkTertiary) // %10
            .arg(Accent)      // %11
            .arg(AccentHover) // %12
            .arg(AccentSoft)  // %13
            .arg(AccentMuted) // %14
            .arg(mono)       // %15
            .arg(Danger)     // %16
            .arg(Success)    // %17
            .arg(Warning);   // %18
    return qss;
}

void applyQtNodesStyle()
{
    using namespace Color;

    // NodeStyle：节点底 surface-1（渐变四色全部同一色 = 纯色，设计禁渐变）、
    // 边框 border、选中 = accent 边框（accent 正当用途：选中态）
    QtNodes::NodeStyle::setNodeStyle(QStringLiteral(R"json(
{
  "NodeStyle": {
    "NormalBoundaryColor": "%1",
    "SelectedBoundaryColor": "%2",
    "GradientColor0": "%3",
    "GradientColor1": "%3",
    "GradientColor2": "%3",
    "GradientColor3": "%3",
    "ShadowColor": "#0A0A0C",
    "FontColor": "%4",
    "FontColorFaded": "%5",
    "ConnectionPointColor": "%5",
    "FilledConnectionPointColor": "%2",
    "WarningColor": "%6",
    "ErrorColor": "%7",
    "PenWidth": 1.0,
    "HoveredPenWidth": 1.5,
    "ConnectionPointDiameter": 8.0,
    "Opacity": 1.0
  }
})json")
                                         .arg(Border, Accent, Surface1, InkPrimary,
                                              InkSecondary, Warning, Danger));

    // ConnectionStyle：正常态 ink-secondary、选中/悬停 accent；
    // 不按数据类型着色（库实现为 hash 随机色，违背设计系统克制原则）
    QtNodes::ConnectionStyle::setConnectionStyle(QStringLiteral(R"json(
{
  "ConnectionStyle": {
    "ConstructionColor": "%1",
    "NormalColor": "%2",
    "SelectedColor": "%3",
    "SelectedHaloColor": "%3",
    "HoveredColor": "%4",
    "LineWidth": 2.0,
    "ConstructionLineWidth": 2.0,
    "PointDiameter": 8.0,
    "UseDataDefinedColors": false
  }
})json")
                                                     .arg(InkTertiary, InkSecondary,
                                                          Accent, AccentSoft));

    // GraphicsViewStyle：画布底 surface-0，网格线极淡
    QtNodes::GraphicsViewStyle::setStyle(QStringLiteral(R"json(
{
  "GraphicsViewStyle": {
    "BackgroundColor": "%1",
    "FineGridColor": "%2",
    "CoarseGridColor": "%3"
  }
})json")
                                                       .arg(Surface0, Surface1, Surface2));
}

void apply(QApplication& app)
{
    registerFonts();

    // Fusion 作为底风格：QSS 表现跨控件更一致（原生 windowsvista 样式会漏白底）
    app.setStyle(QStyleFactory::create(QStringLiteral("Fusion")));

    QFont font(uiFontFamily(), 9);
    app.setFont(font);

    // QPalette 兜底：未被 QSS 覆盖的控件不露原生白底
    using namespace Color;
    QPalette pal;
    pal.setColor(QPalette::Window, QColor(Surface0));
    pal.setColor(QPalette::WindowText, QColor(InkPrimary));
    pal.setColor(QPalette::Base, QColor(Surface1));
    pal.setColor(QPalette::AlternateBase, QColor(Surface0));
    pal.setColor(QPalette::Text, QColor(InkPrimary));
    pal.setColor(QPalette::Button, QColor(Surface2));
    pal.setColor(QPalette::ButtonText, QColor(InkPrimary));
    pal.setColor(QPalette::Highlight, QColor(Accent));
    pal.setColor(QPalette::HighlightedText, QColor(InkInverse));
    pal.setColor(QPalette::PlaceholderText, QColor(InkTertiary));
    pal.setColor(QPalette::ToolTipBase, QColor(Surface2));
    pal.setColor(QPalette::ToolTipText, QColor(InkPrimary));
    pal.setColor(QPalette::Disabled, QPalette::Text, QColor(InkTertiary));
    pal.setColor(QPalette::Disabled, QPalette::ButtonText, QColor(InkTertiary));
    pal.setColor(QPalette::Disabled, QPalette::WindowText, QColor(InkTertiary));
    pal.setColor(QPalette::Disabled, QPalette::Highlight, QColor(AccentMuted));
    app.setPalette(pal);

    app.setStyleSheet(appStyleSheet());
    applyQtNodesStyle();
}

} // namespace rvc::Theme
