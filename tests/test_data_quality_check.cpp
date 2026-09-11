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
