#include "ui/SettingsDialog.h"

#include "logic/AppConfig.h"
#include "logic/CameraManager.h"
#include "logic/CameraParamPolicy.h"
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
#include <QSpinBox>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QDoubleValidator>
#include <QDoubleSpinBox>
#include <QMessageBox>
#include <QSignalBlocker>

namespace {

QString paramLabel(const QString& key)
{
    if (key == QStringLiteral("exposure_time_2d"))  return QStringLiteral("2D 曝光 (ms)");
    if (key == QStringLiteral("gain_2d"))           return QStringLiteral("2D 增益");
    if (key == QStringLiteral("exposure_time_3d"))  return QStringLiteral("3D 曝光 (ms)");
    if (key == QStringLiteral("line_scanner_exposure_time_us"))
        return QStringLiteral("单行曝光时间 (us)");
    if (key == QStringLiteral("gain_3d"))           return QStringLiteral("3D 增益");
    return key;
}

QString hintStyle()
{
    return QStringLiteral("color: %1; font-size: %2px;")
        .arg(Theme::TEXT_HINT).arg(Theme::FONT_BODY);
}

QMap<QString, float> toFloatMap(const QVariantMap& in)
{
    QMap<QString, float> out;
    for (auto it = in.constBegin(); it != in.constEnd(); ++it)
        out.insert(it.key(), it.value().toFloat());
    return out;
}

} // namespace

SettingsDialog::SettingsDialog(AppConfig& config, CameraManager* camera,
                               DataManager* data, QWidget* parent)
    : QDialog(parent)
    , m_config(&config)
    , m_camera(camera)
    , m_data(data)
{
    setWindowTitle(QStringLiteral("设置"));
    setMinimumWidth(560);

    m_saveBaseDir = m_config->saveBaseDir();
    m_errorThreshold = m_config->caliboardErrorThreshold();

    auto* layout = new QVBoxLayout(this);

    // ── Save path ──
    auto* pathGroup = new QGroupBox(QStringLiteral("数据保存路径"), this);
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
    layout->addWidget(pathGroup);

    buildCameraGroup(this, layout);

    // ── Flow automation (任务 2): all three default off ──
    auto* autoGroup = new QGroupBox(QStringLiteral("流程自动化"), this);
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
    layout->addWidget(autoGroup);

    // ── Caliboard accuracy warning threshold (warnings never block saving) ──
    auto* qualityGroup = new QGroupBox(QStringLiteral("识别质量"), this);
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
    layout->addWidget(qualityGroup);

    // ── Camera maintenance (任务 3.4) ──
    auto* maintGroup = new QGroupBox(QStringLiteral("相机维护"), this);
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
    layout->addWidget(maintGroup);

    // ── Backup restore ──
    auto* restoreGroup = new QGroupBox(QStringLiteral("数据恢复"), this);
    auto* restoreLayout = new QVBoxLayout(restoreGroup);
    auto* restoreBtn = new QPushButton(QStringLiteral("从备份恢复..."), restoreGroup);
    restoreLayout->addWidget(restoreBtn);
    m_restoreStatus = new QLabel(QStringLiteral("选择备份文件后将恢复会话记录"), restoreGroup);
    m_restoreStatus->setStyleSheet(hintStyle());
    m_restoreStatus->setWordWrap(true);
    restoreLayout->addWidget(m_restoreStatus);
    connect(restoreBtn, &QPushButton::clicked, this, &SettingsDialog::onRestoreBackup);
    layout->addWidget(restoreGroup);

    // ── Buttons ──
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);

    // Capture results on accept
    connect(buttons, &QDialogButtonBox::accepted, this, [this]() {
        m_saveBaseDir = m_pathEdit->text();
        m_errorThreshold = m_thresholdSpin ? static_cast<float>(m_thresholdSpin->value())
                                           : m_errorThreshold;
        m_cameraParams.clear();
        for (auto it = m_camFields.begin(); it != m_camFields.end(); ++it) {
            QLineEdit* edit = it.value();
            bool ok = false;
            const float val = edit ? edit->text().toFloat(&ok) : 0.0f;
            if (ok)
                m_cameraParams[it.key()] = val;
        }
    });

    // A connect/disconnect while the dialog is open must not leave a stale
    // "来源" line or a stale 读取/释放 state behind.
    if (m_camera) {
        connect(m_camera, &CameraManager::cameraConnected, this,
                [this]() { refreshParamSource(); });
        connect(m_camera, &CameraManager::cameraDisconnected, this,
                [this]() { refreshParamSource(); });
    }
    refreshParamSource();
}

