#include "ui/DataInputArea.h"
#include "ui/Theme.h"

DataInputArea::DataInputArea(QWidget* parent)
    : QWidget(parent)
{
    // Locked height — 2 cards get ~68px each, 3 cards get ~44px each.
    // Changing card count never alters this value, so views stay stable.
    setFixedHeight(140);

    m_layout = new QVBoxLayout(this);
    m_layout->setContentsMargins(24, 0, 24, 0);
    m_layout->setSpacing(4);

    m_cardCamTarget = new DataInputCard(
        QStringLiteral("camera_target_xyz"),
        QStringLiteral("相机目标点坐标"),
        QStringLiteral("识别到的相机坐标目标点坐标，也可手动输入"),
        this);
    // ── 问题：三张卡片均分 160px 的固定高度 (每张约 48px)，加上 spacing 8px，
    //    在"眼在手上+戳点标定"三个卡片都可见时，间距叠加后视觉上偏大。
    // ── 修改建议：
    //    1. 减小 m_layout->setSpacing(4) — 将卡片间距从 8px 降到 4px。
    //    2. 将 setFixedHeight(160) 降到 140-150，让三张卡片更紧凑。
    //    3. 如果想更精细：根据可见卡片数量动态调整 spacing 和固定高度，
    //       在 updateVisibility() 中调用 setFixedHeight(visibleCount == 3 ? 140 : 160)。
    m_layout->addWidget(m_cardCamTarget, 1);

    m_cardRobotPose = new DataInputCard(
        QStringLiteral("robot_capture_pose"),
        QStringLiteral("机器人拍照位姿"),
        QStringLiteral("支持手动输入或复制粘贴"),
        this);
    m_layout->addWidget(m_cardRobotPose, 1);

    m_cardRobotTarget = new DataInputCard(
        QStringLiteral("robot_target_xyz"),
        QStringLiteral("机器人目标点坐标"),
        QStringLiteral("也可手动输入或复制粘贴"),
        this);
    m_layout->addWidget(m_cardRobotTarget, 1);
}

void DataInputArea::updateVisibility(bool eyeInHand, bool markerType)
{
    // Card 1: always visible
    m_cardCamTarget->show();

    // Card 2: hidden only in "eye-to-hand + tcp"
    bool hidePose = !eyeInHand && !markerType;
    m_cardRobotPose->setVisible(!hidePose);

    // Card 3: visible only in TCP mode
    m_cardRobotTarget->setVisible(!markerType);

    // Height stays FIXED regardless of visible card count.
    // Cards expand/shrink within this locked space via layout stretch,
    // so 2D/3D visualization views never resize on mode switch.
}

DataInputCard* DataInputArea::card(const QString& id) const
{
    if (id == "camera_target_xyz")   return m_cardCamTarget;
    if (id == "robot_capture_pose")  return m_cardRobotPose;
    if (id == "robot_target_xyz")    return m_cardRobotTarget;
    return nullptr;
}
