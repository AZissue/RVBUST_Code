#include "logic/DataManager.h"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QTextStream>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QDateTime>
#include <QDirIterator>
#include <algorithm>
#include <QSaveFile>

DataManager::DataManager(QObject* parent)
    : QObject(parent)
{
    m_backupTimer = new QTimer(this);
    m_backupTimer->setSingleShot(true);
    m_backupTimer->setInterval(200);
    connect(m_backupTimer, &QTimer::timeout, this, &DataManager::onBackupFlush);
}

// ── Session ──

void DataManager::newSession(const QString& baseDir, EyeHandMode eyeHand, CalibType calibType)
{
    // Milliseconds guard against two sessions created within the same second.
    auto ts = QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd_HHmmss_zzz"));
    m_saveDir = QStringLiteral("%1/calibration_data_%2").arg(baseDir, ts);
    m_backupDir = m_saveDir + QStringLiteral("/backup");
    m_eyeHand = eyeHand;
    m_calibType = calibType;

    m_records.clear();
    m_currentIndex = -1;
    m_backupTimer->stop();
    m_backupPending = false;

    QDir().mkpath(m_backupDir);
    emit dataChanged();
}

QString DataManager::saveDir() const { return m_saveDir; }

std::pair<EyeHandMode, CalibType> DataManager::mode() const
{
    return {m_eyeHand, m_calibType};
}

// ── CRUD ──

void DataManager::addRecord(const QString& pngPath, const QString& plyPath,
                            const QString& cameraTargetXyz,
                            const QString& robotCapturePose,
                            const QString& robotTargetXyz,
                            float cameraErrorPct, int markerCount)
{
    int idx = static_cast<int>(m_records.size()) + 1;
    CaptureRecord rec;
    rec.index = idx;
    rec.pngPath = pngPath;
    rec.plyPath = plyPath;
    rec.cameraTargetXyz = cameraTargetXyz;
    rec.robotCapturePose = robotCapturePose;
    rec.robotTargetXyz = robotTargetXyz;
    rec.cameraErrorPct = cameraErrorPct;
    rec.markerCount = markerCount;

    m_records.push_back(rec);
    m_currentIndex = idx - 1;
    emit progressUpdated(static_cast<int>(m_records.size()), -1);
    emit dataChanged();
    saveBackup();
}

void DataManager::updateRecord(int index, const QString& field, const QString& value)
{
    if (index < 1 || index > static_cast<int>(m_records.size()))
        return;

    auto& rec = m_records[index - 1];
    if (field == "camera_target_xyz")
        rec.cameraTargetXyz = value;
    else if (field == "robot_capture_pose")
        rec.robotCapturePose = value;
    else if (field == "robot_target_xyz")
        rec.robotTargetXyz = value;

    emit dataChanged();
}

bool DataManager::removeLast()
{
    if (m_records.empty())
        return false;

    auto& rec = m_records.back();
    if (!QFile::remove(rec.pngPath))
        qWarning("DataManager: failed to remove %s", qPrintable(rec.pngPath));
    if (!QFile::remove(rec.plyPath))
        qWarning("DataManager: failed to remove %s", qPrintable(rec.plyPath));
    m_records.pop_back();

    m_currentIndex = static_cast<int>(m_records.size()) - 1;
    emit progressUpdated(static_cast<int>(m_records.size()), -1);
    emit dataChanged();
    saveBackup();
    return true;
}

void DataManager::clearAll()
{
    for (auto& rec : m_records) {
        if (!QFile::remove(rec.pngPath))
            qWarning("DataManager: failed to remove %s", qPrintable(rec.pngPath));
        if (!QFile::remove(rec.plyPath))
            qWarning("DataManager: failed to remove %s", qPrintable(rec.plyPath));
    }
    m_records.clear();
    m_currentIndex = -1;
    emit progressUpdated(0, -1);
    emit dataChanged();
    saveBackup();
}

const CaptureRecord* DataManager::getRecord(int index) const
{
    if (index < 1 || index > static_cast<int>(m_records.size()))
        return nullptr;
    return &m_records[index - 1];
}

int DataManager::count() const { return static_cast<int>(m_records.size()); }

int DataManager::currentIndex() const { return m_currentIndex + 1; }

std::vector<CaptureRecord> DataManager::allRecords() const
{
    return m_records;
}

// ── File export ──

bool DataManager::writeHandEyeOutput()
{
    if (m_records.empty())
        return false;

    if (m_calibType == CalibType::Marker)
        writeMarkerOutput();
    else
        writeTcpOutput();

    return true;
}

void DataManager::writeMarkerOutput()
{
    QSaveFile file(m_saveDir + QStringLiteral("/pose.txt"));
    if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        QTextStream out(&file);
        out.setCodec("UTF-8");
        for (const auto& rec : m_records)
            out << rec.robotCapturePose << "\n";
        if (!file.commit())
            qWarning("DataManager: failed to commit %s", qPrintable(file.fileName()));
    } else {
        qWarning("DataManager: failed to write %s", qPrintable(file.fileName()));
    }
}

