#pragma once

// ── Camera release / recovery policy (第 5 回合 任务 3) ──
//
// The 3D camera is the expensive part of this setup, so the teardown rules are
// spelled out as pure state machines instead of being implicit in the order of
// statements inside shutdown():
//
//   * a repeat teardown must be a no-op — no second Close/Destroy, no second
//     SystemShutdown, no second "cameraDisconnected" (3.1);
//   * a failed connect is retried on a bounded schedule, but only when a retry
//     can actually help (3.3);
//   * the failure is classified so the operator gets a readable recovery hint
//     instead of a bare SDK string (3.3).

#include <QString>
#include <vector>

namespace CameraRelease {

// ── Idempotent teardown (3.1) ──
struct State {
    bool deviceOpen = false;    // an X1/X2 object is open
    bool systemInited = false;  // RVC::SystemInit() succeeded
    bool released = false;      // a previous release ran to completion
};

struct Actions {
    bool noop = false;          // repeat call: touch nothing, emit nothing
    bool closeDevice = false;
    bool systemShutdown = false;
    bool emitDisconnected = false;
};

inline Actions plan(const State& s)
{
    // Nothing left to release: a repeat call must not repeat Close/Destroy and
    // must not announce a disconnect that already happened.
    if (s.released && !s.deviceOpen && !s.systemInited)
        return { true, false, false, false };

    Actions a;
    a.closeDevice = s.deviceOpen;
    a.systemShutdown = s.systemInited;
    a.emitDisconnected = true;
    return a;
}

// ── Bounded connect retry (3.3) ──
// `count` retries, waiting (i + 1) seconds before retry i, i.e. 1/2/3 s for the
// default count of 3.  Empty for count <= 0 (retry disabled).
inline std::vector<int> connectRetryDelaysMs(int count)
{
    std::vector<int> delays;
    for (int i = 0; i < count; ++i)
        delays.push_back((i + 1) * 1000);
    return delays;
}

enum class ConnectFailure { Unknown, DeviceNotFound, DeviceBusy, Unsupported, SdkError };

// deviceFound : the serial resolved to a device at all
// deviceInUse : the GigE "In Use" flag reported by GetNetworkConfig — the hard
//               evidence for "上一次没释放干净 / 被别的程序占着"
inline ConnectFailure classify(const QString& errorText, bool deviceFound, bool deviceInUse)
{
    if (!deviceFound)
        return ConnectFailure::DeviceNotFound;
    if (deviceInUse)
        return ConnectFailure::DeviceBusy;

    const QString t = errorText.toLower();
    if (t.contains(QStringLiteral("占用")) || t.contains(QStringLiteral("使用中"))
            || t.contains(QStringLiteral("in use")) || t.contains(QStringLiteral("busy")))
        return ConnectFailure::DeviceBusy;
    if (t.contains(QStringLiteral("不支持")) || t.contains(QStringLiteral("not support")))
        return ConnectFailure::Unsupported;
    if (!errorText.isEmpty())
        return ConnectFailure::SdkError;
    return ConnectFailure::Unknown;
}

// A retry can only help when the device exists and is not permanently
// unusable — an unplugged camera or an unsupported model will fail just as
// often after 3 s of waiting.
inline bool shouldRetry(ConnectFailure f)
{
    return f == ConnectFailure::DeviceBusy
        || f == ConnectFailure::SdkError
        || f == ConnectFailure::Unknown;
}

// Readable recovery advice.  `retriesTried` is how many retries already ran, so
// the "wait N seconds" advice matches what actually happened.
inline QString operatorHint(ConnectFailure f, int retriesTried, const QString& errorText)
{
    switch (f) {
    case ConnectFailure::DeviceBusy:
        return QStringLiteral("相机被占用（可能上一次未正常释放，或被其它程序占用）。"
                              "已自动重试 %1 次（间隔 1/2/3 秒）。建议：等待 10 秒后重试；"
                              "仍失败请重新插拔网线/USB；或重启相机电源。")
            .arg(retriesTried);
    case ConnectFailure::DeviceNotFound:
        return QStringLiteral("未找到设备：请确认相机电源与网线/USB 连接，"
                              "重新插拔后重试。");
    case ConnectFailure::Unsupported:
        return QStringLiteral("该设备不支持 X1/X2 接口，本程序无法用它采集数据。");
    case ConnectFailure::SdkError:
        return QStringLiteral("相机 SDK 报错：%1。建议重启相机电源或重新插拔网线后重试。")
            .arg(errorText);
    default:
        return QStringLiteral("相机连接失败：%1。建议重新插拔网线、确认相机电源后重试。")
            .arg(errorText);
    }
}

} // namespace CameraRelease
