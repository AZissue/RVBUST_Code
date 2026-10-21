#include "ui/RobotProgramPanel.h"

#include "app/RobotProgramController.h"
#include "logic/JogPolicy.h"
#include "ui/Theme.h"

#include <QAbstractButton>
#include <QButtonGroup>
#include <QDoubleSpinBox>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QPushButton>
#include <QSignalBlocker>
#include <QSlider>
#include <QSpinBox>
#include <QStackedWidget>
#include <QVBoxLayout>

#include <algorithm>
#include <variant>

namespace {

QLabel* sectionTitle(const QString& text)
{
    auto* label = new QLabel(text);
    label->setStyleSheet(QStringLiteral(
        "font-size:%1px;font-weight:600;color:%2;")
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_TITLE));
    return label;
}

QFrame* cardFrame()
{
    auto* frame = new QFrame;
    frame->setObjectName(QStringLiteral("rpCard"));
    frame->setStyleSheet(QStringLiteral(
        "QFrame#rpCard { background:%1; border:1px solid %2; border-radius:%3px; }")
        .arg(Theme::BG_MAIN, Theme::BORDER_DEFAULT)
        .arg(Theme::BORDER_RADIUS));
    return frame;
}

QPushButton* compactButton(const QString& text, bool primary = false)
{
    auto* button = new QPushButton(text);
    button->setMinimumHeight(26);
    button->setCursor(Qt::PointingHandCursor);
    button->setStyleSheet(primary ? Theme::primaryButtonStyle()
                                  : Theme::secondaryButtonCompactStyle());
    return button;
}

QString distanceText(double v)
{
    return QString::number(v, 'f', 1);
}

} // namespace

RobotProgramPanel::RobotProgramPanel(QWidget* parent) : QWidget(parent)
{
    buildUi();
    updatePose(m_state);
    refreshActions();
}

