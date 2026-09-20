#include "test_pixel_to_3d_service.h"

#include <QtTest>

#include <array>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

#include "logic/PixelTo3DService.h"
#include "logic/PixelTo3DTools.h"

namespace {

// Point k is (k+0.5, k+1.5, k+2.5) so a wrong index is impossible to miss.
std::vector<double> gridCloud(int w, int h)
{
    std::vector<double> xyz;
    xyz.reserve(static_cast<std::size_t>(w) * h * 3);
    for (int k = 0; k < w * h; ++k) {
        xyz.push_back(k + 0.5);
        xyz.push_back(k + 1.5);
        xyz.push_back(k + 2.5);
    }
    return xyz;
}

std::array<double, 3> pointOfIndex(int k)
{
    return { k + 0.5, k + 1.5, k + 2.5 };
}

// Exact (bit-for-bit) comparison: this task is a pure refactor, so the service
// must not even re-round a coordinate.
bool samePoint(const std::array<double, 3>& a, const std::array<double, 3>& b)
{
    return a[0] == b[0] && a[1] == b[1] && a[2] == b[2];
}

} // namespace

void TestPixelTo3DService::hasDataOnlyWhenUsable()
{
    const std::vector<double> xyz = gridCloud(2, 2);

    PixelTo3DService::Source src;
    QVERIFY(!PixelTo3DService::hasData(src));   // no cloud at all

    src.xyzMm = &xyz;
    QVERIFY(!PixelTo3DService::hasData(src));   // image size still 0

    src.imageWidth = 2;
    src.imageHeight = 2;
    QVERIFY(PixelTo3DService::hasData(src));

    const std::vector<double> empty;
    src.xyzMm = &empty;
    QVERIFY(!PixelTo3DService::hasData(src));
}

void TestPixelTo3DService::missingCloudIsNoData()
{
    PixelTo3DService::Source src;
    src.imageWidth = 4;
    src.imageHeight = 3;
    const PixelTo3DService::Query q = PixelTo3DService::query(src, 1, 1);
    QCOMPARE(q.status, PixelTo3DService::Status::NoData);
}

void TestPixelTo3DService::badImageSizeIsNoData()
{
    const std::vector<double> xyz = gridCloud(2, 2);
    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = 0;
    src.imageHeight = 2;
    QCOMPARE(PixelTo3DService::query(src, 0, 0).status,
             PixelTo3DService::Status::NoData);
}

void TestPixelTo3DService::alignedPixelMapsToItsOwnPoint()
{
    const int w = 4;
    const int h = 3;
    const std::vector<double> xyz = gridCloud(w, h);
    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = w;
    src.imageHeight = h;

    // Aligned layout: idx = py * w + px.
    const int px = 2;
    const int py = 1;
    const PixelTo3DService::Query q = PixelTo3DService::query(src, px, py);
    QCOMPARE(q.status, PixelTo3DService::Status::Ok);
    const std::array<double, 3> expected = pointOfIndex(py * w + px);
    QCOMPARE(q.pointMm[0], expected[0]);
    QCOMPARE(q.pointMm[1], expected[1]);
    QCOMPARE(q.pointMm[2], expected[2]);

    // …and bit for bit the same as composing the pure helpers directly.
    std::size_t idx = 0;
    QVERIFY(PixelTo3DTools::alignedIndex(px, py, w, h, idx));
    std::array<double, 3> viaTools{};
    QVERIFY(PixelTo3DTools::pointAt(xyz, idx, viaTools));
    QVERIFY2(samePoint(q.pointMm, viaTools), "service point differs from PixelTo3DTools");
}

void TestPixelTo3DService::alignedOutOfRangePixelIsOutOfRange()
{
    const int w = 4;
    const int h = 3;
    const std::vector<double> xyz = gridCloud(w, h);
    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = w;
    src.imageHeight = h;

    QCOMPARE(PixelTo3DService::query(src, w, 0).status,
             PixelTo3DService::Status::OutOfRange);
    QCOMPARE(PixelTo3DService::query(src, 0, h).status,
             PixelTo3DService::Status::OutOfRange);
    QCOMPARE(PixelTo3DService::query(src, -1, 0).status,
             PixelTo3DService::Status::OutOfRange);
}

void TestPixelTo3DService::alignedInvalidPointIsNoPointAtPixel()
{
    const int w = 4;
    const int h = 3;
    std::vector<double> xyz = gridCloud(w, h);
    const std::size_t idx = 6;                 // pixel (2, 1)
    xyz[idx * 3 + 2] = std::numeric_limits<double>::quiet_NaN();

    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = w;
    src.imageHeight = h;

    QCOMPARE(PixelTo3DService::query(src, 2, 1).status,
             PixelTo3DService::Status::NoPointAtPixel);
}

void TestPixelTo3DService::nonAlignedWithoutIntrinsicsAsksForThem()
{
    // 5 points, image 4x3 -> not aligned, so intrinsics are required.
    std::vector<double> xyz;
    for (int k = 0; k < 5; ++k) {
        xyz.push_back(k + 0.5);
        xyz.push_back(k + 1.5);
        xyz.push_back(1000.0);
    }
    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = 4;
    src.imageHeight = 3;
    src.hasIntrinsics = false;

    QCOMPARE(PixelTo3DService::query(src, 2, 1).status,
             PixelTo3DService::Status::MissingIntrinsics);
}

void TestPixelTo3DService::nonAlignedWithZeroFocalIsInvalid()
{
    std::vector<double> xyz;
    for (int k = 0; k < 5; ++k) {
        xyz.push_back(k + 0.5);
        xyz.push_back(k + 1.5);
        xyz.push_back(1000.0);
    }
    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = 4;
    src.imageHeight = 3;
    src.hasIntrinsics = true;
    src.intrinsics = { 0.0, 100.0, 2.0, 1.5 };

    QCOMPARE(PixelTo3DService::query(src, 2, 1).status,
             PixelTo3DService::Status::InvalidIntrinsics);
}

