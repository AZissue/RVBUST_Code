#include "test_pose_guide.h"

#include "logic/PoseGuide.h"

#include <QtTest>
#include <cmath>

namespace {
PoseGuide::Pose mk(double x, double y, double z, double rx, double ry, double rz)
{
    PoseGuide::Pose p;
    p.xyz = { x, y, z };
    p.rpyDeg = { rx, ry, rz };
    return p;
}
}

void TestPoseGuide::translationBasic()
{
    QVERIFY(std::abs(PoseGuide::translationMm(mk(0, 0, 0, 0, 0, 0),
                                              mk(3, 4, 0, 0, 0, 0)) - 5.0) < 1e-9);
    QVERIFY(std::abs(PoseGuide::translationMm(mk(1, 2, 3, 0, 0, 0),
                                              mk(4, 6, 3, 0, 0, 0)) - 5.0) < 1e-9);
    QVERIFY(PoseGuide::translationMm(mk(1, 1, 1, 0, 0, 0), mk(1, 1, 1, 0, 0, 0)) == 0.0);
}

void TestPoseGuide::rotationIdentity()
{
    QVERIFY(PoseGuide::rotationAngleDeg(mk(0, 0, 0, 10, 20, 30),
                                        mk(0, 0, 0, 10, 20, 30)) < 1e-9);
}

void TestPoseGuide::rotation90Z()
{
    // 90° about Z: (rx,ry,rz) = (0,0,90) -> minimal angle == 90°.
    QVERIFY(std::abs(PoseGuide::rotationAngleDeg(mk(0, 0, 0, 0, 0, 0),
                                                 mk(0, 0, 0, 0, 0, 90)) - 90.0) < 1e-6);
}

void TestPoseGuide::rotationSymmetric()
{
    const double ab = PoseGuide::rotationAngleDeg(mk(0, 0, 0, 5, -10, 30),
                                                  mk(0, 0, 0, 80, 15, 5));
    const double ba = PoseGuide::rotationAngleDeg(mk(0, 0, 0, 80, 15, 5),
                                                  mk(0, 0, 0, 5, -10, 30));
    QVERIFY(std::abs(ab - ba) < 1e-9);
}

void TestPoseGuide::guideEmpty()
{
    const auto g = PoseGuide::guide(mk(1, 2, 3, 0, 0, 0), {});
    QVERIFY(!g.hasReference);
    QVERIFY(!g.tooClose);
}

void TestPoseGuide::guideTooClose()
{
    // Identical pose -> close in both translation and orientation.
    const auto g = PoseGuide::guide(mk(1, 2, 3, 0, 0, 0),
                                    { mk(1, 2, 3, 0, 0, 0) });
    QVERIFY(g.hasReference);
    QVERIFY(g.tooClose);
    QVERIFY(g.distanceMm < 1e-9);
}

void TestPoseGuide::guideFarPosition()
{
    // Far in position (100mm), close in orientation -> NOT too close.
    const auto g = PoseGuide::guide(mk(100, 0, 0, 0, 0, 0),
                                    { mk(0, 0, 0, 0, 0, 0) });
    QVERIFY(g.hasReference);
    QVERIFY(!g.tooClose);
    QVERIFY(std::abs(g.distanceMm - 100.0) < 1e-9);
}

void TestPoseGuide::guideFarAngle()
{
    // Close in position, far in orientation (30°) -> NOT too close.
    const auto g = PoseGuide::guide(mk(0, 0, 0, 0, 0, 30),
                                    { mk(0, 0, 0, 0, 0, 0) });
    QVERIFY(g.hasReference);
    QVERIFY(!g.tooClose);
    QVERIFY(std::abs(g.angleDeg - 30.0) < 1e-6);
}

void TestPoseGuide::guideBoundary()
{
    // Exactly at the thresholds (50mm, 15°) -> strict "<" -> not too close.
    const auto g = PoseGuide::guide(mk(50, 0, 0, 0, 0, 15),
                                    { mk(0, 0, 0, 0, 0, 0) });
    QVERIFY(!g.tooClose);
}
