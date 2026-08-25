#include "test_transform_tools.h"

#include "logic/TransformTools.h"

#include <QtTest>
#include <cmath>
#include <stdexcept>
#include <vector>

using namespace TransformTools;

namespace {

const double kPi = 3.14159265358979323846;
const double kEps = 1e-9;

bool near(double a, double b, double eps = kEps)
{
    return std::abs(a - b) < eps;
}

bool mat4Near(const Mat4& a, const Mat4& b, double eps = kEps)
{
    for (size_t i = 0; i < a.size(); ++i)
        if (!near(a[i], b[i], eps))
            return false;
    return true;
}

bool rot3Near(const Rot3& a, const Rot3& b, double eps = kEps)
{
    for (size_t i = 0; i < a.size(); ++i)
        if (!near(a[i], b[i], eps))
            return false;
    return true;
}

Mat4 translate(double x, double y, double z)
{
    return Mat4{ 1, 0, 0, x,
                 0, 1, 0, y,
                 0, 0, 1, z,
                 0, 0, 0, 1 };
}

} // namespace

void TestTransformTools::mul4Identity()
{
    const Mat4 id{ 1, 0, 0, 0,
                   0, 1, 0, 0,
                   0, 0, 1, 0,
                   0, 0, 0, 1 };
    const Mat4 a = translate(1, 2, 3);
    QVERIFY(mat4Near(mul4(id, a), a));
    QVERIFY(mat4Near(mul4(a, id), a));
}

void TestTransformTools::mul4TranslationComposition()
{
    // T(1,2,3) * T(10,20,30) == T(11,22,33)
    QVERIFY(mat4Near(mul4(translate(1, 2, 3), translate(10, 20, 30)),
                     translate(11, 22, 33)));
}

void TestTransformTools::transformPointPureTranslation()
{
    double x = 0, y = 0, z = 0;
    transformPoint(translate(5, 6, 7), 1, 1, 1, x, y, z);
    QVERIFY(near(x, 6) && near(y, 7) && near(z, 8));
}

void TestTransformTools::makeMat4Assembly()
{
    const Mat4 m = makeMat4({ 1, 0, 0,
                              0, 1, 0,
                              0, 0, 1 },
                            1, 2, 3);
    QVERIFY(near(m[0], 1) && near(m[5], 1) && near(m[10], 1));
    QVERIFY(near(m[3], 1) && near(m[7], 2) && near(m[11], 3));
    QVERIFY(near(m[12], 0) && near(m[13], 0) && near(m[14], 0) && near(m[15], 1));
}

void TestTransformTools::toRadians()
{
    QVERIFY(near(TransformTools::toRadians(180.0, AngleUnit::Degree), kPi));
    QVERIFY(near(TransformTools::toRadians(90.0, AngleUnit::Degree), kPi / 2.0));
    QVERIFY(near(TransformTools::toRadians(1.25, AngleUnit::Radian), 1.25));
}

void TestTransformTools::eulerRpyKnownAngles()
{
    // Static XYZ (RPY): R = Rz(g) * Ry(b) * Rx(a).
    // Rx(90): +Y -> +Z, +Z -> -Y
    const Rot3 rx90 = eulerRpy(kPi / 2.0, 0, 0);
    QVERIFY(rot3Near(rx90, { 1, 0, 0,
                             0, 0, -1,
                             0, 1, 0 }));
    // Ry(90): +X -> -Z, +Z -> +X
    const Rot3 ry90 = eulerRpy(0, kPi / 2.0, 0);
    QVERIFY(rot3Near(ry90, { 0, 0, 1,
                             0, 1, 0,
                             -1, 0, 0 }));
    // ZYX intrinsic: Rz(90) maps +X -> +Y, +Y -> -X
    const Rot3 rz90 = eulerZyxIntrinsic(0, 0, kPi / 2.0);
    QVERIFY(rot3Near(rz90, { 0, -1, 0,
                             1, 0, 0,
                             0, 0, 1 }));
}

