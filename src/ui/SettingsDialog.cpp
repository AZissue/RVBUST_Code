#include "ui/SettingsDialog.h"

#include "logic/AppConfig.h"
#include "logic/DataManager.h"
#include "ui/Theme.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFormLayout>
#include <QGroupBox>
#include <QLabel>
#include <QCheckBox>
#include <QLineEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QDoubleSpinBox>
#include <QMessageBox>

namespace {

QString hintStyle()
{
    return QStringLiteral("color: %1; font-size: %2px;")
        .arg(Theme::TEXT_HINT).arg(Theme::FONT_BODY);
}

} // namespace

SettingsDialog::SettingsDialog(AppConfig& config, DataManager* data, QWidget* parent)
    : QDialog(parent)
    , m_config(&config)
    , m_data(data)
{
    setWindowTitle(QStringLiteral("设置"));
    // 用户反馈：内容一多，对话框跟着长高，确定按钮被任务栏挡住。 现在内容装在
    // 滚动区里，窗口本身可以任意缩放；最小值只保证还能看，不再随内容增长。
    setMinimumSize(520, 360);
    resize(600, 560);
    setWindowFlags(windowFlags() | Qt::WindowMinMaxButtonsHint);

    m_saveBaseDir = m_config->saveBaseDir();
    m_errorThreshold = m_config->caliboardErrorThreshold();

    auto* layout = new QVBoxLayout(this);

    // ── Scrollable content ──
    // Everything that can grow lives inside the scroll area; the button box below
    // stays outside it, so 「确定 / 取消」 is always on screen whatever the
    // content height or the desktop resolution.
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setStyleSheet(QStringLiteral("QScrollArea { background: transparent; }"));

    auto* content = new QWidget(scroll);
    auto* contentLayout = new QVBoxLayout(content);
    contentLayout->setContentsMargins(0, 0, 0, 0);
    scroll->setWidget(content);
    layout->addWidget(scroll, 1);

    // ── Save path ──
    auto* pathGroup = new QGroupBox(QStringLiteral("数据保存路径"), content);
    auto* pathLayout = new QHBoxLayout(pathGroup);
    m_pathEdit = new QLineEdit(m_saveBaseDir, pathGroup);
    auto* browseBtn = new QPushButton(QStringLiteral("浏览..."), pathGroup);
    pathLayout->addWidget(m_pathEdit, 1);
    pathLayout->addWidget(browseBtn);
    connect(browseBtn, &QPushButton::clicked, this, [this]() {
        const auto dir = QFileDialog::getExistingDirectory(
            this, QStringLiteral("选择保存目录"), m_saveBaseDir);
        if (!dir.isEmpty()) m_pathEdit->setText(dir);
    });
    contentLayout->addWidget(pathGroup);

    // 第 12 回合 任务 1: 这里原本是「拍摄参数」组（曝光/增益/来源/从相机读取）。
    // 现已整体删除——参数只在相机厂商自己的软件里调，本程序不下发任何值。
    auto* camHint = new QLabel(
        QStringLiteral("拍摄参数（曝光/增益/采集模式等）请在相机厂商自带的调试软件里设置，"
                       "本程序不下发任何参数，拍照与预览直接沿用相机当前设置。"
                       "每次连接和拍照的实际取值会写进操作日志（[CAM] 开头）。"),
        content);
    camHint->setStyleSheet(hintStyle());
    camHint->setWordWrap(true);
    contentLayout->addWidget(camHint);

    // ── Flow automation (任务 2): all three default off ──
    auto* autoGroup = new QGroupBox(QStringLiteral("流程自动化"), content);
    auto* autoLayout = new QVBoxLayout(autoGroup);
    m_autoDetectCheck = new QCheckBox(QStringLiteral("拍照成功后自动识别"), autoGroup);
    m_autoDetectCheck->setChecked(m_config->autoDetectAfterCapture());
    m_autoSaveCheck = new QCheckBox(
        QStringLiteral("识别成功后自动保存（必填项校验不通过时不保存）"), autoGroup);
    m_autoSaveCheck->setChecked(m_config->autoSaveAfterDetect());
    m_autoReadPoseCheck = new QCheckBox(
        QStringLiteral("拍照时自动读取机器人位姿（需已连接机器人）"), autoGroup);
    m_autoReadPoseCheck->setChecked(m_config->autoReadRobotPose());
    autoLayout->addWidget(m_autoDetectCheck);
    autoLayout->addWidget(m_autoSaveCheck);
    autoLayout->addWidget(m_autoReadPoseCheck);
    auto* autoHint = new QLabel(
        QStringLiteral("默认全部关闭。自动流程与手动按钮走同一套校验："
                       "质量告警不拦截，必填项缺失会跳过保存并写入操作日志。"),
        autoGroup);
    autoHint->setStyleSheet(hintStyle());
    autoHint->setWordWrap(true);
    autoLayout->addWidget(autoHint);
    contentLayout->addWidget(autoGroup);

    // ── Caliboard accuracy warning threshold (warnings never block saving) ──
    auto* qualityGroup = new QGroupBox(QStringLiteral("识别质量"), content);
    auto* qualityLayout = new QFormLayout(qualityGroup);
    m_thresholdSpin = new QDoubleSpinBox(qualityGroup);
    m_thresholdSpin->setRange(0.0, 100.0);
    m_thresholdSpin->setDecimals(1);
    m_thresholdSpin->setSingleStep(0.5);
    m_thresholdSpin->setSuffix(QStringLiteral(" %"));
    m_thresholdSpin->setValue(m_errorThreshold);
    qualityLayout->addRow(QStringLiteral("标定板误差告警阈值"), m_thresholdSpin);
    auto* qualityHint = new QLabel(
        QStringLiteral("仅影响\"检测误差较大\"提示，不拦截识别与保存"), qualityGroup);
    qualityHint->setStyleSheet(hintStyle());
    qualityLayout->addRow(QString(), qualityHint);
    contentLayout->addWidget(qualityGroup);

    // ── Camera maintenance (任务 3.4) ──
    auto* maintGroup = new QGroupBox(QStringLiteral("相机维护"), content);
    auto* maintLayout = new QFormLayout(maintGroup);

    m_idlePauseSpin = new QSpinBox(maintGroup);
    m_idlePauseSpin->setRange(0, 3600);
    m_idlePauseSpin->setSuffix(QStringLiteral(" 秒"));
    m_idlePauseSpin->setSpecialValueText(QStringLiteral("不暂停"));
    m_idlePauseSpin->setValue(m_config->idlePausePreviewSec());
    maintLayout->addRow(QStringLiteral("无操作后暂停预览"), m_idlePauseSpin);

    m_healthIntervalSpin = new QSpinBox(maintGroup);
    m_healthIntervalSpin->setRange(5, 600);
    m_healthIntervalSpin->setSuffix(QStringLiteral(" 秒"));
    m_healthIntervalSpin->setValue(m_config->healthCheckIntervalSec());
    maintLayout->addRow(QStringLiteral("相机在线检查间隔"), m_healthIntervalSpin);

    auto* releaseBtn = new QPushButton(QStringLiteral("释放相机"), maintGroup);
    maintLayout->addRow(QString(), releaseBtn);
    m_releaseStatus = new QLabel(
        QStringLiteral("用于\"相机被占用/状态异常\"时一键清理：立即断开并重新扫描设备。"),
        maintGroup);
    m_releaseStatus->setStyleSheet(hintStyle());
    m_releaseStatus->setWordWrap(true);
    maintLayout->addRow(QString(), m_releaseStatus);
    connect(releaseBtn, &QPushButton::clicked, this, [this]() {
        m_releaseStatus->setText(QStringLiteral("已请求释放相机并重新扫描，结果见操作日志。"));
        emit cameraReleaseRequested();
    });
    contentLayout->addWidget(maintGroup);

    // ── Backup restore ──
    auto* restoreGroup = new QGroupBox(QStringLiteral("数据恢复"), content);
    auto* restoreLayout = new QVBoxLayout(restoreGroup);
    auto* restoreBtn = new QPushButton(QStringLiteral("从备份恢复..."), restoreGroup);
    restoreLayout->addWidget(restoreBtn);
    m_restoreStatus = new QLabel(QStringLiteral("选择备份文件后将恢复会话记录"), restoreGroup);
    m_restoreStatus->setStyleSheet(hintStyle());
    m_restoreStatus->setWordWrap(true);
    restoreLayout->addWidget(m_restoreStatus);
    connect(restoreBtn, &QPushButton::clicked, this, &SettingsDialog::onRestoreBackup);
    contentLayout->addWidget(restoreGroup);

    contentLayout->addStretch();

    // ── Buttons (outside the scroll area, so they can never be scrolled away) ──
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);

    // Capture results on accept
    connect(buttons, &QDialogButtonBox::accepted, this, [this]() {
        m_saveBaseDir = m_pathEdit->text();
        m_errorThreshold = m_thresholdSpin ? static_cast<float>(m_thresholdSpin->value())
                                           : m_errorThreshold;
    });
}

