#include "test_measure_frame.h"

#include <QtTest>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>

#include <cmath>
#include <functional>
#include <limits>

#include "logic/MeasureFrame.h"

namespace {

constexpr int kGridW = 4;
constexpr int kGridH = 3;

std::vector<double> sampleGrid()
{
    std::vector<double> g(static_cast<std::size_t>(kGridW) * kGridH * 3, 0.0);
    for (int y = 0; y < kGridH; ++y) {
        for (int x = 0; x < kGridW; ++x) {
            const std::size_t base = (static_cast<std::size_t>(y) * kGridW + x) * 3;
            g[base + 0] = 0.5 * x;
            g[base + 1] = 0.25 * y;
            g[base + 2] = 10.0 + x + y;
        }
    }
    // One invalid cell, like the real grid: NaN must survive the float32 round trip.
    g[7] = std::numeric_limits<double>::quiet_NaN();
    return g;
}

QImage sampleImage()
{
    QImage img(8, 6, QImage::Format_Grayscale8);
    img.fill(0);
    for (int y = 0; y < img.height(); ++y)
        img.scanLine(y)[y % img.width()] = static_cast<uchar>(200);
    return img;
}

MeasureFrame::Manifest sampleManifest()
{
    MeasureFrame::Manifest m;
    m.methodId = QStringLiteral("hole3d");
    m.capturedAt = QStringLiteral("2026-11-02T10:00:00");
    m.note = QStringLiteral("4×3 网格，9 个有效点");
    m.gridW = kGridW;
    m.gridH = kGridH;
    m.rois.append({ 1, 1, 6, 4 });
    m.rows.append({ QStringLiteral("直径"), QStringLiteral("5.0032"),
                    QStringLiteral("mm"), QStringLiteral("高"), 480 });
    m.primaryKey = QStringLiteral("直径");
    m.primaryValue = 5.0032;
    m.hasPrimary = true;
    m.extra.insert(QStringLiteral("coverage"), 0.97);
    m.extra.insert(QStringLiteral("subpixel"), true);
    return m;
}

// Rewrites frame.json in place so a test can corrupt one field at a time.
bool editManifest(const QString& dir, const std::function<void(QJsonObject&)>& edit)
{
    const QString path = QDir(dir).filePath(QString::fromLatin1(MeasureFrame::kManifestName));
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return false;
    QJsonObject root = QJsonDocument::fromJson(f.readAll()).object();
    f.close();
    edit(root);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return false;
    f.write(QJsonDocument(root).toJson());
    return true;
}

} // namespace

void TestMeasureFrame::roundTripKeepsEverything()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    const QString dir = MeasureFrame::suggestDir(base.path(), QStringLiteral("hole3d"),
                                                 QDateTime::currentDateTime());

    QString error;
    QVERIFY2(MeasureFrame::save(dir, sampleManifest(), sampleGrid(), sampleImage(), &error),
             qPrintable(error));

    MeasureFrame::Manifest loaded;
    std::vector<double> grid;
    QImage image;
    QVERIFY2(MeasureFrame::load(dir, &loaded, &grid, &image, &error), qPrintable(error));

    QCOMPARE(loaded.methodId, QStringLiteral("hole3d"));
    QCOMPARE(loaded.gridW, kGridW);
    QCOMPARE(loaded.gridH, kGridH);
    QCOMPARE(loaded.note, QStringLiteral("4×3 网格，9 个有效点"));
    QCOMPARE(loaded.rois.size(), 1);
    QCOMPARE(loaded.rois[0].left, 1);
    QCOMPARE(loaded.rois[0].bottom, 4);
    QCOMPARE(loaded.rows.size(), 1);
    QCOMPARE(loaded.rows[0].method, QStringLiteral("直径"));
    QCOMPARE(loaded.rows[0].value, QStringLiteral("5.0032"));
    QCOMPARE(loaded.rows[0].points, 480);
    QCOMPARE(loaded.primaryKey, QStringLiteral("直径"));
    QVERIFY(loaded.hasPrimary);
    QCOMPARE(loaded.extra.value(QStringLiteral("coverage")).toDouble(), 0.97);
    QCOMPARE(loaded.extra.value(QStringLiteral("subpixel")).toBool(), true);

    QVERIFY(loaded.hasImage);
    QCOMPARE(image.width(), 8);
    QCOMPARE(image.height(), 6);

    QCOMPARE(grid.size(), sampleGrid().size());
    QVERIFY(std::isnan(grid[7]));
    QCOMPARE(grid[0], 0.0);
    QCOMPARE(grid[5], 11.0);   // cell (1,0): z = 10 + 1 + 0
    QCOMPARE(grid[3], 0.5);   // x = 1 -> 0.5, stored as float32
}