void RobotProgramPanel::buildUi()
{
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(8);

    // ── 顶部状态条 ────────────────────────────────────────────────
    auto* header = new QFrame;
    header->setStyleSheet(QStringLiteral(
        "QFrame { background:%1; border:1px solid %2; border-radius:%3px; }")
        .arg(Theme::BG_CARD, Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));
    auto* headerLayout = new QHBoxLayout(header);
    headerLayout->setContentsMargins(10, 8, 10, 8);
    headerLayout->setSpacing(8);

    m_statusDot = new QLabel;
    m_statusDot->setFixedSize(10, 10);
    m_statusDot->setStyleSheet(QStringLiteral(
        "background:%1;border-radius:5px;").arg(Theme::ERROR));
    headerLayout->addWidget(m_statusDot);

    auto* statusBox = new QVBoxLayout;
    statusBox->setSpacing(0);
    m_statusLabel = new QLabel(QStringLiteral("未连接"));
    m_statusLabel->setStyleSheet(QStringLiteral(
        "font-size:%1px;font-weight:600;color:%2;")
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_TITLE));
    m_backendLabel = new QLabel(QStringLiteral("仿真后端 · 不控制真机"));
    m_backendLabel->setStyleSheet(QStringLiteral(
        "font-size:%1px;color:%2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    statusBox->addWidget(m_statusLabel);
    statusBox->addWidget(m_backendLabel);
    headerLayout->addLayout(statusBox);
    headerLayout->addStretch(1);

    m_connectButton = compactButton(QStringLiteral("连接"));
    m_connectButton->setObjectName(QStringLiteral("robot_program_connect"));
    m_enableButton = compactButton(QStringLiteral("使能"));
    m_enableButton->setObjectName(QStringLiteral("robot_program_enable"));
    m_enableButton->setCheckable(true);
    m_stopButton = compactButton(QStringLiteral("停止"), true);
    m_stopButton->setObjectName(QStringLiteral("robot_program_stop"));
    m_stopButton->setStyleSheet(Theme::dangerButtonStyle());
    headerLayout->addWidget(m_connectButton);
    headerLayout->addWidget(m_enableButton);
    headerLayout->addWidget(m_stopButton);
    root->addWidget(header);

    // ── 地址行（仿真后端不访问；真机后端接入后使用）──────────────
    auto* addressRow = new QHBoxLayout;
    addressRow->setSpacing(6);
    auto* addressLabel = new QLabel(QStringLiteral("地址"));
    addressLabel->setStyleSheet(QStringLiteral("color:%1;").arg(Theme::TEXT_HINT));
    m_hostEdit = new QLineEdit(QStringLiteral("192.168.0.38"));
    m_hostEdit->setObjectName(QStringLiteral("robot_program_host"));
    m_hostEdit->setMinimumHeight(26);
    m_hostEdit->setStyleSheet(Theme::inputStyle());
    m_portSpin = new QSpinBox;
    m_portSpin->setRange(1, 65535);
    m_portSpin->setValue(30001);
    m_portSpin->setMinimumHeight(26);
    m_portSpin->setMaximumWidth(90);
    m_portSpin->setStyleSheet(Theme::spinBoxStyle());
    addressRow->addWidget(addressLabel);
    addressRow->addWidget(m_hostEdit, 1);
    addressRow->addWidget(m_portSpin);
    auto* addressHint = new QLabel(QStringLiteral("仿真不访问该地址"));
    addressHint->setStyleSheet(QStringLiteral(
        "font-size:%1px;color:%2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    addressRow->addWidget(addressHint);
    root->addLayout(addressRow);

    // ── 主体：左程序 / 右手动控制 ─────────────────────────────────
    auto* body = new QHBoxLayout;
    body->setSpacing(10);

    auto* programCard = cardFrame();
    auto* programLayout = new QVBoxLayout(programCard);
    programLayout->setContentsMargins(8, 8, 8, 8);
    programLayout->setSpacing(6);

    auto* programHeader = new QHBoxLayout;
    programHeader->addWidget(sectionTitle(QStringLiteral("程序节点")));
    programHeader->addStretch(1);
    m_countLabel = new QLabel(QStringLiteral("0 个"));
    m_countLabel->setStyleSheet(QStringLiteral(
        "font-size:%1px;color:%2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    programHeader->addWidget(m_countLabel);
    programLayout->addLayout(programHeader);

    m_nodeList = new QListWidget;
    m_nodeList->setObjectName(QStringLiteral("robot_program_nodes"));
    m_nodeList->setWordWrap(true);
    m_nodeList->setSelectionMode(QAbstractItemView::SingleSelection);
    m_nodeList->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_nodeList->setStyleSheet(QStringLiteral(
        "QListWidget { background:%1; border:1px solid %2; border-radius:%3px;"
        " font-size:%4px; color:%5; }"
        "QListWidget::item { padding:5px 6px; border-bottom:1px solid %6; }"
        "QListWidget::item:selected { background:%7; color:#FFFFFF; }")
        .arg(Theme::BG_MAIN, Theme::BORDER_DEFAULT)
        .arg(Theme::BORDER_RADIUS)
        .arg(Theme::FONT_HINT)
        .arg(Theme::TEXT_BODY)
        .arg(Theme::withAlpha(Theme::BORDER_DEFAULT, 0.6))
        .arg(Theme::PRIMARY));
    programLayout->addWidget(m_nodeList, 1);

    auto* addRow = new QHBoxLayout;
    addRow->setSpacing(4);
    m_addMoveButton = compactButton(QStringLiteral("+ 移动"));
    m_addMoveButton->setObjectName(QStringLiteral("robot_program_add_move"));
    m_addPhotoButton = compactButton(QStringLiteral("+ 拍照"));
    m_addPhotoButton->setObjectName(QStringLiteral("robot_program_add_photo"));
    m_addPhotoButton->setToolTip(QStringLiteral(
        "拍照节点会读取「机器人通信」页已连接机器人的实时位姿；"
        "请先在该页连接机器人，否则节点会停下并提示原因。"));
    m_addWaitButton = compactButton(QStringLiteral("+ 等待"));
    m_addWaitButton->setObjectName(QStringLiteral("robot_program_add_wait"));
    m_waitSeconds = new QDoubleSpinBox;
    m_waitSeconds->setRange(0.0, 3600.0);
    m_waitSeconds->setDecimals(1);
    m_waitSeconds->setValue(1.0);
    m_waitSeconds->setSuffix(QStringLiteral(" s"));
    m_waitSeconds->setMaximumWidth(72);
    m_waitSeconds->setStyleSheet(Theme::spinBoxStyle());
    addRow->addWidget(m_addMoveButton);
    addRow->addWidget(m_addPhotoButton);
    addRow->addWidget(m_addWaitButton);
    addRow->addWidget(m_waitSeconds);
    programLayout->addLayout(addRow);

    auto* editRow = new QHBoxLayout;
    editRow->setSpacing(4);
    m_updateTargetButton = compactButton(QStringLiteral("用当前位姿更新所选"));
    m_updateTargetButton->setObjectName(QStringLiteral("robot_program_update_target"));
    m_deleteButton = compactButton(QStringLiteral("删除"));
    m_deleteButton->setObjectName(QStringLiteral("robot_program_delete"));
    editRow->addWidget(m_updateTargetButton, 1);
    editRow->addWidget(m_deleteButton);
    programLayout->addLayout(editRow);

    auto* runRow = new QHBoxLayout;
    runRow->setSpacing(4);
    m_runSelectedButton = compactButton(QStringLiteral("运行所选"));
    m_runSelectedButton->setObjectName(QStringLiteral("robot_program_run_one"));
    m_runAllButton = compactButton(QStringLiteral("运行全部"), true);
    m_runAllButton->setObjectName(QStringLiteral("robot_program_run_all"));
    runRow->addWidget(m_runSelectedButton, 1);
    runRow->addWidget(m_runAllButton, 1);
    programLayout->addLayout(runRow);

    programCard->setMinimumWidth(235);
    programCard->setMaximumWidth(275);
    body->addWidget(programCard);

    auto* controlCard = cardFrame();
    auto* controlLayout = new QVBoxLayout(controlCard);
    controlLayout->setContentsMargins(8, 8, 8, 8);
    controlLayout->setSpacing(6);
    controlLayout->addWidget(sectionTitle(QStringLiteral("手动控制")));

    auto* modeRow = new QHBoxLayout;
    modeRow->setSpacing(4);
    auto* cartButton = compactButton(QStringLiteral("笛卡尔"));
    auto* jointButton = compactButton(QStringLiteral("关节"));
    cartButton->setObjectName(QStringLiteral("robot_program_mode_cart"));
    jointButton->setObjectName(QStringLiteral("robot_program_mode_joint"));
    for (auto* b : { cartButton, jointButton }) {
        b->setCheckable(true);
        b->setStyleSheet(Theme::toggleUnselectedStyle());
    }
    cartButton->setChecked(true);
    m_modeGroup = new QButtonGroup(this);
    m_modeGroup->addButton(cartButton, 0);
    m_modeGroup->addButton(jointButton, 1);
    modeRow->addWidget(cartButton);
    modeRow->addWidget(jointButton);
    modeRow->addStretch(1);
    controlLayout->addLayout(modeRow);

    auto* speedRow = new QHBoxLayout;
    speedRow->setSpacing(6);
    auto* speedTitle = new QLabel(QStringLiteral("速度"));
    speedTitle->setStyleSheet(QStringLiteral("color:%1;").arg(Theme::TEXT_HINT));
    m_speedSlider = new QSlider(Qt::Horizontal);
    m_speedSlider->setObjectName(QStringLiteral("robot_program_speed"));
    m_speedSlider->setRange(1, 100);
    m_speedSlider->setValue(30);
    m_speedLabel = new QLabel(QStringLiteral("30%"));
    m_speedLabel->setMinimumWidth(36);
    m_speedLabel->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
    m_speedLabel->setStyleSheet(QStringLiteral("color:%1;").arg(Theme::TEXT_BODY));
    speedRow->addWidget(speedTitle);
    speedRow->addWidget(m_speedSlider, 1);
    speedRow->addWidget(m_speedLabel);
    controlLayout->addLayout(speedRow);

    auto* stepRow = new QHBoxLayout;
    stepRow->setSpacing(6);
    auto* stepTitle = new QLabel(QStringLiteral("步长"));
    stepTitle->setStyleSheet(QStringLiteral("color:%1;").arg(Theme::TEXT_HINT));
    m_stepSpin = new QDoubleSpinBox;
    m_stepSpin->setObjectName(QStringLiteral("robot_program_step"));
    m_stepSpin->setRange(JogPolicy::MIN_STEP, JogPolicy::MAX_STEP);
    m_stepSpin->setDecimals(2);
    m_stepSpin->setValue(1.0);
    m_stepSpin->setMinimumHeight(26);
    m_stepSpin->setStyleSheet(Theme::spinBoxStyle());
    stepRow->addWidget(stepTitle);
    stepRow->addWidget(m_stepSpin, 1);
    auto* stepUnit = new QLabel(QStringLiteral("mm / 度"));
    stepUnit->setStyleSheet(QStringLiteral(
        "font-size:%1px;color:%2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    stepRow->addWidget(stepUnit);
    controlLayout->addLayout(stepRow);

    m_jogStack = new QStackedWidget;

    // 笛卡尔页：6 行，每行 [轴] [当前值] [-] [+]
    auto* cartPage = new QWidget;
    auto* cartGrid = new QGridLayout(cartPage);
    cartGrid->setContentsMargins(0, 4, 0, 0);
    cartGrid->setHorizontalSpacing(4);
    cartGrid->setVerticalSpacing(4);
    const char* cartNames[6] = { "X", "Y", "Z", "RX", "RY", "RZ" };
    for (int i = 0; i < 6; ++i) {
        auto* name = new QLabel(QString::fromLatin1(cartNames[i]));
        name->setMinimumWidth(24);
        name->setStyleSheet(QStringLiteral(
            "font-weight:600;color:%1;").arg(Theme::TEXT_BODY));
        m_poseValueLabels[i] = new QLabel(QStringLiteral("0.0"));
        m_poseValueLabels[i]->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
        m_poseValueLabels[i]->setStyleSheet(QStringLiteral(
            "color:%1;font-family:Consolas;").arg(Theme::TEXT_TITLE));
        auto* minus = compactButton(QStringLiteral("-"));
        auto* plus = compactButton(QStringLiteral("+"));
        minus->setFixedWidth(28);
        plus->setFixedWidth(28);
        minus->setStyleSheet(Theme::secondaryButtonCompactStyle());
        plus->setStyleSheet(Theme::secondaryButtonCompactStyle());
        const int axis = i;
        connect(minus, &QPushButton::clicked, this,
                [this, axis]() { onJog(axis, -1); });
        connect(plus, &QPushButton::clicked, this,
                [this, axis]() { onJog(axis, +1); });
        m_jogButtons.push_back(minus);
        m_jogButtons.push_back(plus);
        cartGrid->addWidget(name, i, 0);
        cartGrid->addWidget(m_poseValueLabels[i], i, 1);
        cartGrid->addWidget(minus, i, 2);
        cartGrid->addWidget(plus, i, 3);
    }
    cartGrid->setColumnStretch(1, 1);
    m_jogStack->addWidget(cartPage);

    // 关节页：6 行，每行 [J] [当前值] [滑杆] [-] [+]
    auto* jointPage = new QWidget;
    auto* jointGrid = new QGridLayout(jointPage);
    jointGrid->setContentsMargins(0, 4, 0, 0);
    jointGrid->setHorizontalSpacing(4);
    jointGrid->setVerticalSpacing(4);
    for (int i = 0; i < 6; ++i) {
        auto* name = new QLabel(QStringLiteral("J%1").arg(i + 1));
        name->setMinimumWidth(22);
        name->setStyleSheet(QStringLiteral(
            "font-weight:600;color:%1;").arg(Theme::TEXT_BODY));
        auto* value = new QLabel(QStringLiteral("0.0"));
        value->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
        value->setMinimumWidth(46);
        value->setStyleSheet(QStringLiteral(
            "color:%1;font-family:Consolas;").arg(Theme::TEXT_TITLE));
        auto* slider = new QSlider(Qt::Horizontal);
        slider->setRange(-360, 360);
        slider->setValue(0);
        auto* minus = compactButton(QStringLiteral("-"));
        auto* plus = compactButton(QStringLiteral("+"));
        minus->setFixedWidth(28);
        plus->setFixedWidth(28);
        const int axis = i;
        connect(minus, &QPushButton::clicked, this,
                [this, axis]() { onJog(axis, -1); });
        connect(plus, &QPushButton::clicked, this,
                [this, axis]() { onJog(axis, +1); });
        connect(slider, &QSlider::sliderReleased, this, [this, axis, slider]() {
            onJointSliderReleased(axis, slider->value());
        });
        m_jogButtons.push_back(minus);
        m_jogButtons.push_back(plus);
        m_jointSliders.push_back(slider);
        jointGrid->addWidget(name, i, 0);
        jointGrid->addWidget(value, i, 1);
        jointGrid->addWidget(slider, i, 2);
        jointGrid->addWidget(minus, i, 3);
        jointGrid->addWidget(plus, i, 4);
        // 关节值标签单独存：m_poseValueLabels 只给笛卡尔页。
        m_jointValueLabels.push_back(value);
    }
    jointGrid->setColumnStretch(2, 1);
    m_jogStack->addWidget(jointPage);
    controlLayout->addWidget(m_jogStack, 1);

    m_hintLabel = new QLabel;
    m_hintLabel->setWordWrap(true);
    m_hintLabel->setStyleSheet(QStringLiteral(
        "font-size:%1px;color:%2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    controlLayout->addWidget(m_hintLabel);

    body->addWidget(controlCard, 1);
    root->addLayout(body, 1);

    // ── 连接信号（全在 UI 线程）───────────────────────────────────
    connect(m_connectButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onConnectClicked);
    connect(m_enableButton, &QPushButton::toggled,
            this, &RobotProgramPanel::onEnableToggled);
    connect(m_stopButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onStopClicked);
    connect(m_addMoveButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onAddMove);
    connect(m_addPhotoButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onAddPhoto);
    connect(m_addWaitButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onAddWait);
    connect(m_deleteButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onDeleteNode);
    connect(m_updateTargetButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onUpdateTarget);
    connect(m_runSelectedButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onRunSelected);
    connect(m_runAllButton, &QPushButton::clicked,
            this, &RobotProgramPanel::onRunAll);
    connect(m_nodeList, &QListWidget::currentRowChanged,
            this, [this](int) { refreshSelection(); });
    connect(m_modeGroup, QOverload<int>::of(&QButtonGroup::buttonClicked),
            this, &RobotProgramPanel::onModeChanged);
    connect(m_speedSlider, &QSlider::valueChanged, this, [this](int v) {
        m_speedLabel->setText(QStringLiteral("%1%").arg(v));
        if (m_controller)
            m_controller->setJogSpeed(v);
    });

    onModeChanged(0);
}

void RobotProgramPanel::setController(RobotProgramController* controller)
{
    if (m_controller == controller)
        return;
    if (m_controller)
        QObject::disconnect(m_controller, nullptr, this, nullptr);
    m_controller = controller;
    if (!m_controller) {
        refreshActions();
        return;
    }
    bindController();
}

void RobotProgramPanel::bindController()
{
    m_backendLabel->setText(
        QStringLiteral("%1后端 · %2")
            .arg(m_controller->backend()->name(),
                 m_controller->backend()->isSimulated()
                     ? QStringLiteral("不控制真机")
                     : QStringLiteral("真机")));
    m_controller->setJogSpeed(m_speedSlider->value());

    connect(m_controller, &RobotProgramController::connectedChanged,
            this, &RobotProgramPanel::setConnected);
    connect(m_controller, &RobotProgramController::enabledChanged,
            this, &RobotProgramPanel::setEnabled);
    connect(m_controller, &RobotProgramController::poseUpdated,
            this, &RobotProgramPanel::updatePose);
    connect(m_controller, &RobotProgramController::statusMessage,
            this, [this](const QString& text, bool error) {
                setStatus(text, error);
                log(text, error);
            });
    connect(m_controller, &RobotProgramController::programChanged,
            this, &RobotProgramPanel::refreshNodes);
    connect(m_controller, &RobotProgramController::runnerStateChanged,
            this, &RobotProgramPanel::onRunnerState);
    connect(m_controller, &RobotProgramController::nodeStarted,
            this, [this](int index) {
                const auto& nodes = m_controller->program().nodes;
                if (index >= 0 && index < static_cast<int>(nodes.size()))
                    log(QStringLiteral("执行第 %1 个节点：%2")
                            .arg(index + 1)
                            .arg(RobotProgram::displayTitle(
                                nodes[static_cast<std::size_t>(index)].payload)));
                refreshNodes();
            });
    connect(m_controller, &RobotProgramController::nodeFinished,
            this, [this](int index, bool ok, const QString& error) {
                if (ok) {
                    log(QStringLiteral("第 %1 个节点完成").arg(index + 1));
                } else {
                    setStatus(QStringLiteral("第 %1 个节点失败：%2")
                                  .arg(index + 1).arg(error), true);
                    log(QStringLiteral("第 %1 个节点失败：%2")
                            .arg(index + 1).arg(error), true);
                }
            });
    connect(m_controller, &RobotProgramController::runFinished,
            this, [this](bool ok, const QString& error) {
                if (ok) {
                    setStatus(QStringLiteral("程序运行完成"), false);
                    log(QStringLiteral("程序运行完成"));
                } else if (error != QStringLiteral("已停止")) {
                    setStatus(QStringLiteral("程序运行失败：%1").arg(error), true);
                    log(QStringLiteral("程序运行失败：%1").arg(error), true);
                } else {
                    setStatus(QStringLiteral("已停止"), false);
                }
                refreshActions();
            });
    connect(m_controller, &RobotProgramController::photoStarted,
            this, [this]() {
                setStatus(QStringLiteral("拍照节点：采集链路运行中…"), false);
            });

    m_state = m_controller->backend()->state();
    updatePose(m_state);
    setConnected(m_controller->backend()->isConnected());
    setEnabled(m_controller->backend()->isEnabled());
    onRunnerState(m_controller->runner()->state());
    refreshNodes();
}

void RobotProgramPanel::refreshNodes()
{
    if (!m_controller) {
        m_nodeList->clear();
        m_countLabel->setText(QStringLiteral("0 个"));
        refreshSelection();
        return;
    }
    const int keepRow = m_nodeList->currentRow();
    const QString keepId = m_nodeList->currentItem()
        ? m_nodeList->currentItem()->data(Qt::UserRole).toString()
        : QString();

    m_nodeList->clear();
    const auto& nodes = m_controller->program().nodes;
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        const auto& node = nodes[i];
        const QString text =
            QStringLiteral("%1  %2  %3\n      %4")
                .arg(static_cast<int>(i) + 1, 2, 10, QLatin1Char('0'))
                .arg(RobotProgram::kindTag(RobotProgram::kindOf(node.payload)),
                     RobotProgram::displayTitle(node.payload),
                     RobotProgram::displayDetail(node.payload));
        auto* item = new QListWidgetItem(text, m_nodeList);
        item->setData(Qt::UserRole, node.id);
        item->setSizeHint(QSize(0, 44));
        item->setToolTip(RobotProgram::displayDetail(node.payload));
    }

    m_countLabel->setText(QStringLiteral("%1 个")
                              .arg(static_cast<int>(nodes.size())));
    int restored = -1;
    if (!keepId.isEmpty()) {
        for (int i = 0; i < m_nodeList->count(); ++i) {
            if (m_nodeList->item(i)->data(Qt::UserRole).toString() == keepId) {
                restored = i;
                break;
            }
        }
    }
    if (restored >= 0)
        m_nodeList->setCurrentRow(restored);
    else if (keepRow >= 0 && keepRow < m_nodeList->count())
        m_nodeList->setCurrentRow(keepRow);
    else if (m_nodeList->count() > 0)
        m_nodeList->setCurrentRow(m_nodeList->count() - 1);
    refreshSelection();
    refreshActions();
}

void RobotProgramPanel::refreshSelection()
{
    const int row = m_nodeList->currentRow();
    const bool has = m_controller && row >= 0;
    bool isMove = false;
    if (has) {
        const auto& nodes = m_controller->program().nodes;
        if (row < static_cast<int>(nodes.size())) {
            isMove = std::holds_alternative<RobotProgram::MoveNode>(
                nodes[static_cast<std::size_t>(row)].payload);
        }
    }
    m_deleteButton->setEnabled(has && !m_running);
    m_updateTargetButton->setEnabled(has && isMove && !m_running && m_connected);
    m_runSelectedButton->setEnabled(has && !m_running);
}

void RobotProgramPanel::refreshActions()
{
    const bool bound = m_controller != nullptr;
    const bool editable = bound && !m_running;

    m_addMoveButton->setEnabled(editable);
    m_addPhotoButton->setEnabled(editable);
    m_addWaitButton->setEnabled(editable);
    m_waitSeconds->setEnabled(editable);
    m_runAllButton->setEnabled(
        editable && !m_controller->program().nodes.empty());

    m_connectButton->setText(m_connected ? QStringLiteral("断开")
                                         : QStringLiteral("连接"));
    m_connectButton->setEnabled(bound);
    {
        const QSignalBlocker blocker(m_enableButton);
        m_enableButton->setChecked(m_enabled);
    }
    m_enableButton->setText(m_enabled ? QStringLiteral("已使能")
                                      : QStringLiteral("使能"));
    m_enableButton->setEnabled(bound && m_connected && !m_running);
    m_stopButton->setEnabled(bound && (m_running || m_connected));

    const bool jogEnabled = bound && m_connected && m_enabled && !m_running;
    for (auto* b : m_jogButtons)
        b->setEnabled(jogEnabled);
    for (auto* s : m_jointSliders)
        s->setEnabled(jogEnabled);
    m_speedSlider->setEnabled(!m_running);
    m_stepSpin->setEnabled(!m_running);
    if (m_modeGroup) {
        for (auto* b : m_modeGroup->buttons())
            b->setEnabled(!m_running);
    }

    if (m_hintLabel) {
        if (!bound)
            m_hintLabel->setText(QStringLiteral("控制端未接入"));
        else if (m_running)
            m_hintLabel->setText(QStringLiteral("程序运行中：点动与编辑已锁定"));
        else if (!m_connected)
            m_hintLabel->setText(QStringLiteral("先点「连接」；当前是仿真后端，不会动真机"));
        else if (!m_enabled)
            m_hintLabel->setText(QStringLiteral("已连接，点「使能」后可手动移动"));
        else
            m_hintLabel->setText(
                QStringLiteral("就绪：可点动，或把当前位姿加入程序后运行"));
    }
    refreshSelection();
}

void RobotProgramPanel::updatePose(const RobotMotion::State& state)
{
    m_state = state;
    for (int i = 0; i < 6; ++i) {
        if (m_poseValueLabels[i]) {
            m_poseValueLabels[i]->setText(
                distanceText(state.cart[static_cast<std::size_t>(i)]));
        }
    }
    for (int i = 0; i < m_jointValueLabels.size(); ++i) {
        const double v = state.joint[static_cast<std::size_t>(i)];
        m_jointValueLabels[i]->setText(distanceText(v));
        if (i < m_jointSliders.size() && !m_jointSliders[i]->isSliderDown()) {
            const QSignalBlocker blocker(m_jointSliders[i]);
            m_jointSliders[i]->setValue(
                std::clamp(static_cast<int>(std::lround(v)), -360, 360));
        }
    }
}

void RobotProgramPanel::setConnected(bool connected)
{
    m_connected = connected;
    m_statusDot->setStyleSheet(
        QStringLiteral("background:%1;border-radius:5px;")
            .arg(connected ? Theme::SUCCESS : Theme::ERROR));
    if (!connected)
        m_enabled = false;
    setStatus(connected ? QStringLiteral("已连接")
                        : QStringLiteral("未连接"), false);
    refreshActions();
}

void RobotProgramPanel::setEnabled(bool enabled)
{
    m_enabled = enabled;
    refreshActions();
    if (m_connected) {
        setStatus(enabled ? QStringLiteral("已连接 · 已使能")
                          : QStringLiteral("已连接 · 未使能"), false);
    }
}

void RobotProgramPanel::onRunnerState(ProgramRunner::State state)
{
    m_running = state != ProgramRunner::State::Idle;
    refreshActions();
    refreshNodes();
    if (state == ProgramRunner::State::Running)
        setStatus(QStringLiteral("程序运行中…"), false);
}

void RobotProgramPanel::setStatus(const QString& text, bool error)
{
    if (!m_statusLabel)
        return;
    m_statusLabel->setText(text);
    if (error) {
        m_statusDot->setStyleSheet(
            QStringLiteral("background:%1;border-radius:5px;").arg(Theme::ERROR));
    } else if (m_connected) {
        m_statusDot->setStyleSheet(
            QStringLiteral("background:%1;border-radius:5px;").arg(Theme::SUCCESS));
    }
}

void RobotProgramPanel::log(const QString& text, bool error)
{
    emit logMessage(QStringLiteral("[机器人控制台] %1").arg(text));
    Q_UNUSED(error);
}

void RobotProgramPanel::onConnectClicked()
{
    if (!m_controller)
        return;
    if (m_connected) {
        m_controller->disconnectDevice();
        return;
    }
    const QString host = m_hostEdit->text().trimmed();
    if (host.isEmpty()) {
        setStatus(QStringLiteral("请先填写机器人地址"), true);
        return;
    }
    m_controller->connectDevice(host, static_cast<quint16>(m_portSpin->value()));
}

void RobotProgramPanel::onEnableToggled(bool on)
{
    if (!m_controller)
        return;
    m_controller->setEnabled(on);
    // 后端拒绝（未连接）时不会发 enabledChanged，把按钮拨回去。
    if (on && !m_controller->backend()->isEnabled()) {
        const QSignalBlocker blocker(m_enableButton);
        m_enableButton->setChecked(false);
    }
}

void RobotProgramPanel::onStopClicked()
{
    if (!m_controller)
        return;
    m_controller->stop();
    setStatus(QStringLiteral("停止指令已发出"), false);
}

void RobotProgramPanel::onAddMove()
{
    if (!m_controller)
        return;
    RobotProgram::MoveNode move;
    move.space = m_jointMode ? RobotProgram::MoveNode::Space::Joint
                             : RobotProgram::MoveNode::Space::Cartesian;
    move.target = m_jointMode ? m_state.joint : m_state.cart;
    move.speedPct = m_speedSlider->value();
    m_controller->addNode(move);
    if (m_nodeList->count() > 0)
        m_nodeList->setCurrentRow(m_nodeList->count() - 1);
}

void RobotProgramPanel::onAddPhoto()
{
    if (!m_controller)
        return;
    RobotProgram::PhotoNode photo;
    photo.autoSave = true;
    m_controller->addNode(photo);
    if (m_nodeList->count() > 0)
        m_nodeList->setCurrentRow(m_nodeList->count() - 1);
}

void RobotProgramPanel::onAddWait()
{
    if (!m_controller)
        return;
    RobotProgram::WaitNode wait;
    wait.seconds = m_waitSeconds->value();
    m_controller->addNode(wait);
    if (m_nodeList->count() > 0)
        m_nodeList->setCurrentRow(m_nodeList->count() - 1);
}

void RobotProgramPanel::onDeleteNode()
{
    if (!m_controller)
        return;
    const int row = m_nodeList->currentRow();
    if (row < 0)
        return;
    m_controller->removeNode(row);
    if (m_nodeList->count() > 0)
        m_nodeList->setCurrentRow(std::min(row, m_nodeList->count() - 1));
}

void RobotProgramPanel::onUpdateTarget()
{
    if (!m_controller)
        return;
    const int row = m_nodeList->currentRow();
    if (row < 0)
        return;
    const auto& nodes = m_controller->program().nodes;
    if (row >= static_cast<int>(nodes.size()))
        return;
    const auto* move = std::get_if<RobotProgram::MoveNode>(
        &nodes[static_cast<std::size_t>(row)].payload);
    if (!move)
        return;
    const RobotMotion::Pose target = move->space == RobotProgram::MoveNode::Space::Joint
        ? m_state.joint : m_state.cart;
    if (m_controller->updateMoveTarget(row, target)) {
        log(QStringLiteral("已用当前位姿更新第 %1 个节点").arg(row + 1));
        setStatus(QStringLiteral("节点已更新"), false);
    }
}

void RobotProgramPanel::onRunSelected()
{
    if (!m_controller)
        return;
    m_controller->runOne(m_nodeList->currentRow());
}

void RobotProgramPanel::onRunAll()
{
    if (!m_controller)
        return;
    m_controller->runAll();
}

void RobotProgramPanel::onJog(int axis, int direction)
{
    if (!m_controller)
        return;
    const double delta = m_stepSpin->value() * direction;
    m_controller->jog(axis, delta, m_jointMode);
}

void RobotProgramPanel::onJointSliderReleased(int axis, int value)
{
    if (!m_controller)
        return;
    m_controller->moveJointAxisTo(axis, static_cast<double>(value));
}

void RobotProgramPanel::onModeChanged(int id)
{
    m_jointMode = (id == 1);
    m_jogStack->setCurrentIndex(m_jointMode ? 1 : 0);
    for (auto* b : m_modeGroup->buttons()) {
        b->setStyleSheet((m_modeGroup->id(b) == id)
                             ? Theme::toggleSelectedStyle()
                             : Theme::toggleUnselectedStyle());
    }
    refreshSelection();
}