// ── Capture-parameter group (任务 1) ──────────────────────────────────

void SettingsDialog::buildCameraGroup(QWidget* parent, QVBoxLayout* layout)
{
    const bool connected = m_camera && m_camera->isConnected();
    m_cameraRead = m_camera ? m_camera->cameraReadSettings() : QMap<QString, float>{};

    auto* camGroup = new QGroupBox(QStringLiteral("拍摄参数"), parent);
    auto* camLayout = new QVBoxLayout(camGroup);

    // "当前相机参数" + where the numbers come from.
    m_paramSourceLabel = new QLabel(camGroup);
    m_paramSourceLabel->setWordWrap(true);
    camLayout->addWidget(m_paramSourceLabel);

    auto* checkRow = new QHBoxLayout();
    m_useCameraParamsCheck = new QCheckBox(
        QStringLiteral("使用相机内部参数（相机调试软件里设定的值，不下发任何参数）"),
        camGroup);
    m_useCameraParamsCheck->setChecked(m_config->useCameraParams());
    checkRow->addWidget(m_useCameraParamsCheck);
    checkRow->addStretch();

    m_readParamsBtn = new QPushButton(QStringLiteral("从相机读取当前参数"), camGroup);
    m_readParamsBtn->setEnabled(connected);
    if (!connected)
        m_readParamsBtn->setToolTip(QStringLiteral("请先连接相机"));
    checkRow->addWidget(m_readParamsBtn);
    camLayout->addLayout(checkRow);

    auto* form = new QFormLayout();
    camLayout->addLayout(form);

    m_paramHint = new QLabel(camGroup);
    m_paramHint->setStyleSheet(hintStyle());
    m_paramHint->setWordWrap(true);
    camLayout->addWidget(m_paramHint);

    // Which values to show: the device's own when we have them and the setting
    // says to use them, otherwise the effective / last-saved ones.
    QMap<QString, float> shown;
    if (connected && m_config->useCameraParams() && !m_cameraRead.isEmpty())
        shown = m_cameraRead;
    else if (connected && m_camera)
        shown = m_camera->currentSettings();
    else
        shown = toFloatMap(m_config->cameraParams());

    // Stable, readable order instead of the QMap's alphabetical one.
    const QStringList known = {
        QStringLiteral("exposure_time_2d"),
        QStringLiteral("gain_2d"),
        QStringLiteral("exposure_time_3d"),
        QStringLiteral("line_scanner_exposure_time_us"),
        QStringLiteral("gain_3d"),
    };
    for (const QString& key : known) {
        if (shown.contains(key))
            m_paramOrder << key;
    }
    // Anything the device/config reports that we do not know about still has to
    // be editable, so append it rather than dropping it silently.
    for (auto it = shown.constBegin(); it != shown.constEnd(); ++it) {
        if (!m_paramOrder.contains(it.key()))
            m_paramOrder << it.key();
    }

    for (const QString& key : m_paramOrder) {
        auto* edit = new QLineEdit(camGroup);
        const auto range = CameraManager::cameraParamRange(key);
        if (range.first != range.second)
            edit->setValidator(new QDoubleValidator(range.first, range.second, 2, edit));
        else
            edit->setValidator(new QDoubleValidator(-99999, 99999, 2, edit));
        // textEdited (not textChanged) so programmatic refills do not count as
        // an operator change.
        connect(edit, &QLineEdit::textEdited, this, [this]() { onParamEdited(); });
        form->addRow(paramLabel(key), edit);
        m_camFields[key] = edit;
    }
    fillParamFields(shown);

    connect(m_useCameraParamsCheck, &QCheckBox::toggled, this, [this](bool on) {
        if (on) {
            // Switching back to "camera internal" discards the edits: the fields
            // must show what will really be used.
            m_camParamsEdited = false;
            QMap<QString, float> values =
                !m_cameraRead.isEmpty() ? m_cameraRead
                                        : toFloatMap(m_config->cameraParams());
            if (m_camera && m_camera->isConnected()) {
                const auto eff = m_camera->currentSettings();
                if (!eff.isEmpty())
                    values = eff;
            }
            fillParamFields(values);
        }
        refreshParamSource();
    });
    connect(m_readParamsBtn, &QPushButton::clicked, this,
            &SettingsDialog::onReadFromCamera);

    layout->addWidget(camGroup);
}

