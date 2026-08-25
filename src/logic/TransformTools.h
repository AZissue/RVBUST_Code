#pragma once

#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

// Pure 4x4 homogeneous-transform helpers for the coordinate-transform /
// robot walk-point validation tool.  No SDK/Qt dependency, unit-tested.
namespace TransformTools {

enum class RotationFormat {
    EulerRpy,            // Static XYZ (RPY): R = Rz(g)*Ry(b)*Rx(a); KUKA ABC / FANUC WPR compatible
    EulerWpr,            // FANUC XYZ-WPR: values order (W, P, R), R = Rz(W)*Ry(P)*Rx(R)
    EulerZyxIntrinsic,   // R = Rx(a)*Ry(b)*Rz(g)
    QuatWxyz,            // rotation values order: w, x, y, z
    QuatXyzw,            // rotation values order: x, y, z, w
    RotationMatrix9,     // 9 values, row-major 3x3
    RotationVector       // axis-angle: vector length = angle (UR style)
};

enum class AngleUnit { Degree, Radian };
enum class Mounting { EyeToHand, EyeInHand };
enum class LengthUnit { Millimeter, Meter };

using Mat4 = std::array<double, 16>; // row-major 4x4 (r00 r01 r02 tx ...)
using Rot3 = std::array<double, 9>;  // row-major 3x3

// Number of raw rotation values a format consumes (3 / 4 / 9).
inline int rotationValueCount(RotationFormat fmt)
{
    switch (fmt) {
    case RotationFormat::EulerRpy:
    case RotationFormat::EulerWpr:
    case RotationFormat::EulerZyxIntrinsic:
    case RotationFormat::RotationVector:
        return 3;
    case RotationFormat::QuatWxyz:
    case RotationFormat::QuatXyzw:
        return 4;
    case RotationFormat::RotationMatrix9:
        return 9;
    }
    throw std::invalid_argument("TransformTools: unknown rotation format");
}

inline Mat4 mul4(const Mat4& a, const Mat4& b)
{
    Mat4 r{};
    for (int row = 0; row < 4; ++row) {
        for (int col = 0; col < 4; ++col) {
            double sum = 0.0;
            for (int k = 0; k < 4; ++k)
                sum += a[row * 4 + k] * b[k * 4 + col];
            r[row * 4 + col] = sum;
        }
    }
    return r;
}

inline void transformPoint(const Mat4& t, double x, double y, double z,
                           double& ox, double& oy, double& oz)
{
    ox = t[0] * x + t[1] * y + t[2] * z + t[3];
    oy = t[4] * x + t[5] * y + t[6] * z + t[7];
    oz = t[8] * x + t[9] * y + t[10] * z + t[11];
}

inline Mat4 makeMat4(const Rot3& rot, double px, double py, double pz)
{
    return Mat4{ rot[0], rot[1], rot[2], px,
                 rot[3], rot[4], rot[5], py,
                 rot[6], rot[7], rot[8], pz,
                 0.0,    0.0,    0.0,    1.0 };
}

inline double toRadians(double v, AngleUnit unit)
{
    return unit == AngleUnit::Degree ? v * 3.14159265358979323846 / 180.0 : v;
}

inline double toMillimeters(double v, LengthUnit unit)
{
    return unit == LengthUnit::Meter ? v * 1000.0 : v;
}

// R = Rz(g) * Ry(b) * Rx(a)  (Static XYZ / RPY).  Angles in radians.
inline Rot3 eulerRpy(double a, double b, double g)
{
    const double ca = std::cos(a), sa = std::sin(a);
    const double cb = std::cos(b), sb = std::sin(b);
    const double cg = std::cos(g), sg = std::sin(g);
    return {
        cb * cg, sa * sb * cg - ca * sg, ca * sb * cg + sa * sg,
        cb * sg, sa * sb * sg + ca * cg, ca * sb * sg - sa * cg,
        -sb,     sa * cb,                ca * cb
    };
}

// R = Rx(a) * Ry(b) * Rz(g)  (ZYX intrinsic).  Angles in radians.
inline Rot3 eulerZyxIntrinsic(double a, double b, double g)
{
    const double ca = std::cos(a), sa = std::sin(a);
    const double cb = std::cos(b), sb = std::sin(b);
    const double cg = std::cos(g), sg = std::sin(g);
    return {
        cb * cg, -cb * sg, sb,
        ca * sg + sa * sb * cg, ca * cg - sa * sb * sg, -sa * cb,
        sa * sg - ca * sb * cg, sa * cg + ca * sb * sg, ca * cb
    };
}

// Unit-quaternion -> rotation matrix.  Degenerate quaternion -> identity.
inline Rot3 quatToRot(double qx, double qy, double qz, double qw)
{
    const double norm = std::sqrt(qx * qx + qy * qy + qz * qz + qw * qw);
    if (norm < 1e-12)
        return { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
    const double x = qx / norm, y = qy / norm, z = qz / norm, w = qw / norm;
    return {
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w),
        2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)
    };
}

