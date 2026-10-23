#include "test_data_manager.h"

#include "logic/BackupDocument.h"
#include "logic/DataManager.h"

#include <QtTest>
#include <QTemporaryDir>
#include <QFile>
#include <QDir>
#include <QDateTime>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace {

bool writeBytes(const QString& path, const QByteArray& data)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly))
        return false;
    return f.write(data) == data.size();
}

// version < 0 omits the version field; records=false omits the records array.
QByteArray backupJson(const QString& pngPath, const QString& plyPath,
                      int version = 1, bool records = true)
{
    QJsonObject rec;
    rec[QStringLiteral("index")] = 1;
    rec[QStringLiteral("png_path")] = pngPath;
    rec[QStringLiteral("ply_path")] = plyPath;
    rec[QStringLiteral("camera_target_xyz")] = QStringLiteral("1 2 3");
    rec[QStringLiteral("robot_capture_pose")] = QStringLiteral("1 2 3 4 5 6");

    QJsonObject root;
    if (version >= 0)
        root[QStringLiteral("version")] = version;
    root[QStringLiteral("eye_in_hand")] = true;
    root[QStringLiteral("marker_type")] = true;
    if (records)
        root[QStringLiteral("records")] = QJsonArray{ rec };
    return QJsonDocument(root).toJson();
}

bool makeSessionWithOneRecord(DataManager& dm, const QString& baseDir,
                              QString* saveDirOut)
{
    dm.newSession(baseDir, EyeHandMode::EyeInHand, CalibType::Marker);
    const QString saveDir = dm.saveDir();
    if (saveDir.isEmpty())
        return false;
    const QString png = saveDir + QStringLiteral("/1.png");
    const QString ply = saveDir + QStringLiteral("/1.ply");
    if (!writeBytes(png, "png") || !writeBytes(ply, "ply"))
        return false;
    dm.addRecord(png, ply, QStringLiteral("1 2 3"),
                 QStringLiteral("1 2 3 4 5 6"), QString(), -1.0f, 44);
    if (saveDirOut) *saveDirOut = saveDir;
    return true;
}

} // namespace

void TestDataManager::backupRoundTripResolvesRelativePaths()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    DataManager dm;
    dm.newSession(tmp.path(), EyeHandMode::EyeInHand, CalibType::Marker);
    const QString saveDir = dm.saveDir();
    QVERIFY(!saveDir.isEmpty());

    const QString png = saveDir + QStringLiteral("/1.png");
    const QString ply = saveDir + QStringLiteral("/1.ply");
    {
        QFile f(png);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("png");
    }
    {
        QFile f(ply);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("ply");
    }

    dm.addRecord(png, ply, QStringLiteral("1 2 3"), QStringLiteral("1 2 3 4 5 6"),
                 QString(), -1.0f, 44);
    dm.saveBackup(true);  // force write

    const QString backup = DataManager::findLatestBackup(tmp.path());
    QVERIFY(!backup.isEmpty());

    // Stored paths must be relative to the session dir
    {
        QFile f(backup);
        QVERIFY(f.open(QIODevice::ReadOnly));
        const auto root = QJsonDocument::fromJson(f.readAll()).object();
        const auto rec = root[QStringLiteral("records")].toArray().first().toObject();
        QCOMPARE(rec[QStringLiteral("png_path")].toString(), QStringLiteral("1.png"));
        QCOMPARE(rec[QStringLiteral("ply_path")].toString(), QStringLiteral("1.ply"));
        QCOMPARE(rec[QStringLiteral("marker_count")].toInt(), 44);
        QCOMPARE(rec[QStringLiteral("camera_error_pct")].toDouble(), -1.0);
    }

    // Loading the backup must resolve relative paths back to absolute
    DataManager dm2;
    QVERIFY(dm2.loadBackup(backup));
    QCOMPARE(dm2.count(), 1);
    const CaptureRecord* rec = dm2.getRecord(1);
    QVERIFY(rec);
    QCOMPARE(rec->pngPath, png);
    QCOMPARE(rec->plyPath, ply);
    QCOMPARE(rec->markerCount, 44);
    QCOMPARE(dm2.saveDir(), saveDir);
}

