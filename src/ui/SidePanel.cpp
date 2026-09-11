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

    // ── Top area: merged "操作日志" (notes + tips + pose guide + quality) ──
    // Elastic (shares vertical space equally with the file preview card
    // below); append-only log with a scrollbar so users can scroll back to
    // earlier entries while new ones auto-scroll into view. On startup this
    // defaults to the former "标定注意事项" content, tagged [注意事项].
    m_timelineCard = new QFrame(this);
    m_timelineCard->setStyleSheet(QStringLiteral("background: %1; border: 1px solid %2; border-radius: %3px;")
                                  .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));
    auto* tlLayout = new QVBoxLayout(m_timelineCard);
    tlLayout->setContentsMargins(12, 10, 12, 10);
    tlLayout->setSpacing(6);

    auto* tlHeader = new QHBoxLayout();
    auto* tlTitle = new QLabel(QStringLiteral("操作日志"), m_timelineCard);
    tlTitle->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2; border: none;")
                           .arg(Theme::FONT_BODY).arg(Theme::PRIMARY));
    tlHeader->addWidget(tlTitle);
    tlHeader->addStretch();
    m_btnRunQuality = new QPushButton(QStringLiteral("运行质检"), m_timelineCard);
    m_btnRunQuality->setFixedHeight(26);
    m_btnRunQuality->setCursor(Qt::PointingHandCursor);
    m_btnRunQuality->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: %1; background: %2; border: 1px solid %1; border-radius: 4px;
                      font-size: %3px; padding: 0 10px; }
        QPushButton:hover { background: %4; }
    )").arg(Theme::PRIMARY).arg(Theme::BG_MAIN).arg(Theme::FONT_HINT).arg(Theme::PRIMARY_LIGHT));
    tlHeader->addWidget(m_btnRunQuality);
    tlLayout->addLayout(tlHeader);

    m_timeline = new QTextEdit(m_timelineCard);
    m_timeline->setReadOnly(true);
    m_timeline->setStyleSheet(QStringLiteral("background: %1; border: 1px solid %2; border-radius: 4px; "
                                             "font-size: %3px; color: %4;")
                              .arg(Theme::BG_CARD).arg(Theme::BORDER_DEFAULT)
                              .arg(Theme::FONT_HINT).arg(Theme::TEXT_BODY));
    // Default content on first open: the former "标定注意事项" text, tagged
    // [注意事项] so it reads consistently with later [提示]/[姿态引导]/
    // [数据质检] entries appended by setTip()/setPoseGuide()/setQualityReport().
    appendTimeline(QStringLiteral("注意事项"), Theme::TEXT_TITLE,
                   QStringLiteral("标定过程中严禁移动相机和机器人基座"));
    appendTimeline(QStringLiteral("注意事项"), Theme::TEXT_TITLE,
                   QStringLiteral("标定板应尽量充满相机视野的不同区域"));
    appendTimeline(QStringLiteral("注意事项"), Theme::WARNING,
                   QStringLiteral("建议采集 15-20 组不同位姿的数据"));
    appendTimeline(QStringLiteral("注意事项"), Theme::TEXT_TITLE,
                   QStringLiteral("位姿应包含不同的角度和距离"));
    tlLayout->addWidget(m_timeline, 1);
    mainLayout->addWidget(m_timelineCard, 1);

    connect(m_btnRunQuality, &QPushButton::clicked, this, &SidePanel::qualityCheckRequested);

    // ── Bottom area: file preview (shares space equally with 操作日志) ──
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

void SidePanel::appendTimeline(const QString& label, const QString& colorHex, const QString& text)
{
    const QString html = QStringLiteral(
        "<div style='margin-bottom:6px;'>"
        "<span style='color:%1; font-weight:600;'>[%2]</span> "
        "<span style='color:%3;'>%4</span>"
        "</div>")
        .arg(colorHex).arg(label).arg(Theme::TEXT_BODY).arg(text.toHtmlEscaped());
    m_timeline->append(html);
    QScrollBar* bar = m_timeline->verticalScrollBar();
    if (bar)
        bar->setValue(bar->maximum());
}

void SidePanel::setTip(const QString& text, bool isError)
{
    appendTimeline(QStringLiteral("提示"), isError ? Theme::ERROR : Theme::PRIMARY, text);
}

void SidePanel::setCalibrationResult(const QString& text)
{
    m_calibResult = text;
    if (m_activeTab == QStringLiteral("calib_result"))
        showCalibrationResult();
}

void SidePanel::setPoseGuide(const QString& text, bool warning)
{
    appendTimeline(QStringLiteral("姿态引导"), warning ? Theme::WARNING : Theme::TEXT_TITLE, text);
}

void SidePanel::setQualityReport(const QString& html)
{
    appendTimeline(QStringLiteral("数据质检"), Theme::TEXT_TITLE, html);
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
