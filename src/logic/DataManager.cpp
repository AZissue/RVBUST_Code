#include "logic/DataManager.h"
#include "logic/BackupDocument.h"
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
    removeRecordFile(rec.pngPath);
    removeRecordFile(rec.plyPath);
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
        removeRecordFile(rec.pngPath);
        removeRecordFile(rec.plyPath);
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
    m_lastExportError.clear();
    // Always (re)write the export files — even with zero records they are
    // written empty so the on-disk state reflects the current session.  A
    // failure to write is reported through the return value / lastExportError()
    // instead of being silently swallowed.
    if (m_calibType == CalibType::Marker)
        return writeMarkerOutput();
    return writeTcpOutput();
}

QString DataManager::lastExportError() const
{
    return m_lastExportError;
}

bool DataManager::writeMarkerOutput()
{
    const QString path = m_saveDir + QStringLiteral("/pose.txt");
    QSaveFile file(path);
    if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        QTextStream out(&file);
        out.setCodec("UTF-8");
        for (const auto& rec : m_records)
            out << rec.robotCapturePose << "\n";
        if (file.commit())
            return true;
        m_lastExportError = QStringLiteral("写入 %1 失败: %2")
            .arg(QFileInfo(path).fileName(), file.errorString());
    } else {
        m_lastExportError = QStringLiteral("无法写入 %1: %2")
            .arg(QFileInfo(path).fileName(), file.errorString());
    }
    qWarning("DataManager: failed to write %s", qPrintable(path));
    return false;
}

bool DataManager::writeTcpOutput()
{
    bool ok = true;
    auto writeFile = [this, &ok](const QString& path, const auto& records,
                                 const auto& field) {
        QSaveFile file(path);
        if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
            QTextStream out(&file);
            out.setCodec("UTF-8");
            for (const auto& rec : records)
                out << field(rec) << "\n";
            if (file.commit())
                return;
            if (ok)
                m_lastExportError = QStringLiteral("写入 %1 失败: %2")
                    .arg(QFileInfo(path).fileName(), file.errorString());
        } else {
            if (ok)
                m_lastExportError = QStringLiteral("无法写入 %1: %2")
                    .arg(QFileInfo(path).fileName(), file.errorString());
        }
        ok = false;
        qWarning("DataManager: failed to write %s", qPrintable(path));
    };

    writeFile(m_saveDir + QStringLiteral("/cameraCapturePointXyz.txt"),
              m_records, [](const CaptureRecord& r) { return r.cameraTargetXyz; });
    writeFile(m_saveDir + QStringLiteral("/tcp.txt"),
              m_records, [](const CaptureRecord& r) { return r.robotTargetXyz; });

    if (m_eyeHand == EyeHandMode::EyeInHand) {
        writeFile(m_saveDir + QStringLiteral("/cameraCaptureRobotPose.txt"),
                  m_records, [](const CaptureRecord& r) { return r.robotCapturePose; });
    }
    return ok;
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
    root["version"] = 1;
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

    // Atomic write: QSaveFile writes a temp file and renames it into place on
    // commit, so a killed process can never leave a half-written backup behind.
    QSaveFile file(path);
    if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
        if (!file.commit())
            qWarning("DataManager: failed to commit backup %s", qPrintable(path));
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
    m_lastLoadError.clear();

    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        m_lastLoadError = QStringLiteral("无法打开备份文件：%1").arg(file.errorString());
        return false;
    }
    const QByteArray bytes = file.readAll();
    file.close();

    // The backup lives at <sessionDir>/backup/xxx.json.  Paths inside the JSON
    // are stored relative to the session dir (legacy absolute paths still work,
    // but must point inside it as well).
    QDir sessionDir(QFileInfo(path).absoluteDir());
    if (sessionDir.dirName() == QStringLiteral("backup"))
        sessionDir.cdUp();
    const QString sessionPath = sessionDir.path();

    // Validate the whole document — structure, version, every path — before
    // touching any member.  A rejected backup must leave the current session
    // exactly as it was; before this, a JSON object without "records" was
    // accepted as a successful restore of zero records.
    const BackupDocument::ParseResult parsed =
        BackupDocument::parseForSession(bytes, sessionPath);
    if (!parsed.ok) {
        m_lastLoadError = parsed.error;
        qWarning("DataManager: rejected backup %s: %s",
                 qPrintable(path), qPrintable(parsed.error));
        return false;
    }

    std::vector<CaptureRecord> records;
    records.reserve(parsed.records.size());
    for (const auto& src : parsed.records) {
        CaptureRecord rec;
        rec.index = src.index;
        rec.pngPath = src.pngPath;
        rec.plyPath = src.plyPath;
        rec.cameraTargetXyz = src.cameraTargetXyz;
        rec.robotCapturePose = src.robotCapturePose;
        rec.robotTargetXyz = src.robotTargetXyz;
        rec.cameraErrorPct = src.cameraErrorPct;
        rec.markerCount = src.markerCount;
        records.push_back(rec);
    }

    // Commit point.
    m_eyeHand = parsed.eyeInHand ? EyeHandMode::EyeInHand : EyeHandMode::EyeToHand;
    m_calibType = parsed.markerType ? CalibType::Marker : CalibType::TcpTouch;
    m_saveDir = sessionPath;
    m_backupDir = sessionPath + QStringLiteral("/backup");
    m_records = std::move(records);
    m_currentIndex = static_cast<int>(m_records.size()) - 1;
    emit dataChanged();
    emit progressUpdated(static_cast<int>(m_records.size()), -1);
    return true;
}

QString DataManager::lastLoadError() const
{
    return m_lastLoadError;
}

bool DataManager::removeRecordFile(const QString& path)
{
    // Defense in depth: loadBackup() already rejects outside paths, but a
    // delete must not trust that alone — it is the one operation that destroys
    // data outside this program's own state.
    if (!BackupDocument::isWithinDir(m_saveDir, path)) {
        qWarning("DataManager: refused to remove file outside session: %s",
                 qPrintable(path));
        return false;
    }
    if (!QFile::remove(path)) {
        qWarning("DataManager: failed to remove %s", qPrintable(path));
        return false;
    }
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

    // Only consider backups that parseForSession() would actually accept — the
    // same validator loadBackup() uses, so "newest intact" cannot name a file
    // the restore path is going to reject.  The mtime is used to pick the
    // newest *of those*: a newer truncated (half-written) file must never win
    // over an older intact one.
    auto isIntactBackup = [](const QString& p) {
        QFile file(p);
        if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
            return false;
        const QByteArray bytes = file.readAll();
        QDir sessionDir(QFileInfo(p).absoluteDir());
        if (sessionDir.dirName() == QStringLiteral("backup"))
            sessionDir.cdUp();
        return BackupDocument::parseForSession(bytes, sessionDir.path()).ok;
    };

    QFileInfo latest;
    for (const auto& f : candidates) {
        if (!isIntactBackup(f))
            continue;
        QFileInfo fi(f);
        if (!latest.exists() || fi.lastModified() > latest.lastModified())
            latest = fi;
    }
    if (!latest.exists())
        return {};
    return latest.absoluteFilePath();
}
