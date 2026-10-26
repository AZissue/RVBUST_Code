#pragma once

// Which connection supplies the pose for a calibration photo.
//
// There are two independent robot connections in the app:
//   * the communication tool (RobotController), used for manual/auto pose reads;
//   * the console (RobotProgramController), which owns the motion backend.
//
// The program's photo node used to require only the first, so a console-only
// connection failed with "拍照前需要先连接机器人".  The rule below is the one
// fix point.  It is deliberately pure (no Qt objects) so the precedence and the
// fail-closed conditions are unit-tested:
//
//   1. communication tool connected  -> use it (existing behaviour, unchanged);
//   2. console connected, real backend, fresh pose, not moving -> use it;
//   3. otherwise -> no pose source (the node must fail, never save a stale or
//      simulated pose into a calibration record).
//
// "Simulated" is rejected on purpose: the console's simulated backend produces
// plausible-looking numbers that must never enter a calibration card.
#include <QString>

namespace RobotPoseSource {

enum class Source {
    None,
    Communication,
    Console
};

struct Inputs {
    bool communicationConnected = false;
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
    if (in.communicationConnected)
        return Source::Communication;
    if (in.consoleConnected && !in.consoleSimulated
        && in.consolePoseFresh && !in.consoleMoving) {
        return Source::Console;
    }
    return Source::None;
}

inline QString label(Source s)
{
    switch (s) {
    case Source::Communication:
        return QStringLiteral("机器人通信");
    case Source::Console:
        return QStringLiteral("机器人控制台");
    case Source::None:
        break;
    }
    return QStringLiteral("无");
}

} // namespace RobotPoseSource
