#include "ui/Theme.h"

#include <QColor>
#include <QString>

namespace Theme {

QString withAlpha(const char* color, double alpha)
{
    const QColor c(QString::fromLatin1(color));
    return QStringLiteral("rgba(%1,%2,%3,%4)")
        .arg(c.red())
        .arg(c.green())
        .arg(c.blue())
        .arg(alpha);
}

QString globalStylesheet()
{
    return QStringLiteral(R"(
        QMainWindow {
            background-color: %1;
        }
        QToolTip {
            background-color: %2;
            border: 1px solid %3;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: %4px;
            color: %5;
        }
        QProgressBar {
            border: none;
            background-color: %3;
            border-radius: 3px;
            height: 6px;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: %6;
            border-radius: 3px;
        }
        QScrollArea {
            border: none;
            background: transparent;
        }
        QSplitter::handle {
            background-color: %3;
            width: 2px;
        }
    )")
    .arg(BG_MAIN)
    .arg(BG_CARD)
    .arg(BORDER_DEFAULT)
    .arg(FONT_HINT)
    .arg(TEXT_BODY)
    .arg(PRIMARY);
}

QString primaryButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: #FFFFFF;
            border: none;
            border-radius: %2px;
            padding: 0 24px;
            font-size: %3px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover { background-color: %4; }
        QPushButton:pressed { background-color: %5; }
        QPushButton:disabled { opacity: 0.5; }
    )")
    .arg(PRIMARY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(PRIMARY_HOVER)
    .arg(PRIMARY_CLICK);
}

QString secondaryButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: %2;
            border: 1px solid %3;
            border-radius: %4px;
            padding: 0 24px;
            font-size: %5px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover { background-color: %6; }
        QPushButton:disabled { opacity: 0.5; }
    )")
    .arg(BG_MAIN)
    .arg(TEXT_BODY)
    .arg(BORDER_DEFAULT)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(BG_CARD);
}

QString secondaryButtonCompactStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: %2;
            border: 1px solid %3;
            border-radius: %4px;
            padding: 0 12px;
            font-size: %5px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover { background-color: %6; }
        QPushButton:disabled { opacity: 0.5; }
    )")
    .arg(BG_MAIN)
    .arg(TEXT_BODY)
    .arg(BORDER_DEFAULT)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(BG_CARD);
}

QString secondaryEmphasisButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: %2;
            border: 1px solid %2;
            border-radius: %3px;
            padding: 0 24px;
            font-size: %4px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover { background-color: %5; }
        QPushButton:disabled { opacity: 0.5; }
    )")
    .arg(BG_MAIN)
    .arg(PRIMARY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(PRIMARY_LIGHT);
}

QString dangerButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: %2;
            border: 1px solid %2;
            border-radius: %3px;
            padding: 0 24px;
            font-size: %4px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover { background-color: %5; }
        QPushButton:disabled { opacity: 0.5; }
    )")
    .arg(BG_MAIN)
    .arg(ERROR)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(ERROR_BG);
}

QString busyButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton, QPushButton:disabled {
            color: #FFFFFF;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 %1,
                                        stop:1 %2);
            border: 1px solid %3;
            border-radius: %4px;
            padding: 0 24px;
            font-size: %5px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 %6,
                                        stop:1 %7);
        }
    )")
    .arg(withAlpha(PRIMARY, 0.55))
    .arg(withAlpha(PRIMARY, 0.12))
    .arg(PRIMARY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(withAlpha(PRIMARY_HOVER, 0.65))
    .arg(withAlpha(PRIMARY_HOVER, 0.18));
}

QString flashButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            color: #FFFFFF;
            background-color: %1;
            border: 1px solid %2;
            border-radius: %3px;
            padding: 0 24px;
            font-size: %4px;
            font-weight: 500;
            height: 40px;
        }
    )")
    .arg(withAlpha(PRIMARY, 0.85))
    .arg(PRIMARY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY);
}

QString inputStyle(int fontSize)
{
    return QStringLiteral(R"(
        QLineEdit {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 4px;
            padding: 4px 8px;
            color: %3;
            font-size: %4px;
        }
        QLineEdit:focus {
            border: 1px solid %5;
            background-color: %6;
        }
    )")
    .arg(BG_MAIN)
    .arg(BORDER_DEFAULT)
    .arg(TEXT_BODY)
    .arg(fontSize)
    .arg(BORDER_FOCUS)
    .arg(PRIMARY_LIGHT);
}

