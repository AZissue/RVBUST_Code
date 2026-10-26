#include "test_fairino.h"

#include <QtTest>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <mutex>
#include <thread>
#include <winsock2.h>

#include "logic/FairinoCommand.h"
#include "logic/FairinoMath.h"
#include "logic/FairinoPoseReader.h"
#include "logic/FairinoRealtime.h"
#include "logic/FairinoXmlRpc.h"
#include "logic/FairinoXmlRpcClient.h"
#include "logic/RobotPose.h"

namespace {

using FairinoXmlRpc::HttpStatus;
using FairinoXmlRpc::Value;

constexpr int kFrameBytes = FairinoRealtime::kStructBytes;

void putU16LE(QByteArray& bytes, int offset, quint16 value)
{
    bytes[offset] = static_cast<char>(value & 0xFF);
    bytes[offset + 1] = static_cast<char>((value >> 8) & 0xFF);
}

void putI32LE(QByteArray& bytes, int offset, qint32 value)
{
    const quint32 raw = static_cast<quint32>(value);
    for (int i = 0; i < 4; ++i)
        bytes[offset + i] = static_cast<char>((raw >> (8 * i)) & 0xFF);
}

void putDoubleLE(QByteArray& bytes, int offset, double value)
{
    quint64 raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    for (int i = 0; i < 8; ++i)
        bytes[offset + i] = static_cast<char>((raw >> (8 * i)) & 0xFF);
}

// 1229 字节 payload 的 20004 帧。字段偏移直接用生产解析器里的常量 ——
// 这里要证明的是"读到的值来自正确的偏移"，所以 flange 故意填 900+i：
// 如果 TCP 读错了字段，拿到的就是 900 量级而不是 100 量级。
QByteArray buildFrame(const std::array<double, 6>& tcp,
                      const std::array<double, 6>& joint, quint8 counter,
                      qint32 motionDone = 1, qint32 queueLength = 0,
                      qint32 enabled = 1, quint8 robotMode = 0,
                      qint32 tool = 1, qint32 user = 2)
{
    QByteArray frame(kFrameBytes, '\0');
    frame[0] = static_cast<char>(FairinoRealtime::kFrameHead);
    frame[1] = static_cast<char>(FairinoRealtime::kFrameHead);
    frame[2] = static_cast<char>(counter);
    putU16LE(frame, 3,
             static_cast<quint16>(FairinoRealtime::kMinPayloadBytes));
    frame[FairinoRealtime::kProgramStateOffset] = 1;
    frame[FairinoRealtime::kRobotStateOffset] = 1;
    frame[FairinoRealtime::kRobotModeOffset] = static_cast<char>(robotMode);
    for (int i = 0; i < 6; ++i) {
        putDoubleLE(frame, FairinoRealtime::kJointOffset + i * 8, joint[i]);
        putDoubleLE(frame, FairinoRealtime::kTcpPoseOffset + i * 8, tcp[i]);
        putDoubleLE(frame, FairinoRealtime::kFlangePoseOffset + i * 8,
                    900.0 + i);
    }
    putI32LE(frame, FairinoRealtime::kToolOffset, tool);
    putI32LE(frame, FairinoRealtime::kUserOffset, user);
    putI32LE(frame, FairinoRealtime::kMotionDoneOffset, motionDone);
    putI32LE(frame, FairinoRealtime::kQueueLengthOffset, queueLength);
    putI32LE(frame, FairinoRealtime::kEnabledOffset, enabled);

    quint32 sum = 0;
    for (int i = 0; i < FairinoRealtime::kChecksumOffset; ++i)
        sum += static_cast<quint8>(frame.at(i));
    putU16LE(frame, FairinoRealtime::kChecksumOffset,
             static_cast<quint16>(sum & 0xFFFFu));
    return frame;
}

std::array<double, 6> joints123456()
{
    return { 1.0, 2.0, 3.0, 4.0, 5.0, 6.0 };
}

// 一个会持续推 20004 帧的假控制器。和 UR 的 mock 一样，只有"持续推"才能
// 复现"只消费一帧 → 界面永远停在连接时位姿"（stage-10 现场问题）。
class MockFairinoStream {
public:
    ~MockFairinoStream() { stop(); }

