#include "ui/SidePanel.h"
#include "ui/Theme.h"
#include "models/CaptureRecord.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QScrollBar>
#include <QFormLayout>
#include <sstream>

SidePanel::SidePanel(QWidget* parent)
    : QWidget(parent)
{
    setFixedWidth(408);
    setStyleSheet(QStringLiteral("background-color: %1;").arg(Theme::BG_MAIN));

    auto* mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(0, 0, 24, 0);
    mainLayout->setSpacing(12);

    // ── Card 1: Tips (elastic) ──
    m_tipsCard = new QFrame(this);
    m_tipsCard->setMinimumHeight(70);
    m_tipsCard->setMaximumHeight(140);
    m_tipsCard->setStyleSheet(QStringLiteral("background: %1; border: 1px solid %2; border-radius: %3px;")
                              .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));
    auto* tipsLayout = new QVBoxLayout(m_tipsCard);
    tipsLayout->setContentsMargins(12, 10, 12, 10);
    tipsLayout->setSpacing(4);

    auto* tipsTitle = new QLabel(QStringLiteral("当前操作提示"), m_tipsCard);
    tipsTitle->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2; border: none;")
                             .arg(Theme::FONT_BODY).arg(Theme::PRIMARY));
    tipsLayout->addWidget(tipsTitle);

    m_tipsContent = new QLabel(QStringLiteral("请连接相机并选择标定模式"), m_tipsCard);
    m_tipsContent->setWordWrap(true);
    m_tipsContent->setAlignment(Qt::AlignLeft | Qt::AlignVCenter);
    m_tipsContent->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                 .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    tipsLayout->addWidget(m_tipsContent, 1);
    mainLayout->addWidget(m_tipsCard);

    // ── Card 2: Notes (collapsible) ──
    m_notesCard = new QFrame(this);
    m_notesCard->setStyleSheet(QStringLiteral("background: %1; border: 1px solid %2; border-radius: %3px;")
                               .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));
    auto* notesLayout = new QVBoxLayout(m_notesCard);
    notesLayout->setContentsMargins(0, 0, 0, 0);
    notesLayout->setSpacing(0);

    // Header with collapse button
    auto* notesHeader = new QWidget(m_notesCard);
    notesHeader->setFixedHeight(32);
    notesHeader->setStyleSheet(QStringLiteral("background-color: %1; "
                               "border-top-left-radius: %2px; border-top-right-radius: %2px;")
                               .arg(Theme::PRIMARY).arg(Theme::BORDER_RADIUS));
    auto* hdrLayout = new QHBoxLayout(notesHeader);
    hdrLayout->setContentsMargins(12, 0, 4, 0);

    auto* notesTitle = new QLabel(QStringLiteral("标定注意事项"), notesHeader);
    notesTitle->setStyleSheet(QStringLiteral("color: #FFF; font-size: %1px; font-weight: 600; border: none;")
                              .arg(Theme::FONT_BODY));
    hdrLayout->addWidget(notesTitle);
    hdrLayout->addStretch();

    m_btnCollapseNotes = new QPushButton(QStringLiteral("−"), notesHeader);
    m_btnCollapseNotes->setFixedSize(24, 24);
    m_btnCollapseNotes->setStyleSheet(QStringLiteral(
        "QPushButton { color: #FFF; background: transparent; border: none; font-size: 16px; font-weight: bold; }"
        "QPushButton:hover { background: rgba(255,255,255,0.15); border-radius: 4px; }"));
    hdrLayout->addWidget(m_btnCollapseNotes);
    notesLayout->addWidget(notesHeader);

    // Collapsible content
    m_notesContent = new QWidget(m_notesCard);
    auto* ncLayout = new QVBoxLayout(m_notesContent);
    ncLayout->setContentsMargins(12, 10, 12, 10);
    auto* ncLabel = new QLabel(m_notesContent);
    ncLabel->setWordWrap(true);
    ncLabel->setText(QStringLiteral(
        "<p style='line-height:20px;'><b>标定过程中严禁移动相机和机器人基座</b></p>"
        "<p style='line-height:20px;'>标定板应尽量充满相机视野的不同区域</p>"
        "<p style='line-height:20px; color:#FAAD14;'><b>建议采集 15-20 组不同位姿的数据</b></p>"
        "<p style='line-height:20px;'>位姿应包含不同的角度和距离</p>"));
    ncLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                           .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    ncLayout->addWidget(ncLabel);
    notesLayout->addWidget(m_notesContent);

    connect(m_btnCollapseNotes, &QPushButton::clicked, this, [this]() {
        bool collapsed = m_notesContent->isVisible();
        m_notesContent->setVisible(!collapsed);
        m_btnCollapseNotes->setText(collapsed ? QStringLiteral("−") : QStringLiteral("+"));
    });

    mainLayout->addWidget(m_notesCard);

    // ── Card 3: File Preview (gets remaining space) ──
    m_previewCard = new QFrame(this);
    m_previewCard->setStyleSheet(QStringLiteral("background: %1; border: 1px solid %2; border-radius: %3px;")
                                 .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));
    auto* previewLayout = new QVBoxLayout(m_previewCard);
    previewLayout->setContentsMargins(12, 10, 12, 10);
    previewLayout->setSpacing(6);

    auto* previewTitle = new QLabel(QStringLiteral("文件预览"), m_previewCard);
    previewTitle->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2; border: none;")
                                .arg(Theme::FONT_BODY).arg(Theme::TEXT_TITLE));
    previewLayout->addWidget(previewTitle);

    // Tab buttons
    auto* tabLayout = new QHBoxLayout();
    tabLayout->setSpacing(4);

    auto makeTab = [&](const QString& text) -> QPushButton* {
        auto* b = new QPushButton(text, m_previewCard);
        b->setCheckable(true);
        b->setFixedHeight(22);
        b->setStyleSheet(QStringLiteral(R"(
            QPushButton { color: %1; background: transparent; border: 1px solid %2;
                          border-radius: 3px; font-size: %3px; padding: 0 8px; }
            QPushButton:hover { border-color: %4; }
            QPushButton:checked { border-color: %4; color: %4; }
        )").arg(Theme::TEXT_HINT).arg(Theme::BORDER_DEFAULT).arg(Theme::FONT_HINT).arg(Theme::PRIMARY));
        return b;
    };

    m_tabCamTarget  = makeTab(QStringLiteral("相机目标点"));
    m_tabRobotPose  = makeTab(QStringLiteral("机器人位姿"));
    m_tabRobotTarget = makeTab(QStringLiteral("机器人TCP点"));
    m_tabCalibResult = makeTab(QStringLiteral("标定结果"));

    tabLayout->addWidget(m_tabCamTarget);
    tabLayout->addWidget(m_tabRobotPose);
    tabLayout->addWidget(m_tabRobotTarget);
    tabLayout->addWidget(m_tabCalibResult);
    tabLayout->addStretch();
    previewLayout->addLayout(tabLayout);

    m_previewText = new QTextEdit(m_previewCard);
    m_previewText->setReadOnly(true);
    m_previewText->setStyleSheet(QStringLiteral("background: %1; border: 1px solid %2; border-radius: 4px; "
                                                 "font-size: %3px; color: %4; font-family: Consolas, monospace;")
                                 .arg(Theme::BG_CARD).arg(Theme::BORDER_DEFAULT)
                                 .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    previewLayout->addWidget(m_previewText, 1);

    mainLayout->addWidget(m_previewCard, 1);

    // ── Card 4: Robot communication (isolated, off by default) ──
    m_robotCard = new QFrame(this);
    m_robotCard->setStyleSheet(QStringLiteral(
        "background: %1; border: 1px solid %2; border-radius: %3px;")
        .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT)
        .arg(Theme::BORDER_RADIUS));
    auto* robotLayout = new QVBoxLayout(m_robotCard);
    robotLayout->setContentsMargins(12, 10, 12, 10);
    robotLayout->setSpacing(6);

    auto* robotTitle = new QLabel(QStringLiteral("机器人通信（可选）"), m_robotCard);
    robotTitle->setStyleSheet(QStringLiteral(
        "font-size: %1px; font-weight: 600; color: %2; border: none;")
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_TITLE));
    robotLayout->addWidget(robotTitle);

    auto* protoRow = new QHBoxLayout();
    protoRow->setSpacing(6);
    m_robotProtocol = new QComboBox(m_robotCard);
    m_robotProtocol->addItem(QStringLiteral("Modbus TCP"));
    m_robotProtocol->setStyleSheet(Theme::comboBoxStyle());
    protoRow->addWidget(m_robotProtocol, 1);
    m_robotStatus = new QLabel(QStringLiteral("未连接"), m_robotCard);
    m_robotStatus->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2; border: none;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    protoRow->addWidget(m_robotStatus);
    robotLayout->addLayout(protoRow);

    auto* hostRow = new QHBoxLayout();
    hostRow->setSpacing(6);
    hostRow->addWidget(new QLabel(QStringLiteral("IP"), m_robotCard));
    m_robotHost = new QLineEdit(QStringLiteral("192.168.0.1"), m_robotCard);
    m_robotHost->setStyleSheet(Theme::inputStyle(Theme::FONT_HINT));
    hostRow->addWidget(m_robotHost, 1);
    hostRow->addWidget(new QLabel(QStringLiteral("端口"), m_robotCard));
    m_robotPort = new QSpinBox(m_robotCard);
    m_robotPort->setRange(1, 65535);
    m_robotPort->setValue(502);
    m_robotPort->setFixedWidth(72);
    hostRow->addWidget(m_robotPort);
    robotLayout->addLayout(hostRow);

    auto* cfgRow = new QHBoxLayout();
    cfgRow->setSpacing(6);
    cfgRow->addWidget(new QLabel(QStringLiteral("格式"), m_robotCard));
    m_robotFormat = new QComboBox(m_robotCard);
    m_robotFormat->addItem(QStringLiteral("Float32"));
    m_robotFormat->addItem(QStringLiteral("Int32×系数"));
    m_robotFormat->addItem(QStringLiteral("Int16×系数"));
    m_robotFormat->setStyleSheet(Theme::comboBoxStyle());
    cfgRow->addWidget(m_robotFormat, 1);
    cfgRow->addWidget(new QLabel(QStringLiteral("系数"), m_robotCard));
    m_robotScale = new QLineEdit(QStringLiteral("1.0"), m_robotCard);
    m_robotScale->setFixedWidth(56);
    m_robotScale->setStyleSheet(Theme::inputStyle(Theme::FONT_HINT));
    cfgRow->addWidget(m_robotScale);
    robotLayout->addLayout(cfgRow);

    auto* addrRow = new QHBoxLayout();
    addrRow->setSpacing(6);
    addrRow->addWidget(new QLabel(QStringLiteral("起始寄存器"), m_robotCard));
    m_robotStartAddr = new QSpinBox(m_robotCard);
    m_robotStartAddr->setRange(0, 65535);
    m_robotStartAddr->setValue(0);
    addrRow->addWidget(m_robotStartAddr);
    addrRow->addWidget(new QLabel(QStringLiteral("站号"), m_robotCard));
    m_robotUnitId = new QSpinBox(m_robotCard);
    m_robotUnitId->setRange(1, 255);
    m_robotUnitId->setValue(1);
    addrRow->addWidget(m_robotUnitId);
    addrRow->addStretch();
    robotLayout->addLayout(addrRow);

    auto* btnRow = new QHBoxLayout();
    btnRow->setSpacing(6);
    m_btnRobotConnect = new QPushButton(QStringLiteral("连接"), m_robotCard);
    m_btnRobotConnect->setStyleSheet(Theme::secondaryButtonStyle());
    btnRow->addWidget(m_btnRobotConnect);
    m_btnRobotRead = new QPushButton(QStringLiteral("读取位姿"), m_robotCard);
    m_btnRobotRead->setStyleSheet(Theme::secondaryButtonStyle());
    m_btnRobotRead->setEnabled(false);
    btnRow->addWidget(m_btnRobotRead);
    m_robotAutoRead = new QCheckBox(QStringLiteral("拍照时自动读取"), m_robotCard);
    m_robotAutoRead->setChecked(false);
    m_robotAutoRead->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_BODY));
    btnRow->addWidget(m_robotAutoRead);
    btnRow->addStretch();
    robotLayout->addLayout(btnRow);

    mainLayout->addWidget(m_robotCard);

    connect(m_btnRobotConnect, &QPushButton::clicked, this, [this]() {
        if (m_btnRobotConnect->text() == QStringLiteral("连接")) {
            bool okScale = false;
            const double scale = m_robotScale->text().trimmed().toDouble(&okScale);
            if (!okScale) {
                setRobotStatus(QStringLiteral("系数格式无效"), true);
                return;
            }
            emit robotConnectRequested(
                m_robotHost->text().trimmed(),
                static_cast<quint16>(m_robotPort->value()),
                m_robotFormat->currentIndex(), scale,
                static_cast<quint8>(m_robotUnitId->value()),
                static_cast<quint16>(m_robotStartAddr->value()));
        } else {
            emit robotDisconnectRequested();
        }
    });
    connect(m_btnRobotRead, &QPushButton::clicked, this,
            [this]() { emit robotReadRequested(); });
    connect(m_robotAutoRead, &QCheckBox::toggled, this,
            [this](bool on) { emit robotAutoReadToggled(on); });

    // Tab connections
    m_tabCamTarget->setChecked(true);
    m_activeTab = "cam_target";
    auto onTab = [this](const QString& key) {
        if (m_activeTab == key) return;
        m_activeTab = key;
        m_tabCamTarget->setChecked(key == "cam_target");
        m_tabRobotPose->setChecked(key == "robot_pose");
        m_tabRobotTarget->setChecked(key == "robot_target");
        m_tabCalibResult->setChecked(key == "calib_result");
        if (key == "calib_result")
            showCalibrationResult();
        else if (!m_markerType)
            showTcpPreview(m_activeTab, m_eyeInHand, m_cachedRecords);
        else
            showMarkerPreview(m_cachedRecords);
    };
    connect(m_tabCamTarget, &QPushButton::clicked, this, [onTab]() { onTab("cam_target"); });
    connect(m_tabRobotPose, &QPushButton::clicked, this, [onTab]() { onTab("robot_pose"); });
    connect(m_tabRobotTarget, &QPushButton::clicked, this, [onTab]() { onTab("robot_target"); });
    connect(m_tabCalibResult, &QPushButton::clicked, this, [onTab]() { onTab("calib_result"); });
}