void SettingsDialog::fillParamFields(const QMap<QString, float>& values)
{
    for (auto it = m_camFields.begin(); it != m_camFields.end(); ++it) {
        if (!values.contains(it.key()))
            continue;
        QLineEdit* edit = it.value();
        if (!edit)
            continue;
        // setText does not emit textEdited, so this cannot be mistaken for an
        // operator edit.
        edit->setText(QString::number(values.value(it.key()), 'f', 2));
    }
}

void SettingsDialog::refreshParamSource()
{
    const bool connected = m_camera && m_camera->isConnected();
    const bool useCam = m_useCameraParamsCheck && m_useCameraParamsCheck->isChecked();

    if (m_paramSourceLabel) {
        m_paramSourceLabel->setText(
            QStringLiteral("当前相机参数　%1")
                .arg(CameraParamPolicy::describeSource(
                    useCam ? CameraParamPolicy::Source::CameraInternal
                           : CameraParamPolicy::Source::SavedConfig,
                    connected)));
    }
    if (m_readParamsBtn) {
        m_readParamsBtn->setEnabled(connected);
        m_readParamsBtn->setToolTip(connected ? QString()
                                              : QStringLiteral("请先连接相机"));
    }
    if (m_paramHint) {
        QString h;
        if (useCam)
            h = QStringLiteral("使用相机内部参数：拍照时不下发这些值，"
                               "直接沿用相机当前设置。修改任一数值会自动切换到"
                               "\"使用保存的参数\"。");
        else if (m_camParamsEdited)
            h = QStringLiteral("已修改参数 → 将使用保存的参数（下次连接时下发）。");
        else
            h = QStringLiteral("使用保存的参数：连接相机后会把这里的值下发到相机。");
        m_paramHint->setText(h);
    }
}

void SettingsDialog::onParamEdited()
{
    m_camParamsEdited = true;
    if (m_useCameraParamsCheck && m_useCameraParamsCheck->isChecked()) {
        // Never let an edit be silently ignored: the checkbox follows the edit.
        const QSignalBlocker block(m_useCameraParamsCheck);
        m_useCameraParamsCheck->setChecked(false);
    }
    refreshParamSource();
}

void SettingsDialog::onReadFromCamera()
{
    if (!m_camera || !m_camera->isConnected()) {
        if (m_paramSourceLabel)
            m_paramSourceLabel->setText(QStringLiteral("当前相机参数　相机未连接，无法读取"));
        return;
    }
    if (!m_camera->reloadCameraParamsFromDevice()) {
        if (m_paramHint)
            m_paramHint->setText(QStringLiteral("从相机读取失败，请确认相机连接后重试。"));
        return;
    }
    m_cameraRead = m_camera->cameraReadSettings();
    fillParamFields(m_cameraRead);
    m_camParamsEdited = false;
    refreshParamSource();
}

// ── Getters ───────────────────────────────────────────────────────────

bool SettingsDialog::useCameraParams() const
{
    return m_useCameraParamsCheck ? m_useCameraParamsCheck->isChecked()
                                  : m_config->useCameraParams();
}

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