    // maxFrames >= 0：推这么多帧后保持连接但不再发送（控制器掉线、TCP 未断）。
    bool start(int intervalMs = 2, int maxFrames = -1, bool zeroTcp = false)
    {
        m_intervalMs = intervalMs;
        m_maxFrames = maxFrames;
        m_zeroTcp = zeroTcp;
        m_running.store(true);
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
            return false;
        m_wsaUp = true;
        m_listen = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (m_listen == INVALID_SOCKET)
            return false;
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        addr.sin_port = 0;
        if (bind(m_listen, reinterpret_cast<sockaddr*>(&addr), sizeof(addr))
            == SOCKET_ERROR)
            return false;
        if (listen(m_listen, 4) == SOCKET_ERROR)
            return false;
        sockaddr_in bound{};
        int len = sizeof(bound);
        if (getsockname(m_listen, reinterpret_cast<sockaddr*>(&bound), &len)
            == SOCKET_ERROR)
            return false;
        m_port = ntohs(bound.sin_port);
        m_thread = std::thread([this]() { serve(); });
        return true;
    }

    quint16 port() const { return m_port; }
    int sent() const { return m_sent.load(); }

    void stop()
    {
        m_running.store(false);
        if (m_listen != INVALID_SOCKET) {
            closesocket(m_listen);
            m_listen = INVALID_SOCKET;
        }
        if (m_thread.joinable())
            m_thread.join();
        if (m_wsaUp) {
            WSACleanup();
            m_wsaUp = false;
        }
    }

private:
    void serve()
    {
        SOCKET client = accept(m_listen, nullptr, nullptr);
        if (client == INVALID_SOCKET)
            return;
        DWORD sndTimeout = 300;
        setsockopt(client, SOL_SOCKET, SO_SNDTIMEO,
                   reinterpret_cast<const char*>(&sndTimeout),
                   sizeof(sndTimeout));

        int i = 0;
        while (m_running.load()) {
            if (m_maxFrames >= 0 && i >= m_maxFrames) {
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
                continue;
            }
            const std::array<double, 6> tcp = m_zeroTcp
                ? std::array<double, 6>{ 0, 0, 0, 0, 0, 0 }
                : std::array<double, 6>{ 100.0 + i, 200.0, 300.0,
                                         10.0, 20.0, 30.0 };
            const QByteArray frame =
                buildFrame(tcp, joints123456(), static_cast<quint8>(i & 0xFF));
            if (::send(client, frame.constData(),
                       static_cast<int>(frame.size()), 0) == SOCKET_ERROR)
                break;
            m_sent.store(++i);
            std::this_thread::sleep_for(
                std::chrono::milliseconds(m_intervalMs));
        }
        closesocket(client);
    }

    SOCKET m_listen = INVALID_SOCKET;
    quint16 m_port = 0;
    int m_intervalMs = 2;
    int m_maxFrames = -1;
    bool m_zeroTcp = false;
    bool m_wsaUp = false;
    std::atomic<bool> m_running{false};
    std::atomic<int> m_sent{0};
    std::thread m_thread;
};

// 一条请求、一条固定应答的 20003 假服务。记录请求原文，用来断言真正的
// 方法名/参数确实上了线（而不是只测了我们自己的构造函数）。
class MockXmlRpcServer {
public:
    ~MockXmlRpcServer() { stop(); }

    bool start(const QByteArray& response)
    {
        m_response = response;
        m_running.store(true);
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
            return false;
        m_wsaUp = true;
        m_listen = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (m_listen == INVALID_SOCKET)
            return false;
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        addr.sin_port = 0;
        if (bind(m_listen, reinterpret_cast<sockaddr*>(&addr), sizeof(addr))
            == SOCKET_ERROR)
            return false;
        if (listen(m_listen, 4) == SOCKET_ERROR)
            return false;
        sockaddr_in bound{};
        int len = sizeof(bound);
        if (getsockname(m_listen, reinterpret_cast<sockaddr*>(&bound), &len)
            == SOCKET_ERROR)
            return false;
        m_port = ntohs(bound.sin_port);
        m_thread = std::thread([this]() { serve(); });
        return true;
    }

    quint16 port() const { return m_port; }

    QByteArray request() const
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_request;
    }

    void stop()
    {
        m_running.store(false);
        if (m_listen != INVALID_SOCKET) {
            closesocket(m_listen);
            m_listen = INVALID_SOCKET;
        }
        if (m_thread.joinable())
            m_thread.join();
        if (m_wsaUp) {
            WSACleanup();
            m_wsaUp = false;
        }
    }

private:
    static int contentLength(const QByteArray& header)
    {
        const QByteArray lower = header.toLower();
        const int at = lower.indexOf("content-length:");
        if (at < 0)
            return 0;
        int end = lower.indexOf("\r\n", at);
        if (end < 0)
            end = lower.size();
        bool ok = false;
        const int value = lower.mid(at + 15, end - at - 15).trimmed().toInt(&ok);
        return ok && value > 0 ? value : 0;
    }

    void serve()
    {
        SOCKET client = accept(m_listen, nullptr, nullptr);
        if (client == INVALID_SOCKET)
            return;
        DWORD timeout = 3000;
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO,
                   reinterpret_cast<const char*>(&timeout), sizeof(timeout));
        setsockopt(client, SOL_SOCKET, SO_SNDTIMEO,
                   reinterpret_cast<const char*>(&timeout), sizeof(timeout));