void TestPixelTo3DService::projectedPathMatchesTheOldComputation()
{
    const int w = 8;
    const int h = 6;
    const PixelTo3DTools::Intrinsics k{ 100.0, 100.0, 3.5, 2.5 };
    // Row-major cloud -> camera transform with a translation, so the service
    // cannot pass by ignoring the extrinsics.
    double ext[16] = { 1, 0, 0, 5.0,
                       0, 1, 0, -3.0,
                       0, 0, 1, 0,
                       0, 0, 0, 1 };

    // Build a cloud whose points project exactly onto pixel centres, but leave
    // one point out so the cloud is *not* the aligned size.
    std::vector<double> xyz;
    for (int py = 0; py < h; ++py) {
        for (int px = 0; px < w; ++px) {
            if (px == w - 1 && py == h - 1)
                continue;
            const double z = 1000.0 + py * 10.0;
            const double xCamera = (px - k.cx) * z / k.fx;
            const double yCamera = (py - k.cy) * z / k.fy;
            xyz.push_back(xCamera - ext[3]);
            xyz.push_back(yCamera - ext[7]);
            xyz.push_back(z);
        }
    }
    QVERIFY(xyz.size() != static_cast<std::size_t>(w) * h * 3);

    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = w;
    src.imageHeight = h;
    src.hasIntrinsics = true;
    src.intrinsics = k;
    src.extrinsics16 = ext;

    const int px = 2;
    const int py = 3;
    const PixelTo3DService::Query q = PixelTo3DService::query(src, px, py);
    QCOMPARE(q.status, PixelTo3DService::Status::Ok);

    // The returned point is the *cloud* point of that pixel, unchanged.
    const std::size_t dropped = static_cast<std::size_t>(px)
        + static_cast<std::size_t>(py) * w;
    const std::size_t cloudIndex = dropped;   // rows before py are complete
    const std::array<double, 3> expected{
        xyz[cloudIndex * 3 + 0], xyz[cloudIndex * 3 + 1], xyz[cloudIndex * 3 + 2]
    };
    QVERIFY2(samePoint(q.pointMm, expected), "projected path returned the wrong cloud point");

    // …and identical to the pre-refactor composition of the pure helpers.
    std::vector<int> index;
    PixelTo3DTools::buildProjectedIndex(xyz, ext, k, w, h, index);
    std::array<double, 3> viaTools{};
    QVERIFY(PixelTo3DTools::queryIndex(index, w, h, px, py, xyz, viaTools));
    QVERIFY2(samePoint(q.pointMm, viaTools), "service point differs from PixelTo3DTools");
}

void TestPixelTo3DService::correspondMapBeatsAlignedLayout()
{
    // 4 points on a 2x2 image would take the aligned path; the correspond map
    // must win, otherwise the online path would silently pick the wrong point.
    const std::vector<double> xyz = gridCloud(2, 2);
    const std::vector<double> cmap = {
        1.2, 1.1,   // point 0 -> pixel (1, 1)
        0.1, 0.2,   // point 1 -> pixel (0, 0)
        1.4, 0.3,   // point 2 -> pixel (1, 0)
        0.4, 1.3    // point 3 -> pixel (0, 1)
    };

    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = 2;
    src.imageHeight = 2;
    src.correspondMap = &cmap;

    const PixelTo3DService::Query q = PixelTo3DService::query(src, 0, 0);
    QCOMPARE(q.status, PixelTo3DService::Status::Ok);
    const std::array<double, 3> expected = pointOfIndex(1);   // not point 0
    QVERIFY2(samePoint(q.pointMm, expected), "correspond map did not beat the aligned layout");
}

void TestPixelTo3DService::correspondMapOutOfRangePixel()
{
    const std::vector<double> xyz = gridCloud(2, 2);
    const std::vector<double> cmap = { 1.2, 1.1, 0.1, 0.2, 1.4, 0.3, 0.4, 1.3 };
    PixelTo3DService::Source src;
    src.xyzMm = &xyz;
    src.imageWidth = 2;
    src.imageHeight = 2;
    src.correspondMap = &cmap;

    QCOMPARE(PixelTo3DService::query(src, 2, 2).status,
             PixelTo3DService::Status::OutOfRange);
}

void TestPixelTo3DService::formatPointKeepsThreeDecimals()
{
    const std::string text =
        PixelTo3DService::formatPoint({ 1.23456, -2.5, 0.0 });
    QCOMPARE(QString::fromStdString(text), QStringLiteral("1.235, -2.500, 0.000"));
}

void TestPixelTo3DService::statusTextIsReadableChinese()
{
    const std::string noPoint = PixelTo3DService::statusText(
        PixelTo3DService::Status::NoPointAtPixel);
    QVERIFY2(QString::fromStdString(noPoint).contains(QStringLiteral("该像素无有效 3D 点")),
             noPoint.c_str());

    // Every status must say something: an empty hint would leave the tool page
    // silently stuck after a failed click.
    const PixelTo3DService::Status all[] = {
        PixelTo3DService::Status::Ok,
        PixelTo3DService::Status::NoData,
        PixelTo3DService::Status::MissingIntrinsics,
        PixelTo3DService::Status::InvalidIntrinsics,
        PixelTo3DService::Status::OutOfRange,
        PixelTo3DService::Status::NoPointAtPixel
    };
    for (PixelTo3DService::Status status : all)
        QVERIFY(!PixelTo3DService::statusText(status).empty());
}
