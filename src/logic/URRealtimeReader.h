#pragma once

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

private:
	QTcpSocket* m_socket = nullptr;
	int m_timeoutMs = 1500;
	QString m_error;
};

} // namespace RobotPose