        QByteArray data;
        char buffer[4096];
        while (data.indexOf("\r\n\r\n") < 0) {
            const int got = ::recv(client, buffer, sizeof(buffer), 0);
            if (got <= 0)
                break;
            data.append(buffer, got);
            if (data.size() > (1 << 20))
                break;
        }
        const int headerEnd = data.indexOf("\r\n\r\n");
        if (headerEnd >= 0) {
            const int bodyStart = headerEnd + 4;
            const int expected = bodyStart + contentLength(data.left(headerEnd));
            while (data.size() < expected) {
                const int got = ::recv(client, buffer, sizeof(buffer), 0);
                if (got <= 0)
                    break;
                data.append(buffer, got);
            }
        }
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_request = data;
        }
        if (!m_response.isEmpty())
            ::send(client, m_response.constData(),
                   static_cast<int>(m_response.size()), 0);
        closesocket(client);
    }

    SOCKET m_listen = INVALID_SOCKET;
    quint16 m_port = 0;
    QByteArray m_response;
    mutable std::mutex m_mutex;
    QByteArray m_request;
    bool m_wsaUp = false;
    std::atomic<bool> m_running{false};
    std::thread m_thread;
};

QByteArray httpResponse(const QByteArray& xml)
{
    QByteArray out = "HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\n"
                     "Content-Length: ";
    out += QByteArray::number(xml.size());
    out += "\r\nConnection: close\r\n\r\n";
    out += xml;
    return out;
}

QByteArray arrayResponse(const QByteArray& valuesXml)
{
    return "<methodResponse><params><param><value><array><data>"
         + valuesXml
         + "</data></array></value></param></params></methodResponse>";
}

QByteArray intValue(int v)
{
    return "<value><int>" + QByteArray::number(v) + "</int></value>";
}

} // namespace

// ── XML-RPC ───────────────────────────────────────────────────────────

void TestFairino::xmlBuildIncludesMethodAndParams()
{
    const QString xml = FairinoXmlRpc::buildMethodCall(
        QStringLiteral("GetInverseKin"),
        { Value::fromInt(0),
          Value::fromArray({ Value::fromDouble(1.5),
                             Value::fromString(QStringLiteral("a&b")) }),
          Value::fromInt(-1) });

    QVERIFY(xml.contains(QStringLiteral("<methodName>GetInverseKin</methodName>")));
    QVERIFY(xml.contains(QStringLiteral("<int>0</int>")));
    QVERIFY(xml.contains(QStringLiteral("<double>1.5</double>")));
    QVERIFY(xml.contains(QStringLiteral("a&amp;b")));
    QVERIFY(xml.contains(QStringLiteral("<array><data>")));

    const QByteArray http = FairinoXmlRpc::buildHttpPost(
        QStringLiteral("192.168.58.2"), 20003, xml.toUtf8());
    QVERIFY(http.startsWith("POST /RPC2 HTTP/1.1\r\n"));
    QVERIFY(http.contains("Host: 192.168.58.2:20003\r\n"));
    QVERIFY(http.contains("Content-Type: text/xml\r\n"));
    QVERIFY(http.contains("Connection: close\r\n"));
    QVERIFY(http.contains("Content-Length: "
                          + QByteArray::number(xml.toUtf8().size()) + "\r\n"));
    QVERIFY(http.endsWith(xml.toUtf8()));
}

void TestFairino::xmlParsesWrappedArray()
{
    const QByteArray xml = arrayResponse(
        "<value><i4>0</i4></value>"
        "<value><double>1.25</double></value>"
        "<value><string>ok</string></value>"
        "<value><boolean>1</boolean></value>");

    QList<Value> values;
    QString fault;
    QString error;
    QVERIFY(FairinoXmlRpc::parseMethodResponse(xml, values, &fault, &error));
    QVERIFY2(fault.isEmpty(), qPrintable(fault));
    QVERIFY2(error.isEmpty(), qPrintable(error));
    QCOMPARE(values.size(), 4);

    int code = -1;
    QVERIFY(FairinoXmlRpc::firstErrorCode(values, &code, &error));
    QCOMPARE(code, 0);
    double d = 0.0;
    QVERIFY(values.at(1).asDouble(&d));
    QCOMPARE(d, 1.25);
    QCOMPARE(values.at(2).stringValue, QStringLiteral("ok"));
    QVERIFY(values.at(3).kind == Value::Kind::Bool);
    QVERIFY(values.at(3).boolValue);
}

