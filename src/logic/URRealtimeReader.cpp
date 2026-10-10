#include "logic/URRealtimeReader.h"

#include <QDataStream>
#include <QElapsedTimer>
#include <QNetworkProxy>
#include <QTcpSocket>

namespace RobotPose {

namespace {
// Offset (in bytes, from the start of the message body, i.e. right after the
// 4-byte length prefix) of the 6 big-endian doubles this adapter reads.
// Empirically confirmed against a real UR/URSim capture (see the Python
// reference used during integration): body = timestamp(8) + 4 * 48-byte
// blocks, then the 48-byte (6 x double) pose block we want.
constexpr int kPoseOffset = 8 + 48 * 4;   // 200
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

bool URRealtimeReader::parsePacket(const QByteArray& packet, Pose& out) const
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