void TestMeasureFrame::saveRejectsGridSizeMismatch()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    QString error;
    std::vector<double> tooSmall(3, 1.0);
    QVERIFY(!MeasureFrame::save(MeasureFrame::suggestDir(base.path(), QStringLiteral("flatness"),
                                                         QDateTime::currentDateTime()),
                                sampleManifest(), tooSmall, QImage(), &error));
    QVERIFY(error.contains(QStringLiteral("不一致")));

    MeasureFrame::Manifest noMethod = sampleManifest();
    noMethod.methodId.clear();
    QVERIFY(!MeasureFrame::save(base.path() + QStringLiteral("/no_method"),
                                noMethod, sampleGrid(), QImage(), &error));
    QVERIFY(error.contains(QStringLiteral("方法")));
}

void TestMeasureFrame::loadRejectsManifestGridMismatch()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    const QString dir = base.path() + QStringLiteral("/frame");
    QString error;
    QVERIFY(MeasureFrame::save(dir, sampleManifest(), sampleGrid(), QImage(), &error));

    QVERIFY(editManifest(dir, [](QJsonObject& root) {
        QJsonObject grid = root.value(QStringLiteral("grid")).toObject();
        grid.insert(QStringLiteral("w"), static_cast<double>(kGridW + 1));
        root.insert(QStringLiteral("grid"), grid);
    }));

    MeasureFrame::Manifest loaded;
    std::vector<double> grid;
    QVERIFY(!MeasureFrame::load(dir, &loaded, &grid, nullptr, &error));
    QVERIFY2(error.contains(QStringLiteral("不一致")), qPrintable(error));
}

void TestMeasureFrame::loadRejectsBadGridHeader()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    const QString dir = base.path() + QStringLiteral("/frame");
    QString error;
    QVERIFY(MeasureFrame::save(dir, sampleManifest(), sampleGrid(), QImage(), &error));

    // Overwrite the grid with a broken header: load must refuse rather than
    // pretend the frame is usable.
    QFile bad(QDir(dir).filePath(QString::fromLatin1(MeasureFrame::kGridName)));
    QVERIFY(bad.open(QIODevice::WriteOnly | QIODevice::Truncate));
    bad.write("not a header\n");
    bad.close();

    MeasureFrame::Manifest loaded;
    std::vector<double> grid;
    QVERIFY(!MeasureFrame::load(dir, &loaded, &grid, nullptr, &error));
    QVERIFY2(!error.isEmpty(), "a refusal must come with a readable reason");
    QVERIFY2(error.contains(QStringLiteral("网格")), qPrintable(error));

    // Correct header, truncated payload: also refused.
    QVERIFY(bad.open(QIODevice::WriteOnly | QIODevice::Truncate));
    bad.write("4 3\n");
    bad.write("\0\0\0\0", 4);
    bad.close();
    QVERIFY(!MeasureFrame::load(dir, &loaded, &grid, nullptr, &error));
    QVERIFY2(error.contains(QStringLiteral("长度")), qPrintable(error));
}

void TestMeasureFrame::loadRejectsRoiOutsideImage()
{
    QTemporaryDir base;
    QVERIFY(base.isValid());
    const QString dir = base.path() + QStringLiteral("/frame");
    QString error;
    QVERIFY(MeasureFrame::save(dir, sampleManifest(), sampleGrid(), sampleImage(), &error));

    QVERIFY(editManifest(dir, [](QJsonObject& root) {
        QJsonArray rois = root.value(QStringLiteral("rois")).toArray();
        QJsonObject r = rois.at(0).toObject();
        r.insert(QStringLiteral("right"), 99.0);
        rois.replace(0, r);
        root.insert(QStringLiteral("rois"), rois);
    }));

    MeasureFrame::Manifest loaded;
    std::vector<double> grid;
    QVERIFY(!MeasureFrame::load(dir, &loaded, &grid, nullptr, &error));
    QVERIFY2(error.contains(QStringLiteral("超出图像")), qPrintable(error));
}

void TestMeasureFrame::suggestDirKeepsMethodIdAscii()
{
    const QDateTime when(QDate(2026, 11, 2), QTime(9, 8, 7));
    const QString dir = MeasureFrame::suggestDir(QStringLiteral("D:/data"),
                                                 QStringLiteral("hole3d/../x"),
                                                 when);
    QVERIFY2(dir.endsWith(QStringLiteral("measure_frames/hole3d____x_20261102_090807")),
             qPrintable(dir));

    const QString empty = MeasureFrame::suggestDir(QStringLiteral("D:/data"), QString(), when);
    QVERIFY2(empty.contains(QStringLiteral("measure_20261102_090807")), qPrintable(empty));
}
