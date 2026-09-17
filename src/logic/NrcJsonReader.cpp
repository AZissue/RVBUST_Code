#include "logic/NrcJsonReader.h"

#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QNetworkProxy>
#include <QTcpSocket>

#include <array>

#include "logic/RuntimeLog.h"

namespace RobotPose {

namespace {

constexpr quint8 kNrcMagic0 = 0x4E;   // 'N'
constexpr quint8 kNrcMagic1 = 0x66;   // 'f'

constexpr int kNrcHeaderBytes = 6;    // magic(2) + length(2) + cmd(2)
constexpr int kNrcCrcBytes    = 4;

// A payload larger than this means the stream is desynchronized, not that the
// robot sent a huge reply.
constexpr int kNrcMaxPayloadBytes = 8192;

// RuntimeLog lines go through a 1024-byte buffer (see RuntimeLog.cpp), so the
// raw-response dump is capped well below that.
constexpr int kNrcMaxLoggedHexBytes = 300;
constexpr int kNrcMaxLoggedTextBytes = 400;

// Candidate response field names, tried in this order at the top level and
// inside one level of nesting afterwards.  The response schema could not be
// confirmed against real hardware, so this list is intentionally generous —
// the first array with >= 6 numbers wins.
const char* const kNrcPoseKeys[] = {
    "posValue", "currentPos", "realPosMCS", "realPosACS", "pos", "position",
    "jointPos", "axisPos", "curPos", "cartPos", "pose", "data", "value"
};

const std::array<quint32, 256>& crcTable()
{
    static const std::array<quint32, 256> table = [] {
        std::array<quint32, 256> t{};
        for (quint32 i = 0; i < 256; ++i) {
            quint32 c = i;
            for (int k = 0; k < 8; ++k)
                c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            t[i] = c;
        }
        return t;
    }();
    return table;
}

quint8 byteAt(const QByteArray& b, int i)
{
    return static_cast<quint8>(b.at(i));
}

quint16 readU16BE(const QByteArray& b, int offset)
{
    return static_cast<quint16>((static_cast<quint16>(byteAt(b, offset)) << 8)
                                | byteAt(b, offset + 1));
}

quint32 readU32BE(const QByteArray& b, int offset)
{
    return (static_cast<quint32>(byteAt(b, offset)) << 24)
        | (static_cast<quint32>(byteAt(b, offset + 1)) << 16)
        | (static_cast<quint32>(byteAt(b, offset + 2)) << 8)
        | static_cast<quint32>(byteAt(b, offset + 3));
}

void appendU16BE(QByteArray& out, quint16 v)
{
    out.push_back(static_cast<char>((v >> 8) & 0xFF));
    out.push_back(static_cast<char>(v & 0xFF));
}

void appendU32BE(QByteArray& out, quint32 v)
{
    out.push_back(static_cast<char>((v >> 24) & 0xFF));
    out.push_back(static_cast<char>((v >> 16) & 0xFF));
    out.push_back(static_cast<char>((v >> 8) & 0xFF));
    out.push_back(static_cast<char>(v & 0xFF));
}

QString hexDump(const QByteArray& b, int maxBytes)
{
    const int n = qMin(b.size(), maxBytes);
    QString s = QString::fromLatin1(b.left(n).toHex(' '));
    if (n < b.size())
        s += QStringLiteral(" ... (%1 bytes total)").arg(b.size());
    return s;
}

QString textDump(const QByteArray& b, int maxChars)
{
    QString s = QString::fromUtf8(b).trimmed();
    // Keep the log line on one line and inside the RuntimeLog buffer.
    s.replace(QLatin1Char('\n'), QLatin1Char(' '));
    if (s.size() > maxChars)
        s = s.left(maxChars) + QStringLiteral("...");
    return s;
}

QString cmdHex(quint16 cmd)
{
    // "0x2F07" — the 0x prefix must stay lowercase, so the hex digits alone
    // are upper-cased here instead of the whole string.
    return QStringLiteral("0x")
        + QString::number(cmd, 16).toUpper().rightJustified(4, QLatin1Char('0'));
}

// Fills `out` from a JSON array of >= 6 numbers (numeric strings accepted).
bool arrayToPose(const QJsonArray& arr, Pose& out)
{
    if (arr.size() < 6)
        return false;
    double v[6] = {0, 0, 0, 0, 0, 0};
    for (int i = 0; i < 6; ++i) {
        const QJsonValue val = arr.at(i);
        if (val.isDouble()) {
            v[i] = val.toDouble();
        } else if (val.isString()) {
            bool ok = false;
            const double d = val.toString().toDouble(&ok);
            if (!ok)
                return false;
            v[i] = d;
        } else {
            return false;
        }
    }
    // Project convention (see RobotPose::Pose): mm + degrees, passthrough.
    out.xyz = { v[0], v[1], v[2] };
    out.rpy = { v[3], v[4], v[5] };
    return true;
}

// `depth` is the number of additional nesting levels to search.
bool findPoseArray(const QJsonObject& obj, int depth, Pose& out, QString* why)
{
    // 1st pass: the documented candidate names, in order.
    for (const char* key : kNrcPoseKeys) {
        const QJsonValue val = obj.value(QLatin1String(key));
        if (!val.isArray())
            continue;
        if (arrayToPose(val.toArray(), out))
            return true;
        if (why && why->isEmpty()) {
            const int n = val.toArray().size();
            *why = n < 6
                ? QStringLiteral("字段 %1 只有 %2 个数值，需要至少 6 个")
                      .arg(QLatin1String(key)).arg(n)
                : QStringLiteral("字段 %1 的前 6 个元素不是数值").arg(QLatin1String(key));
        }
    }

    // 2nd pass: a bare >= 6 element array under a name that is not on the
    // candidate list, then (one level only) nested objects such as
    // {"data":{...}} / {"result":{...}}.  The real schema is unconfirmed, so a
    // correct-looking array beats a hard failure.
    for (auto it = obj.begin(); it != obj.end(); ++it) {
        if (it.value().isArray() && arrayToPose(it.value().toArray(), out))
            return true;
        if (depth > 0 && it.value().isObject()
            && findPoseArray(it.value().toObject(), depth - 1, out, why)) {
            return true;
        }
    }
    return false;
}

} // namespace

NrcJsonReader::~NrcJsonReader()
{
    disconnect();
}

quint32 NrcJsonReader::crc32(const QByteArray& data)
{
    const std::array<quint32, 256>& table = crcTable();
    quint32 c = 0xFFFFFFFFu;
    for (char ch : data) {
        const quint8 b = static_cast<quint8>(static_cast<unsigned char>(ch));
        c = table[(c ^ b) & 0xFFu] ^ (c >> 8);
    }
    return c ^ 0xFFFFFFFFu;
}

QByteArray NrcJsonReader::buildFrame(quint16 cmd, const QByteArray& json)
{
    QByteArray frame;
    frame.reserve(kNrcHeaderBytes + json.size() + kNrcCrcBytes);
    frame.push_back(static_cast<char>(kNrcMagic0));
    frame.push_back(static_cast<char>(kNrcMagic1));
    appendU16BE(frame, static_cast<quint16>(json.size()));
    appendU16BE(frame, cmd);
    frame.append(json);
    // CRC covers the length field through the last JSON byte.
    appendU32BE(frame, crc32(frame.mid(2, frame.size() - 2)));
    return frame;
}

QByteArray NrcJsonReader::connectRequestJson(int robot)
{
    return QByteArrayLiteral("{\"robot\":") + QByteArray::number(robot) + QByteArrayLiteral("}\n");
}

QByteArray NrcJsonReader::poseRequestJson(int coord, int robot)
{
    return QByteArrayLiteral("{\"coord\":") + QByteArray::number(coord)
        + QByteArrayLiteral(",\"robot\":") + QByteArray::number(robot) + QByteArrayLiteral("}\n");
}

Status NrcJsonReader::parsePoseJson(const QByteArray& json, Pose& out, QString* error)
{
    auto fail = [error](const QString& why) {
        if (error)
            *error = why;
        return Status::ProtocolError;
    };

    QJsonParseError pe{};
    const QJsonDocument doc = QJsonDocument::fromJson(json, &pe);
    if (pe.error != QJsonParseError::NoError) {
        return fail(QStringLiteral("应答 JSON 解析失败（偏移 %1：%2）")
                        .arg(pe.offset).arg(pe.errorString()));
    }

    QString why;
    if (doc.isArray()) {
        if (arrayToPose(doc.array(), out)) {
            if (error)
                error->clear();
            return Status::Ok;
        }
        why = doc.array().size() < 6
            ? QStringLiteral("应答数组只有 %1 个数值，需要至少 6 个").arg(doc.array().size())
            : QStringLiteral("应答数组的前 6 个元素不是数值");
    } else if (doc.isObject()) {
        if (findPoseArray(doc.object(), 1, out, &why)) {
            if (error)
                error->clear();
            return Status::Ok;
        }
    } else {
        why = QStringLiteral("应答既不是 JSON 对象也不是数组");
    }

    if (why.isEmpty())
        why = QStringLiteral("应答中找不到 6 元素位姿数组（候选字段：posValue/currentPos/"
                             "realPosMCS/realPosACS/pos/position/jointPos/axisPos/curPos/"
                             "cartPos/pose/data/value）");
    return fail(why);
}

bool NrcJsonReader::isConnected() const
{
    return m_socket && m_socket->state() == QAbstractSocket::ConnectedState;
}

void NrcJsonReader::setTimeoutMs(int ms)
{
    if (ms > 0)
        m_timeoutMs = ms;
}

void NrcJsonReader::disconnect()
{
    if (m_socket) {
        if (m_socket->state() != QAbstractSocket::UnconnectedState)
            m_socket->disconnectFromHost();
        m_socket->deleteLater();
        m_socket = nullptr;
    }
    m_lastResponse.clear();
}

void NrcJsonReader::dropPendingInput()
{
    if (m_socket)
        m_socket->readAll();
}

bool NrcJsonReader::connect(const QString& host, quint16 port)
{
    disconnect();
    m_socket = new QTcpSocket;
    // Some environments (notably VMs) have Qt auto-detect a system proxy that
    // does not support raw TCP sockets.  Force no proxy for this direct robot
    // connection (same as the Modbus / UR adapters).
    m_socket->setProxy(QNetworkProxy::NoProxy);
    m_socket->connectToHost(host, port);
    if (!m_socket->waitForConnected(m_timeoutMs)) {
        m_error = QStringLiteral("连接 %1:%2 失败: %3")
                      .arg(host).arg(port).arg(m_socket->errorString());
        disconnect();
        return false;
    }

    // The vendor SDK opens every session with connect_robot (0x2002).  Its
    // reply schema is unconfirmed, so the handshake is best-effort: the robot
    // is usable even if it stays silent, and a reply that does arrive is
    // logged plus skipped by transact() (command id mismatch) instead of being
    // mis-parsed as a pose.
    const QByteArray frame = buildFrame(kNrcCmdConnect, connectRequestJson());
    if (m_socket->write(frame) != frame.size() || !m_socket->waitForBytesWritten(m_timeoutMs)) {
        m_error = QStringLiteral("发送连接握手(0x2002)失败: %1").arg(m_socket->errorString());
        disconnect();
        return false;
    }
    m_socket->flush();
    m_error.clear();
    RuntimeLog::log("[NRC] handshake 0x2002 -> %s:%u (%d bytes)",
                    qPrintable(host), static_cast<unsigned>(port), frame.size());
    return true;
}

Status NrcJsonReader::readFrame(QByteArray& payload, quint16& cmd, int budgetMs)
{
    payload.clear();
    cmd = 0;

    QElapsedTimer clock;
    clock.start();
    auto remaining = [&clock, budgetMs]() {
        return qMax(1, budgetMs - static_cast<int>(clock.elapsed()));
    };
    // Accumulates into `payload` until it holds `need` bytes.  On failure the
    // socket input is dropped so the next call starts at a frame boundary.
    auto fill = [this, &payload, &remaining](int need) -> Status {
        while (payload.size() < need) {
            if (m_socket->bytesAvailable() <= 0 && !m_socket->waitForReadyRead(remaining())) {
                m_error = QStringLiteral("等待机器人应答超时");
                dropPendingInput();
                return Status::Timeout;
            }
            const QByteArray chunk = m_socket->read(need - payload.size());
            if (chunk.isEmpty()) {
                // Wait reported data but nothing arrived: the peer is gone.
                dropPendingInput();
                if (m_socket->state() != QAbstractSocket::ConnectedState) {
                    m_error = QStringLiteral("机器人连接已断开");
                    return Status::NotConnected;
                }
                m_error = QStringLiteral("等待机器人应答超时");
                return Status::Timeout;
            }
            payload += chunk;
        }
        return Status::Ok;
    };

    Status s = fill(kNrcHeaderBytes);
    if (s != Status::Ok)
        return s;

    if (byteAt(payload, 0) != kNrcMagic0 || byteAt(payload, 1) != kNrcMagic1) {
        m_error = QStringLiteral("应答帧头异常（期望 'Nf'，收到 %1）")
                      .arg(QString::fromLatin1(payload.left(2).toHex(' ')));
        dropPendingInput();
        return Status::ProtocolError;
    }

    const int len = readU16BE(payload, 2);
    cmd = readU16BE(payload, 4);
    if (len <= 0 || len > kNrcMaxPayloadBytes) {
        m_error = QStringLiteral("应答数据长度异常: %1").arg(len);
        dropPendingInput();
        return Status::ProtocolError;
    }

    s = fill(kNrcHeaderBytes + len + kNrcCrcBytes);
    if (s != Status::Ok)
        return s;

    const quint32 want = readU32BE(payload, kNrcHeaderBytes + len);
    const quint32 got = crc32(payload.mid(2, 4 + len));
    if (want != got) {
        m_error = QStringLiteral("应答 CRC 校验失败（收到 0x%1，计算 0x%2）")
                      .arg(want, 8, 16, QLatin1Char('0'))
                      .arg(got, 8, 16, QLatin1Char('0'));
        return Status::ProtocolError;
    }

    payload = payload.mid(kNrcHeaderBytes, len);   // keep only the JSON body
    return Status::Ok;
}

Status NrcJsonReader::transact(quint16 cmd, const QByteArray& json, QByteArray& payload)
{
    payload.clear();
    if (!isConnected())
        return Status::NotConnected;

    const QByteArray frame = buildFrame(cmd, json);
    if (m_socket->write(frame) != frame.size()) {
        m_error = QStringLiteral("发送 %1 命令失败").arg(cmdHex(cmd));
        return Status::ProtocolError;
    }
    m_socket->flush();

    // Frames for another command (e.g. a late reply to the 0x2002 handshake)
    // are skipped rather than mis-parsed as the pose.
    QElapsedTimer clock;
    clock.start();
    while (true) {
        const int left = m_timeoutMs - static_cast<int>(clock.elapsed());
        if (left <= 0) {
            m_error = QStringLiteral("等待 %1 应答超时").arg(cmdHex(cmd));
            dropPendingInput();
            return Status::Timeout;
        }
        quint16 got = 0;
        const Status s = readFrame(payload, got, left);
        if (s != Status::Ok)
            return s;
        if (got == cmd)
            return Status::Ok;
        RuntimeLog::log("[NRC] skip %s frame while waiting for %s (%d bytes)",
                        qPrintable(cmdHex(got)), qPrintable(cmdHex(cmd)), payload.size());
        payload.clear();
    }
}

Status NrcJsonReader::readPose(Pose& out)
{
    m_lastResponse.clear();

    QByteArray payload;
    const Status s = transact(kNrcCmdGetCurrentPosition, poseRequestJson(0, 1), payload);
    if (s != Status::Ok)
        return s;

    m_lastResponse = payload;
    // Always dump the raw reply: the response schema is unconfirmed, so the
    // log is what a field session uses to pin the real field names down.
    RuntimeLog::log("[NRC] %s resp %d bytes: %s",
                    qPrintable(cmdHex(kNrcCmdGetCurrentPosition)), payload.size(),
                    qPrintable(hexDump(payload, kNrcMaxLoggedHexBytes)));
    RuntimeLog::log("[NRC] %s resp text: %s",
                    qPrintable(cmdHex(kNrcCmdGetCurrentPosition)),
                    qPrintable(textDump(payload, kNrcMaxLoggedTextBytes)));

    QString why;
    const Status p = parsePoseJson(payload, out, &why);
    if (p != Status::Ok) {
        m_error = why;
        RuntimeLog::log("[NRC] pose parse failed: %s", qPrintable(why));
        return p;
    }

    m_error.clear();
    RuntimeLog::log("[NRC] pose ok: x=%.3f y=%.3f z=%.3f rx=%.3f ry=%.3f rz=%.3f",
                    out.xyz[0], out.xyz[1], out.xyz[2],
                    out.rpy[0], out.rpy[1], out.rpy[2]);
    return Status::Ok;
}

QString NrcJsonReader::lastError() const
{
    return m_error;
}

} // namespace RobotPose