void TestFairino::xmlParsesMultipleParams()
{
    const QByteArray xml =
        "<methodResponse><params>"
        "<param><value><int>0</int></value></param>"
        "<param><value><int>7</int></value></param>"
        "</params></methodResponse>";
    QList<Value> values;
    QString fault;
    QString error;
    QVERIFY(FairinoXmlRpc::parseMethodResponse(xml, values, &fault, &error));
    QCOMPARE(values.size(), 2);
    int code = -1;
    QVERIFY(FairinoXmlRpc::firstErrorCode(values, &code, &error));
    QCOMPARE(code, 0);
    qint64 second = 0;
    QVERIFY(values.at(1).asInt(&second));
    QCOMPARE(second, qint64(7));
}

void TestFairino::xmlParsesFault()
{
    const QByteArray xml =
        "<methodResponse><fault><value><struct>"
        "<member><name>faultCode</name><value><int>1</int></value></member>"
        "<member><name>faultString</name><value><string>boom</string></value>"
        "</member></struct></value></fault></methodResponse>";
    QList<Value> values;
    QString fault;
    QString error;
    QVERIFY(!FairinoXmlRpc::parseMethodResponse(xml, values, &fault, &error));
    QVERIFY(values.isEmpty());
    QVERIFY2(fault.contains(QStringLiteral("boom")), qPrintable(fault));
    QVERIFY2(fault.contains(QStringLiteral("1")), qPrintable(fault));
}

void TestFairino::xmlRejectsGarbage()
{
    QList<Value> values;
    QString fault;
    QString error;
    QVERIFY(!FairinoXmlRpc::parseMethodResponse("<html><body/>", values, &fault,
                                               &error));
    QVERIFY(!error.isEmpty());
    QVERIFY(!FairinoXmlRpc::parseMethodResponse(QByteArray(), values, &fault,
                                                &error));
    QVERIFY(!error.isEmpty());
}

void TestFairino::firstErrorCodeRejectsNonInteger()
{
    QList<Value> values{ Value::fromString(QStringLiteral("oops")) };
    int code = 0;
    QString error;
    QVERIFY(!FairinoXmlRpc::firstErrorCode(values, &code, &error));
    QVERIFY(!error.isEmpty());

    values = { Value::fromDouble(0.0) };
    QVERIFY(FairinoXmlRpc::firstErrorCode(values, &code, &error));
    QCOMPARE(code, 0);
}

// ── HTTP 分帧 ─────────────────────────────────────────────────────────

void TestFairino::httpContentLengthSplitAcrossReads()
{
    const QByteArray full =
        "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello";
    QByteArray buffer = full.left(20);   // header cut in the middle
    QByteArray body;
    QString error;
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::NeedMore);

    buffer = full.left(full.size() - 2);   // header + "hel"
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::NeedMore);

    buffer = full + "WORLD";   // complete response plus the next one's bytes
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::Complete);
    QCOMPARE(body, QByteArray("hello"));
    QCOMPARE(buffer, QByteArray("WORLD"));
}

void TestFairino::httpChunked()
{
    QByteArray buffer =
        "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        "5\r\nhello\r\n1\r\n \r\n5\r\nworld\r\n0\r\n\r\n";
    const QByteArray complete = buffer;
    buffer = complete.left(complete.size() - 8);
    QByteArray body;
    QString error;
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::NeedMore);
    buffer = complete;
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::Complete);
    QCOMPARE(body, QByteArray("hello world"));
    QVERIFY(buffer.isEmpty());
}

void TestFairino::httpCloseDelimited()
{
    QByteArray buffer = "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nabc";
    QByteArray body;
    QString error;
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::NeedMore);
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, true, body, &error),
             HttpStatus::Complete);
    QCOMPARE(body, QByteArray("abc"));
    QVERIFY(buffer.isEmpty());
}

void TestFairino::httpRejectsNon200()
{
    QByteArray buffer = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n";
    QByteArray body;
    QString error;
    QCOMPARE(FairinoXmlRpc::takeHttpResponse(buffer, false, body, &error),
             HttpStatus::Invalid);
    QVERIFY2(error.contains(QStringLiteral("404")), qPrintable(error));
}

// ── 20004 状态包 ──────────────────────────────────────────────────────