void TestDataManager::noSessionConfigJsonWritten()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    // Session metadata now goes to the application log; the session directory
    // must NOT contain a config.json (only the backup/ subdirectory).
    DataManager dm;
    dm.newSession(tmp.path(), EyeHandMode::EyeToHand, CalibType::TcpTouch);

    const QString cfg = dm.saveDir() + QStringLiteral("/config.json");
    QVERIFY(!QFile::exists(cfg));

    // The session dir itself stays clean apart from backup/.
    QDir dir(dm.saveDir());
    const auto entries = dir.entryList(QDir::Files);
    QVERIFY(entries.isEmpty());
}

// ── Restore validation (E-06 类问题：无效备份不得改动当前会话) ──────────

void TestDataManager::malformedBackupLeavesSessionUntouched()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    DataManager dm;
    QString saveDir;
    QVERIFY(makeSessionWithOneRecord(dm, tmp.path(), &saveDir));

    const QString bad = tmp.path() + QStringLiteral("/bad.json");
    QVERIFY(writeBytes(bad, "this is not json"));

    QVERIFY(!dm.loadBackup(bad));
    QVERIFY(!dm.lastLoadError().isEmpty());
    QCOMPARE(dm.count(), 1);
    QCOMPARE(dm.saveDir(), saveDir);
    QCOMPARE(dm.mode().first, EyeHandMode::EyeInHand);
    QCOMPARE(dm.mode().second, CalibType::Marker);

    // A missing file is also a failure with a reason, not a silent no-op.
    QVERIFY(!dm.loadBackup(tmp.path() + QStringLiteral("/nope.json")));
    QVERIFY(!dm.lastLoadError().isEmpty());
    QCOMPARE(dm.count(), 1);
}

void TestDataManager::backupWithoutRecordsArrayRejected()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    DataManager dm;
    QString saveDir;
    QVERIFY(makeSessionWithOneRecord(dm, tmp.path(), &saveDir));

    // Structurally valid JSON, but not a backup: used to be accepted as a
    // successful restore of zero records, silently wiping the session.
    const QString p = tmp.path() + QStringLiteral("/no_records.json");
    QVERIFY(writeBytes(p, backupJson("1.png", "1.ply", 1, /*records=*/false)));

    QVERIFY(!dm.loadBackup(p));
    QVERIFY(dm.lastLoadError().contains(QStringLiteral("records")));
    QCOMPARE(dm.count(), 1);
    QCOMPARE(dm.saveDir(), saveDir);
}

void TestDataManager::unsupportedVersionRejected()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    DataManager dm;
    QString saveDir;
    QVERIFY(makeSessionWithOneRecord(dm, tmp.path(), &saveDir));

    const QString future = tmp.path() + QStringLiteral("/future.json");
    QVERIFY(writeBytes(future, backupJson("1.png", "1.ply", 99)));
    QVERIFY(!dm.loadBackup(future));
    QVERIFY(dm.lastLoadError().contains(QStringLiteral("版本")));
    QCOMPARE(dm.count(), 1);

    const QString noVersion = tmp.path() + QStringLiteral("/no_version.json");
    QVERIFY(writeBytes(noVersion, backupJson("1.png", "1.ply", -1)));
    QVERIFY(!dm.loadBackup(noVersion));
    QVERIFY(dm.lastLoadError().contains(QStringLiteral("version")));
    QCOMPARE(dm.count(), 1);
}

