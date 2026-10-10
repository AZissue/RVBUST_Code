#pragma once

#include <QByteArray>
#include <QElapsedTimer>

#include "logic/RobotPose.h"

class QTcpSocket;

// Universal Robots "Primary"/Realtime interface reader (stage 8).
//
// UR controllers push a variable-length binary packet on this port every
// control cycle (default 8ms) without the client having to request anything:
//   [int32 BE message length (includes these 4 bytes)] [message body]
// Inside the body (offsets are from the start of the body, i.e. right after
// the 4-byte length):
//   timestamp          8 bytes (double)
//   target_q           48 bytes (6 doubles)
//   target_qd          ... (older UR versions have different fields ordering
//                           historically, but the layout used here matches
//                           the "actual_TCP_pose" position confirmed against
//                           a real URSim capture: see logic/RobotPose.h)
//   target_tcp_pose    48 bytes (6 doubles)
//   actual_q           48 bytes (6 doubles)
//   actual_tcp_pose    48 bytes (6 doubles)  <- this is what we read
// actual_tcp_pose = (x, y, z, rx, ry, rz) with x/y/z in meters and rx/ry/rz
// as an axis-angle rotation vector in radians (NOT static-XYZ euler degrees).
//
// This adapter converts x/y/z to millimeters (matching the rest of the app's
// unit convention) and passes rx/ry/rz through unchanged (radians, axis-angle)
// -- see the comment on RobotPose::Pose::rpy for why no degree conversion is
// applied.
//
// Because the port is a *stream* and not a request/response protocol, the
// reader consumes it continuously and keeps only the newest packet:
//   * a `readyRead` handler drains whatever has arrived, so nothing is left
//     queued in the socket buffer while the user is not reading a pose;
//   * readPose() answers with the newest pose already parsed, and only waits
//     (bounded by the timeout) for the very first packet after connect().
// Consuming one packet per readPose() call instead would answer with the pose
// from right after connect -- a value that looks frozen until the user
// reconnects -- and would grow the client's memory by the whole stream
// (~9 MB/min at 125 Hz). That was the stage-10 field report (2026-10-10).
namespace RobotPose {

class URRealtimeReader : public Reader {
public:
    URRealtimeReader() = default;
    ~URRealtimeReader() override;

    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    Status readPose(Pose& out) override;
    QString lastError() const override;

    void setTimeoutMs(int ms) { m_timeoutMs = ms; }
    bool isConnected() const;

    // Diagnostics: packets consumed since connect(). The controller pushes
    // whether or not anyone asks, so this must keep growing on its own while a
    // connection is up; if it stops, the socket buffer is what grows instead.
    quint64 packetsConsumed() const { return m_packetsConsumed; }

private:
    void drain();                                         // parse what has arrived
    bool parsePacket(const QByteArray& packet, Pose& out) const;

    QTcpSocket* m_socket = nullptr;
    QByteArray m_buf;                // tail of a partially received packet
    Pose m_latest{};
    bool m_hasPose = false;
    QElapsedTimer m_lastPacketAt;    // freshness of m_latest
    quint64 m_packetsConsumed = 0;
    quint64 m_badHeaders = 0;
    int m_timeoutMs = 1500;
    QString m_error;
};

} // namespace RobotPose
