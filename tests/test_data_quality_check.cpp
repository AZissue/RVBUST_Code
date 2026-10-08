#include "test_data_quality_check.h"

#include "logic/DataQualityCheck.h"

#include <QtTest>
#include <cmath>

namespace {
using Record = DataQualityCheck::Record;

Record mk(double x, double y, double z, double rx, double ry, double rz,
          float err = -1.0f)
{
    Record r;
    r.xyz = { x, y, z };
    r.rpyDeg = { rx, ry, rz };
    r.hasPose = true;
    r.errorPct = err;
    return r;
}
}

void TestDataQualityCheck::parsePoseText()
{
    auto a = DataQualityCheck::recordFromText(QStringLiteral("1 2 3 4 5 6"), -1.0f, 0);
    QVERIFY(a.hasPose);
    QCOMPARE(a.xyz[0], 1.0);
    QCOMPARE(a.xyz[2], 3.0);
    QCOMPARE(a.rpyDeg[1], 5.0);

    auto b = DataQualityCheck::recordFromText(QStringLiteral("1, 2, 3, 4, 5, 6"), -1.0f, 0);
    QVERIFY(b.hasPose);

    QVERIFY(!DataQualityCheck::recordFromText(QStringLiteral("1 2 3"), -1.0f, 0).hasPose);
    QVERIFY(!DataQualityCheck::recordFromText(QStringLiteral("bad data"), -1.0f, 0).hasPose);
}

void TestDataQualityCheck::countEmpty()
{
    const auto rep = DataQualityCheck::run({});
    QCOMPARE(rep.count.level, DataQualityCheck::Level::Fail);
    QVERIFY(rep.overall.contains(QStringLiteral("尚无数据")));
}

void TestDataQualityCheck::countTooFew()
{
    std::vector<Record> rs;
    for (int i = 0; i < 3; ++i) rs.push_back(mk(i * 100, 0, 0, 0, 0, 0));
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.count.level, DataQualityCheck::Level::Fail);
}

void TestDataQualityCheck::countAdvisory()
{
    std::vector<Record> rs;
    for (int i = 0; i < 8; ++i) rs.push_back(mk(i * 100, 0, 0, i * 10, 0, 0));
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.count.level, DataQualityCheck::Level::Warn);
}

void TestDataQualityCheck::countEnough()
{
    std::vector<Record> rs;
    for (int i = 0; i < 20; ++i) rs.push_back(mk(i * 100, 0, 0, i * 10, 0, 0));
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.count.level, DataQualityCheck::Level::Pass);
}

void TestDataQualityCheck::nearDuplicate()
{
    std::vector<Record> rs = { mk(0, 0, 0, 0, 0, 0), mk(0, 0, 0, 0, 0, 0) };
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.nearDup.level, DataQualityCheck::Level::Warn);
    QCOMPARE(rep.nearDup.details.size(), std::size_t{1});
    QCOMPARE(rep.nearDup.frames.size(), std::size_t{2});
    QCOMPARE(rep.nearDup.frames[0], 1);
    QCOMPARE(rep.nearDup.frames[1], 2);
}

void TestDataQualityCheck::noNearDuplicate()
{
    std::vector<Record> rs = { mk(0, 0, 0, 0, 0, 0), mk(200, 200, 200, 0, 0, 0) };
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.nearDup.level, DataQualityCheck::Level::Pass);
}

void TestDataQualityCheck::outlierPosition()
{
    // Four clustered poses + one far pose (frame 5) -> position outlier.
    std::vector<Record> rs = {
        mk(0, 0, 0, 0, 0, 0),
        mk(1, 0, 0, 0, 0, 0),
        mk(0, 1, 0, 0, 0, 0),
        mk(0, 0, 1, 0, 0, 0),
        mk(1000, 0, 0, 0, 0, 0),
    };
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.outlier.level, DataQualityCheck::Level::Warn);
    QCOMPARE(rep.outlier.frames.size(), std::size_t{1});
    QCOMPARE(rep.outlier.frames[0], 5);
}

void TestDataQualityCheck::frameErrorHigh()
{
    std::vector<Record> rs = { mk(0, 0, 0, 0, 0, 0, 8.0f),
                               mk(100, 0, 0, 0, 0, 0, 3.0f),
                               mk(200, 0, 0, 0, 0, 0, -1.0f) };
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.frameError.level, DataQualityCheck::Level::Warn);
    QCOMPARE(rep.frameError.frames.size(), std::size_t{1});
    QCOMPARE(rep.frameError.frames[0], 1);
}

void TestDataQualityCheck::spreadInsufficient()
{
    // All poses identical -> both position and orientation spread are 0.
    std::vector<Record> rs = { mk(0, 0, 0, 0, 0, 0),
                               mk(0, 0, 0, 0, 0, 0),
                               mk(0, 0, 0, 0, 0, 0) };
    const auto rep = DataQualityCheck::run(rs);
    QCOMPARE(rep.spread.level, DataQualityCheck::Level::Warn);
    QCOMPARE(rep.spread.details.size(), std::size_t{2});
}

