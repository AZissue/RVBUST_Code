#include "test_save_export.h"

#include <QtTest>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTemporaryDir>

#include "logic/CaptureFlow.h"
#include "logic/DataManager.h"

namespace {

// A deterministic way to make the export fail without touching permissions:
// `QSaveFile` cannot replace a path that is an existing *directory*, so parking
// a directory named "pose.txt" inside the session dir breaks exactly the
// marker export and nothing else.
bool breakPoseExport(const QString& saveDir)
{
    return QDir().mkpath(saveDir + QStringLiteral("/pose.txt"));
}

DataManager* makeSavedSession(QTemporaryDir& base, int records = 2)
{
    auto* dm = new DataManager;
    dm->newSession(base.path(), EyeHandMode::EyeInHand, CalibType::Marker);
    for (int i = 0; i < records; ++i) {
        dm->addRecord(QStringLiteral("/tmp/%1.png").arg(i + 1),
                      QStringLiteral("/tmp/%1.ply").arg(i + 1),
                      QStringLiteral("1.0 2.0 3.0"),
                      QStringLiteral("10 20 30 0.1 0.2 0.3"),
                      QStringLiteral("4.0 5.0 6.0"));
    }
    return dm;
}

} // namespace

void TestSaveExport::exportFailureIsReported()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    DataManager* dm = makeSavedSession(base);
    QVERIFY(breakPoseExport(dm->saveDir()));

    QVERIFY2(!dm->writeHandEyeOutput(),
             "a failed export must not be reported as success");
    const QString why = dm->lastExportError();
    QVERIFY2(!why.isEmpty(), "the failure must come with a readable reason");
    QVERIFY2(why.contains(QStringLiteral("pose.txt")),
             qPrintable(QStringLiteral("reason should name the file that failed: ") + why));
    delete dm;
}

void TestSaveExport::exportSuccessStillWrites()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    DataManager* dm = makeSavedSession(base);

    QVERIFY(dm->writeHandEyeOutput());
    QVERIFY(dm->lastExportError().isEmpty());
    QFile f(dm->saveDir() + QStringLiteral("/pose.txt"));
    QVERIFY(f.open(QIODevice::ReadOnly | QIODevice::Text));
    const QStringList lines = QString::fromUtf8(f.readAll())
                                  .split(QLatin1Char('\n'), Qt::SkipEmptyParts);
    QCOMPARE(lines.size(), 2);
    QCOMPARE(lines[0].trimmed(), QStringLiteral("10 20 30 0.1 0.2 0.3"));
    delete dm;
}

void TestSaveExport::captureFlowSurfacesExportFailure()
{
    QTemporaryDir base;
    QTemporaryDir captured;
    QVERIFY(base.isValid() && captured.isValid());

    // The flow copies the captured files into the session dir first; that part
    // must keep working so only the export is broken.
    const QString png = captured.path() + QStringLiteral("/shot.png");
    const QString ply = captured.path() + QStringLiteral("/shot.ply");
    for (const QString& p : { png, ply }) {
        QFile f(p);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("x");
        f.close();
    }

    DataManager dm;
    dm.newSession(base.path(), EyeHandMode::EyeInHand, CalibType::Marker);
    CaptureFlow flow(nullptr, &dm);
    CalibrationMode mode;
    mode.eyeHand = EyeHandMode::EyeInHand;
    mode.calibType = CalibType::Marker;
    flow.setMode(mode);

    QSignalSpy toasts(&flow, &CaptureFlow::toastRequested);
    QSignalSpy logs(&flow, &CaptureFlow::logRequested);
    flow.onCaptureReady(png, ply, {}, {}, QImage());
    QVERIFY(breakPoseExport(dm.saveDir()));
    flow.save(QStringLiteral("1.0 2.0 3.0"),
              QStringLiteral("10 20 30 0.1 0.2 0.3"),
              QStringLiteral("4.0 5.0 6.0"));

    QCOMPARE(dm.count(), 1);   // the data itself is not lost

    bool sawSuccessToast = false, sawFailureToast = false;
    for (const auto& call : toasts) {
        const QString text = call.at(0).toString();
        if (call.at(1).toBool()) {
            sawSuccessToast = true;
        } else if (text.contains(QStringLiteral("pose.txt"))) {
            sawFailureToast = true;
        }
    }
    QVERIFY2(!sawSuccessToast,
             "the operator must not be told 保存成功 when the export failed");
    QVERIFY2(sawFailureToast,
             "the failure toast must name the file that could not be written");

    bool sawErrorLog = false;
    for (const auto& call : logs) {
        const QString level = call.at(1).toString();
        const QString text = call.at(0).toString();
        if (level == QLatin1String("error")
                && text.contains(QStringLiteral("pose.txt")))
            sawErrorLog = true;
    }
    QVERIFY2(sawErrorLog, "the export failure must land in the operation log");
}

