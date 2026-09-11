#include "test_board_pose_fit.h"

#include "logic/BoardPoseFit.h"
#include "logic/TransformTools.h"

#include <QtTest>
#include <cmath>

namespace {
using Pt = std::array<float, 3>;
}

void TestBoardPoseFit::fitXyPlane()
{
    // A 2x3 grid on the z=100 plane (x in 0..1, y in 0..2) -> normal +z.
    std::vector<Pt> pts = {
        { 0, 0, 100 }, { 1, 0, 100 }, { 0, 1, 100 },
        { 1, 1, 100 }, { 0, 2, 100 }, { 1, 2, 100 },
    };
    const auto p = BoardPoseFit::fit(pts);
    QVERIFY(p.valid);
    QVERIFY(std::abs(p.center[0] - 0.5f) < 1e-3f);
    QVERIFY(std::abs(p.center[1] - 1.0f) < 1e-3f);
    QVERIFY(std::abs(p.center[2] - 100.0f) < 1e-3f);
    // Normal is unit and points along +z.
    QVERIFY(std::abs(p.normal[2] - 1.0f) < 1e-3f);
    QVERIFY(std::abs(p.normal[0]) < 1e-3f);
    QVERIFY(std::abs(p.normal[1]) < 1e-3f);
    // Extents: long axis (y range 2) + short axis (x range 1).
    QVERIFY(std::abs((p.extentX + p.extentY) - 3.0f) < 0.01f);
    QVERIFY(std::abs(p.extentX - 2.0f) < 0.01f);
    QVERIFY(std::abs(p.extentY - 1.0f) < 0.01f);
}

void TestBoardPoseFit::fitTiltedPlane()
{
    // Rotate the z=100 plane by 90° about X -> points have constant y = -100.
    std::vector<Pt> pts = {
        { 0, -100, 0 }, { 1, -100, 0 }, { 0, -100, 1 },
        { 1, -100, 1 }, { 0, -100, 2 }, { 1, -100, 2 },
    };
    const auto p = BoardPoseFit::fit(pts);
    QVERIFY(p.valid);
    // Normal is along +-Y (magnitude 1, negligible x/z components).
    QVERIFY(std::abs(std::abs(p.normal[1]) - 1.0f) < 1e-3f);
    QVERIFY(std::abs(p.normal[0]) < 1e-3f);
    QVERIFY(std::abs(p.normal[2]) < 1e-3f);
    // Center on the plane.
    QVERIFY(std::abs(p.center[1] - (-100.0f)) < 1e-3f);
}

void TestBoardPoseFit::fitDegenerate()
{
    QVERIFY(!BoardPoseFit::fit({}).valid);
    QVERIFY(!BoardPoseFit::fit({ { 0, 0, 0 }, { 1, 1, 1 } }).valid);
}

void TestBoardPoseFit::fitSkipsInvalidPoints()
{
    std::vector<Pt> pts = {
        { 0, 0, 100 }, { 1, 0, 100 }, { 0, 1, 100 },
        { 1, 1, 100 },
        { 0, 0, 0 },                       // zero-padded tail
        { std::nanf(""), 0, 0 },           // NaN
    };
    const auto p = BoardPoseFit::fit(pts);
    QVERIFY(p.valid);
    QVERIFY(std::abs(p.center[0] - 0.5f) < 1e-3f);
    QVERIFY(std::abs(p.center[1] - 0.5f) < 1e-3f);
    QVERIFY(std::abs(p.center[2] - 100.0f) < 1e-3f);
}

void TestBoardPoseFit::quatRoundtrip()
{
    std::vector<Pt> pts = {
        { 0, 0, 100 }, { 1, 0, 100 }, { 0, 1, 100 }, { 1, 1, 100 },
    };
    const auto p = BoardPoseFit::fit(pts);
    QVERIFY(p.valid);
    // Reconstruct the rotation matrix from the (x,y,z,w) quaternion and check
    // its third column equals the fitted normal (matches TransformTools order).
    const TransformTools::Rot3 r = TransformTools::quatToRot(
        p.quat[0], p.quat[1], p.quat[2], p.quat[3]);
    QVERIFY(std::abs(r[2] - p.normal[0]) < 1e-3f);
    QVERIFY(std::abs(r[5] - p.normal[1]) < 1e-3f);
    QVERIFY(std::abs(r[8] - p.normal[2]) < 1e-3f);
}