void TestDataQualityCheck::overallOk()
{
    std::vector<Record> rs = {
        mk(0, 0, 0, 0, 0, 0),
        mk(100, 0, 0, 0, 0, 0),
        mk(0, 100, 0, 0, 0, 0),
        mk(0, 0, 0, 0, 0, 40),
        mk(100, 100, 0, 30, 30, 30),
        mk(200, 0, 0, 0, 40, 0),
    };
    const auto rep = DataQualityCheck::run(rs);
    QVERIFY(rep.overall.contains(QStringLiteral("可用于标定")));
}

// ── 按标定方式选数据源 ────────────────────────────────────────────────

namespace {

using Source = DataQualityCheck::PoseSource;
using Level = DataQualityCheck::Level;

// 3 值的"机器人目标点"记录。
Record mkTarget(const QString& target, const QString& camera = QStringLiteral("0 0 0"))
{
    Record r;
    r.hasPose = DataQualityCheck::parseXyzText(target, r.xyz);
    r.hasCameraTarget = DataQualityCheck::parseXyzText(camera, r.cameraXyz);
    r.errorPct = -1.0f;
    return r;
}

DataQualityCheck::Params targetParams()
{
    DataQualityCheck::Params p;
    p.source = Source::RobotTargetXyz;
    return p;
}

} // namespace

void TestDataQualityCheck::sourceForFollowsCalibrationMode()
{
    // 判据 = DataInputArea 的 hidePose = !eyeInHand && !isMarkerCalib
    QVERIFY(DataQualityCheck::sourceFor(/*eyeInHand*/ false, /*marker*/ false)
            == Source::RobotTargetXyz);   // 眼在手外 + 戳点：唯一的例外
    QVERIFY(DataQualityCheck::sourceFor(true, false) == Source::RobotCapturePose);
    QVERIFY(DataQualityCheck::sourceFor(true, true) == Source::RobotCapturePose);
    QVERIFY(DataQualityCheck::sourceFor(false, true) == Source::RobotCapturePose);

    QVERIFY(!DataQualityCheck::sourceHasOrientation(Source::RobotTargetXyz));
    QVERIFY(DataQualityCheck::sourceHasOrientation(Source::RobotCapturePose));
    QVERIFY(DataQualityCheck::sourceName(Source::RobotTargetXyz)
                .contains(QStringLiteral("机器人目标点")));
}

void TestDataQualityCheck::eyeToHandTouchFlagsIdenticalTargetPoints()
{
    // 用户报告：眼在手外 + 戳点标定 + 同心圆，连续静止采集 15 组一样的数据。
    std::vector<Record> rs;
    for (int i = 0; i < 15; ++i) {
        Record r = mkTarget(QStringLiteral("100 200 300"), QStringLiteral("10 20 300"));
        r.markerCount = 44;
        rs.push_back(r);
    }
    const auto rep = DataQualityCheck::run(rs, targetParams());

    QVERIFY(rep.count.level == Level::Pass);
    QVERIFY(rep.source.level == Level::Pass);
    QVERIFY2(rep.source.summary.contains(QStringLiteral("机器人目标点")),
             qPrintable(rep.source.summary));

    // 15 组完全相同 -> 近重复与分散度都必须报出来。
    QVERIFY(rep.nearDup.level == Level::Warn);
    QVERIFY(rep.spread.level == Level::Warn);
    QVERIFY2(!rep.overall.contains(QStringLiteral("可用于标定")),
             qPrintable(rep.overall));

    // 计数要说真话（C(15,2) = 105 对），明细行要封顶（否则面板被刷满）。
    QVERIFY2(rep.nearDup.summary.contains(QStringLiteral("105")),
             qPrintable(rep.nearDup.summary));
    QVERIFY2(rep.nearDup.details.size() <= 13,
             qPrintable(QStringLiteral("明细行没有封顶：%1 行")
                            .arg(rep.nearDup.details.size())));
    QCOMPARE(rep.nearDup.frames.size(), std::size_t{210});   // 105 对 × 2
}

void TestDataQualityCheck::emptySourceIsFailNotPass()
{
    // 有 6 帧记录，但本方式的数据源整列为空 —— 既不是"通过"，也不是"不适用"。
    std::vector<Record> rs(6);
    const auto rep = DataQualityCheck::run(rs, targetParams());

    QVERIFY(rep.source.level == Level::Fail);
    QVERIFY2(rep.source.summary.contains(QStringLiteral("机器人目标点")),
             qPrintable(rep.source.summary));
    QVERIFY(rep.nearDup.level == Level::NotApplicable);
    QVERIFY(rep.spread.level == Level::NotApplicable);
    QVERIFY(rep.nearDup.level != Level::Pass);
    QVERIFY(rep.spread.level != Level::Pass);
    QVERIFY2(!rep.overall.contains(QStringLiteral("可用于标定")),
             qPrintable(rep.overall));
}