void SidePanel::setTip(const QString& text, bool isError)
{
    m_tipsContent->setText(text);
    if (isError) {
        m_tipsContent->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                     .arg(Theme::FONT_BODY).arg(Theme::ERROR));
    } else {
        m_tipsContent->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; border: none;")
                                     .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    }
}

void SidePanel::setCalibrationResult(const QString& text)
{
    m_calibResult = text;
    if (m_activeTab == QStringLiteral("calib_result"))
        showCalibrationResult();
}

void SidePanel::setRobotStatus(const QString& text, bool ok)
{
    m_robotStatus->setText(text);
    m_robotStatus->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2; border: none;")
        .arg(Theme::FONT_HINT)
        .arg(ok ? Theme::ERROR : Theme::TEXT_HINT));
}

void SidePanel::setRobotConnected(bool connected)
{
    m_btnRobotConnect->setText(connected ? QStringLiteral("断开")
                                         : QStringLiteral("连接"));
    m_btnRobotRead->setEnabled(connected);
}

void SidePanel::updateFilePreview(bool eyeInHand, bool markerType,
                                  const std::vector<CaptureRecord>& records)
{
    m_eyeInHand = eyeInHand;
    m_markerType = markerType;
    m_cachedRecords = records;

    m_tabCamTarget->show();
    m_tabRobotTarget->setVisible(!markerType);
    m_tabRobotPose->setVisible(!(!eyeInHand && !markerType));
    m_tabCalibResult->show();

    if (m_activeTab == QStringLiteral("calib_result")) {
        showCalibrationResult();
    } else if (markerType) {
        showMarkerPreview(records);
    } else {
        showTcpPreview(m_activeTab, eyeInHand, records);
    }
}

void SidePanel::showCalibrationResult()
{
    m_previewText->setText(m_calibResult.isEmpty()
                               ? QStringLiteral("（尚未计算标定结果）")
                               : m_calibResult);
}

void SidePanel::showMarkerPreview(const std::vector<CaptureRecord>& records)
{
    std::ostringstream oss;
    for (const auto& r : records) {
        oss << r.robotCapturePose.toStdString() << "\n";
    }
    m_previewText->setText(QString::fromStdString(oss.str()));
}

void SidePanel::showTcpPreview(const QString& key, bool eyeInHand,
                               const std::vector<CaptureRecord>& records)
{
    std::ostringstream oss;
    for (const auto& r : records) {
        if (key == "cam_target")
            oss << r.cameraTargetXyz.toStdString() << "\n";
        else if (key == "robot_pose" && eyeInHand)
            oss << r.robotCapturePose.toStdString() << "\n";
        else if (key == "robot_target")
            oss << r.robotTargetXyz.toStdString() << "\n";
    }
    m_previewText->setText(QString::fromStdString(oss.str()));
}
