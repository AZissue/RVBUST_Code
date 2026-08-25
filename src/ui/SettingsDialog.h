#pragma once

#include <QDialog>
#include <QString>
#include <QVariantMap>
#include <QMap>

class CameraManager;
class DataManager;
class QLineEdit;
class QDoubleSpinBox;
class QLabel;

// Settings dialog: data save path + camera parameters (when connected).
// Values are read back via saveBaseDir() / cameraParams() after exec().
class SettingsDialog : public QDialog {
    Q_OBJECT
public:
    explicit SettingsDialog(const QString& saveBaseDir, float errorThreshold,
                            CameraManager* camera, DataManager* data,
                            QWidget* parent = nullptr);

    QString saveBaseDir() const { return m_saveBaseDir; }
    QVariantMap cameraParams() const { return m_cameraParams; }
    float errorThreshold() const { return m_errorThreshold; }
    QString restoredBackupPath() const { return m_restoredBackupPath; }

private:
    void onRestoreBackup();

    QString m_saveBaseDir;
    float m_errorThreshold = 5.0f;
    QString m_restoredBackupPath;
    QVariantMap m_cameraParams;
    QMap<QString, QLineEdit*> m_camFields;
    QLineEdit* m_pathEdit = nullptr;
    QDoubleSpinBox* m_thresholdSpin = nullptr;
    QLabel* m_restoreStatus = nullptr;
    DataManager* m_data = nullptr;
};
