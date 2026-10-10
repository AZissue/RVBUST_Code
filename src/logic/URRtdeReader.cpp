#include "logic/URRtdeReader.h"

#include <QDataStream>
#include <QElapsedTimer>
#include <QNetworkProxy>
#include <QTcpSocket>

#include <cmath>
#include <cstring>

namespace RobotPose {

namespace {
// Package types (UR's rtde/package_header.h).
constexpr quint8 kRequestProtocolVersion = 86;
constexpr quint8 kSetupOutputs           = 79;
constexpr quint8 kControlStart           = 83;
constexpr quint8 kDataPackage            = 85;

// Every RTDE packet is [uint16 BE size][uint8 type][payload]; `size` includes
// the 3-byte header.
constexpr int kHeaderBytes = 3;
constexpr int kPoseBytes   = 48;   // VECTOR6D = 6 doubles

// 125 Hz is the CB3 ceiling and the rate port 30003 runs at, so the RTDE path
// is a drop-in replacement for the pose-reading cadence. The controller
// divides: it sends at floor(125 / frequency).
constexpr double kFrequencyHz = 125.0;

constexpr quint32 kMaxPacket = 8192;
// Only reachable while desynced; keep a resync from growing without bound.
constexpr int kMaxBuffered = 1 << 20;

// The TCP pose, in the base frame, as reported by actual_TCP_pose.
constexpr char kPoseVariable[] = "actual_TCP_pose";
constexpr char kPoseType[]     = "VECTOR6D";

// Sanity bound for the parsed x/y/z (meters). A UR TCP stays within ~1.3 m of
// the base; 100 m is far beyond any real installation yet still catches the
// denormal/absurd magnitudes a byte-misaligned read produces.
constexpr double kMaxAbsMeters = 100.0;

QByteArray beDouble(double v)
{
    quint64 raw = 0;
    std::memcpy(&raw, &v, sizeof(raw));
    QByteArray out;
    out.reserve(8);
    for (int shift = 56; shift >= 0; shift -= 8)
        out.push_back(static_cast<char>((raw >> shift) & 0xFF));
    return out;
}
} // namespace

URRtdeReader::~URRtdeReader()
{
    disconnect();
}

bool URRtdeReader::connect(const QString& host, quint16 port)
{
    disconnect();
    m_socket = new QTcpSocket;
    // Same reason as the 30003 adapter: a system proxy that does not support
    // raw TCP sockets breaks a direct robot connection even when there is no
    // real proxy in the way.
    m_socket->setProxy(QNetworkProxy::NoProxy);
    m_socket->connectToHost(host, port);
    if (!m_socket->waitForConnected(m_timeoutMs)) {
        m_error = QStringLiteral("连接 %1:%2 失败: %3")
                      .arg(host).arg(port).arg(m_socket->errorString());
        disconnect();
        return false;
    }
    if (!handshake()) {
        // disconnect() does not touch m_error, so the message naming the step
        // that failed survives the cleanup.
        disconnect();
        return false;
    }
    // Only now: the readyRead handler would otherwise consume the handshake
    // replies out from under readResponse().
    QObject::connect(m_socket, &QTcpSocket::readyRead, m_socket, [this]() {
        drain();
    });
    m_error.clear();
    return true;
}

void URRtdeReader::disconnect()
{
    if (m_socket) {
        if (m_socket->state() != QAbstractSocket::UnconnectedState)
            m_socket->disconnectFromHost();
        m_socket->deleteLater();
        m_socket = nullptr;
    }
    m_buf.clear();
    m_hasPose = false;
    m_badPose = false;
    m_latest = Pose{};
    m_lastPacketAt.invalidate();
    m_packetsConsumed = 0;
    m_badHeaders = 0;
    m_recipeId = 0;
}

bool URRtdeReader::isConnected() const
{
    return m_socket && m_socket->state() == QAbstractSocket::ConnectedState;
}

// ── handshake: version -> output recipe -> start ────────────────────────────

bool URRtdeReader::sendCommand(quint8 type, const QByteArray& payload)
{
    const quint16 size = static_cast<quint16>(payload.size() + kHeaderBytes);
    QByteArray packet;
    packet.reserve(size);
    packet.push_back(static_cast<char>((size >> 8) & 0xFF));
    packet.push_back(static_cast<char>(size & 0xFF));
    packet.push_back(static_cast<char>(type));
    packet.append(payload);
    if (m_socket->write(packet) != packet.size()
        || !m_socket->waitForBytesWritten(m_timeoutMs)) {
        m_error = QStringLiteral("向控制器发送 RTDE 命令失败: %1")
                      .arg(m_socket->errorString());
        return false;
    }
    return true;
}

// Read packets until one of `expectedType` arrives. Text messages (and any
// other chatter) are skipped, but the deadline is the single authority, so a
// controller that only answers with surprises cannot spin here forever.
bool URRtdeReader::readResponse(quint8 expectedType, QByteArray& payload)
{
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < m_timeoutMs) {
        if (m_socket->state() != QAbstractSocket::ConnectedState) {
            m_error = QStringLiteral("RTDE 连接已被控制器关闭");
            return false;
        }
        if (m_socket->bytesAvailable() < kHeaderBytes) {
            const int remaining = m_timeoutMs - static_cast<int>(timer.elapsed());
            if (!m_socket->waitForReadyRead(qMax(1, remaining)))
                break;
            continue;
        }
        const QByteArray head = m_socket->read(kHeaderBytes);
        if (head.size() < kHeaderBytes)
            continue;
        const quint16 size = static_cast<quint16>(
            (quint16(static_cast<quint8>(head.at(0))) << 8)
            | quint16(static_cast<quint8>(head.at(1))));
        const quint8 type = static_cast<quint8>(head.at(2));
        if (size < kHeaderBytes || size > kMaxPacket) {
            m_error = QStringLiteral("RTDE 应答长度异常: %1").arg(size);
            return false;
        }
        QByteArray body;
        const int bodyLen = static_cast<int>(size) - kHeaderBytes;
        while (body.size() < bodyLen) {
            if (m_socket->bytesAvailable() <= 0
                && !m_socket->waitForReadyRead(m_timeoutMs)) {
                m_error = QStringLiteral("等待 RTDE 应答超时");
                return false;
            }
            body += m_socket->read(bodyLen - body.size());
        }
        if (type == expectedType) {
            payload = body;
            return true;
        }
        // Not ours (e.g. RTDE_TEXT_MESSAGE): keep the packet moving.
    }
    m_error = QStringLiteral("等待 RTDE 应答超时");
    return false;
}

