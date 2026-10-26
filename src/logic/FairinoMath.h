#pragma once

// ── 法奥位姿数学（纯函数）─────────────────────────────────────────────
//
// 法奥的笛卡尔位姿是 [x,y,z,rx,ry,rz]：位置 mm，姿态是**绕基座固定轴**的
// 欧拉角（度）。官方手册给出的齐次矩阵旋转顺序是 ZYX（浮动坐标系），即
//
//     R = Rz(rz) · Ry(ry) · Rx(rx)
//
// 与本程序卡片/坐标转换工具使用的 static-XYZ（RPY）完全一致，所以读取位姿
// 不需要任何角度换算 —— 但点动 RX/RY/RZ 不是"给欧拉角分量加一个数"：
// 旋转不可交换。控制台要求"绕基座轴转 delta 度"，正确做法是
//
//     R_new = R_delta(base axis) · R_current
//
// 再把 R_new 分解回 RPY。这里就是这套运算，附万向锁（ry = ±90°）处理。
#include <algorithm>
#include <array>
#include <cmath>

namespace FairinoMath {

using Vec3 = std::array<double, 3>;
using Pose6 = std::array<double, 6>;
using Mat3 = std::array<double, 9>;   // row-major

constexpr double kPi = 3.14159265358979323846;
constexpr double kDegToRad = kPi / 180.0;
constexpr double kRadToDeg = 180.0 / kPi;

inline Mat3 identity()
{
    return Mat3{ 1, 0, 0, 0, 1, 0, 0, 0, 1 };
}

inline Mat3 multiply(const Mat3& a, const Mat3& b)
{
    Mat3 out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            double sum = 0.0;
            for (int k = 0; k < 3; ++k)
                sum += a[static_cast<std::size_t>(r * 3 + k)]
                     * b[static_cast<std::size_t>(k * 3 + c)];
            out[static_cast<std::size_t>(r * 3 + c)] = sum;
        }
    }
    return out;
}

inline Mat3 fromRows(const Vec3& r0, const Vec3& r1, const Vec3& r2)
{
    return Mat3{ r0[0], r0[1], r0[2], r1[0], r1[1], r1[2], r2[0], r2[1], r2[2] };
}

// R = Rz(rz) · Ry(ry) · Rx(rx)，角度为度。
inline Mat3 eulerDegToMatrix(const Vec3& rpyDeg)
{
    const double a = rpyDeg[0] * kDegToRad;
    const double b = rpyDeg[1] * kDegToRad;
    const double g = rpyDeg[2] * kDegToRad;
    const double ca = std::cos(a), sa = std::sin(a);
    const double cb = std::cos(b), sb = std::sin(b);
    const double cg = std::cos(g), sg = std::sin(g);
    return fromRows(
        Vec3{ cb * cg, sa * sb * cg - ca * sg, ca * sb * cg + sa * sg },
        Vec3{ cb * sg, sa * sb * sg + ca * cg, ca * sb * sg - sa * cg },
        Vec3{ -sb, sa * cb, ca * cb });
}

// 旋转矩阵 → RPY（度），R = Rz·Ry·Rx。万向锁时令 rx = 0（该自由度不可观测，
// 但分解出的 Rz·Ry·Rx 仍与输入矩阵等价；不能保持原 rx）。
inline Vec3 matrixToEulerDeg(const Mat3& m)
{
    double sy = -m[6];
    sy = std::clamp(sy, -1.0, 1.0);
    // 括号包住 std::max：<winsock2.h>/<windows.h> 的 max 宏会把 std::max(
    // 展开成非法记号（单测目标同时包含两者）。
    const double cb = std::sqrt((std::max)(0.0, 1.0 - sy * sy));
    const double ry = std::asin(sy);
    double rx = 0.0;
    double rz = 0.0;
    if (cb > 1e-6) {
        rx = std::atan2(m[7], m[8]);
        rz = std::atan2(m[3], m[0]);
    } else if (sy > 0.0) {
        // b = +90°: m01 = sin(a-g), m02 = cos(a-g); set a = 0.
        rz = std::atan2(-m[1], m[2]);
    } else {
        // b = -90°: m01 = -sin(a+g), m02 = -cos(a+g); set a = 0.
        rz = std::atan2(-m[1], -m[2]);
    }
    return Vec3{ rx * kRadToDeg, ry * kRadToDeg, rz * kRadToDeg };
}

// 绕基座 X/Y/Z 轴转 deltaDeg（左乘），返回新的 RPY（度）。
inline Vec3 rotateEulerAboutBaseAxisDeg(const Vec3& rpyDeg, int axis,
                                        double deltaDeg)
{
    if (axis < 0 || axis > 2)
        return rpyDeg;
    const double d = deltaDeg * kDegToRad;
    const double c = std::cos(d);
    const double s = std::sin(d);
    Mat3 delta = identity();
    if (axis == 0) {
        delta = fromRows(Vec3{ 1, 0, 0 }, Vec3{ 0, c, -s }, Vec3{ 0, s, c });
    } else if (axis == 1) {
        delta = fromRows(Vec3{ c, 0, s }, Vec3{ 0, 1, 0 }, Vec3{ -s, 0, c });
    } else {
        delta = fromRows(Vec3{ c, -s, 0 }, Vec3{ s, c, 0 }, Vec3{ 0, 0, 1 });
    }
    return matrixToEulerDeg(multiply(delta, eulerDegToMatrix(rpyDeg)));
}

// 两个姿态之间的最小旋转角（度）。179° 与 -179° 差 2°，不是 358°。
inline double rotationDistanceDeg(const Vec3& aDeg, const Vec3& bDeg)
{
    const Mat3 a = eulerDegToMatrix(aDeg);
    const Mat3 b = eulerDegToMatrix(bDeg);
    double trace = 0.0;
    for (int r = 0; r < 3; ++r) {
        for (int k = 0; k < 3; ++k)
            trace += a[static_cast<std::size_t>(k * 3 + r)]
                   * b[static_cast<std::size_t>(k * 3 + r)];
    }
    return std::acos(std::clamp((trace - 1.0) * 0.5, -1.0, 1.0)) * kRadToDeg;
}

inline bool poseFinite(const Pose6& pose)
{
    for (double v : pose) {
        if (!std::isfinite(v))
            return false;
    }
    return true;
}

inline bool reachedCartesian(const Pose6& actual, const Pose6& target,
                             double toleranceMm, double toleranceDeg)
{
    const double dx = actual[0] - target[0];
    const double dy = actual[1] - target[1];
    const double dz = actual[2] - target[2];
    if (std::sqrt(dx * dx + dy * dy + dz * dz) > toleranceMm)
        return false;
    return rotationDistanceDeg(Vec3{ actual[3], actual[4], actual[5] },
                               Vec3{ target[3], target[4], target[5] })
        <= toleranceDeg;
}

inline bool reachedJoint(const Pose6& actual, const Pose6& target,
                         double toleranceDeg)
{
    for (std::size_t i = 0; i < 6; ++i) {
        if (std::fabs(actual[i] - target[i]) > toleranceDeg)
            return false;
    }
    return true;
}

} // namespace FairinoMath
