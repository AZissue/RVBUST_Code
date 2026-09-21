#pragma once

#include <QDialog>
#include <QMap>
#include <QString>
#include <QStringList>
#include <QVariantMap>

class AppConfig;
class DataManager;
class QCheckBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QSpinBox;

// Settings dialog: data save path, optional flow automation, caliboard quality
// threshold, camera maintenance and backup restore.
//
// 第 12 回合 任务 1 removed the whole 拍摄参数 group: exposure/gain/mode are
// tuned in the camera vendor's own tool and the app pushes nothing, so there is
// no longer any capture parameter to read back, edit or persist here.
//
// Values are read back through the getters after exec(); nothing is persisted
// here — MainWindow owns AppConfig and applies the result, so there is exactly
// one writer.
class SettingsDialog : public QDialog {
    Q_OBJECT
public:
    SettingsDialog(AppConfig& config, DataManager* data, QWidget* parent = nullptr);

    QString saveBaseDir() const { return m_saveBaseDir; }
    float errorThreshold() const { return m_errorThreshold; }
    QString restoredBackupPath() const { return m_restoredBackupPath; }

    bool autoDetectAfterCapture() const;
    bool autoSaveAfterDetect() const;
    bool autoReadRobotPose() const;
    int idlePausePreviewSec() const;
    int healthCheckIntervalSec() const;

signals:
    // 相机维护 →「释放相机」.  MainWindow performs shutdown + rescan (it owns the
    // logger), so the button works while the dialog is still open.
    void cameraReleaseRequested();

private:
    void onRestoreBackup();

    AppConfig* m_config = nullptr;
    DataManager* m_data = nullptr;

    QString m_saveBaseDir;
    float m_errorThreshold = 5.0f;
    QString m_restoredBackupPath;

    QLineEdit* m_pathEdit = nullptr;
    QDoubleSpinBox* m_thresholdSpin = nullptr;
    QLabel* m_restoreStatus = nullptr;

    QCheckBox* m_autoDetectCheck = nullptr;
    QCheckBox* m_autoSaveCheck = nullptr;
    QCheckBox* m_autoReadPoseCheck = nullptr;

    QSpinBox* m_idlePauseSpin = nullptr;
    QSpinBox* m_healthIntervalSpin = nullptr;
    QLabel* m_releaseStatus = nullptr;
};