void DataManager::writeTcpOutput()
{
    auto writeFile = [](const QString& path, const auto& records,
                         const auto& field) {
        QSaveFile file(path);
        if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
            QTextStream out(&file);
            out.setCodec("UTF-8");
            for (const auto& rec : records)
                out << field(rec) << "\n";
            if (!file.commit())
                qWarning("DataManager: failed to commit %s", qPrintable(file.fileName()));
        } else {
            qWarning("DataManager: failed to write %s", qPrintable(path));
        }
    };

    writeFile(m_saveDir + QStringLiteral("/cameraCapturePointXyz.txt"),
              m_records, [](const CaptureRecord& r) { return r.cameraTargetXyz; });
    writeFile(m_saveDir + QStringLiteral("/tcp.txt"),
              m_records, [](const CaptureRecord& r) { return r.robotTargetXyz; });

    if (m_eyeHand == EyeHandMode::EyeInHand) {
        writeFile(m_saveDir + QStringLiteral("/cameraCaptureRobotPose.txt"),
                  m_records, [](const CaptureRecord& r) { return r.robotCapturePose; });
    }
}

// ── Backup ──

void DataManager::saveBackup(bool force)
{
    if (m_backupDir.isEmpty())
        return;

    if (force) {
        m_backupTimer->stop();
        m_backupPending = false;
        writeBackupNow();
        return;
    }

    // Debounce: rapid save/undo bursts collapse into one write, but the last
    // state is always flushed shortly after the final change.
    m_backupPending = true;
    m_backupTimer->start();
}

void DataManager::onBackupFlush()
{
    if (!m_backupPending)
        return;
    m_backupPending = false;
    writeBackupNow();
}

void DataManager::writeBackupNow()
{
    auto ts = QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd_HHmmss_zzz"));
    auto path = QStringLiteral("%1/calibration_data_%2.json").arg(m_backupDir, ts);

    QJsonObject root;
    root["eye_in_hand"] = (m_eyeHand == EyeHandMode::EyeInHand);
    root["marker_type"] = (m_calibType == CalibType::Marker);

    QJsonArray recordsArr;
    for (const auto& rec : m_records) {
        QJsonObject robj;
        robj["index"] = rec.index;
        // Store paths relative to the session dir so backups survive moving machines.
        robj["png_path"] = QDir(m_saveDir).relativeFilePath(rec.pngPath);
        robj["ply_path"] = QDir(m_saveDir).relativeFilePath(rec.plyPath);
        robj["camera_target_xyz"] = rec.cameraTargetXyz;
        robj["robot_capture_pose"] = rec.robotCapturePose;
        robj["robot_target_xyz"] = rec.robotTargetXyz;
        robj["camera_error_pct"] = rec.cameraErrorPct;
        robj["marker_count"] = rec.markerCount;
        recordsArr.append(robj);
    }
    root["records"] = recordsArr;

    QFile file(path);
    if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    } else {
        qWarning("DataManager: failed to write backup %s", qPrintable(path));
    }

    cleanupBackups();
}

void DataManager::cleanupBackups()
{
    QDir dir(m_backupDir);
    if (!dir.exists())
        return;

    auto entries = dir.entryInfoList({"calibration_data_*.json"}, QDir::Files,
                                     QDir::Time | QDir::Reversed);
    // entries are sorted oldest-first; remove excess
    while (entries.size() > 10) {
        QFile::remove(entries.first().absoluteFilePath());
        entries.removeFirst();
    }
}

bool DataManager::loadBackup(const QString& path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return false;

    auto doc = QJsonDocument::fromJson(file.readAll());
    if (doc.isNull()) return false;

    auto root = doc.object();
    m_eyeHand = root["eye_in_hand"].toBool() ? EyeHandMode::EyeInHand : EyeHandMode::EyeToHand;
    m_calibType = root["marker_type"].toBool() ? CalibType::Marker : CalibType::TcpTouch;

    // The backup lives at <sessionDir>/backup/xxx.json.  Paths inside the JSON
    // are stored relative to the session dir (legacy absolute paths still work).
    QDir sessionDir(QFileInfo(path).absoluteDir());
    if (sessionDir.dirName() == QStringLiteral("backup"))
        sessionDir.cdUp();
    m_saveDir = sessionDir.path();
    m_backupDir = m_saveDir + QStringLiteral("/backup");

    auto resolve = [&sessionDir](const QString& p) {
        return QFileInfo(p).isAbsolute() ? p : sessionDir.filePath(p);
    };

    m_records.clear();
    for (const auto& val : root["records"].toArray()) {
        auto obj = val.toObject();
        CaptureRecord rec;
        rec.index = obj["index"].toInt();
        rec.pngPath = resolve(obj["png_path"].toString());
        rec.plyPath = resolve(obj["ply_path"].toString());
        rec.cameraTargetXyz = obj["camera_target_xyz"].toString();
        rec.robotCapturePose = obj["robot_capture_pose"].toString();
        rec.robotTargetXyz = obj["robot_target_xyz"].toString();
        rec.cameraErrorPct = static_cast<float>(obj["camera_error_pct"].toDouble(-1.0));
        rec.markerCount = obj["marker_count"].toInt(0);
        m_records.push_back(rec);
    }
    m_currentIndex = static_cast<int>(m_records.size()) - 1;
    emit dataChanged();
    emit progressUpdated(static_cast<int>(m_records.size()), -1);
    return true;
}

QString DataManager::findLatestBackup(const QString& baseDir)
{
    QStringList candidates;
    QDirIterator it(baseDir, {"calibration_data_*.json"},
                    QDir::Files, QDirIterator::Subdirectories);
    while (it.hasNext()) {
        candidates.append(it.next());
    }
    if (candidates.isEmpty())
        return {};

    QFileInfo latest;
    for (const auto& f : candidates) {
        QFileInfo fi(f);
        if (!latest.exists() || fi.lastModified() > latest.lastModified())
            latest = fi;
    }
    return latest.absoluteFilePath();
}