// Axis-angle / rotation vector: |v| is the angle (after unit conversion).
inline Rot3 rotationVectorToRot(double rx, double ry, double rz, AngleUnit unit)
{
    const double theta = std::sqrt(rx * rx + ry * ry + rz * rz);
    if (theta < 1e-12)
        return { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
    const double ang = toRadians(theta, unit);
    const double ux = rx / theta, uy = ry / theta, uz = rz / theta;
    const double c = std::cos(ang), s = std::sin(ang), v = 1 - c;
    return {
        ux * ux * v + c,       ux * uy * v - uz * s, ux * uz * v + uy * s,
        uy * ux * v + uz * s,  uy * uy * v + c,      uy * uz * v - ux * s,
        uz * ux * v - uy * s,  uz * uy * v + ux * s, uz * uz * v + c
    };
}

// Build a 3x3 rotation from raw format values.
// Throws std::invalid_argument if the value count does not match the format.
inline Rot3 rotationFromValues(RotationFormat fmt, AngleUnit unit,
                               const std::vector<double>& v)
{
    if (static_cast<int>(v.size()) != rotationValueCount(fmt))
        throw std::invalid_argument("TransformTools: rotation value count mismatch");
    switch (fmt) {
    case RotationFormat::EulerRpy:
        return eulerRpy(toRadians(v[0], unit), toRadians(v[1], unit),
                        toRadians(v[2], unit));
    case RotationFormat::EulerWpr:
        // FANUC XYZ-WPR: W about Z, P about Y, R about X.
        return eulerRpy(toRadians(v[2], unit), toRadians(v[1], unit),
                        toRadians(v[0], unit));
    case RotationFormat::EulerZyxIntrinsic:
        return eulerZyxIntrinsic(toRadians(v[0], unit), toRadians(v[1], unit),
                                 toRadians(v[2], unit));
    case RotationFormat::QuatWxyz:
        return quatToRot(v[1], v[2], v[3], v[0]);
    case RotationFormat::QuatXyzw:
        return quatToRot(v[0], v[1], v[2], v[3]);
    case RotationFormat::RotationMatrix9:
        return Rot3{ v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8] };
    case RotationFormat::RotationVector:
        return rotationVectorToRot(v[0], v[1], v[2], unit);
    }
    throw std::invalid_argument("TransformTools: unknown rotation format");
}

// Build the 4x4 pose matrix from position + raw rotation values.
inline Mat4 poseToMat4(double px, double py, double pz,
                       RotationFormat fmt, AngleUnit unit,
                       const std::vector<double>& rotValues)
{
    return makeMat4(rotationFromValues(fmt, unit, rotValues), px, py, pz);
}

// Eye-to-hand: p_base = T_cam->base * p_cam
inline void eyeToHandPoint(const Mat4& camToBase,
                           double cx, double cy, double cz,
                           double& bx, double& by, double& bz)
{
    transformPoint(camToBase, cx, cy, cz, bx, by, bz);
}

// Eye-in-hand: p_base = T_base->tcp * T_cam->tool * p_cam
inline void eyeInHandPoint(const Mat4& camToTool, const Mat4& baseToTcp,
                           double cx, double cy, double cz,
                           double& bx, double& by, double& bz)
{
    transformPoint(mul4(baseToTcp, camToTool), cx, cy, cz, bx, by, bz);
}

// Unified walk-point dispatcher.
// camTransform: calibration result (camera->base for eye-to-hand,
// camera->tool for eye-in-hand).  baseToTcp is only used for eye-in-hand.
inline void walkPoint(const Mat4& camTransform, Mounting mounting,
                      const Mat4& baseToTcp,
                      double cx, double cy, double cz,
                      double& bx, double& by, double& bz)
{
    if (mounting == Mounting::EyeToHand)
        eyeToHandPoint(camTransform, cx, cy, cz, bx, by, bz);
    else
        eyeInHandPoint(camTransform, baseToTcp, cx, cy, cz, bx, by, bz);
}

} // namespace TransformTools