void TestDataManager::missingModeFieldsRejected()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    DataManager dm;
    QVERIFY(makeSessionWithOneRecord(dm, tmp.path(), nullptr));

    QJsonObject root;
    root[QStringLiteral("version")] = 1;
    root[QStringLiteral("records")] = QJsonArray{};
    const QString p = tmp.path() + QStringLiteral("/no_mode.json");
    QVERIFY(writeBytes(p, QJsonDocument(root).toJson()));

    QVERIFY(!dm.loadBackup(p));
    QCOMPARE(dm.count(), 1);
}

void TestDataManager::outsidePathRejectedAtomically()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    const QString session = tmp.path() + QStringLiteral("/session");
    const QString outside = tmp.path() + QStringLiteral("/outside.png");
    QVERIFY(writeBytes(outside, "must survive"));

    // 1) Relative escape.
    const QString rel = session + QStringLiteral("/backup/rel_escape.json");
    QVERIFY(writeBytes(rel, backupJson(QStringLiteral("../../outside.png"),
                                       QStringLiteral("../../outside.ply"))));

    DataManager dm;
    QString saveDir;
    QVERIFY(makeSessionWithOneRecord(dm, tmp.path(), &saveDir));

    QVERIFY(!dm.loadBackup(rel));
    QVERIFY(dm.lastLoadError().contains(QStringLiteral("png_path")));
    QCOMPARE(dm.count(), 1);
    QCOMPARE(dm.saveDir(), saveDir);
    QVERIFY(QFile::exists(outside));

    // 2) Absolute path outside the session.
    const QString abs = session + QStringLiteral("/backup/abs_escape.json");
    QVERIFY(writeBytes(abs, backupJson(QDir::toNativeSeparators(outside),
                                       QDir::toNativeSeparators(
                                           tmp.path() + QStringLiteral("/x.ply")))));
    QVERIFY(!dm.loadBackup(abs));
    QCOMPARE(dm.count(), 1);
    QVERIFY(QFile::exists(outside));

    // 3) One bad record rejects the whole document — no partial restore.
    QJsonObject good;
    good[QStringLiteral("index")] = 1;
    good[QStringLiteral("png_path")] = QStringLiteral("1.png");
    good[QStringLiteral("ply_path")] = QStringLiteral("1.ply");
    QJsonObject bad;
    bad[QStringLiteral("index")] = 2;
    bad[QStringLiteral("png_path")] = QStringLiteral("../../outside.png");
    bad[QStringLiteral("ply_path")] = QStringLiteral("2.ply");
    QJsonObject root;
    root[QStringLiteral("version")] = 1;
    root[QStringLiteral("eye_in_hand")] = true;
    root[QStringLiteral("marker_type")] = true;
    root[QStringLiteral("records")] = QJsonArray{ good, bad };
    const QString partial = session + QStringLiteral("/backup/partial.json");
    QVERIFY(writeBytes(partial, QJsonDocument(root).toJson()));

    QVERIFY(!dm.loadBackup(partial));
    QVERIFY(dm.lastLoadError().contains(QStringLiteral("第 2 条记录")));
    QCOMPARE(dm.count(), 1);
    QVERIFY(QFile::exists(outside));
}

void TestDataManager::legacyAbsolutePathInsideSessionAccepted()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    const QString session = tmp.path() + QStringLiteral("/session");
    const QString png = session + QStringLiteral("/1.png");
    const QString ply = session + QStringLiteral("/1.ply");
    QVERIFY(writeBytes(png, "png"));
    QVERIFY(writeBytes(ply, "ply"));

    const QString p = session + QStringLiteral("/backup/legacy.json");
    QVERIFY(writeBytes(p, backupJson(QDir::toNativeSeparators(png),
                                     QDir::toNativeSeparators(ply))));

    DataManager dm;
    QVERIFY(dm.loadBackup(p));
    QVERIFY(dm.lastLoadError().isEmpty());
    QCOMPARE(dm.count(), 1);
    QCOMPARE(dm.getRecord(1)->pngPath, QDir::cleanPath(png));
    QCOMPARE(dm.saveDir(), QDir::cleanPath(session));
}

