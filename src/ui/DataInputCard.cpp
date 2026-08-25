#include "ui/DataInputCard.h"
#include "ui/Theme.h"
#include <QHBoxLayout>
#include <QApplication>
#include <QClipboard>
#include <algorithm>

DataInputCard::DataInputCard(const QString& cardId, const QString& label,
                             const QString& hint, QWidget* parent)
    : QWidget(parent)
    , m_cardId(cardId)
    , m_hint(hint)
{
    setMinimumHeight(32);
    setStyleSheet(QStringLiteral(
        "background-color: %1; border-radius: %2px;")
        .arg(Theme::BG_CARD).arg(Theme::BORDER_RADIUS));

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(12, 4, 12, 4);
    layout->setSpacing(8);
    layout->setAlignment(Qt::AlignVCenter);

    // Status dot
    m_statusDot = new QLabel(this);
    m_statusDot->setFixedSize(8, 8);
    m_statusDot->setStyleSheet(QStringLiteral(
        "background-color: %1; border-radius: 4px;").arg(Theme::TEXT_HINT));
    layout->addWidget(m_statusDot);

    // Label — centered, adaptive width
    m_label = new QLabel(label, this);
    m_label->setMinimumWidth(90);
    m_label->setMaximumWidth(140);
    m_label->setAlignment(Qt::AlignVCenter);
    m_label->setStyleSheet(QStringLiteral(
        "font-size: %1px; font-weight: 600; color: %2; border: none;")
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_TITLE));
    layout->addWidget(m_label);

    // Input — adaptive font via resizeEvent
    m_input = new QLineEdit(this);
    m_input->setPlaceholderText(hint);
    m_input->setStyleSheet(Theme::inputStyle());
    layout->addWidget(m_input, 1);

    // Copy button
    m_btnCopy = new QPushButton(QStringLiteral("复制"), this);
    m_btnCopy->setFixedSize(56, 30);
    m_btnCopy->setStyleSheet(QStringLiteral(R"(
        QPushButton {
            background-color: #FFFFFF;
            color: %1;
            border: 1px solid %1;
            border-radius: 4px;
            font-size: %2px;
        }
        QPushButton:hover { background-color: %3; }
    )").arg(Theme::PRIMARY).arg(Theme::FONT_HINT).arg(Theme::PRIMARY_LIGHT));
    layout->addWidget(m_btnCopy);

    connect(m_input, &QLineEdit::textChanged, this, &DataInputCard::onTextChanged);
    connect(m_btnCopy, &QPushButton::clicked, this, &DataInputCard::onCopy);
}

QString DataInputCard::cardId() const { return m_cardId; }

QString DataInputCard::value() const { return m_input->text().trimmed(); }

void DataInputCard::setValue(const QString& text)
{
    m_input->blockSignals(true);
    m_input->setText(text);
    m_input->blockSignals(false);
    setStatus(text.trimmed().isEmpty() ? QStringLiteral("empty") : QStringLiteral("ok"));
}

void DataInputCard::setStatus(const QString& status)
{
    QString color;
    if (status == "ok")
        color = Theme::SUCCESS;
    else if (status == "error")
        color = Theme::ERROR;
    else
        color = Theme::TEXT_HINT;

    m_statusDot->setStyleSheet(QStringLiteral(
        "background-color: %1; border-radius: 4px;").arg(color));

    if (status == "error") {
        m_input->setStyleSheet(Theme::inputErrorStyle());
    } else {
        m_input->setStyleSheet(Theme::inputStyle());
    }
}

void DataInputCard::onTextChanged(const QString& text)
{
    QString status = text.trimmed().isEmpty() ? "empty" : "ok";
    setStatus(status);
    emit valueChanged(text.trimmed());
}

void DataInputCard::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    int fs = std::clamp(height() / 3, 11, 14);
    m_input->setStyleSheet(Theme::inputStyle(fs));
}

void DataInputCard::onCopy()
{
    QApplication::clipboard()->setText(m_input->text().trimmed());
}
