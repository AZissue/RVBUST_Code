#pragma once

// ── 法奥命令参数（纯函数，可单测）────────────────────────────────────
//
// 参数顺序**逐字**对齐官方 Python SDK v2.1.7.1 里实际发给控制器的调用，
// 不是按名字猜的：
//
//   MoveL（Robot.py:1157）把 33 个数放在**一个数组参数**里：
//     j1..j6, x,y,z,rx,ry,rz, tool, user, vel, acc, ovl, blendR, blendMode,
//     exaxis1..4, search, offset_flag, offset_x..rz, 100.0, velAccParamMode
//   并且 Python 在 joint_pos 全 0 时先调用 GetInverseKin(0, desc_pos, -1)，
//   所以 C++ 侧也必须先解逆解，不能把全 0 关节直接发下去。
//
//   MoveJ（Robot.py:1098）逐个参数发：
//     joint_pos[6](array), desc_pos[6](array), tool, user, vel, acc, ovl,
//     exaxis_pos[4](array), blendT, offset_flag, offset_pos[6](array)
//
// 速度单位是百分比 [0,100]；blendR/blendT = -1 表示到位停（协议手册：
// -1 Stop/block，0~1000 为平滑半径 mm）。
#include <QList>
#include <algorithm>
#include <array>

#include "logic/FairinoXmlRpc.h"

namespace FairinoCommand {

using Pose = std::array<double, 6>;   // 笛卡尔 mm/度 或 关节 度

inline QList<FairinoXmlRpc::Value> zeros(int count)
{
    QList<FairinoXmlRpc::Value> out;
    out.reserve(count);
    for (int i = 0; i < count; ++i)
        out.append(FairinoXmlRpc::Value::fromDouble(0.0));
    return out;
}

inline QList<FairinoXmlRpc::Value> poseValues(const Pose& pose)
{
    QList<FairinoXmlRpc::Value> out;
    out.reserve(6);
    for (double v : pose)
        out.append(FairinoXmlRpc::Value::fromDouble(v));
    return out;
}

inline double clampSpeed(double speedPct)
{
    return std::clamp(speedPct, 0.0, 100.0);
}

// GetInverseKin(type=0 绝对位姿(基坐标), desc_pos, config=-1 参考当前关节)。
inline QList<FairinoXmlRpc::Value> inverseKinParams(const Pose& cart)
{
    return {
        FairinoXmlRpc::Value::fromInt(0),
        FairinoXmlRpc::Value::fromArray(poseValues(cart)),
        FairinoXmlRpc::Value::fromInt(-1),
    };
}

// GetForwardKin(joint_pos)
inline QList<FairinoXmlRpc::Value> forwardKinParams(const Pose& joint)
{
    return { FairinoXmlRpc::Value::fromArray(poseValues(joint)) };
}

// MoveL：一个 33 元素数组参数。
inline QList<FairinoXmlRpc::Value> moveLParams(const Pose& joint,
                                               const Pose& cart, int tool,
                                               int user, double speedPct)
{
    QList<FairinoXmlRpc::Value> args;
    args.reserve(33);
    for (double v : joint)
        args.append(FairinoXmlRpc::Value::fromDouble(v));
    for (double v : cart)
        args.append(FairinoXmlRpc::Value::fromDouble(v));
    args.append(FairinoXmlRpc::Value::fromInt(tool));
    args.append(FairinoXmlRpc::Value::fromInt(user));
    args.append(FairinoXmlRpc::Value::fromDouble(clampSpeed(speedPct)));
    args.append(FairinoXmlRpc::Value::fromDouble(0.0));    // acc（SDK：暂不开放）
    args.append(FairinoXmlRpc::Value::fromDouble(100.0));  // ovl
    args.append(FairinoXmlRpc::Value::fromDouble(-1.0));   // blendR：到位停
    args.append(FairinoXmlRpc::Value::fromInt(0));         // blendMode
    for (int i = 0; i < 4; ++i)                            // exaxis_pos
        args.append(FairinoXmlRpc::Value::fromDouble(0.0));
    args.append(FairinoXmlRpc::Value::fromInt(0));         // search
    args.append(FairinoXmlRpc::Value::fromInt(0));         // offset_flag
    for (int i = 0; i < 6; ++i)                            // offset_pos
        args.append(FairinoXmlRpc::Value::fromDouble(0.0));
    args.append(FairinoXmlRpc::Value::fromDouble(100.0));  // SDK 固定值
    args.append(FairinoXmlRpc::Value::fromInt(0));         // velAccParamMode=百分比

    return { FairinoXmlRpc::Value::fromArray(args) };
}

// MoveJ：11 个参数（两个 6 元数组 + 一个 4 元数组）。
inline QList<FairinoXmlRpc::Value> moveJParams(const Pose& joint,
                                               const Pose& cart, int tool,
                                               int user, double speedPct)
{
    QList<FairinoXmlRpc::Value> exaxis;
    exaxis.reserve(4);
    for (int i = 0; i < 4; ++i)
        exaxis.append(FairinoXmlRpc::Value::fromDouble(0.0));

    return {
        FairinoXmlRpc::Value::fromArray(poseValues(joint)),
        FairinoXmlRpc::Value::fromArray(poseValues(cart)),
        FairinoXmlRpc::Value::fromInt(tool),
        FairinoXmlRpc::Value::fromInt(user),
        FairinoXmlRpc::Value::fromDouble(clampSpeed(speedPct)),
        FairinoXmlRpc::Value::fromDouble(0.0),    // acc（SDK：暂不开放）
        FairinoXmlRpc::Value::fromDouble(100.0),  // ovl
        FairinoXmlRpc::Value::fromArray(exaxis),
        FairinoXmlRpc::Value::fromDouble(-1.0),   // blendT：到位停
        FairinoXmlRpc::Value::fromInt(0),         // offset_flag
        FairinoXmlRpc::Value::fromArray(zeros(6)),
    };
}

inline QList<FairinoXmlRpc::Value> enableParams(bool enabled)
{
    return { FairinoXmlRpc::Value::fromInt(enabled ? 1 : 0) };
}

inline QList<FairinoXmlRpc::Value> modeParams(int mode)
{
    return { FairinoXmlRpc::Value::fromInt(mode) };
}

} // namespace FairinoCommand