void TestDataQualityCheck::sourceReportsMissingFrames()
{
    std::vector<Record> rs;
    for (int i = 0; i < 5; ++i) {
        if (i == 2)
            rs.push_back(Record{});   // 第 3 组缺数据源
        else
            rs.push_back(mkTarget(QStringLiteral("0 0 0")));
    }
    const auto rep = DataQualityCheck::run(rs);

    QVERIFY(rep.source.level == Level::Warn);
    QCOMPARE(rep.source.frames.size(), std::size_t{1});
    QCOMPARE(rep.source.frames[0], 3);
    QVERIFY2(rep.source.summary.contains(QStringLiteral("5 帧中 4 帧")),
             qPrintable(rep.source.summary));
}

void TestDataQualityCheck::positionOnlySourceSkipsAngleChecks()
{
    std::vector<Record> rs;
    for (int i = 0; i < 3; ++i)
        rs.push_back(mkTarget(QStringLiteral("5 6 7")));

    const auto rep = DataQualityCheck::run(rs, targetParams());

    // 位置分散不足报 1 条；不许再出现"姿态覆盖范围仅 0°，分散不足"。
    QVERIFY(rep.spread.level == Level::Warn);
    QCOMPARE(rep.spread.details.size(), std::size_t{1});
    QVERIFY2(rep.spread.details[0].contains(QStringLiteral("机器人目标点")),
             qPrintable(rep.spread.details[0]));
    QVERIFY2(rep.spread.summary.contains(QStringLiteral("机器人目标点")),
             qPrintable(rep.spread.summary));
}

void TestDataQualityCheck::cameraTargetOutlierDetected()
{
    std::vector<Record> rs;
    for (int i = 0; i < 5; ++i) {
        rs.push_back(mkTarget(QStringLiteral("0 0 0"),
                              i == 3 ? QStringLiteral("900 0 0")
                                     : QStringLiteral("0 0 0")));
    }
    const auto rep = DataQualityCheck::run(rs);

    QVERIFY(rep.cameraTarget.level == Level::Warn);
    QCOMPARE(rep.cameraTarget.frames.size(), std::size_t{1});
    QCOMPARE(rep.cameraTarget.frames[0], 4);
}

void TestDataQualityCheck::markerCountMismatchIsWarned()
{
    const int counts[5] = { 44, 44, 44, 0, 40 };
    std::vector<Record> rs;
    for (int i = 0; i < 5; ++i) {
        Record r = mkTarget(QStringLiteral("0 0 0"));
        r.markerCount = counts[i];
        rs.push_back(r);
    }
    const auto rep = DataQualityCheck::run(rs);

    QVERIFY(rep.detection.level == Level::Warn);
    QCOMPARE(rep.detection.frames.size(), std::size_t{2});
    QCOMPARE(rep.detection.frames[0], 4);
    QCOMPARE(rep.detection.frames[1], 5);
    QVERIFY2(rep.detection.summary.contains(QStringLiteral("44")),
             qPrintable(rep.detection.summary));
}

void TestDataQualityCheck::frameErrorNotApplicableWithoutErrorValues()
{
    std::vector<Record> rs;
    for (int i = 0; i < 6; ++i)
        rs.push_back(mkTarget(QStringLiteral("0 0 0")));   // errorPct = -1

    const auto rep = DataQualityCheck::run(rs);

    QVERIFY(rep.frameError.level == Level::NotApplicable);
    QVERIFY2(!rep.frameError.summary.contains(QStringLiteral("正常")),
             qPrintable(rep.frameError.summary));
}

void TestDataQualityCheck::makeRecordSelectsTheModeColumn()
{
    // 眼在手外 + 戳点：没有拍照位姿，只有机器人目标点 + 相机目标点。
    const auto tcp = DataQualityCheck::makeRecord(
        Source::RobotTargetXyz,
        QString(),                       // robot_capture_pose 是空的
        QStringLiteral("1 2 3"),
        QStringLiteral("4 5 6"), -1.0f, 7);
    QVERIFY(tcp.hasPose);
    QCOMPARE(tcp.xyz[0], 1.0);
    QCOMPARE(tcp.xyz[2], 3.0);
    QVERIFY(tcp.hasCameraTarget);
    QCOMPARE(tcp.cameraXyz[1], 5.0);
    QCOMPARE(tcp.markerCount, 7);
    QCOMPARE(tcp.errorPct, -1.0f);

    // 标定板：拍照位姿（6 值）进 xyz/rpy。
    const auto marker = DataQualityCheck::makeRecord(
        Source::RobotCapturePose,
        QStringLiteral("10 20 30 40 50 60"),
        QStringLiteral("1 2 3"),
        QStringLiteral("4 5 6"), 1.5f, 0);
    QVERIFY(marker.hasPose);
    QCOMPARE(marker.xyz[1], 20.0);
    QCOMPARE(marker.rpyDeg[2], 60.0);
    QCOMPARE(marker.errorPct, 1.5f);
}
