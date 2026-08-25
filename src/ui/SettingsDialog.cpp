#include "ui/SettingsDialog.h"

#include "logic/CameraManager.h"
#include "logic/DataManager.h"
#include "ui/Theme.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFormLayout>
#include <QGroupBox>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QDoubleValidator>
#include <QDoubleSpinBox>
#include <QMessageBox>

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

} // namespace

SettingsDialog::SettingsDialog(const QString& saveBaseDir, float errorThreshold,
                               CameraManager* camera, DataManager* data,
                               QWidget* parent)
    : QDialog(parent)
    , m_saveBaseDir(saveBaseDir)
    , m_errorThreshold(errorThreshold)
    , m_data(data)
{
    setWindowTitle(QStringLiteral("设置"));
    setMinimumWidth(500);

    auto* layout = new QVBoxLayout(this);

    // Save path
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

    // Caliboard accuracy warning threshold (warnings never block saving)
    auto* qualityGroup = new QGroupBox(QStringLiteral("识别质量"), this);
    auto* qualityLayout = new QFormLayout(qualityGroup);
    m_thresholdSpin = new QDoubleSpinBox(qualityGroup);
    m_thresholdSpin->setRange(0.0, 100.0);
    m_thresholdSpin->setDecimals(1);
    m_thresholdSpin->setSingleStep(0.5);
    m_thresholdSpin->setSuffix(QStringLiteral(" %"));
    m_thresholdSpin->setValue(errorThreshold);
    qualityLayout->addRow(QStringLiteral("标定板误差告警阈值"), m_thresholdSpin);
    auto* qualityHint = new QLabel(
        QStringLiteral("仅影响\"检测误差较大\"提示，不拦截识别与保存"), qualityGroup);
    qualityHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                               .arg(Theme::TEXT_HINT).arg(Theme::FONT_BODY));
    qualityLayout->addRow(QString(), qualityHint);
    layout->addWidget(qualityGroup);

    // Backup restore entry (DataManager::loadBackup is already implemented)
    auto* restoreGroup = new QGroupBox(QStringLiteral("数据恢复"), this);
    auto* restoreLayout = new QVBoxLayout(restoreGroup);
    auto* restoreBtn = new QPushButton(QStringLiteral("从备份恢复..."), restoreGroup);
    restoreLayout->addWidget(restoreBtn);
    m_restoreStatus = new QLabel(QStringLiteral("选择备份文件后将恢复会话记录"), restoreGroup);
    m_restoreStatus->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                   .arg(Theme::TEXT_HINT).arg(Theme::FONT_BODY));
    m_restoreStatus->setWordWrap(true);
    restoreLayout->addWidget(m_restoreStatus);
    connect(restoreBtn, &QPushButton::clicked, this, &SettingsDialog::onRestoreBackup);
    layout->addWidget(restoreGroup);

    // Camera params
    if (camera && camera->isConnected()) {
        auto* camGroup = new QGroupBox(QStringLiteral("相机参数"), this);
        auto* formLayout = new QFormLayout(camGroup);
        const auto settings = camera->currentSettings();

        for (auto it = settings.begin(); it != settings.end(); ++it) {
            auto* edit = new QLineEdit(QString::number(it.value(), 'f', 2), camGroup);
            const auto range = CameraManager::cameraParamRange(it.key());
            const double lo = range.first, hi = range.second;
            if (lo != hi)
                edit->setValidator(new QDoubleValidator(lo, hi, 2, edit));
            else
                edit->setValidator(new QDoubleValidator(-99999, 99999, 2, edit));
            formLayout->addRow(paramLabel(it.key()), edit);
            m_camFields[it.key()] = edit;
        }
        layout->addWidget(camGroup);
    } else {
        auto* hint = new QLabel(QStringLiteral("请先连接相机以调整相机参数"), this);
        hint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px; padding: 8px 0;")
                            .arg(Theme::TEXT_HINT).arg(Theme::FONT_BODY));
        layout->addWidget(hint);
    }

    // Buttons
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
}

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
