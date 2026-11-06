#include "ui/ActionButtons.h"
#include "ui/Theme.h"
#include <QColor>
#include <QHBoxLayout>
#include <QSize>
#include <QTimer>

ActionButtons::ActionButtons(QWidget* parent)
    : QWidget(parent)
    , m_busyTimeout(new QTimer(this))
{
    // 行高 5 行（40px），按钮间距 1 行（8px）：8 个按钮在 8 列内容区里放得下。
    setMinimumHeight(Theme::Grid::ActionH + Theme::Grid::Row);
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addStretch();
    layout->setSpacing(Theme::Grid::Row);

    auto makeBtn = [&](const QString& text, const QString& style) -> QPushButton* {
        auto* btn = new QPushButton(text, this);
        btn->setFixedHeight(Theme::Grid::ActionH);
        btn->setStyleSheet(style);
        btn->setMinimumWidth(80);
        btn->setIconSize(QSize(Theme::Grid::IconSm, Theme::Grid::IconSm));
        layout->addWidget(btn);
        return btn;
    };
    const QColor bodyColor(QString::fromLatin1(Theme::TEXT_BODY));

    // Preview button (replaces Load Test, to left of Capture)
    m_btnPreview = makeBtn(QStringLiteral("预览"), Theme::secondaryButtonStyle());
    m_btnPreview->setEnabled(false);
    m_btnCapture = makeBtn(QStringLiteral("拍照"),  Theme::secondaryButtonStyle());
    m_btnDetect  = makeBtn(QStringLiteral("识别"),  Theme::secondaryButtonStyle());
    m_btnSave    = makeBtn(QStringLiteral("保存"),  Theme::secondaryButtonStyle());
    m_btnCalc    = makeBtn(QStringLiteral("计算"),  Theme::secondaryButtonStyle());
    m_btnUndo    = makeBtn(QStringLiteral("撤销"),  Theme::secondaryButtonStyle());
    m_btnCalc->setEnabled(false);

    m_btnPreview->setIcon(Theme::icon(QStringLiteral("eye"), bodyColor, Theme::Grid::IconSm));
    m_btnCapture->setIcon(Theme::icon(QStringLiteral("camera"), bodyColor, Theme::Grid::IconSm));
    m_btnDetect->setIcon(Theme::icon(QStringLiteral("scan"), bodyColor, Theme::Grid::IconSm));
    m_btnSave->setIcon(Theme::icon(QStringLiteral("save"), bodyColor, Theme::Grid::IconSm));
    m_btnCalc->setIcon(Theme::icon(QStringLiteral("calculator"), bodyColor, Theme::Grid::IconSm));
    m_btnUndo->setIcon(Theme::icon(QStringLiteral("undo"), bodyColor, Theme::Grid::IconSm));

    // Robot read buttons — live in the same action row (same style/font), but
    // are hidden until a robot connection is established (see MainWindow).
    m_btnReadCapturePose = makeBtn(QStringLiteral("拍照位姿"), Theme::secondaryButtonCompactStyle());
    m_btnReadTouchPose   = makeBtn(QStringLiteral("戳点位姿"), Theme::secondaryButtonCompactStyle());
    m_btnReadCapturePose->setMinimumWidth(88);
    m_btnReadTouchPose->setMinimumWidth(88);
    m_btnReadCapturePose->setIcon(
        Theme::icon(QStringLiteral("crosshair"), bodyColor, Theme::Grid::IconSm));
    m_btnReadTouchPose->setIcon(
        Theme::icon(QStringLiteral("crosshair"), bodyColor, Theme::Grid::IconSm));
    m_btnReadCapturePose->setToolTip(QStringLiteral("读取机器人拍照位姿"));
    m_btnReadTouchPose->setToolTip(QStringLiteral("读取机器人戳点位姿"));
    m_btnReadCapturePose->hide();
    m_btnReadTouchPose->hide();

    layout->addStretch();

    connect(m_btnPreview, &QPushButton::clicked, this, [this]() {
        emit previewToggled(!m_previewActive);
    });
    connect(m_btnCapture, &QPushButton::clicked, this, &ActionButtons::captureClicked);
    connect(m_btnDetect,  &QPushButton::clicked, this, &ActionButtons::detectClicked);
    connect(m_btnSave,    &QPushButton::clicked, this, &ActionButtons::saveClicked);
    connect(m_btnCalc,    &QPushButton::clicked, this, &ActionButtons::calcClicked);
    connect(m_btnUndo,    &QPushButton::clicked, this, &ActionButtons::undoClicked);
    connect(m_btnReadCapturePose, &QPushButton::clicked, this, &ActionButtons::readCapturePoseClicked);
    connect(m_btnReadTouchPose,   &QPushButton::clicked, this, &ActionButtons::readTouchPoseClicked);
    // Quick actions: flash once while they execute (they are fast/synchronous).
    connect(m_btnSave, &QPushButton::clicked, this, [this]() { flash(m_btnSave); });
    connect(m_btnCalc, &QPushButton::clicked, this, [this]() { flash(m_btnCalc); });
    connect(m_btnUndo, &QPushButton::clicked, this, [this]() { flash(m_btnUndo); });

    m_busyTimeout->setSingleShot(true);
    connect(m_busyTimeout, &QTimer::timeout, this, [this]() {
        if (m_busy) {
            qWarning("ActionButtons: busy timeout — forcing clear");
            clearBusy();
        }
    });

    m_flashTimer = new QTimer(this);
    m_flashTimer->setSingleShot(true);
    connect(m_flashTimer, &QTimer::timeout, this, [this]() {
        if (m_flashButton) {
            applyBaseStyle(m_flashButton);
            restoreIcon(m_flashButton);
            m_flashButton = nullptr;
        }
    });
}