bool URRtdeReader::handshake()
{
    // 1. Protocol version 2. Version 1 is a different (frequency-less) output
    //    setup, so say so plainly rather than guessing: a v1 controller would
    //    otherwise be parsed with the wrong layout.
    QByteArray payload;
    payload.push_back(char(0));
    payload.push_back(char(2));            // uint16 BE = 2
    if (!sendCommand(kRequestProtocolVersion, payload))
        return false;
    if (!readResponse(kRequestProtocolVersion, payload))
        return false;
    if (payload.size() < 1 || static_cast<quint8>(payload.at(0)) != 1) {
        m_error = QStringLiteral(
            "控制器拒绝了 RTDE 协议版本 2（只支持版本 1）；"
            "本版只实现了版本 2，请改回 UR Realtime (30003) 或升级控制器软件");
        return false;
    }

    // 2. Output recipe. Protocol v2 carries the frequency before the names; the
    //    controller answers with a recipe id and the type it assigned to each
    //    requested variable.
    QByteArray setup = beDouble(kFrequencyHz);
    setup.append(kPoseVariable);
    setup.push_back('\0');
    if (!sendCommand(kSetupOutputs, setup))
        return false;
    if (!readResponse(kSetupOutputs, payload))
        return false;
    if (payload.isEmpty()) {
        m_error = QStringLiteral("控制器对 RTDE 输出配置没有应答内容");
        return false;
    }
    m_recipeId = static_cast<quint8>(payload.at(0));
    const QString types =
        QString::fromLatin1(payload.mid(1)).remove(QLatin1Char('\0')).trimmed();
    if (!types.startsWith(QLatin1String(kPoseType))) {
        m_error = QStringLiteral(
            "控制器没有提供 actual_TCP_pose（应答类型：%1）；"
            "若机器上已有别的 RTDE 客户端，请先断开它再试")
                      .arg(types.isEmpty() ? QStringLiteral("空") : types);
        return false;
    }

    // 3. Start streaming.
    if (!sendCommand(kControlStart, QByteArray()))
        return false;
    if (!readResponse(kControlStart, payload))
        return false;
    if (payload.isEmpty() || static_cast<quint8>(payload.at(0)) != 1) {
        m_error = QStringLiteral("控制器拒绝开始推送 RTDE 数据");
        return false;
    }
    return true;
}

// ── streaming ───────────────────────────────────────────────────────────────

