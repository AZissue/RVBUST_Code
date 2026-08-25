#include "ui/ToastOverlay.h"
#include "ui/Theme.h"
#include <QVBoxLayout>
#include <QGraphicsOpacityEffect>
#include <QPropertyAnimation>

ToastOverlay::ToastOverlay(QWidget* parent)
    : QWidget(parent)
    , m_label(new QLabel(this))
{
    setWindowFlags(Qt::FramelessWindowHint | Qt::Tool | Qt::WindowStaysOnTopHint);
    setAttribute(Qt::WA_TransparentForMouseEvents);
    setAttribute(Qt::WA_TranslucentBackground);
    setAttribute(Qt::WA_ShowWithoutActivating);

    m_label->setAlignment(Qt::AlignCenter);
    m_label->setStyleSheet(QStringLiteral(
        "background-color: %1; color: #FFF; border-radius: 6px; "
        "padding: 10px 24px; font-size: %2px; font-weight: 500;")
        .arg(Theme::SUCCESS)
        .arg(Theme::FONT_BODY));

    m_label->setSizePolicy(QSizePolicy::Minimum, QSizePolicy::Fixed);
    m_label->setFixedHeight(40);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_label, 0, Qt::AlignCenter);

    m_hideTimer.setSingleShot(true);
    connect(&m_hideTimer, &QTimer::timeout, this, &QWidget::hide);
    hide();
}

void ToastOverlay::showMessage(const QString& text, bool success, int durationMs)
{
    auto bg = success ? QString(Theme::SUCCESS) : QString(Theme::ERROR);
    m_label->setStyleSheet(QStringLiteral(
        "background-color: %1; color: #FFF; border-radius: 6px; "
        "padding: 10px 24px; font-size: %2px; font-weight: 500;")
        .arg(bg)
        .arg(Theme::FONT_BODY));
    m_label->setText(text);
    m_label->adjustSize();

    // Position below the top nav bar (48px tall + 24px top margin)
    if (parentWidget()) {
        auto pw = parentWidget()->width();
        move((pw - m_label->width()) / 2, 88);
    }
    setFixedSize(m_label->sizeHint());

    show();
    raise();
    m_hideTimer.start(durationMs);
}