void TestDataManager::pathContainment()
{
    using BackupDocument::isWithinDir;
    using BackupDocument::resolveStoredPath;

    QVERIFY(isWithinDir("C:/sessions/s1", "C:/sessions/s1/1.png"));
    QVERIFY(isWithinDir("C:/sessions/s1", "C:/SESSIONS/S1/1.png"));   // Windows: 大小写不敏感
    QVERIFY(!isWithinDir("C:/sessions/s1", "C:/sessions/s10/1.png")); // 前缀相同但不是后代
    QVERIFY(!isWithinDir("C:/sessions/s1", "C:/sessions/s1/../x.png"));
    QVERIFY(!isWithinDir("C:/sessions/s1", "C:/sessions/s1"));
    QVERIFY(!isWithinDir(QString(), "C:/sessions/s1/1.png"));

    QString out;
    QString err;
    QVERIFY(resolveStoredPath("C:/sessions/s1", QStringLiteral("1.png"), &out, &err));
    QCOMPARE(out, QStringLiteral("C:/sessions/s1/1.png"));
    QVERIFY(resolveStoredPath("C:/sessions/s1", QStringLiteral(".\\sub\\1.png"), &out, &err));
    QCOMPARE(out, QStringLiteral("C:/sessions/s1/sub/1.png"));
    QVERIFY(!resolveStoredPath("C:/sessions/s1", QStringLiteral("../1.png"), &out, &err));
    QVERIFY(!err.isEmpty());
    QVERIFY(!resolveStoredPath("C:/sessions/s1", QStringLiteral("C:/Windows/1.png"), &out, &err));
    QVERIFY(!resolveStoredPath("C:/sessions/s1", QString(), &out, &err));
}

void TestDataManager::clearAllOnlyDeletesInsideSession()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    const QString outside = tmp.path() + QStringLiteral("/outside.png");
    QVERIFY(writeBytes(outside, "must survive"));

    DataManager dm;
    QString saveDir;
    QVERIFY(makeSessionWithOneRecord(dm, tmp.path(), &saveDir));

    const QString png = dm.getRecord(1)->pngPath;
    const QString ply = dm.getRecord(1)->plyPath;
    QVERIFY(QFile::exists(png));
    QVERIFY(QFile::exists(ply));

    dm.clearAll();
    QCOMPARE(dm.count(), 0);
    QVERIFY(!QFile::exists(png));
    QVERIFY(!QFile::exists(ply));
    QVERIFY(QFile::exists(outside));
}

void TestDataManager::findLatestBackupSkipsInvalid()
{
    QTemporaryDir tmp;
    QVERIFY(tmp.isValid());

    const QString session = tmp.path() + QStringLiteral("/session");
    QVERIFY(writeBytes(session + QStringLiteral("/1.png"), "png"));
    QVERIFY(writeBytes(session + QStringLiteral("/1.ply"), "ply"));

    const QString good = session + QStringLiteral("/backup/calibration_data_good.json");
    QVERIFY(writeBytes(good, backupJson("1.png", "1.ply")));

    // Structurally broken but newer: must not win over the intact one.
    const QString bad = session + QStringLiteral("/backup/calibration_data_bad.json");
    QVERIFY(writeBytes(bad, "{\"version\":1,\"records\":[]}"));
    {
        QFile f(bad);
        QVERIFY(f.open(QIODevice::ReadWrite));
        QVERIFY(f.setFileTime(QDateTime::currentDateTime().addSecs(120),
                              QFile::FileModificationTime));
    }

    {
        QFile f(good);
        QVERIFY(f.open(QIODevice::ReadOnly));
        const auto parsed = BackupDocument::parseForSession(f.readAll(), session);
        QVERIFY2(parsed.ok, qPrintable(parsed.error));
    }

    QCOMPARE(DataManager::findLatestBackup(session), QFileInfo(good).absoluteFilePath());
}
