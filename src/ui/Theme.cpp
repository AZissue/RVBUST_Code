#include "ui/Theme.h"

namespace Theme {

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
                                        stop:0 rgba(22,119,255,0.55),
                                        stop:1 rgba(22,119,255,0.12));
            border: 1px solid %1;
            border-radius: %2px;
            padding: 0 24px;
            font-size: %3px;
            font-weight: 500;
            height: 40px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 rgba(64,150,255,0.65),
                                        stop:1 rgba(64,150,255,0.18));
        }
    )")
    .arg(PRIMARY)
    .arg(BORDER_RADIUS)
    .arg(FONT_BODY);
}

QString flashButtonStyle()
{
    return QStringLiteral(R"(
        QPushButton {
            color: #FFFFFF;
            background-color: rgba(22,119,255,0.85);
            border: 1px solid %1;
            border-radius: %2px;
            padding: 0 24px;
            font-size: %3px;
            font-weight: 500;
            height: 40px;
        }
    )")
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

} // namespace Theme
