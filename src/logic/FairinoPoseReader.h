#pragma once

// 法奥位姿读取适配器（机器人通信工具）。
//
// 只读位姿：连 20004 实时口，持续排空状态流，readPose() 返回最新一帧的
// tl_cur_pos（TCP 位姿，mm + 度，static XYZ / R = Rz·Ry·Rx）。
//
// 为什么不像 Modbus 那样"读一次问一次"：法奥 20004 是控制器主动推的流，
// USB/UR 30003 一样。按包消费会让界面永远显示连接后第一帧（stage-10 的
// UR 现场问题），所以这里只保留最新帧，并把流持续读掉。
//
// 20003（XML-RPC 命令口）不在这里使用：通信工具只需要位姿；控制台连接时
// 才同时探测 20003（见 FairinoMotionBackend）。
#include <QElapsedTimer>
#include <QString>

#include "logic/FairinoRealtime.h"
#include "logic/RobotPose.h"

class QTcpSocket;

class FairinoPoseReader : public RobotPose::Reader {
public:
    FairinoPoseReader() = default;
    ~FairinoPoseReader() override;

    // port = 20004 实时口（0 → 默认 20004）。
    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    RobotPose::Status readPose(RobotPose::Pose& out) override;
    QString lastError() const override;

    void setTimeoutMs(int ms) { m_timeoutMs = ms; }
    // 测试/特殊固件用：默认就是协议规定的 20004。
    void setRealtimePort(quint16 port) { m_realtimePort = port; }

    quint64 framesConsumed() const { return m_parser.acceptedFrames(); }
    quint64 badChecksums() const { return m_parser.rejectedChecksums(); }

private:
    void drain();
    RobotPose::Status currentPose(RobotPose::Pose& out);

    QTcpSocket* m_socket = nullptr;
    FairinoRealtime::Parser m_parser;
    FairinoRealtime::State m_latest;
    bool m_hasState = false;
    QElapsedTimer m_lastFrameAt;
    quint16 m_realtimePort = 20004;
    int m_timeoutMs = 1800;
    QString m_error;
};
