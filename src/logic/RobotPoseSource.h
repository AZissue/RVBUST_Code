#pragma once

// Which connection supplies the pose for a calibration photo.
//
// 「机器人通信」与「机器人控制」合并后，机器人只剩一条连接（控制台后端，
// 品牌见 RobotProgramController::BackendKind）。本规则就是"这份位姿能不能
// 写进标定记录"的唯一判定点；它是纯函数（无 Qt 对象），优先级与失败条件
// 都有单测：
//
//   控制台已连接 + 真机后端 + 位姿新鲜 + 未在运动 -> 用这份位姿；
//   否则 -> 没有位姿来源（拍照节点必须失败，绝不把旧位姿或仿真位姿写进
//   标定记录）。
//
// "仿真" 被明确排除：仿真的数字看起来完全合理，但它不是这台机器人的真实
// 位姿，一旦进卡片，整个标定结果都是错的。
#include <QString>

namespace RobotPoseSource {

enum class Source {
    None,
    Console
};

struct Inputs {
    bool consoleConnected = false;
    // True for the console's 仿真 backend (or any other non-real backend).
    bool consoleSimulated = true;
    // The last console pose arrived within the freshness window.
    bool consolePoseFresh = false;
    // The console has a motion in flight.  A pose read mid-motion would pair
    // the image with a pose the robot no longer has.
    bool consoleMoving = false;
};

// The freshness window.  30003 packets arrive every 8 ms (throttled to 50 ms
// for the UI); 1 s means "the stream stopped" rather than "a slow frame".
constexpr qint64 kConsolePoseFreshMs = 1000;

inline Source choose(const Inputs& in)
{
    if (in.consoleConnected && !in.consoleSimulated
        && in.consolePoseFresh && !in.consoleMoving) {
        return Source::Console;
    }
    return Source::None;
}

inline QString label(Source s)
{
    switch (s) {
    case Source::Console:
        return QStringLiteral("机器人控制");
    case Source::None:
        break;
    }
    return QStringLiteral("无");
}

} // namespace RobotPoseSource