void TestFairino::realtimeDecodesMeasuredOffsets()
{
    const std::array<double, 6> tcp{ 101.5, 202.5, 303.5, 11.0, 22.0, 33.0 };
    const QByteArray frame = buildFrame(tcp, joints123456(), 7, 1, 0, 1, 0, 3, 4);

    FairinoRealtime::State state;
    QVERIFY(FairinoRealtime::decodeFrame(frame, &state));
    QCOMPARE(int(state.frameCounter), 7);
    QCOMPARE(state.mainCode, 0);
    QCOMPARE(state.subCode, 0);
    QCOMPARE(int(state.robotMode), 0);
    QCOMPARE(state.motionDone, 1);
    QCOMPARE(state.queueLength, 0);
    QCOMPARE(state.enabled, 1);
    QCOMPARE(state.toolId, 3);
    QCOMPARE(state.userId, 4);
    for (int i = 0; i < 6; ++i) {
        QCOMPARE(state.tcp[static_cast<std::size_t>(i)], tcp[static_cast<std::size_t>(i)]);
        QCOMPARE(state.joint[static_cast<std::size_t>(i)], double(i + 1));
        // flange 的哨兵值：读错字段会在这里立刻暴露。
        QCOMPARE(state.flange[static_cast<std::size_t>(i)], 900.0 + i);
    }
    QVERIFY(FairinoRealtime::stateHasFinitePose(state));
}

void TestFairino::realtimeParserWaitsForSplitFrame()
{
    const QByteArray frame = buildFrame({ 100, 200, 300, 10, 20, 30 },
                                        joints123456(), 1);
    FairinoRealtime::Parser parser;
    FairinoRealtime::State latest;
    QCOMPARE(parser.feed(frame.left(100), &latest), 0);
    QCOMPARE(parser.bufferedBytes(), 100);
    QCOMPARE(parser.feed(frame.mid(100), &latest), 1);
    QCOMPARE(parser.acceptedFrames(), quint64(1));
    QCOMPARE(latest.tcp[0], 100.0);
}

void TestFairino::realtimeParserKeepsNewestOfCoalescedFrames()
{
    const QByteArray first = buildFrame({ 100, 200, 300, 10, 20, 30 },
                                        joints123456(), 1);
    const QByteArray second = buildFrame({ 400, 500, 600, 40, 50, 60 },
                                         joints123456(), 2);
    FairinoRealtime::Parser parser;
    FairinoRealtime::State latest;
    QCOMPARE(parser.feed(first + second, &latest), 2);
    QCOMPARE(latest.tcp[0], 400.0);
    QCOMPARE(int(latest.frameCounter), 2);
    QCOMPARE(parser.bufferedBytes(), 0);
}

void TestFairino::realtimeParserResyncsAfterGarbage()
{
    const QByteArray frame = buildFrame({ 100, 200, 300, 10, 20, 30 },
                                        joints123456(), 1);
    FairinoRealtime::Parser parser;
    FairinoRealtime::State latest;
    QCOMPARE(parser.feed(QByteArray("\x01\x02\x03", 3) + frame, &latest), 1);
    QCOMPARE(parser.skippedBytes(), quint64(3));
    QCOMPARE(latest.tcp[1], 200.0);
}

void TestFairino::realtimeRejectsBadChecksum()
{
    QByteArray bad = buildFrame({ 100, 200, 300, 10, 20, 30 },
                                joints123456(), 1);
    bad[100] = static_cast<char>(bad.at(100) ^ 0x01);
    const QByteArray good = buildFrame({ 700, 800, 900, 70, 80, 90 },
                                       joints123456(), 2);

    FairinoRealtime::Parser parser;
    FairinoRealtime::State latest;
    QCOMPARE(parser.feed(bad + good, &latest), 1);
    QCOMPARE(parser.rejectedChecksums(), quint64(1));
    QCOMPARE(latest.tcp[0], 700.0);
}

void TestFairino::realtimeRejectsWrongDataLength()
{
    QByteArray frame = buildFrame({ 100, 200, 300, 10, 20, 30 },
                                  joints123456(), 1);
    putU16LE(frame, 3, 100);   // < kMinPayloadBytes
    FairinoRealtime::State state;
    QVERIFY(!FairinoRealtime::decodeFrame(frame, &state));
}

// ── 命令参数（与 Robot.py 实测一致）────────────────────────────────

