#include "test_data_manager.h"

#include "logic/DataManager.h"

#include <QtTest>
#include <QTemporaryDir>
#include <QFile>
#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>

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