void TestTransformTools::eulerWprKnownAngles()
{
    // FANUC XYZ-WPR: values order (W, P, R), R = Rz(W) * Ry(P) * Rx(R).
    // W = rotation about Z: 90 deg maps +X -> +Y
    const Rot3 rz90 = rotationFromValues(RotationFormat::EulerWpr,
                                         AngleUnit::Degree, { 90, 0, 0 });
    QVERIFY(rot3Near(rz90, { 0, -1, 0,
                             1, 0, 0,
                             0, 0, 1 }));
    // P = rotation about Y: 90 deg maps +X -> -Z
    const Rot3 ry90 = rotationFromValues(RotationFormat::EulerWpr,
                                         AngleUnit::Degree, { 0, 90, 0 });
    QVERIFY(rot3Near(ry90, { 0, 0, 1,
                             0, 1, 0,
                             -1, 0, 0 }));
    // R = rotation about X: 90 deg maps +Y -> +Z
    const Rot3 rx90 = rotationFromValues(RotationFormat::EulerWpr,
                                         AngleUnit::Degree, { 0, 0, 90 });
    QVERIFY(rot3Near(rx90, { 1, 0, 0,
                             0, 0, -1,
                             0, 1, 0 }));
}

void TestTransformTools::eulerRpyDegreeMatchesRadian()
{
    const Rot3 deg = rotationFromValues(RotationFormat::EulerRpy,
                                        AngleUnit::Degree, { 30, 60, 45 });
    const Rot3 rad = rotationFromValues(RotationFormat::EulerRpy,
                                        AngleUnit::Radian,
                                        { 30 * kPi / 180.0, 60 * kPi / 180.0, 45 * kPi / 180.0 });
    QVERIFY(rot3Near(deg, rad));
}

void TestTransformTools::toMillimetersConversion()
{
    QVERIFY(near(TransformTools::toMillimeters(1.0, LengthUnit::Meter), 1000.0));
    QVERIFY(near(TransformTools::toMillimeters(0.60411, LengthUnit::Meter), 604.11));
    QVERIFY(near(TransformTools::toMillimeters(505.55, LengthUnit::Millimeter), 505.55));
}

void TestTransformTools::quatToRotNormalized()
{
    // Non-unit quaternion must give the same rotation as its normalized version.
    QVERIFY(rot3Near(quatToRot(0, 0, 2, 0), quatToRot(0, 0, 1, 0)));
    // Degenerate quaternion -> identity rotation (safe default).
    QVERIFY(rot3Near(quatToRot(0, 0, 0, 0), { 1, 0, 0,
                                              0, 1, 0,
                                              0, 0, 1 }));
}

void TestTransformTools::quatMatchesRotationVector()
{
    // 90 deg about Z: quaternion (w,z) = (sqrt(0.5), sqrt(0.5))
    // equals rotation vector (0,0,pi/2).
    const double s = std::sqrt(0.5);
    const Rot3 q = quatToRot(0, 0, s, s);
    const Rot3 v = rotationVectorToRot(0, 0, kPi / 2.0, AngleUnit::Radian);
    QVERIFY(rot3Near(q, v));
    QVERIFY(rot3Near(q, { 0, -1, 0,
                          1, 0, 0,
                          0, 0, 1 }));
}

void TestTransformTools::rotationOrthonormal()
{
    const Rot3 r = eulerRpy(0.3, -0.7, 1.2);
    Rot3 rrt{};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k)
                sum += r[i * 3 + k] * r[j * 3 + k];
            rrt[i * 3 + j] = sum;
        }
    QVERIFY(rot3Near(rrt, { 1, 0, 0,
                            0, 1, 0,
                            0, 0, 1 }, 1e-8));
    const double det = r[0] * (r[4] * r[8] - r[5] * r[7])
                     - r[1] * (r[3] * r[8] - r[5] * r[6])
                     + r[2] * (r[3] * r[7] - r[4] * r[6]);
    QVERIFY(near(det, 1.0, 1e-8));
}

void TestTransformTools::rotationFromValuesQuaternionOrders()
{
    // Same components, different declared order -> same rotation matrix.
    const Rot3 wxyz = rotationFromValues(RotationFormat::QuatWxyz,
                                         AngleUnit::Radian, { 0.5, 0.5, 0.5, 0.5 });
    const Rot3 xyzw = rotationFromValues(RotationFormat::QuatXyzw,
                                         AngleUnit::Radian, { 0.5, 0.5, 0.5, 0.5 });
    QVERIFY(rot3Near(wxyz, quatToRot(0.5, 0.5, 0.5, 0.5)));
    QVERIFY(rot3Near(wxyz, xyzw));
}