void TestFairino::moveLArgumentLayout()
{
    const std::array<double, 6> joint{ 1, 2, 3, 4, 5, 6 };
    const std::array<double, 6> cart{ 100, 200, 300, 10, 20, 30 };
    const QList<Value> params =
        FairinoCommand::moveLParams(joint, cart, 3, 4, 25.0);

    QCOMPARE(params.size(), 1);
    QVERIFY(params.first().kind == Value::Kind::Array);
    const QList<Value>& args = params.first().arrayValue;
    QCOMPARE(args.size(), 33);

    for (int i = 0; i < 6; ++i) {
        double v = 0.0;
        QVERIFY(args.at(i).asDouble(&v));
        QCOMPARE(v, joint[static_cast<std::size_t>(i)]);
        QVERIFY(args.at(6 + i).asDouble(&v));
        QCOMPARE(v, cart[static_cast<std::size_t>(i)]);
    }
    qint64 tool = 0;
    qint64 user = 0;
    QVERIFY(args.at(12).asInt(&tool));
    QVERIFY(args.at(13).asInt(&user));
    QCOMPARE(tool, qint64(3));
    QCOMPARE(user, qint64(4));

    double v = 0.0;
    QVERIFY(args.at(14).asDouble(&v));
    QCOMPARE(v, 25.0);   // vel %
    QVERIFY(args.at(15).asDouble(&v));
    QCOMPARE(v, 0.0);    // acc（SDK 暂不开放）
    QVERIFY(args.at(16).asDouble(&v));
    QCOMPARE(v, 100.0);  // ovl
    QVERIFY(args.at(17).asDouble(&v));
    QCOMPARE(v, -1.0);   // blendR = 到位停
    qint64 blendMode = 1;
    QVERIFY(args.at(18).asInt(&blendMode));
    QCOMPARE(blendMode, qint64(0));
    for (int i = 19; i <= 22; ++i) {   // exaxis 1..4
        QVERIFY(args.at(i).asDouble(&v));
        QCOMPARE(v, 0.0);
    }
    qint64 search = 1;
    QVERIFY(args.at(23).asInt(&search));
    QCOMPARE(search, qint64(0));
    qint64 offsetFlag = 1;
    QVERIFY(args.at(24).asInt(&offsetFlag));
    QCOMPARE(offsetFlag, qint64(0));
    for (int i = 25; i <= 30; ++i) {   // offset_pos
        QVERIFY(args.at(i).asDouble(&v));
        QCOMPARE(v, 0.0);
    }
    QVERIFY(args.at(31).asDouble(&v));
    QCOMPARE(v, 100.0);   // SDK 固定值
    qint64 velAccMode = 1;
    QVERIFY(args.at(32).asInt(&velAccMode));
    QCOMPARE(velAccMode, qint64(0));
}

void TestFairino::moveJArgumentLayout()
{
    const std::array<double, 6> joint{ 1, 2, 3, 4, 5, 6 };
    const std::array<double, 6> cart{ 100, 200, 300, 10, 20, 30 };
    const QList<Value> params =
        FairinoCommand::moveJParams(joint, cart, 3, 4, 25.0);

    QCOMPARE(params.size(), 11);
    QCOMPARE(params.at(0).arrayValue.size(), 6);
    QCOMPARE(params.at(1).arrayValue.size(), 6);
    for (int i = 0; i < 6; ++i) {
        double v = 0.0;
        QVERIFY(params.at(0).arrayValue.at(i).asDouble(&v));
        QCOMPARE(v, joint[static_cast<std::size_t>(i)]);
        QVERIFY(params.at(1).arrayValue.at(i).asDouble(&v));
        QCOMPARE(v, cart[static_cast<std::size_t>(i)]);
    }
    qint64 tool = 0;
    qint64 user = 0;
    QVERIFY(params.at(2).asInt(&tool));
    QVERIFY(params.at(3).asInt(&user));
    QCOMPARE(tool, qint64(3));
    QCOMPARE(user, qint64(4));

    double v = 0.0;
    QVERIFY(params.at(4).asDouble(&v));
    QCOMPARE(v, 25.0);
    QVERIFY(params.at(5).asDouble(&v));
    QCOMPARE(v, 0.0);    // acc
    QVERIFY(params.at(6).asDouble(&v));
    QCOMPARE(v, 100.0);  // ovl
    QCOMPARE(params.at(7).arrayValue.size(), 4);
    QVERIFY(params.at(8).asDouble(&v));
    QCOMPARE(v, -1.0);   // blendT = 到位停
    qint64 offsetFlag = 1;
    QVERIFY(params.at(9).asInt(&offsetFlag));
    QCOMPARE(offsetFlag, qint64(0));
    QCOMPARE(params.at(10).arrayValue.size(), 6);
    for (const Value& zero : params.at(10).arrayValue) {
        QVERIFY(zero.asDouble(&v));
        QCOMPARE(v, 0.0);
    }
}

// ── 姿态数学 ─────────────────────────────────────────────────────────

void TestFairino::eulerRoundTrip()
{
    const std::array<FairinoMath::Vec3, 5> cases{
        FairinoMath::Vec3{ 0, 0, 0 },
        FairinoMath::Vec3{ 10, 20, 30 },
        FairinoMath::Vec3{ -170, 45, 179 },
        FairinoMath::Vec3{ 120, -80, 15 },
        FairinoMath::Vec3{ 30, 89.9, -60 },
    };
    for (const FairinoMath::Vec3& rpy : cases) {
        const FairinoMath::Vec3 back =
            FairinoMath::matrixToEulerDeg(FairinoMath::eulerDegToMatrix(rpy));
        const FairinoMath::Mat3 a = FairinoMath::eulerDegToMatrix(rpy);
        const FairinoMath::Mat3 b = FairinoMath::eulerDegToMatrix(back);
        for (std::size_t i = 0; i < a.size(); ++i)
            QVERIFY2(std::abs(a[i] - b[i]) < 1e-9, "euler round trip");
    }
}