// Parse every complete packet currently buffered, keeping only the newest
// pose.  Called from the readyRead handler (so the stream is consumed even
// while nobody reads a pose -- the controller drops a client that stops
// receiving for 10 s) and from readPose().
void URRtdeReader::drain()
{
    if (!m_socket)
        return;
    m_buf.append(m_socket->readAll());

    int scan = 0;
    while (m_buf.size() - scan >= kHeaderBytes) {
        const quint16 size = static_cast<quint16>(
            (quint16(static_cast<quint8>(m_buf.at(scan))) << 8)
            | quint16(static_cast<quint8>(m_buf.at(scan + 1))));
        const quint8 type = static_cast<quint8>(m_buf.at(scan + 2));
        if (size < kHeaderBytes || size > kMaxPacket) {
            // Not a length this protocol could have produced: the stream lost
            // its alignment. Step one byte and look for the next header.
            ++scan;
            ++m_badHeaders;
            continue;
        }
        if (m_buf.size() - scan < size)
            break;
        if (type == kDataPackage)
            parseData(m_buf.mid(scan + kHeaderBytes, size - kHeaderBytes));
        // Text messages and anything else are skipped by their own length.
        scan += size;
    }
    if (scan > 0)
        m_buf.remove(0, scan);
    if (m_buf.size() > kMaxBuffered) {
        m_buf.clear();
        m_error = QStringLiteral("RTDE 数据流长时间无法同步，已丢弃缓冲");
    }
}

void URRtdeReader::parseData(const QByteArray& payload)
{
    // Data payload = uint8 recipe id + the requested values. The recipe id is
    // part of the v2 data package; deciding by length instead of assuming it
    // (49 bytes with, 48 without) keeps a one-byte misalignment from silently
    // shifting every double.
    const int off = (payload.size() >= kPoseBytes + 1) ? 1 : 0;
    if (payload.size() < off + kPoseBytes)
        return;

    QDataStream ds(payload);
    ds.setByteOrder(QDataStream::BigEndian);
    ds.skipRawData(off);
    double vals[6] = {0, 0, 0, 0, 0, 0};
    for (double& v : vals)
        ds >> v;

    // A misaligned read does not fail, it returns numbers -- just not ones any
    // TCP can have. Refuse those instead of reporting them as a pose.
    for (double v : vals) {
        if (!std::isfinite(v)) {
            m_badPose = true;
            m_error = QStringLiteral("RTDE 位姿出现非有限值，解析可能错位");
            return;
        }
    }
    if (std::fabs(vals[0]) > kMaxAbsMeters
        || std::fabs(vals[1]) > kMaxAbsMeters
        || std::fabs(vals[2]) > kMaxAbsMeters) {
        m_badPose = true;
        m_error = QStringLiteral("RTDE 位姿超出合理范围（|x|>%1 m），解析可能错位")
                      .arg(kMaxAbsMeters);
        return;
    }
    // Six exact zeros are not a pose either (a UR TCP cannot sit at the base
    // origin) -- that signature is what the 30003 offset bug produced.
    if (vals[0] == 0.0 && vals[1] == 0.0 && vals[2] == 0.0
        && vals[3] == 0.0 && vals[4] == 0.0 && vals[5] == 0.0) {
        m_badPose = true;
        m_error = QStringLiteral("RTDE 位姿六个分量全为 0，不是真实位姿");
        return;
    }

    // Meters -> millimeters; rx/ry/rz stay an axis-angle vector in radians.
    m_latest.xyz = { vals[0] * 1000.0, vals[1] * 1000.0, vals[2] * 1000.0 };
    m_latest.rpy = { vals[3], vals[4], vals[5] };
    m_hasPose = true;
    m_lastPacketAt.start();
    ++m_packetsConsumed;
}

Status URRtdeReader::readPose(Pose& out)
{
    if (!isConnected())
        return Status::NotConnected;

    // The controller pushes every cycle, so a stream that has gone quiet means
    // the connection lost the controller even though TCP may still be up.
    // Handing back the last pose as if it were current would be worse than an
    // error: it gets recorded into the cards.
    if (m_hasPose && m_lastPacketAt.elapsed() > m_timeoutMs) {
        m_error = QStringLiteral("机器人数据流已停止（已 %1 ms 未收到数据）")
                      .arg(m_lastPacketAt.elapsed());
        return Status::Timeout;
    }

    drain();

    if (!m_hasPose) {
        // Nothing yet: wait for the controller's first push. The deadline is
        // the single authority, so a socket error cannot turn this into a spin.
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
            if (m_badPose) {
                // m_error already carries the specific cause.
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

QString URRtdeReader::lastError() const
{
    return m_error;
}

} // namespace RobotPose