void ActionButtons::setCaptureEnabled(bool enabled)
{
    m_captureEnabled = enabled;
    applyEnabledStates();
}

QPushButton* ActionButtons::buttonFor(BusyTarget target) const
{
    switch (target) {
    case BusyTarget::Capture: return m_btnCapture;
    case BusyTarget::Detect:  return m_btnDetect;
    case BusyTarget::Save:    return m_btnSave;
    case BusyTarget::Undo:    return m_btnUndo;
    case BusyTarget::Preview: return m_btnPreview;
    case BusyTarget::Calc:    return m_btnCalc;
    }
    return nullptr;
}

void ActionButtons::setBusy(BusyTarget target, const QString& text)
{
    m_busy = true;
    m_busyTarget = target;
    if (auto* btn = buttonFor(target)) {
        btn->setText(text);
        btn->setStyleSheet(Theme::busyButtonStyle());
        setIconOnPrimary(btn);
    }
    for (auto* btn : {m_btnPreview, m_btnCapture, m_btnDetect, m_btnSave, m_btnCalc, m_btnUndo})
        btn->setEnabled(false);
    // Auto-clear stuck busy after 30s
    m_busyTimeout->start(30000);
}

void ActionButtons::clearBusy()
{
    m_busy = false;
    m_busyTimeout->stop();
    // Restore the default label of the button that showed the busy text.
    if (auto* btn = buttonFor(m_busyTarget)) {
        switch (m_busyTarget) {
        case BusyTarget::Capture: btn->setText(QStringLiteral("拍照")); break;
        case BusyTarget::Detect:  btn->setText(QStringLiteral("识别")); break;
        case BusyTarget::Save:    btn->setText(QStringLiteral("保存")); break;
        case BusyTarget::Undo:    btn->setText(QStringLiteral("撤销")); break;
        case BusyTarget::Preview: btn->setText(QStringLiteral("预览")); break;
        case BusyTarget::Calc:    btn->setText(QStringLiteral("计算")); break;
        }
        // Restore the button's normal look (preview keeps its active style).
        if (m_busyTarget == BusyTarget::Preview) {
            applyPreviewStyle();
        } else {
            applyBaseStyle(btn);
            restoreIcon(btn);
        }
    }
    applyEnabledStates();
}

void ActionButtons::applyEnabledStates()
{
    if (m_busy) return;
    m_btnDetect->setEnabled(m_detectEnabled);
    m_btnSave->setEnabled(m_saveEnabled);
    m_btnUndo->setEnabled(m_undoEnabled);
    m_btnCalc->setEnabled(m_calcEnabled);
    m_btnPreview->setEnabled(m_previewEnabled);
    m_btnCapture->setEnabled(m_captureEnabled);
}

