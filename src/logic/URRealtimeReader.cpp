#include "logic/URRealtimeReader.h"

#include <QDataStream>
#include <QElapsedTimer>
#include <QNetworkProxy>
#include <QTcpSocket>

namespace RobotPose {

namespace {
// Offset (in bytes, from the start of the message body, i.e. right after the
// 4-byte length prefix) of the 6 big-endian doubles this adapter reads.
//
// The 30003 body is: timestamp(8) then a run of 48-byte (6 x double) fields,
// so every field sits at 8 + 48k -- NOT at 48k, the timestamp shifts the grid.
// The field order is  q_actual, qd_actual, I_actual, actual_TCP_pose, ...
// which puts the pose at k = 3:
//
//   8 + 48*1 =  56  q_actual        (joint angles)
//   8 + 48*2 = 104  qd_actual       (joint velocities)
//   8 + 48*3 = 152  actual_TCP_pose  <- what we want
//   8 + 48*4 = 200  actual_TCP_speed
//
// 2026-10-10 field report: the constant used to be 200 (= 8 + 48*4) and the
// tool reported a TCP pose of (0, 0, 0, 0, 0, 0) while the pendant showed a
// real base-frame pose. Six exact zeros cannot be a pose -- joint angles,
// currents, torques and the pose are all non-zero at rest -- but they are
// exactly what a *velocity* field reads at a standstill, and those same zeros
// rule out the other published layout (five target blocks first, pose at 440),
// where body 200 would be M_target: commanded torques holding the arm against
// gravity are never zero. So the offset was one 48-byte field too far.
// `tools/ur_realtime_probe.ps1` prints every field of a real packet next to
// this constant's, to re-confirm it on the machine rather than on a document.
constexpr int kPoseOffset = 8 + 48 * 3;   // 152
constexpr int kPoseBytes  = 48;           // 6 doubles
constexpr int kHeaderBytes = 4;
constexpr quint32 kMaxPacket = 8192;

// Cap on the bytes we will hold while the stream does not line up (see the
// resync branch in drain()). Packets are ~1 KB, so 1 MiB is far beyond any
// legitimate partial packet and keeps a desynced stream from growing.
constexpr int kMaxBuffered = 1 << 20;

// Big-endian 32-bit length field.
quint32 beU32(const char* p)
{
    return (quint32(static_cast<quint8>(p[0])) << 24)
         | (quint32(static_cast<quint8>(p[1])) << 16)
         | (quint32(static_cast<quint8>(p[2])) << 8)
         |  quint32(static_cast<quint8>(p[3]));
}
} // namespace

URRealtimeReader::~URRealtimeReader()
{
    disconnect();
}

bool URRealtimeReader::connect(const QString& host, quint16 port)
{
    disconnect();
    m_buf.clear();
    m_hasPose = false;
    m_zeroPose = false;
    m_latest = Pose{};
    m_packetsConsumed = 0;
    m_badHeaders = 0;

    m_socket = new QTcpSocket;
    // Some environments (notably VMs) have Qt auto-detect a system proxy that
    // does not support raw TCP sockets, failing with "The proxy type is
    // invalid for this operation" even though there is no real proxy in the
    // way. Force no proxy for this direct robot connection.
    m_socket->setProxy(QNetworkProxy::NoProxy);
    m_socket->connectToHost(host, port);
    if (!m_socket->waitForConnected(m_timeoutMs)) {
        m_error = QStringLiteral("连接 %1:%2 失败: %3")
                      .arg(host).arg(port).arg(m_socket->errorString());
        disconnect();
        return false;
    }
    // The port pushes packets on its own; consume them here so the socket read
    // buffer never grows while nobody is asking for a pose. Note we do NOT put
    // a cap on the receive buffer: applying back-pressure to the controller's
    // realtime stream could stall *its* send, which is the robot's business,
    // not ours.
    QObject::connect(m_socket, &QTcpSocket::readyRead, m_socket,
                     [this]() { drain(); });
    m_error.clear();
    return true;
}

void URRealtimeReader::disconnect()
{
    if (m_socket) {
        if (m_socket->state() != QAbstractSocket::UnconnectedState)
            m_socket->disconnectFromHost();
        m_socket->deleteLater();
        m_socket = nullptr;
    }
    m_buf.clear();
    m_hasPose = false;
    m_zeroPose = false;
    m_latest = Pose{};
    m_lastPacketAt.invalidate();
    m_packetsConsumed = 0;
    m_badHeaders = 0;
}

bool URRealtimeReader::isConnected() const
{
    return m_socket
        && m_socket->state() == QAbstractSocket::ConnectedState;
}

// Parse every complete packet currently buffered, keeping only the newest pose.
// Called both from the readyRead handler (so the stream is consumed even while
// nobody reads a pose) and from readPose().
void URRealtimeReader::drain()
{
    if (!m_socket)
        return;
    m_buf.append(m_socket->readAll());

    int scan = 0;
    while (m_buf.size() - scan >= kHeaderBytes) {
        const quint32 msgLen = beU32(m_buf.constData() + scan);
        if (msgLen < kHeaderBytes || msgLen > kMaxPacket) {
            // Not a length this protocol could have produced: the stream has
            // lost its alignment. Step one byte and look for the next header
            // instead of dropping everything for a single bad byte.
            ++scan;
            ++m_badHeaders;
            continue;
        }
        const int total = static_cast<int>(msgLen);
        if (m_buf.size() - scan < total)
            break;                       // wait for the rest of this packet
        Pose pose;
        if (parsePacket(m_buf.mid(scan, total), pose)) {
            m_latest = pose;
            m_hasPose = true;
            m_lastPacketAt.start();
            ++m_packetsConsumed;
        }
        scan += total;
    }
    if (scan > 0)
        m_buf.remove(0, scan);

    if (m_buf.size() > kMaxBuffered) {
        // Only reachable while desynced; never let it grow without bound.
        m_buf.clear();
        m_error = QStringLiteral("机器人数据流长时间无法同步，已丢弃缓冲");
    }
}

bool URRealtimeReader::parsePacket(const QByteArray& packet, Pose& out)
{
    // packet = [4-byte BE length][body]
    if (packet.size() < kHeaderBytes + kPoseOffset + kPoseBytes)
        return false;

    QDataStream ds(packet);
    ds.setByteOrder(QDataStream::BigEndian);
    ds.skipRawData(kHeaderBytes + kPoseOffset);

    double vals[6] = {0, 0, 0, 0, 0, 0};
    for (double& v : vals)
        ds >> v;

    // An all-zero block is never a real pose (a UR TCP cannot sit at the base
    // origin), but it is exactly what a velocity field reads at a standstill --
    // which is how the wrong-offset bug above showed up in the field: a
    // "successful" read of (0, 0, 0, 0, 0, 0) that silently went into the
    // cards. Report it as an error instead of as a pose.
    if (vals[0] == 0.0 && vals[1] == 0.0 && vals[2] == 0.0
        && vals[3] == 0.0 && vals[4] == 0.0 && vals[5] == 0.0) {
        m_error = QStringLiteral(
            "读到的位姿六个分量全为 0，不是真实位姿（很可能是字段偏移错位）；"
            "请用 tools/ur_realtime_probe.ps1 抓一个真实数据包核对");
        m_zeroPose = true;
        return false;
    }

    // UR reports actual_TCP_pose in meters; project convention is millimeters.
    out.xyz = { vals[0] * 1000.0, vals[1] * 1000.0, vals[2] * 1000.0 };
    // rx, ry, rz are an axis-angle rotation vector in radians (NOT static-XYZ
    // euler degrees) -- passed through unchanged, see RobotPose::Pose::rpy.
    out.rpy = { vals[3], vals[4], vals[5] };
    return true;
}

Status URRealtimeReader::readPose(Pose& out)
{
    if (!isConnected())
        return Status::NotConnected;

    // The controller pushes every control cycle, so a stream that has gone
    // quiet means the connection lost the controller (cable, power) even
    // though TCP may still be up. Report that instead of handing back the last
    // pose as if it were current -- a stale pose silently recorded into the
    // cards would be worse than an error.
    if (m_hasPose && m_lastPacketAt.elapsed() > m_timeoutMs) {
        m_error = QStringLiteral("机器人数据流已停止（已 %1 ms 未收到数据）")
                      .arg(m_lastPacketAt.elapsed());
        return Status::Timeout;
    }

    // Non-blocking: on this port the controller has normally already pushed
    // several packets since the last call, so this advances straight to the
    // newest one. Consuming exactly one packet here would answer with a pose
    // frozen at connect time (stage-10 field report, 2026-10-10).
    drain();

    if (!m_hasPose) {
        // Nothing has arrived yet: wait for the controller's first push. The
        // deadline is the single authority, so a socket error cannot turn this
        // into a busy spin.
        QElapsedTimer timer;
        timer.start();
        while (!m_hasPose && timer.elapsed() < m_timeoutMs) {
            if (m_socket->state() != QAbstractSocket::ConnectedState)
                break;
            const int remaining = m_timeoutMs - static_cast<int>(timer.elapsed());
            if (m_socket->bytesAvailable() <= 0)
                m_socket->waitForReadyRead(qMax(1, remaining));
            drain();
        }
        if (!m_hasPose) {
            if (m_zeroPose) {
                // Every packet parsed, but the pose field is all zeros: report
                // the specific cause (m_error is already set by parsePacket)
                // rather than the generic "no data" timeout.
                return Status::ProtocolError;
            }
            m_error = (m_socket->state() != QAbstractSocket::ConnectedState)
                ? QStringLiteral("机器人连接已断开")
                : QStringLiteral("等待机器人数据超时");
            return Status::Timeout;
        }
    }

    out = m_latest;
    m_error.clear();
    return Status::Ok;
}

QString URRealtimeReader::lastError() const
{
    return m_error;
}

} // namespace RobotPose
