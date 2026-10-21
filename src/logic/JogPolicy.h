#pragma once

// ── 点动 / 到位判据（纯函数）────────────────────────────────────────────
//
// 点动按钮和关节滑杆都只是"把当前位置加一个增量，然后让后端移动到新目标"。
// 这里集中放三件容易写错、又必须能单测的事：
//   * 步长/速度的合法区间；
//   * 角度差走最短路径（179° 与 -179° 只差 2°，不是 358°）；
//   * 到位判据（位置用欧氏距离，姿态/关节用最大单轴角度差）。
#include <algorithm>
#include <array>
#include <cmath>

namespace JogPolicy {

using Pose = std::array<double, 6>;

constexpr double MIN_STEP = 0.01;      // mm / 度
constexpr double MAX_STEP = 500.0;
constexpr double MIN_SPEED = 1.0;      // %
constexpr double MAX_SPEED = 100.0;

inline double clampStep(double step)
{
    if (!std::isfinite(step))
        return 1.0;
    return std::clamp(step, MIN_STEP, MAX_STEP);
}

inline double clampSpeed(double pct)
{
    if (!std::isfinite(pct))
        return 30.0;
    return std::clamp(pct, MIN_SPEED, MAX_SPEED);
}

// 把角度差归一化到 (-180, 180]。用于到位判据和日志里的"还差多少"。
inline double angleDiff(double a, double b)
{
    double d = std::fmod(a - b, 360.0);
    if (d > 180.0)
        d -= 360.0;
    else if (d <= -180.0)
        d += 360.0;
    return d;
}

inline bool validAxis(int axis)
{
    return axis >= 0 && axis < 6;
}

// 单轴增量。轴 0..2 = X/Y/Z（或 J1..J3），3..5 = RX/RY/RZ（或 J4..J6）。
// 越界轴返回原值，调用方不会因此移动到一个莫名其妙的位置。
inline Pose jog(const Pose& current, int axis, double delta)
{
    Pose out = current;
    if (validAxis(axis) && std::isfinite(delta))
        out[static_cast<std::size_t>(axis)] += delta;
    return out;
}

// 关节目标的安全区间：±360°。这是"界面上不会给出圈数"的边界，不是机器人
// 的机械限位——真正的限位由机器人控制器拒绝（UR 会返回错误，我们转成提示）。
inline double clampJoint(double deg)
{
    if (!std::isfinite(deg))
        return 0.0;
    return std::clamp(deg, -360.0, 360.0);
}

inline Pose clampJoints(const Pose& joints)
{
    Pose out = joints;
    for (double& v : out)
        v = clampJoint(v);
    return out;
}

// 笛卡尔到位：位置三维欧氏距离 + 各姿态角最短差。
inline bool reachedCartesian(const Pose& actual, const Pose& target,
                             double toleranceMm, double toleranceDeg)
{
    const double dx = actual[0] - target[0];
    const double dy = actual[1] - target[1];
    const double dz = actual[2] - target[2];
    if (std::sqrt(dx * dx + dy * dy + dz * dz) > toleranceMm)
        return false;
    for (int i = 3; i < 6; ++i) {
        if (std::abs(angleDiff(actual[static_cast<std::size_t>(i)],
                               target[static_cast<std::size_t>(i)]))
            > toleranceDeg)
            return false;
    }
    return true;
}

// 关节到位：六轴最大角度差。
inline bool reachedJoint(const Pose& actual, const Pose& target,
                         double toleranceDeg)
{
    for (int i = 0; i < 6; ++i) {
        if (std::abs(angleDiff(actual[static_cast<std::size_t>(i)],
                               target[static_cast<std::size_t>(i)]))
            > toleranceDeg)
            return false;
    }
    return true;
}

// 运动时长估计（仅仿真后端用）：按最大单轴行程和速度百分比换算，夹在
// 300 ms..20 s 之间，避免"原地移动 0.01 mm 也要等 15 秒"。
inline int simulatedDurationMs(const Pose& from, const Pose& to, double speedPct,
                               bool angular)
{
    double dist = 0.0;
    for (std::size_t i = 0; i < to.size(); ++i) {
        double d = std::abs(to[i] - from[i]);
        if (angular && i >= 3)
            d = std::abs(angleDiff(to[i], from[i]));
        dist = std::max(dist, d);
    }
    const double speed = clampSpeed(speedPct) / 100.0;
    // 100% ≈ 250 mm/s / 90 °/s 的量级；只用于让动画看起来合理。
    const double unitsPerSecond = (angular ? 90.0 : 250.0) * speed;
    const double ms = dist / std::max(unitsPerSecond, 1.0) * 1000.0;
    return static_cast<int>(std::clamp(ms, 300.0, 20000.0));
}

} // namespace JogPolicy
