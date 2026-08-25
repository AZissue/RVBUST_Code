#include "themes.h"

#include <QApplication>
#include <QPalette>
#include <QStyle>

namespace app {

namespace {

const char* kLightStyle = R"(
    /* ---------- global ---------- */
    QMainWindow, QDialog {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #EAF2FF, stop:0.5 #F4F8FE, stop:1 #F8FAFC);
    }
    QWidget {
        color: #1E293B;
        font-family: "Segoe UI", "Microsoft YaHei";
        font-size: 13px;
    }

    /* ---------- frosted glass panels ---------- */
    QGroupBox {
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid #CFE0FF;
        border-radius: 8px;
        margin-top: 10px;
        padding-top: 4px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        top: 2px;
        padding: 0 6px;
        color: #2563EB;
        font-weight: 600;
    }

    /* ---------- canvas ---------- */
    QGraphicsView {
        background: #FFFFFF;
        border: 1px solid #CFE0FF;
        border-radius: 8px;
    }

    /* ---------- lists & trees ---------- */
    QListWidget, QTreeWidget, QPlainTextEdit {
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid #CFE0FF;
        border-radius: 8px;
        outline: none;
    }
    QListWidget::item {
        border-radius: 6px;
        padding: 6px 8px;
        margin: 2px 4px;
    }
    QListWidget::item:hover { background: #EFF4FF; }
    QListWidget::item:selected {
        background: #2563EB;
        color: white;
    }
    QTreeWidget::item { padding: 3px; }
    QTreeWidget::item:hover { background: #EFF4FF; }
    QTreeWidget::item:selected {
        background: #2563EB;
        color: white;
    }
    QHeaderView::section {
        background: #F1F5FB;
        color: #475569;
        border: none;
        border-bottom: 1px solid #CFE0FF;
        padding: 5px;
        font-weight: 600;
    }

    /* ---------- inputs ---------- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: rgba(255, 255, 255, 0.9);
        border: 1px solid #BFD6FF;
        border-radius: 6px;
        padding: 3px 6px;
        selection-background-color: #2563EB;
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid #2563EB;
    }
    QComboBox::drop-down { border: none; width: 20px; }
    QCheckBox { spacing: 6px; }

    /* ---------- buttons ---------- */
    QPushButton {
        background: #EAF2FF;
        border: 1px solid #BFD6FF;
        border-radius: 6px;
        padding: 6px 14px;
        color: #1D4ED8;
    }
    QPushButton:hover { background: #DBEAFE; border-color: #93BDFB; }
    QPushButton:pressed { background: #BFDBFE; }
    QPushButton:disabled { background: #F1F5FB; color: #94A3B8; }

    /* ---------- tabs ---------- */
    QTabWidget::pane {
        border: 1px solid #CFE0FF;
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.82);
        top: -1px;
    }
    QTabBar::tab {
        background: rgba(255, 255, 255, 0.55);
        border: 1px solid transparent;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 6px 16px;
        margin-right: 2px;
        color: #64748B;
    }
    QTabBar::tab:hover { background: #EFF4FF; }
    QTabBar::tab:selected {
        background: rgba(255, 255, 255, 0.92);
        color: #2563EB;
        font-weight: 600;
        border-color: #CFE0FF;
    }

    /* ---------- menus & status ---------- */
    QMenuBar {
        background: rgba(255, 255, 255, 0.85);
        border-bottom: 1px solid #CFE0FF;
        padding: 2px 6px;
    }
    QMenuBar::item { padding: 5px 10px; border-radius: 6px; }
    QMenuBar::item:selected { background: #EFF4FF; color: #1D4ED8; }
    QMenu {
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid #CFE0FF;
        border-radius: 8px;
        padding: 4px;
    }
    QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; }
    QMenu::item:selected { background: #2563EB; color: white; }
    QStatusBar { background: rgba(255, 255, 255, 0.70); border-top: 1px solid #CFE0FF; }
    QDockWidget::title {
        background: rgba(255, 255, 255, 0.70);
        border-bottom: 1px solid #CFE0FF;
        padding: 4px 8px;
        color: #2563EB;
        font-weight: 600;
    }

    /* ---------- scrollbars ---------- */
    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical {
        background: #C7D9F7;
        border-radius: 5px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover { background: #9DBEF4; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
    QScrollBar::handle:horizontal {
        background: #C7D9F7;
        border-radius: 5px;
        min-width: 24px;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
)";

const char* kDarkStyle = R"(
    QMainWindow, QDialog {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #111827, stop:0.6 #1B2436, stop:1 #232F42);
    }
    QWidget { color: #E2E8F0; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 13px; }
    QGroupBox {
        background: rgba(30, 41, 59, 0.82);
        border: 1px solid #2F415C;
        border-radius: 8px;
        margin-top: 10px;
        padding-top: 4px;
    }
    QGroupBox::title {
        subcontrol-origin: margin; left: 10px; top: 2px; padding: 0 6px;
        color: #60A5FA; font-weight: 600;
    }
    QGraphicsView {
        background: #0F172A;
        border: 1px solid #2F415C;
        border-radius: 8px;
    }
    QListWidget, QTreeWidget, QPlainTextEdit {
        background: rgba(23, 33, 50, 0.8);
        border: 1px solid #2F415C;
        border-radius: 8px;
        outline: none;
    }
    QListWidget::item { border-radius: 6px; padding: 6px 8px; margin: 2px 4px; }
    QListWidget::item:hover { background: #24344D; }
    QListWidget::item:selected { background: #2563EB; color: white; }
    QTreeWidget::item { padding: 3px; }
    QTreeWidget::item:hover { background: #24344D; }
    QTreeWidget::item:selected { background: #2563EB; color: white; }
    QHeaderView::section {
        background: #1B2436; color: #94A3B8; border: none;
        border-bottom: 1px solid #2F415C; padding: 5px; font-weight: 600;
    }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid #33466B;
        border-radius: 6px;
        padding: 3px 6px;
        selection-background-color: #2563EB;
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid #60A5FA;
    }
    QComboBox::drop-down { border: none; width: 20px; }
    QPushButton {
        background: #1E3A5F; border: 1px solid #33507C; border-radius: 6px;
        padding: 6px 14px; color: #BFDBFE;
    }
    QPushButton:hover { background: #25476F; }
    QPushButton:pressed { background: #1B3250; }
    QPushButton:disabled { background: #1B2436; color: #475569; }
    QTabWidget::pane {
        border: 1px solid #2F415C; border-radius: 8px;
        background: rgba(30, 41, 59, 0.82); top: -1px;
    }
    QTabBar::tab {
        background: rgba(30, 41, 59, 0.55);
        border: 1px solid transparent;
        border-top-left-radius: 8px; border-top-right-radius: 8px;
        padding: 6px 16px; margin-right: 2px; color: #94A3B8;
    }
    QTabBar::tab:hover { background: #24344D; }
    QTabBar::tab:selected {
        background: rgba(30, 41, 59, 0.95); color: #60A5FA;
        font-weight: 600; border-color: #2F415C;
    }
    QMenuBar {
        background: rgba(17, 24, 39, 0.85);
        border-bottom: 1px solid #2F415C; padding: 2px 6px;
    }
    QMenuBar::item { padding: 5px 10px; border-radius: 6px; }
    QMenuBar::item:selected { background: #24344D; color: #93C5FD; }
    QMenu {
        background: rgba(23, 33, 50, 0.96);
        border: 1px solid #2F415C; border-radius: 8px; padding: 4px;
    }
    QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; }
    QMenu::item:selected { background: #2563EB; color: white; }
    QStatusBar { background: rgba(17, 24, 39, 0.7); border-top: 1px solid #2F415C; }
    QDockWidget::title {
        background: rgba(17, 24, 39, 0.7);
        border-bottom: 1px solid #2F415C;
        padding: 4px 8px; color: #60A5FA; font-weight: 600;
    }
    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #33466B; border-radius: 5px; min-height: 24px; }
    QScrollBar::handle:vertical:hover { background: #40587F; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
    QScrollBar::handle:horizontal { background: #33466B; border-radius: 5px; min-width: 24px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
)";

}  // namespace

QString themeStyleSheet(bool dark) {
    return QString::fromUtf8(dark ? kDarkStyle : kLightStyle);
}

void applyTheme(QApplication& app, bool dark) {
    app.setStyle("Fusion");
    QPalette palette;
    if (dark) {
        palette.setColor(QPalette::Window, QColor(23, 33, 50));
        palette.setColor(QPalette::WindowText, QColor(226, 232, 240));
        palette.setColor(QPalette::Base, QColor(15, 23, 42));
        palette.setColor(QPalette::AlternateBase, QColor(27, 36, 54));
        palette.setColor(QPalette::Text, QColor(226, 232, 240));
        palette.setColor(QPalette::Button, QColor(30, 58, 95));
        palette.setColor(QPalette::ButtonText, QColor(191, 219, 254));
        palette.setColor(QPalette::Highlight, QColor(37, 99, 235));
        palette.setColor(QPalette::HighlightedText, Qt::white);
        palette.setColor(QPalette::ToolTipBase, QColor(23, 33, 50));
        palette.setColor(QPalette::ToolTipText, QColor(226, 232, 240));
    } else {
        palette.setColor(QPalette::Window, QColor(248, 250, 252));
        palette.setColor(QPalette::WindowText, QColor(30, 41, 59));
        palette.setColor(QPalette::Base, QColor(255, 255, 255));
        palette.setColor(QPalette::AlternateBase, QColor(239, 244, 255));
        palette.setColor(QPalette::Text, QColor(30, 41, 59));
        palette.setColor(QPalette::Button, QColor(234, 242, 255));
        palette.setColor(QPalette::ButtonText, QColor(29, 78, 216));
        palette.setColor(QPalette::Highlight, QColor(37, 99, 235));
        palette.setColor(QPalette::HighlightedText, Qt::white);
        palette.setColor(QPalette::ToolTipBase, QColor(255, 255, 255));
        palette.setColor(QPalette::ToolTipText, QColor(30, 41, 59));
    }
    app.setPalette(palette);
    app.setStyleSheet(themeStyleSheet(dark));
}

}  // namespace app