void TestFairino::eulerGimbalLock()
{
    for (double pitch : { 90.0, -90.0 }) {
        const FairinoMath::Vec3 rpy{ 35.0, pitch, -25.0 };
        const FairinoMath::Vec3 back =
            FairinoMath::matrixToEulerDeg(FairinoMath::eulerDegToMatrix(rpy));
        for (double value : back)
            QVERIFY(std::isfinite(value));
        QVERIFY2(std::abs(FairinoMath::rotationDistanceDeg(rpy, back)) < 1e-6,
                 "gimbal lock decomposition must be equivalent");
        QVERIFY(std::abs(back[1] - pitch) < 1e-6);
    }
}

void TestFairino::rotateAboutBaseAxis()
{
    // 绕基座 Z 转 90°：单位姿态 → (0,0,90)。
    const FairinoMath::Vec3 z = FairinoMath::rotateEulerAboutBaseAxisDeg(
        FairinoMath::Vec3{ 0, 0, 0 }, 2, 90.0);
    QVERIFY(std::abs(FairinoMath::rotationDistanceDeg(
                         z, FairinoMath::Vec3{ 0, 0, 90 })) < 1e-9);

    // 已有 Rz(90) 的姿态再绕基座 X 转 90°：必须左乘 Rx，不能给 rx 直接加 90。
    const FairinoMath::Vec3 composed = FairinoMath::rotateEulerAboutBaseAxisDeg(
        FairinoMath::Vec3{ 0, 0, 90 }, 0, 90.0);
    const FairinoMath::Mat3 expected = FairinoMath::multiply(
        FairinoMath::eulerDegToMatrix(FairinoMath::Vec3{ 90, 0, 0 }),
        FairinoMath::eulerDegToMatrix(FairinoMath::Vec3{ 0, 0, 90 }));
    const FairinoMath::Mat3 actual = FairinoMath::eulerDegToMatrix(composed);
    for (std::size_t i = 0; i < expected.size(); ++i)
        QVERIFY(std::abs(expected[i] - actual[i]) < 1e-9);
}

void TestFairino::rotationDistanceIsShortestPath()
{
    QVERIFY(std::abs(FairinoMath::rotationDistanceDeg(
                         { 179, 0, 0 }, { -179, 0, 0 }) - 2.0) < 1e-6);
    QVERIFY(std::abs(FairinoMath::rotationDistanceDeg(
                         { 0, 0, 0 }, { 0, 0, 90 }) - 90.0) < 1e-6);
    QVERIFY(std::abs(FairinoMath::rotationDistanceDeg(
                         { 10, 20, 30 }, { 10, 20, 30 })) < 1e-9);
}

void TestFairino::reachedCartesianUsesPositionAndAngle()
{
    const FairinoMath::Pose6 origin{ 0, 0, 0, 0, 0, 0 };
    QVERIFY(FairinoMath::reachedCartesian(origin, { 1, 0, 0, 0, 0, 0 },
                                          2.0, 1.0));
    QVERIFY(!FairinoMath::reachedCartesian(origin, { 10, 0, 0, 0, 0, 0 },
                                           2.0, 1.0));
    QVERIFY(!FairinoMath::reachedCartesian(origin, { 0, 0, 0, 0, 0, 180 },
                                           2.0, 1.0));
    QVERIFY(FairinoMath::reachedCartesian(origin, { 0, 0, 0, 0, 0, 180 },
                                          2.0, 181.0));
    QVERIFY(FairinoMath::reachedJoint({ 1, 2, 3, 4, 5, 6 },
                                      { 1, 2, 3, 4, 5, 6.5 }, 0.6));
    QVERIFY(!FairinoMath::reachedJoint({ 1, 2, 3, 4, 5, 6 },
                                       { 1, 2, 3, 4, 5, 6.5 }, 0.4));
}

// ── 位姿 Reader（真实 TCP 流）────────────────────────────────────────

void TestFairino::poseReaderStreamsNewestFrame()
{
    MockFairinoStream server;
    QVERIFY(server.start(2));

    FairinoPoseReader reader;
    reader.setTimeoutMs(1500);
    QVERIFY2(reader.connect(QStringLiteral("127.0.0.1"), server.port()),
             qPrintable(reader.lastError()));

    RobotPose::Pose first{};
    QCOMPARE(reader.readPose(first), RobotPose::Status::Ok);
    QTest::qWait(60);
    RobotPose::Pose later{};
    QCOMPARE(reader.readPose(later), RobotPose::Status::Ok);

    // 控制器一直在推；如果只消费"连接后的第一帧"，两次读数会一模一样。
    QVERIFY2(later.xyz[0] > first.xyz[0],
             qPrintable(QStringLiteral("first=%1 later=%2")
                            .arg(first.xyz[0]).arg(later.xyz[0])));
    QVERIFY(reader.framesConsumed() > 1);
    QCOMPARE(reader.badChecksums(), quint64(0));
}

