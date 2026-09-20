#pragma once

#include "logic/RobotPose.h"

#include <QString>
#include <array>

// 埃夫特（EFORT）机器人通信适配器（用户反馈 7）。
//
// 厂商 SDK 是 third_party/EfortSDK（EftSdk.lib / EftSdk.dll + EfortSdk.h）。
// 与 Modbus / UR / 博纳斯三条链路一样，本文件只实现 RobotPose::Reader，
// 由 MainWindow 负责连接、断开与读位姿的编排；不碰采集/保存/检测管线。
//
// 本头文件**故意不包含 SDK 头**：EfortSdk.h 里是 `using namespace std;` +
// `__declspec(dllexport)` 的全局声明，包含进来会污染每个包含它的编译单元。
// SDK 的 include 只出现在 EfortPoseReader.cpp 里，所以 normalizePose()
// 这个纯函数可以在没有 SDK 的编译单元里被单测直接调用。
namespace EfortPoseReader {

// SDK 读到的 6 个原始值 → 项目约定（位置 mm、姿态度、静态 XYZ，R = Rz*Ry*Rx）。
// rawIsMillimeter / rawIsDegree 说明原始单位；输出永远归一化成 mm + 度。
// 任一坐标非有限值 → 返回 false 且不改 out。
bool normalizePose(const double raw[6], bool rawIsMillimeter, bool rawIsDegree,
                   RobotPose::Pose& out);

// SDK 返回码 → RobotPose::Status（纯函数，单测可直接断言）。
RobotPose::Status statusFromSdkCode(int code);

// SDK 返回码 → 可读中文（用于 lastError / 侧栏提示）。
QString sdkErrorText(int code);

class EfortReader : public RobotPose::Reader {
public:
    EfortReader() = default;
    ~EfortReader() override;

    // SDK 的 ConnectRobot(robot_addr) 只吃一个地址串：这里传 `host`
    // （host 里已经带 ':' 就原样传；否则 port != 0 时拼成 "host:port"，
    // port == 0 就只传 host）。地址格式由 SDK 决定，UI 默认只填 IP。
    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    RobotPose::Status readPose(RobotPose::Pose& out) override;
    QString lastError() const override;

    bool isConnected() const { return m_connected; }
    // 最近一次连接拿到的 devId（SDK 的多机器人句柄）。
    unsigned int deviceId() const { return m_devId; }

private:
    bool m_connected = false;
    unsigned int m_devId = 0;
    QString m_error;
};

} // namespace EfortPoseReader
