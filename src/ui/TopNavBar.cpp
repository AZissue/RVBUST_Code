#include "ui/TopNavBar.h"
#include "ui/Theme.h"
#include <QHBoxLayout>

TopNavBar::TopNavBar(QWidget* parent)
    : QWidget(parent)
{
    setFixedHeight(48);
    setStyleSheet(QStringLiteral("background-color: %1; border-bottom: 1px solid %2;")
                  .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT));

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(24, 0, 24, 0);
    layout->setSpacing(16);

    // Title
    m_title = new QLabel(QStringLiteral("手眼标定数据收集助手 V1.0"), this);
    m_title->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2; border: none;")
                           .arg(Theme::FONT_H1).arg(Theme::TEXT_TITLE));
    layout->addWidget(m_title);

    // Progress
    m_progressLabel = new QLabel(QStringLiteral("已采集 0/15 组数据"), this);
    m_progressLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                   .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    layout->addWidget(m_progressLabel);

    m_progressBar = new QProgressBar(this);
    m_progressBar->setFixedSize(120, 6);
    m_progressBar->setRange(0, Theme::RECOMMENDED_COUNT);
    m_progressBar->setValue(0);
    m_progressBar->setTextVisible(false);
    layout->addWidget(m_progressBar);

    layout->addStretch();

    // Camera status
    m_cameraDot = new QLabel(this);
    m_cameraDot->setFixedSize(10, 10);
    m_cameraDot->setStyleSheet(QStringLiteral("background-color: %1; border-radius: 5px;").arg(Theme::TEXT_HINT));
    layout->addWidget(m_cameraDot);

    m_cameraLabel = new QLabel(QStringLiteral("未连接"), this);
    m_cameraLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                 .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    layout->addWidget(m_cameraLabel);

    m_btnConnect = new QPushButton(QStringLiteral("连接"), this);
    m_btnConnect->setFixedSize(60, 28);
    m_btnConnect->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: %1; background: transparent; border: 1px solid %1;
                      border-radius: 4px; font-size: %2px; }
        QPushButton:hover { border-color: %3; color: %3; }
    )").arg(Theme::PRIMARY).arg(Theme::FONT_HINT).arg(Theme::PRIMARY_HOVER));
    layout->addWidget(m_btnConnect);

    // Settings / Help
    m_btnSettings = new QPushButton(QStringLiteral("设置"), this);
    m_btnSettings->setFixedSize(48, 28);
    m_btnSettings->setStyleSheet(QStringLiteral("color: %1; background: transparent; border: none; font-size: %2px;")
                                 .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    m_btnHelp = new QPushButton(QStringLiteral("帮助"), this);
    m_btnHelp->setFixedSize(48, 28);
    m_btnHelp->setStyleSheet(QStringLiteral("color: %1; background: transparent; border: none; font-size: %2px;")
                             .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));

    layout->addWidget(m_btnSettings);
    layout->addWidget(m_btnHelp);

    connect(m_btnConnect,  &QPushButton::clicked, this, &TopNavBar::onConnectBtnClicked);
    connect(m_btnSettings, &QPushButton::clicked, this, &TopNavBar::settingsClicked);
    connect(m_btnHelp,     &QPushButton::clicked, this, &TopNavBar::helpClicked);
}

void TopNavBar::updateProgress(int current, int total)
{
    int t = (total > 0) ? total : Theme::RECOMMENDED_COUNT;
    m_progressLabel->setText(QStringLiteral("已采集 %1/%2 组数据").arg(current).arg(t));
    m_progressBar->setMaximum(t);
    m_progressBar->setValue(current);
}

void TopNavBar::setCameraStatus(bool connected, const QString& deviceName)
{
    m_cameraConnected = connected;
    m_btnConnect->setEnabled(true);
    if (connected) {
        m_cameraDot->setStyleSheet(QStringLiteral("background-color: %1; border-radius: 5px;").arg(Theme::SUCCESS));
        m_cameraLabel->setText(deviceName.isEmpty() ? QStringLiteral("已连接") : deviceName);
        m_cameraLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                     .arg(Theme::FONT_HINT).arg(Theme::SUCCESS));
        m_btnConnect->setText(QStringLiteral("断开"));
    } else {
        m_cameraDot->setStyleSheet(QStringLiteral("background-color: %1; border-radius: 5px;").arg(Theme::TEXT_HINT));
        m_cameraLabel->setText(QStringLiteral("未连接"));
        m_cameraLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                     .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
        m_btnConnect->setText(QStringLiteral("连接"));
    }
}

void TopNavBar::setConnectBusy(bool busy, const QString& text)
{
    if (busy) {
        m_btnConnect->setText(text);
        m_btnConnect->setEnabled(false);
    } else {
        m_btnConnect->setEnabled(true);
        m_btnConnect->setText(m_cameraConnected ? QStringLiteral("断开") : QStringLiteral("连接"));
    }
}

void TopNavBar::onConnectBtnClicked()
{
    if (m_cameraConnected)
        emit disconnectCameraClicked();
    else
        emit connectCameraClicked();
}