// ── Getters ───────────────────────────────────────────────────────────

bool SettingsDialog::autoDetectAfterCapture() const
{
    return m_autoDetectCheck && m_autoDetectCheck->isChecked();
}

bool SettingsDialog::autoSaveAfterDetect() const
{
    return m_autoSaveCheck && m_autoSaveCheck->isChecked();
}

bool SettingsDialog::autoReadRobotPose() const
{
    return m_autoReadPoseCheck && m_autoReadPoseCheck->isChecked();
}

int SettingsDialog::idlePausePreviewSec() const
{
    return m_idlePauseSpin ? m_idlePauseSpin->value() : m_config->idlePausePreviewSec();
}

int SettingsDialog::healthCheckIntervalSec() const
{
    return m_healthIntervalSpin ? m_healthIntervalSpin->value()
                                : m_config->healthCheckIntervalSec();
}

// ── Backup restore ────────────────────────────────────────────────────

void SettingsDialog::onRestoreBackup()
{
    if (!m_data)
        return;

    const auto reply = QMessageBox::question(
        this, QStringLiteral("恢复备份"),
        QStringLiteral("恢复备份将替换当前会话的采集记录，是否继续？"));
    if (reply != QMessageBox::Yes)
        return;

    const auto path = QFileDialog::getOpenFileName(
        this, QStringLiteral("选择备份文件"), m_saveBaseDir,
        QStringLiteral("备份文件 (*.json)"));
    if (path.isEmpty())
        return;

    if (!m_data->loadBackup(path)) {
        QMessageBox::warning(this, QStringLiteral("恢复失败"),
                             QStringLiteral("无法读取备份文件，请确认文件格式正确。"));
        return;
    }

    m_restoredBackupPath = path;
    m_restoreStatus->setText(QStringLiteral("已恢复 %1 条记录，关闭对话框后生效。")
                             .arg(m_data->count()));
}
