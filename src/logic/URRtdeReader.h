#pragma once

#include <QByteArray>
#include <QElapsedTimer>

#include "logic/RobotPose.h"

class QTcpSocket;

namespace RobotPose {

// Universal Robots RTDE reader (port 30004).
//
// This is the interface UR recommends now that the 30003 realtime port has
// been deprecated, and it fixes the *class* of bug the 30003 adapter hit: on
// 30003 the pose sits at a hard-coded byte offset, so a wrong constant reads a
// different field and returns a plausible-looking number (2026-10-10 field
// report: the tool reported a TCP pose of (0,0,0,0,0,0) because the offset was
// one 48-byte field too far and landed on actual_TCP_speed).  On RTDE the
// client asks for the variable *by name*:
//
//   1. RTDE_REQUEST_PROTOCOL_VERSION (86)        -> answered with accepted(1/0)
//   2. RTDE_CONTROL_PACKAGE_SETUP_OUTPUTS (79)   -> the client sends the output
//      frequency ("actual_TCP_pose", a VECTOR6D = 6 doubles) and the
//      controller answers with the types it assigned.  Only one output recipe
//      per client is allowed, so a second RTDE client on the robot makes this
//      step fail -- that is a robot-side condition, not a parse error.
//   3. RTDE_CONTROL_PACKAGE_START (83)           -> the controller then streams
//      RTDE_DATA_PACKAGE (85) at floor(125 / frequency) Hz.
//
// Every packet is [uint16 BE size (includes this header)][uint8 type][payload];
// a data payload is a uint8 recipe id followed by the requested values, all
// big-endian doubles.
//
// actual_TCP_pose = (x, y, z, rx, ry, rz) in the *base* frame, x/y/z in meters
// and rx/ry/rz as an axis-angle rotation vector in RADIANS -- the same
// convention as the 30003 adapter, so this class converts x/y/z to millimeters
// and passes rx/ry/rz through unchanged (see RobotPose::Pose::rpy).
//
// Addressing these fields by name makes a wrong index impossible; the reader
// still refuses an implausible pose (non-finite, out of range, or all zeros),
// because a byte-misaligned read produces magnitudes no TCP can have.
class URRtdeReader : public RobotPose::Reader {
public:
    URRtdeReader() = default;
    ~URRtdeReader() override;

    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    RobotPose::Status readPose(RobotPose::Pose& out) override;
    QString lastError() const override;

    void setTimeoutMs(int ms) { m_timeoutMs = ms; }
    bool isConnected() const;

    // Diagnostics: data packages consumed since connect().  The controller
    // pushes them whether or not anyone asks, so this must keep growing on its
    // own while a connection is up; if it stops, the socket buffer grows
    // instead (and the controller drops a client that stops receiving for 10 s).
    quint64 packetsConsumed() const { return m_packetsConsumed; }

private:
    bool handshake();
    bool sendCommand(quint8 type, const QByteArray& payload);
    bool readResponse(quint8 expectedType, QByteArray& payload);
    void drain();
    void parseData(const QByteArray& payload);

    QTcpSocket* m_socket = nullptr;
    QByteArray m_buf;                // tail of a partially received packet
    RobotPose::Pose m_latest{};
    bool m_hasPose = false;
    // A data package arrived but its values are not a plausible pose (see
    // parseData).  Kept so readPose() can say that instead of "no data".
    bool m_badPose = false;
    QElapsedTimer m_lastPacketAt;
    quint64 m_packetsConsumed = 0;
    quint64 m_badHeaders = 0;
    quint8  m_recipeId = 0;
    int m_timeoutMs = 1500;
    QString m_error;
};

} // namespace RobotPose