QString inputErrorStyle()
{
    return QStringLiteral(R"(
        QLineEdit {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 6px;
            padding: 6px 12px;
            color: %3;
            font-size: %4px;
            height: 32px;
        }
    )")
    .arg(BG_MAIN)
    .arg(ERROR)
    .arg(TEXT_BODY)
    .arg(FONT_BODY);
}

QString toggleSelectedStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: #FFFFFF;
            border: none;
            border-radius: %2px;
            font-size: %3px;
            font-weight: 500;
            height: 32px;
            min-width: 80px;
        }
    )")
    .arg(PRIMARY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY);
}

QString toggleUnselectedStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            background-color: %1;
            color: %2;
            border: none;
            border-radius: %3px;
            font-size: %4px;
            font-weight: 400;
            height: 32px;
            min-width: 80px;
        }
        QPushButton:hover { background-color: %5; }
    )")
    .arg(BG_CARD)
    .arg(TEXT_BODY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY)
    .arg(PRIMARY_LIGHT);
}

QString comboBoxStyle()
{
    return QStringLiteral(R"(
        QComboBox {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 4px;
            padding: 4px 8px;
            color: %3;
            font-size: %4px;
        }
        QComboBox:hover { border-color: %5; }
        QComboBox:focus { border-color: %5; }
        QComboBox::drop-down { border: none; width: 24px; }
        QComboBox QAbstractItemView {
            background-color: %1;
            border: 1px solid %2;
            selection-background-color: %6;
            selection-color: #FFFFFF;
        }
    )")
    .arg(BG_MAIN)
    .arg(BORDER_DEFAULT)
    .arg(TEXT_BODY)
    .arg(FONT_BODY)
    .arg(BORDER_FOCUS)
    .arg(PRIMARY);
}

QString spinBoxStyle()
{
    return QStringLiteral(R"(
        QDoubleSpinBox {
            background-color: %1;
            border: 1px solid %2;
            border-radius: 4px;
            padding: 4px 8px;
            color: %3;
            font-size: %4px;
        }
        QDoubleSpinBox:hover { border-color: %5; }
        QDoubleSpinBox:focus { border-color: %5; }
    )")
    .arg(BG_MAIN)
    .arg(BORDER_DEFAULT)
    .arg(TEXT_BODY)
    .arg(FONT_BODY)
    .arg(BORDER_FOCUS);
}

// ── 2D/3D 视窗的浮层（T-001 判据 3）──────────────────────────────────
// 人原话：「不要有边框不要有背景色，只要每个按钮的背景模糊即可」。
// 所以这里**不再给恒定 alpha 的实心底色**（那正是上一轮留下的"一块底色"）：
// 常态背景 transparent，背后的画面由控件自己铺——2D 侧在 Image2DView 里铺
// 背后画面的模糊副本，3D 侧走 Windows 合成的 blur-behind（见 VisSceneView）。
// 只有 hover / pressed / checked 这些"反馈"状态才叠一层很淡的颜色，状态看得见，
// 模糊也还透得出来。圆角在这里，模糊的裁剪圆角与它保持一致（8px，与
// 共用浮层组件 ui/ViewOverlay.h 的 ViewOverlay::kGlassRadius 同值——
// T-002 判据 6 / T-003 契约冻结）。

QString viewOverlayLabelStyle()
{
    return QStringLiteral(R"(
        QLabel {
            color: #FFFFFF;
            background-color: transparent;
            border: none;
            border-radius: 8px;
            padding: 3px 8px;
            font-size: %1px;
        }
    )")
    .arg(FONT_HINT);
}

QString viewOverlayButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            color: #E6EAF2;
            background-color: transparent;
            border: none;
            border-radius: 8px;
            padding: 3px 9px;
            font-size: %1px;
        }
        QPushButton:hover { background-color: rgba(255, 255, 255, 0.12); }
        QPushButton:pressed { background-color: %2; }
        QPushButton:checked {
            background-color: %3;
            color: #FFFFFF;
            font-weight: 600;
        }
        QPushButton:disabled { color: #9AA0AA; background-color: transparent; }
    )")
    .arg(FONT_HINT)
    .arg(withAlpha(PRIMARY, 0.30))
    .arg(withAlpha(PRIMARY, 0.34));
}

} // namespace Theme
