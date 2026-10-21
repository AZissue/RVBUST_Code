#pragma once

// ── UR 运动数学（纯函数）──────────────────────────────────────────────
//
// UR 的实时端口（30003）给出的姿态是**旋转向量**（轴角，弧度），位置是米；
// URScript 的 movel/movej 也按这个约定收数。本工具内部统一用 "mm + 度"，
// 且点动 RX/RY/RZ 的语义是"绕基座轴转多少度"——直接给旋转向量的分量加
// 一个数在数学上并不等价（旋转不可交换），所以这里用旋转矩阵正确合成：
//
//   反馈 raw (m, rad-rotvec)  →  界面 state (mm, deg-rotvec)
//   界面 state                →  URScript (m, rad-rotvec，范数归一化到 ≤π)
//   点动                       →  R_new = R_delta(base axis) · R_current
//
// 到位判据同样在矩阵上取两个姿态的夹角（179° 与 -179° 差 2°，不是 358°）。
#include <algorithm>
#include <array>
#include <cmath>

namespace UrMotionMath {

using Vec3 = std::array<double, 3>;
using Pose6 = std::array<double, 6>;
using Mat3 = std::array<double, 9>;   // row-major

constexpr double kPi = 3.14159265358979323846;
constexpr double kRadToDeg = 180.0 / kPi;
constexpr double kDegToRad = kPi / 180.0;

inline double norm(const Vec3& v)
{
    return std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}

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

// Rodrigues：旋转向量（弧度）→ 旋转矩阵。
inline Mat3 rotvecToMatrix(const Vec3& rv)
{
    const double theta = norm(rv);
    if (theta < 1e-12)
        return identity();
    const double x = rv[0] / theta;
    const double y = rv[1] / theta;
    const double z = rv[2] / theta;
    const double c = std::cos(theta);
    const double s = std::sin(theta);
    const double t = 1.0 - c;
    return Mat3{
        t * x * x + c,     t * x * y - s * z, t * x * z + s * y,
        t * x * y + s * z, t * y * y + c,     t * y * z - s * x,
        t * x * z - s * y, t * y * z + s * x, t * z * z + c,
    };
}

// 旋转矩阵 → 旋转向量（弧度），范数归一化到 [0, π]。
inline Vec3 matrixToRotvec(const Mat3& m)
{
    const double trace = m[0] + m[4] + m[8];
    const double cosTheta = std::clamp((trace - 1.0) * 0.5, -1.0, 1.0);
    const double theta = std::acos(cosTheta);
    if (theta < 1e-9)
        return Vec3{ 0.0, 0.0, 0.0 };

    Vec3 axis{};
    const double sinTheta = std::sin(theta);
    if (sinTheta > 1e-6) {
        const double k = 1.0 / (2.0 * sinTheta);
        axis = { (m[7] - m[5]) * k, (m[2] - m[6]) * k, (m[3] - m[1]) * k };
    } else {
        // θ≈π：sin 太小，改用对角线与反对称项定轴。
        double x = std::sqrt(std::max(0.0, (m[0] + 1.0) * 0.5));
        double y = std::sqrt(std::max(0.0, (m[4] + 1.0) * 0.5));
        double z = std::sqrt(std::max(0.0, (m[8] + 1.0) * 0.5));
        if (x >= y && x >= z) {
            if (x < 1e-12) return Vec3{ 0.0, 0.0, 0.0 };
            y = m[1] / (2.0 * x);
            z = m[2] / (2.0 * x);
        } else if (y >= z) {
            if (y < 1e-12) return Vec3{ 0.0, 0.0, 0.0 };
            x = m[1] / (2.0 * y);
            z = m[5] / (2.0 * y);
        } else {
            if (z < 1e-12) return Vec3{ 0.0, 0.0, 0.0 };
            x = m[2] / (2.0 * z);
            y = m[5] / (2.0 * z);
        }
        axis = { x, y, z };
        const double n = norm(axis);
        if (n < 1e-12) return Vec3{ 0.0, 0.0, 0.0 };
        axis = { axis[0] / n, axis[1] / n, axis[2] / n };
    }
    return { axis[0] * theta, axis[1] * theta, axis[2] * theta };
}

// 30003 的 actual_TCP_pose（m + 弧度旋转向量）→ 界面状态（mm + 度）。
inline Pose6 feedbackToState(const double raw[6])
{
    return Pose6{
        raw[0] * 1000.0,
        raw[1] * 1000.0,
        raw[2] * 1000.0,
        raw[3] * kRadToDeg,
        raw[4] * kRadToDeg,
        raw[5] * kRadToDeg,
    };
}

// 界面状态（mm + 度）→ URScript pose（m + 弧度，范数 ≤π）。
inline Pose6 stateToScriptPose(const Pose6& state)
{
    Vec3 rv{
        state[3] * kDegToRad,
        state[4] * kDegToRad,
        state[5] * kDegToRad,
    };
    const double angle = norm(rv);
    if (angle > kPi) {
        // 同一个旋转的等价表示：v' = v * (1 - 2π/|v|)，方向取反、范数变小。
        const double scale = 1.0 - 2.0 * kPi / angle;
        rv = { rv[0] * scale, rv[1] * scale, rv[2] * scale };
    }
    return Pose6{
        state[0] * 0.001,
        state[1] * 0.001,
        state[2] * 0.001,
        rv[0], rv[1], rv[2],
    };
}

// 绕基座 X/Y/Z 轴转 deltaDeg，作用在当前姿态上（左乘）。
inline Vec3 rotateVectorAboutBaseAxisDeg(const Vec3& rotvecDeg, int axis,
                                         double deltaDeg)
{
    if (axis < 0 || axis > 2)
        return rotvecDeg;
    const Vec3 currentRad{
        rotvecDeg[0] * kDegToRad,
        rotvecDeg[1] * kDegToRad,
        rotvecDeg[2] * kDegToRad,
    };
    Vec3 deltaAxis{ 0.0, 0.0, 0.0 };
    deltaAxis[static_cast<std::size_t>(axis)] = 1.0;
    const Mat3 delta = rotvecToMatrix(
        Vec3{ deltaAxis[0] * deltaDeg * kDegToRad,
              deltaAxis[1] * deltaDeg * kDegToRad,
              deltaAxis[2] * deltaDeg * kDegToRad });
    const Mat3 combined = multiply(delta, rotvecToMatrix(currentRad));
    const Vec3 out = matrixToRotvec(combined);
    return { out[0] * kRadToDeg, out[1] * kRadToDeg, out[2] * kRadToDeg };
}

// 两个姿态（度）之间的最小旋转角（度）。
inline double rotationDistanceDeg(const Vec3& aDeg, const Vec3& bDeg)
{
    const Mat3 a = rotvecToMatrix(
        Vec3{ aDeg[0] * kDegToRad, aDeg[1] * kDegToRad, aDeg[2] * kDegToRad });
    const Mat3 b = rotvecToMatrix(
        Vec3{ bDeg[0] * kDegToRad, bDeg[1] * kDegToRad, bDeg[2] * kDegToRad });
    // trace(aᵀ b)
    double trace = 0.0;
    for (int r = 0; r < 3; ++r) {
        for (int k = 0; k < 3; ++k)
            trace += a[static_cast<std::size_t>(k * 3 + r)]
                   * b[static_cast<std::size_t>(k * 3 + r)];
    }
    const double c = std::clamp((trace - 1.0) * 0.5, -1.0, 1.0);
    return std::acos(c) * kRadToDeg;
}

inline bool reachedCartesian(const Pose6& actual, const Pose6& target,
                             double toleranceMm, double toleranceDeg)
{
    const double dx = actual[0] - target[0];
    const double dy = actual[1] - target[1];
    const double dz = actual[2] - target[2];
    if (std::sqrt(dx * dx + dy * dy + dz * dz) > toleranceMm)
        return false;
    return rotationDistanceDeg(
               Vec3{ actual[3], actual[4], actual[5] },
               Vec3{ target[3], target[4], target[5] })
        <= toleranceDeg;
}

} // namespace UrMotionMath