void TestSaveExport::undoSurfacesExportFailure()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    DataManager dm;
    dm.newSession(base.path(), EyeHandMode::EyeInHand, CalibType::Marker);
    dm.addRecord(QStringLiteral("/tmp/1.png"), QStringLiteral("/tmp/1.ply"),
                 QStringLiteral("1 2 3"), QStringLiteral("1 2 3 4 5 6"),
                 QStringLiteral("4 5 6"));
    QVERIFY(breakPoseExport(dm.saveDir()));

    CaptureFlow flow(nullptr, &dm);
    CalibrationMode mode;
    mode.eyeHand = EyeHandMode::EyeInHand;
    mode.calibType = CalibType::Marker;
    flow.setMode(mode);
    QSignalSpy toasts(&flow, &CaptureFlow::toastRequested);
    QSignalSpy logs(&flow, &CaptureFlow::logRequested);

    flow.undo();
    QCOMPARE(dm.count(), 0);

    bool sawSuccessToast = false, sawFailureToast = false;
    for (const auto& call : toasts) {
        const QString text = call.at(0).toString();
        if (call.at(1).toBool())
            sawSuccessToast = true;
        else if (text.contains(QStringLiteral("pose.txt")))
            sawFailureToast = true;
    }
    QVERIFY2(!sawSuccessToast, "undo must not claim success when the export failed");
    QVERIFY2(sawFailureToast, "undo must surface the export failure");
    QVERIFY(logs.count() > 0);
}

void TestSaveExport::backupCarriesVersion()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    DataManager* dm = makeSavedSession(base, 1);
    dm->saveBackup(true);

    const QString newest = DataManager::findLatestBackup(base.path());
    QVERIFY(!newest.isEmpty());
    QFile f(newest);
    QVERIFY(f.open(QIODevice::ReadOnly));
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll());
    QVERIFY2(!doc.isNull(), "the backup must be valid JSON on its own");
    QCOMPARE(doc.object().value(QStringLiteral("version")).toInt(), 1);
    delete dm;
}

void TestSaveExport::findLatestBackupSkipsCorrupt()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());

    const QString goodDir = base.path() + QStringLiteral("/calibration_data_aaa/backup");
    QVERIFY(QDir().mkpath(goodDir));
    const QString good = goodDir + QStringLiteral("/calibration_data_1.json");
    {
        QFile f(good);
        QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Text));
        f.write("{\"version\":1,\"records\":[]}");
    }

    // Written second, so it is the newest by mtime — and it is truncated.
    const QString badDir = base.path() + QStringLiteral("/calibration_data_bbb/backup");
    QVERIFY(QDir().mkpath(badDir));
    const QString bad = badDir + QStringLiteral("/calibration_data_2.json");
    {
        QFile f(bad);
        QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Text));
        f.write("{\"version\":1,\"records\":[");
    }

    const QString picked = DataManager::findLatestBackup(base.path());
    QVERIFY2(picked != bad,
             "a truncated backup must not win just because it is the newest file");
    QVERIFY2(picked == good, qPrintable(QStringLiteral("picked: ") + picked));
}
