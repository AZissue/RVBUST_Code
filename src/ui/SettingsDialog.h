#pragma once

#include <QDialog>
#include <QMap>
#include <QString>
#include <QStringList>
#include <QVariantMap>

class AppConfig;
class CameraManager;
class DataManager;
class QCheckBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QSpinBox;

// Settings dialog: data save path, capture parameters (camera / saved),
// optional flow automation, camera maintenance.
//
// Values are read back through the getters after exec(); nothing is persisted
// here — MainWindow owns AppConfig and applies the result, so there is exactly
// one writer.
class SettingsDialog : public QDialog {
    Q_OBJECT
public:
    SettingsDialog(AppConfig& config, CameraManager* camera, DataManager* data,
                   QWidget* parent = nullptr);

    QString saveBaseDir() const { return m_saveBaseDir; }
    QVariantMap cameraParams() const { return m_cameraParams; }
    // True when the operator changed a capture parameter in this dialog.  Only
    // then is the value pushed to the camera — an untouched dialog must not
    // "re-apply" anything, least of all when use_camera_params is on.
    bool cameraParamsEdited() const { return m_camParamsEdited; }
    float errorThreshold() const { return m_errorThreshold; }
    QString restoredBackupPath() const { return m_restoredBackupPath; }

    bool useCameraParams() const;
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
    void buildCameraGroup(QWidget* parent, class QVBoxLayout* layout);
    void fillParamFields(const QMap<QString, float>& values);
    void refreshParamSource();
    void onParamEdited();
    void onReadFromCamera();
    void onRestoreBackup();

    AppConfig* m_config = nullptr;
    CameraManager* m_camera = nullptr;
    DataManager* m_data = nullptr;

    QString m_saveBaseDir;
    float m_errorThreshold = 5.0f;
    QString m_restoredBackupPath;
    QVariantMap m_cameraParams;
    QMap<QString, QLineEdit*> m_camFields;
    QStringList m_paramOrder;          // display order of the parameter rows
    bool m_camParamsEdited = false;
    // Values the device reported at connect (may be empty when nothing was read
    // or when no camera has been connected yet).
    QMap<QString, float> m_cameraRead;

    QLineEdit* m_pathEdit = nullptr;
    QDoubleSpinBox* m_thresholdSpin = nullptr;
    QLabel* m_restoreStatus = nullptr;

    QLabel* m_paramSourceLabel = nullptr;
    QLabel* m_paramHint = nullptr;
    QCheckBox* m_useCameraParamsCheck = nullptr;
    class QPushButton* m_readParamsBtn = nullptr;

    QCheckBox* m_autoDetectCheck = nullptr;
    QCheckBox* m_autoSaveCheck = nullptr;
    QCheckBox* m_autoReadPoseCheck = nullptr;

    QSpinBox* m_idlePauseSpin = nullptr;
    QSpinBox* m_healthIntervalSpin = nullptr;
    QLabel* m_releaseStatus = nullptr;
};
