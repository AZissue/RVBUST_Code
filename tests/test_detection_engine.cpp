#include "test_detection_engine.h"

#include "logic/DetectionEngine.h"

#include <QtTest>
#include <QDebug>
#include <cmath>
#include <array>
#include <tuple>

using Vec3f = std::array<float, 3>;
using Vec2f = std::pair<float, float>;

void TestDetectionEngine::formatXyzForCardSkipsNanAndPicksFirstValid()
{
    std::vector<Vec3f> pts = {
        {{ NAN, 1.0f, 2.0f }},
        {{ 3.0f, 4.0f, 5.0f }},
        {{ 6.0f, 7.0f, 8.0f }}
    };
    QCOMPARE(QString::fromStdString(DetectionEngine::formatXyzForCard(pts)),
             QStringLiteral("3.000 4.000 5.000"));
}

void TestDetectionEngine::formatXyzForCardReturnsEmptyForNoValidPoints()
{
    QCOMPARE(QString::fromStdString(DetectionEngine::formatXyzForCard({})), QString());

    std::vector<Vec3f> allNan = {{{ NAN, NAN, NAN }}};
    QCOMPARE(QString::fromStdString(DetectionEngine::formatXyzForCard(allNan)), QString());
}

void TestDetectionEngine::formatXyzForCardFormatsThreeDecimals()
{
    std::vector<Vec3f> pts = {{{ 1.23456f, -2.5f, 3.0f }}};
    QCOMPARE(QString::fromStdString(DetectionEngine::formatXyzForCard(pts)),
             QStringLiteral("1.235 -2.500 3.000"));
}

void TestDetectionEngine::formatMarkersForOverlayLabelsAndHighlights()
{
    std::vector<Vec2f> pts2d = {
        { 10.0f, 20.0f },
        { 30.0f, 40.0f }
    };
    std::vector<Vec3f> pts3d = {
        {{ 1.0f, 2.0f, 3.0f }},
        {{ NAN, NAN, NAN }}
    };

    auto overlay = DetectionEngine::formatMarkersForOverlay(pts2d, pts3d);

    QCOMPARE(static_cast<int>(overlay.overlay2d.size()), 2);
    QCOMPARE(QString::fromStdString(std::get<2>(overlay.overlay2d[0])), QStringLiteral("0"));
    QCOMPARE(QString::fromStdString(std::get<2>(overlay.overlay2d[1])), QStringLiteral("1"));
    QVERIFY(std::abs(std::get<0>(overlay.overlay2d[1]) - 30.0f) < 1e-4f);

    // NaN 3D point must not produce a highlight
    QCOMPARE(static_cast<int>(overlay.highlights3d.size()), 1);
    QVERIFY(std::abs(overlay.highlights3d[0][0] - 1.0f) < 1e-4f);
    // Highlight indices keep the original 2D label even when a NaN 3D point
    // is skipped (marker 0 -> label 0; NaN marker 1 is dropped).
    QCOMPARE(static_cast<int>(overlay.highlightIndices.size()), 1);
    QCOMPARE(overlay.highlightIndices[0], 0);
}

void TestDetectionEngine::firstValidPoint3dSkipsNan()
{
    std::vector<Vec3f> pts = {
        {{ NAN, 1.0f, 2.0f }},
        {{ 3.0f, 4.0f, 5.0f }},
        {{ 6.0f, 7.0f, 8.0f }}
    };
    const auto origin = DetectionEngine::firstValidPoint3d(pts);
    QCOMPARE(static_cast<int>(origin.size()), 3);
    QVERIFY(std::abs(origin[0] - 3.0f) < 1e-4f);
    QVERIFY(std::abs(origin[1] - 4.0f) < 1e-4f);
    QVERIFY(std::abs(origin[2] - 5.0f) < 1e-4f);
}

void TestDetectionEngine::firstValidPoint3dReturnsEmpty()
{
    QVERIFY(DetectionEngine::firstValidPoint3d({}).empty());
    std::vector<Vec3f> allNan = {{{ NAN, NAN, NAN }}};
    QVERIFY(DetectionEngine::firstValidPoint3d(allNan).empty());
}

void TestDetectionEngine::countValidPoints2DCountsLeadingValid()
{
    // Flat [x,y,...] pairs; the detection API zero-pads the tail.
    const std::vector<float> px = {
        10.0f, 20.0f,
        30.0f, 40.0f,
        0.0f, 0.0f,     // stop here
        50.0f, 60.0f    // ignored
    };
    QCOMPARE(DetectionEngine::countValidPoints2D(px, 4), 2);

    // NaN also stops counting
    const std::vector<float> withNan = {
        1.0f, 2.0f,
        NAN, 3.0f,
        4.0f, 5.0f
    };
    QCOMPARE(DetectionEngine::countValidPoints2D(withNan, 3), 1);

    // maxPoints bounds the scan
    QCOMPARE(DetectionEngine::countValidPoints2D(px, 1), 1);
    QCOMPARE(DetectionEngine::countValidPoints2D({}, 4), 0);
}

void TestDetectionEngine::detectConcentricRegressionOnTestData()
{
    if (qEnvironmentVariableIsEmpty("HAND_EYE_TEST_REGRESSION"))
        QSKIP("Set HAND_EYE_TEST_REGRESSION=1 to run the file-based SDK regression");

    const QString png = QString::fromUtf8(TEST_DATA_DIR "/0.png");
    const QString ply = QString::fromUtf8(TEST_DATA_DIR "/0.ply");

    std::pair<std::vector<Vec2f>, std::vector<Vec3f>> result;
    bool threw = false;
    try {
        result = DetectionEngine::detectConcentric(png.toStdString(), ply.toStdString());
    } catch (...) {
        threw = true;
    }

    QVERIFY2(!threw, "detectConcentric must not throw on test_data samples");
    QCOMPARE(result.first.size(), result.second.size());
    for (const auto& p : result.second) {
        QVERIFY(!std::isnan(p[0]) && !std::isnan(p[1]) && !std::isnan(p[2]));
    }
    qInfo("detectConcentric on 0.png/0.ply returned %d markers",
          static_cast<int>(result.first.size()));
}