void TestFairino::poseReaderRejectsZeroPose()
{
    MockFairinoStream server;
    QVERIFY(server.start(2, -1, true));

    FairinoPoseReader reader;
    reader.setTimeoutMs(1500);
    QVERIFY2(reader.connect(QStringLiteral("127.0.0.1"), server.port()),
             qPrintable(reader.lastError()));
    RobotPose::Pose pose{};
    QCOMPARE(reader.readPose(pose), RobotPose::Status::ProtocolError);
    QVERIFY(!reader.lastError().isEmpty());
}

void TestFairino::poseReaderTimesOutWhenStreamStalls()
{
    MockFairinoStream server;
    QVERIFY(server.start(2, 3));

    FairinoPoseReader reader;
    reader.setTimeoutMs(1500);
    QVERIFY2(reader.connect(QStringLiteral("127.0.0.1"), server.port()),
             qPrintable(reader.lastError()));

    RobotPose::Pose pose{};
    QVERIFY(reader.readPose(pose) == RobotPose::Status::Ok);
    reader.setTimeoutMs(300);
    QTest::qWait(1200);   // 帧龄超过 1000 ms，连接却还开着
    QCOMPARE(reader.readPose(pose), RobotPose::Status::Timeout);
    QVERIFY(reader.lastError().contains(QStringLiteral("20004"))
            || reader.lastError().contains(QStringLiteral("超时"))
            || reader.lastError().contains(QStringLiteral("没有")));
}

// ── 20003 客户端（真实 HTTP 往返）────────────────────────────────────

void TestFairino::rpcClientRoundTrip()
{
    MockXmlRpcServer server;
    QVERIFY(server.start(httpResponse(arrayResponse(intValue(0) + intValue(42)))));

    FairinoXmlRpcClient client;
    client.setEndpoint(QStringLiteral("127.0.0.1"), server.port());
    client.setTimeoutMs(2000);
    QList<Value> values;
    QString error;
    QVERIFY2(client.callOk(QStringLiteral("Mode"),
                           { Value::fromInt(1) }, values, &error),
             qPrintable(error));
    QCOMPARE(values.size(), 2);
    int code = -1;
    QVERIFY(FairinoXmlRpc::firstErrorCode(values, &code, &error));
    QCOMPARE(code, 0);

    const QByteArray request = server.request();
    QVERIFY(request.startsWith("POST /RPC2 HTTP/1.1\r\n"));
    QVERIFY(request.contains("<methodName>Mode</methodName>"));
    QVERIFY(request.contains("<int>1</int>"));
    QVERIFY(request.contains("User-Agent: HandEyeCalibrationTool-FAIRINO\r\n"));
}

void TestFairino::rpcClientReportsErrorCode()
{
    MockXmlRpcServer server;
    QVERIFY(server.start(httpResponse(arrayResponse(intValue(-1) + intValue(0)))));

    FairinoXmlRpcClient client;
    client.setEndpoint(QStringLiteral("127.0.0.1"), server.port());
    client.setTimeoutMs(2000);
    QList<Value> values;
    QString error;
    QVERIFY(!client.callOk(QStringLiteral("MoveL"),
                           { Value::fromInt(0) }, values, &error));
    QVERIFY2(error.contains(QStringLiteral("法奥错误码 -1")), qPrintable(error));
}

void TestFairino::rpcClientReportsFault()
{
    const QByteArray faultXml =
        "<methodResponse><fault><value><struct>"
        "<member><name>faultCode</name><value><int>3</int></value></member>"
        "<member><name>faultString</name><value><string>boom</string></value>"
        "</member></struct></value></fault></methodResponse>";
    MockXmlRpcServer server;
    QVERIFY(server.start(httpResponse(faultXml)));

    FairinoXmlRpcClient client;
    client.setEndpoint(QStringLiteral("127.0.0.1"), server.port());
    client.setTimeoutMs(2000);
    QList<Value> values;
    QString error;
    QVERIFY(!client.call(QStringLiteral("GetControllerIP"),
                         QList<Value>(), values, &error));
    QVERIFY2(error.contains(QStringLiteral("boom")), qPrintable(error));
    QVERIFY2(error.contains(QStringLiteral("fault")), qPrintable(error));
}
