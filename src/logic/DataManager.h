#pragma once
#include <QObject>
#include <QString>
#include <vector>
#include <QTimer>
#include <QVariantMap>
#include "models/CaptureRecord.h"
#include "models/CalibrationMode.h"

class DataManager : public QObject {
    Q_OBJECT
public:
    static constexpr int RECOMMENDED_COUNT = 15;

    explicit DataManager(QObject* parent = nullptr);

    // Session management
    void newSession(const QString& baseDir, EyeHandMode eyeHand, CalibType calibType);
    QString saveDir() const;
    std::pair<EyeHandMode, CalibType> mode() const;

    // Record CRUD
    void addRecord(const QString& pngPath, const QString& plyPath,
                   const QString& cameraTargetXyz,
                   const QString& robotCapturePose,
                   const QString& robotTargetXyz,
                   float cameraErrorPct = -1.0f,
                   int markerCount = 0);
    void updateRecord(int index, const QString& field, const QString& value);
    bool removeLast();
    void clearAll();

    const CaptureRecord* getRecord(int index) const;
    int count() const;
    int currentIndex() const;  // 1-based, 0 = no records
    std::vector<CaptureRecord> allRecords() const;

    // File export (HandEyeManager-compatible format)
    bool writeHandEyeOutput();

    // Backup / restore
    void saveBackup(bool force = false);
    bool loadBackup(const QString& path);
    static QString findLatestBackup(const QString& baseDir);

signals:
    void progressUpdated(int current, int total);
    void dataChanged();

private slots:
    void onBackupFlush();

private:
    void writeMarkerOutput();
    void writeTcpOutput();
    void cleanupBackups();
    void writeBackupNow();

    std::vector<CaptureRecord> m_records;
    QString m_saveDir;
    QString m_backupDir;
    int m_currentIndex = -1;
    EyeHandMode m_eyeHand = EyeHandMode::EyeInHand;
    CalibType m_calibType = CalibType::Marker;
    QTimer* m_backupTimer = nullptr;
    bool m_backupPending = false;
};