void ActionButtons::setDetectEnabled(bool enabled) { m_detectEnabled = enabled; applyEnabledStates(); }
void ActionButtons::setSaveEnabled(bool enabled)   { m_saveEnabled = enabled;   applyEnabledStates(); }
void ActionButtons::setUndoEnabled(bool enabled)   { m_undoEnabled = enabled;   applyEnabledStates(); }
void ActionButtons::setCalcEnabled(bool enabled)   { m_calcEnabled = enabled;   applyEnabledStates(); }

void ActionButtons::setPreviewActive(bool active)
{
    m_previewActive = active;
    applyPreviewStyle();
}

void ActionButtons::applyPreviewStyle()
{
    if (m_previewActive) {
        m_btnPreview->setText(QStringLiteral("停止预览"));
        m_btnPreview->setIcon(
            Theme::icon(QStringLiteral("eye-off"), QColor(Qt::white), Theme::Grid::IconSm));
        m_btnPreview->setStyleSheet(QStringLiteral(R"(
            QPushButton { color: #FFF; background: %3; border: 1px solid %1;
                          border-radius: 8px; font-size: 14px; font-weight: 500; }
            QPushButton:hover { border-color: %2; color: #FFF; }
        )").arg(Theme::PRIMARY).arg(Theme::PRIMARY_HOVER)
           .arg(Theme::withAlpha(Theme::PRIMARY, 0.15)));
    } else {
        m_btnPreview->setText(QStringLiteral("预览"));
        m_btnPreview->setStyleSheet(Theme::secondaryButtonStyle());
        m_btnPreview->setIcon(
            Theme::icon(QStringLiteral("eye"),
                        QColor(QString::fromLatin1(Theme::TEXT_BODY)),
                        Theme::Grid::IconSm));
    }
}

void ActionButtons::applyBaseStyle(QPushButton* btn)
{
    btn->setStyleSheet(Theme::secondaryButtonStyle());
}

QString ActionButtons::iconNameFor(QPushButton* btn) const
{
    if (btn == m_btnPreview) return QStringLiteral("eye");
    if (btn == m_btnCapture) return QStringLiteral("camera");
    if (btn == m_btnDetect)  return QStringLiteral("scan");
    if (btn == m_btnSave)    return QStringLiteral("save");
    if (btn == m_btnCalc)    return QStringLiteral("calculator");
    if (btn == m_btnUndo)    return QStringLiteral("undo");
    if (btn == m_btnReadCapturePose || btn == m_btnReadTouchPose)
        return QStringLiteral("crosshair");
    return {};
}

// flash / busy 是主色（或半透明主色）底，深色图标会失去对比度，状态期间切白；
// 结束后 restoreIcon 按按钮身份还原正文色图标（预览激活态保持白）。
void ActionButtons::setIconOnPrimary(QPushButton* btn)
{
    const QString name = iconNameFor(btn);
    if (!name.isEmpty())
        btn->setIcon(Theme::icon(name, QColor(Qt::white), Theme::Grid::IconSm));
}

void ActionButtons::restoreIcon(QPushButton* btn)
{
    const QString name = iconNameFor(btn);
    if (name.isEmpty())
        return;
    if (btn == m_btnPreview && m_previewActive) {
        btn->setIcon(Theme::icon(QStringLiteral("eye-off"), QColor(Qt::white),
                                 Theme::Grid::IconSm));
        return;
    }
    btn->setIcon(Theme::icon(name, QColor(QString::fromLatin1(Theme::TEXT_BODY)),
                             Theme::Grid::IconSm));
}

void ActionButtons::flash(QPushButton* btn)
{
    // Ignore while a real busy state is active.
    if (m_busy) return;
    m_flashTimer->stop();
    m_flashButton = btn;
    btn->setStyleSheet(Theme::flashButtonStyle());
    setIconOnPrimary(btn);
    m_flashTimer->start(250);
}

void ActionButtons::setPreviewEnabled(bool enabled)
{
    m_previewEnabled = enabled;
    applyEnabledStates();
}

void ActionButtons::setReadCapturePoseVisible(bool visible)
{
    m_btnReadCapturePose->setVisible(visible);
}

void ActionButtons::setReadTouchPoseVisible(bool visible)
{
    m_btnReadTouchPose->setVisible(visible);
}