void TestTransformTools::rotationFromValuesMatrixPassthrough()
{
    const Rot3 m = rotationFromValues(RotationFormat::RotationMatrix9,
                                      AngleUnit::Radian,
                                      { 0, 0, 1,
                                        0, 1, 0,
                                        -1, 0, 0 });
    QVERIFY(rot3Near(m, { 0, 0, 1,
                          0, 1, 0,
                          -1, 0, 0 }));
}

void TestTransformTools::rotationFromValuesRejectsWrongCount()
{
    QVERIFY_EXCEPTION_THROWN(
        rotationFromValues(RotationFormat::EulerRpy, AngleUnit::Degree, { 1, 2 }),
        std::invalid_argument);
    QVERIFY_EXCEPTION_THROWN(
        rotationFromValues(RotationFormat::QuatWxyz, AngleUnit::Degree, { 1, 2, 3 }),
        std::invalid_argument);
    QVERIFY_EXCEPTION_THROWN(
        rotationFromValues(RotationFormat::RotationMatrix9, AngleUnit::Degree,
                           { 1, 2, 3, 4, 5, 6, 7, 8 }),
        std::invalid_argument);
    QVERIFY_EXCEPTION_THROWN(
        rotationFromValues(RotationFormat::RotationVector, AngleUnit::Degree, { 1, 2, 3, 4 }),
        std::invalid_argument);
}

void TestTransformTools::rotationValueCounts()
{
    QCOMPARE(rotationValueCount(RotationFormat::EulerRpy), 3);
    QCOMPARE(rotationValueCount(RotationFormat::EulerWpr), 3);
    QCOMPARE(rotationValueCount(RotationFormat::EulerZyxIntrinsic), 3);
    QCOMPARE(rotationValueCount(RotationFormat::QuatWxyz), 4);
    QCOMPARE(rotationValueCount(RotationFormat::QuatXyzw), 4);
    QCOMPARE(rotationValueCount(RotationFormat::RotationMatrix9), 9);
    QCOMPARE(rotationValueCount(RotationFormat::RotationVector), 3);
}

void TestTransformTools::poseToMat4TranslationAndRotation()
{
    // 90 deg Rx + translation (1,2,3): y-axis point maps to (1, 2, 4).
    const Mat4 pose = poseToMat4(1, 2, 3, RotationFormat::EulerRpy,
                                 AngleUnit::Degree, { 90, 0, 0 });
    double x = 0, y = 0, z = 0;
    transformPoint(pose, 0, 1, 0, x, y, z);
    QVERIFY(near(x, 1) && near(y, 2) && near(z, 4));
}

void TestTransformTools::eyeToHandPoint()
{
    double bx = 0, by = 0, bz = 0;
    TransformTools::eyeToHandPoint(translate(5, 6, 7), 1, 1, 1, bx, by, bz);
    QVERIFY(near(bx, 6) && near(by, 7) && near(bz, 8));
}

void TestTransformTools::eyeInHandPoint()
{
    // p_base = T_base->tcp * T_cam->tool * p_cam
    double bx = 0, by = 0, bz = 0;
    TransformTools::eyeInHandPoint(translate(10, 0, 0), translate(1, 2, 3),
                                   0, 0, 0, bx, by, bz);
    QVERIFY(near(bx, 11) && near(by, 2) && near(bz, 3));
}

void TestTransformTools::walkPointDispatch()
{
    double bx = 0, by = 0, bz = 0;
    // Eye-to-hand: calibration matrix already maps camera -> base.
    walkPoint(translate(5, 6, 7), Mounting::EyeToHand, translate(0, 0, 0),
              1, 1, 1, bx, by, bz);
    QVERIFY(near(bx, 6) && near(by, 7) && near(bz, 8));
    // Eye-in-hand: compose base->tcp with cam->tool.
    walkPoint(translate(10, 0, 0), Mounting::EyeInHand, translate(1, 2, 3),
              0, 0, 0, bx, by, bz);
    QVERIFY(near(bx, 11) && near(by, 2) && near(bz, 3));
}

void TestTransformTools::rotationVectorZeroIsIdentity()
{
    QVERIFY(rot3Near(rotationVectorToRot(0, 0, 0, AngleUnit::Degree),
                     { 1, 0, 0,
                       0, 1, 0,
                       0, 0, 1 }));
}
