#include "test_point_cloud_utils.h"

#include "logic/PointCloudUtils.h"

#include <QtTest>
#include <cmath>

void TestPointCloudUtils::filtersNanAndZeroPoints()
{
    // 4 points: valid, all-zero, NaN-x, all-NaN -> only the first survives
    const double pts[] = {
        0.1f, 0.2f, 0.3f,   // valid
        0.0f, 0.0f, 0.0f,   // zero -> filtered
        NAN,  0.5f, 0.6f,   // NaN x -> filtered
        NAN,  NAN,  NAN     // all NaN -> filtered
    };

    std::vector<float> out, colors;
    PointCloudUtils::filterValidPoints(pts, 4, nullptr, 0, out, colors);

    QCOMPARE(static_cast<int>(out.size()), 3);
    QCOMPARE(static_cast<int>(colors.size()), 3);
    QVERIFY(std::abs(out[0] - 100.0f) < 1e-3f);
    QVERIFY(std::abs(out[1] - 200.0f) < 1e-3f);
    QVERIFY(std::abs(out[2] - 300.0f) < 1e-3f);
}

void TestPointCloudUtils::convertsMetersToMillimeters()
{
    const double pts[] = { 1.0, -2.5, 0.01 };
    std::vector<float> out, colors;
    PointCloudUtils::filterValidPoints(pts, 1, nullptr, 0, out, colors);

    QCOMPARE(static_cast<int>(out.size()), 3);
    QVERIFY(std::abs(out[0] - 1000.0f) < 1e-3f);
    QVERIFY(std::abs(out[1] + 2500.0f) < 1e-3f);
    QVERIFY(std::abs(out[2] - 10.0f) < 1e-3f);
}

void TestPointCloudUtils::extractsBgrColorsAsRgb()
{
    const double pts[] = { 0.1, 0.2, 0.3 };
    // BGR red = (0,0,255) -> RGB (1,0,0); BGR blue = (255,0,0) -> RGB (0,0,1)
    const uint8_t bgr[] = { 0, 0, 255,   255, 0, 0 };

    std::vector<float> out, colors;
    PointCloudUtils::filterValidPoints(pts, 2, bgr, 3, out, colors);

    QCOMPARE(static_cast<int>(colors.size()), 6);
    QVERIFY(std::abs(colors[0] - 1.0f) < 1e-4f);
    QVERIFY(std::abs(colors[1] - 0.0f) < 1e-4f);
    QVERIFY(std::abs(colors[2] - 0.0f) < 1e-4f);
    QVERIFY(std::abs(colors[3] - 0.0f) < 1e-4f);
    QVERIFY(std::abs(colors[4] - 0.0f) < 1e-4f);
    QVERIFY(std::abs(colors[5] - 1.0f) < 1e-4f);
}

void TestPointCloudUtils::usesGrayForMonoImage()
{
    const double pts[] = { 1.0, 1.0, 1.0 };
    const uint8_t mono[] = { 128 };

    std::vector<float> out, colors;
    PointCloudUtils::filterValidPoints(pts, 1, mono, 1, out, colors);

    QCOMPARE(static_cast<int>(colors.size()), 3);
    QVERIFY(std::abs(colors[0] - 128.0f / 255.0f) < 1e-4f);
    QVERIFY(std::abs(colors[1] - 128.0f / 255.0f) < 1e-4f);
    QVERIFY(std::abs(colors[2] - 128.0f / 255.0f) < 1e-4f);
}

void TestPointCloudUtils::defaultsToWhiteWithoutImage()
{
    const double pts[] = { 0.5, 0.5, 0.5 };
    std::vector<float> out, colors;
    PointCloudUtils::filterValidPoints(pts, 1, nullptr, 0, out, colors);

    QCOMPARE(static_cast<int>(colors.size()), 3);
    QVERIFY(std::abs(colors[0] - 1.0f) < 1e-4f);
    QVERIFY(std::abs(colors[1] - 1.0f) < 1e-4f);
    QVERIFY(std::abs(colors[2] - 1.0f) < 1e-4f);
}

void TestPointCloudUtils::projectsLookAtCenterToScreenCenter()
{
    using Vec3 = std::array<float, 3>;
    const Vec3 eye = {{0.0f, 0.0f, 1000.0f}};
    const Vec3 center = {{0.0f, 0.0f, 0.0f}};
    const Vec3 up = {{0.0f, 1.0f, 0.0f}};

    float sx = -1.f, sy = -1.f;
    // The look-at target itself must land exactly on the screen center.
    QVERIFY(PointCloudUtils::projectLookAtToScreen(
        eye, center, up, 800, 600, 30.0f, center, sx, sy));
    QVERIFY(std::abs(sx - 400.0f) < 1e-3f);
    QVERIFY(std::abs(sy - 300.0f) < 1e-3f);
}

void TestPointCloudUtils::projectsOffCenterPointAndRejectsBehindCamera()
{
    using Vec3 = std::array<float, 3>;
    const Vec3 eye = {{0.0f, 0.0f, 1000.0f}};
    const Vec3 center = {{0.0f, 0.0f, 0.0f}};
    const Vec3 up = {{0.0f, 1.0f, 0.0f}};

    // Point 100mm right, 200mm above the view axis, at depth 500mm.
    // focal = 300 / tan(15deg); screenX = 400 + 100*focal/500, screenY = 300 - 200*focal/500.
    const Vec3 pt = {{100.0f, 200.0f, 500.0f}};
    float sx = -1.f, sy = -1.f;
    QVERIFY(PointCloudUtils::projectLookAtToScreen(
        eye, center, up, 800, 600, 30.0f, pt, sx, sy));
    const float focal = 300.0f / std::tan(15.0f * 3.14159265f / 180.0f);
    const float expectedX = 400.0f + 100.0f * focal / 500.0f;
    const float expectedY = 300.0f - 200.0f * focal / 500.0f;
    QVERIFY(std::abs(sx - expectedX) < 1e-2f);
    QVERIFY(std::abs(sy - expectedY) < 1e-2f);

    // Behind the camera -> rejected
    const Vec3 behind = {{0.0f, 0.0f, 1100.0f}};
    QVERIFY(!PointCloudUtils::projectLookAtToScreen(
        eye, center, up, 800, 600, 30.0f, behind, sx, sy));
}
