#include "test_robot_pose.h"

#include <QtTest>
#include <QDataStream>
#include <QThread>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <thread>
#include <winsock2.h>

#include "logic/RobotPose.h"
#include "logic/RobotPoseSource.h"
#include "logic/URRealtimeReader.h"

using namespace RobotPose;

namespace {

// Minimal Modbus TCP server on a worker thread (raw Winsock, blocking IO):
// answers read-holding-registers (0x03) requests with 6 registers in the
// requested format.  A separate thread is required because the Qt client
// waits synchronously and cannot pump the server's event loop itself.
class MockModbusServer {
public:
    MockModbusServer() = default;
    ~MockModbusServer() { stop(); }

    // What the register block holds.  AllZero / NotANumber are the two shapes
    // that look like a reply but are not a pose (see RobotPose.h
    // checkPoseSanity); the reader must refuse them instead of returning them.
    enum class ReplyMode { Normal, AllZero, NotANumber };

    bool start(RegisterFormat fmt)
    {
        return startCommon(fmt, false, ReplyMode::Normal);
    }

    bool startZeroPose()
    {
        return startCommon(RegisterFormat::Float32, false, ReplyMode::AllZero);
    }

    bool startNotANumber()
    {
        return startCommon(RegisterFormat::Float32, false, ReplyMode::NotANumber);
    }

    // Accept connections but never reply -> the client must time out.
    bool startSilent()
    {
        return startCommon(RegisterFormat::Float32, true, ReplyMode::Normal);
    }

    quint16 port() const { return m_port; }

    void stop()
    {
        if (m_listen != INVALID_SOCKET) {
            closesocket(m_listen);
            m_listen = INVALID_SOCKET;
        }
        if (m_thread.joinable())
            m_thread.join();
        WSACleanup();
    }

private:
    bool startCommon(RegisterFormat fmt, bool silent,
                     ReplyMode mode = ReplyMode::Normal)
    {
        m_format = fmt;
        m_silent = silent;
        m_mode = mode;
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
            return false;
        m_listen = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (m_listen == INVALID_SOCKET)
            return false;
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        addr.sin_port = 0;
        if (bind(m_listen, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == SOCKET_ERROR)
            return false;
        if (listen(m_listen, 4) == SOCKET_ERROR)
            return false;
        sockaddr_in bound{};
        int len = sizeof(bound);
        if (getsockname(m_listen, reinterpret_cast<sockaddr*>(&bound), &len) == SOCKET_ERROR)
            return false;
        m_port = ntohs(bound.sin_port);
        m_thread = std::thread([this]() { serve(); });
        return true;
    }

    void serve()
    {
        while (m_listen != INVALID_SOCKET) {
            SOCKET c = accept(m_listen, nullptr, nullptr);
            if (c == INVALID_SOCKET)
                break;
            if (m_silent) {
                // Keep the connection open without replying; poll with a
                // timeout so stop() can join the thread promptly.
                char buf[64];
                while (m_listen != INVALID_SOCKET) {
                    fd_set rfds;
                    FD_ZERO(&rfds);
                    FD_SET(c, &rfds);
                    timeval tv{ 0, 200000 };
                    const int r = select(0, &rfds, nullptr, nullptr, &tv);
                    if (r < 0)
                        break;
                    if (r > 0 && recv(c, buf, sizeof(buf), 0) <= 0)
                        break;
                }
                closesocket(c);
                continue;
            }
            onRequest(c);
        }
    }

    static bool recvAll(SOCKET c, char* buf, int len)
    {
        int got = 0;
        while (got < len) {
            const int n = recv(c, buf + got, len - got, 0);
            if (n <= 0)
                return false;
            got += n;
        }
        return true;
    }

    void onRequest(SOCKET c)
    {
        char req[12];
        if (!recvAll(c, req, 12)) {
            closesocket(c);
            return;
        }
        const quint16 qty = static_cast<quint16>(
            (static_cast<unsigned char>(req[10]) << 8)
            | static_cast<unsigned char>(req[11]));
        QByteArray payload;
        if (m_format == RegisterFormat::Int32Scaled) {
            const qint32 vals[6] = { 100000, 200000, 300000, 10000, 20000, 30000 };
            for (int i = 0; i < 6 && i < qty; ++i) {
                const quint32 raw = static_cast<quint32>(vals[i]);
                payload.push_back(static_cast<char>((raw >> 24) & 0xFF));
                payload.push_back(static_cast<char>((raw >> 16) & 0xFF));
                payload.push_back(static_cast<char>((raw >> 8) & 0xFF));
                payload.push_back(static_cast<char>(raw & 0xFF));
            }
        } else if (m_format == RegisterFormat::Int16Scaled) {
            const qint16 vals[6] = { 1000, 2000, 3000, 100, 200, 300 };
            for (int i = 0; i < 6 && i < qty; ++i) {
                payload.push_back(static_cast<char>((vals[i] >> 8) & 0xFF));
                payload.push_back(static_cast<char>(vals[i] & 0xFF));
            }
        } else {
            const float normal[6] = { 100.0f, 200.0f, 300.0f, 10.0f, 20.0f, 30.0f };
            const float zeros[6]  = { 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f };
            const float notANumber[6] = { std::numeric_limits<float>::quiet_NaN(),
                                          200.0f, 300.0f, 10.0f, 20.0f, 30.0f };
            const float* vals = m_mode == ReplyMode::AllZero ? zeros
                              : m_mode == ReplyMode::NotANumber ? notANumber
                              : normal;
            for (int i = 0; i < 6 && i < qty; ++i) {
                quint32 raw = 0;
                std::memcpy(&raw, &vals[i], sizeof(raw));
                payload.push_back(static_cast<char>((raw >> 24) & 0xFF));
                payload.push_back(static_cast<char>((raw >> 16) & 0xFF));
                payload.push_back(static_cast<char>((raw >> 8) & 0xFF));
                payload.push_back(static_cast<char>(raw & 0xFF));
            }
        }
        QByteArray resp;
        resp.append(req, 4);                 // transaction + protocol
        resp.push_back('\0');
        resp.push_back(static_cast<char>(3 + static_cast<int>(payload.size())));
        resp.push_back(req[6]);              // unit id
        resp.push_back(static_cast<char>(0x03));
        resp.push_back(static_cast<char>(payload.size()));
        resp.append(payload);
        ::send(c, resp.constData(), static_cast<int>(resp.size()), 0);
        closesocket(c);
    }

    SOCKET m_listen = INVALID_SOCKET;
    quint16 m_port = 0;
    RegisterFormat m_format = RegisterFormat::Float32;
    ReplyMode m_mode = ReplyMode::Normal;
    bool m_silent = false;
    std::thread m_thread;
};

// Minimal UR "Primary"/Realtime interface mock. Speaks the real protocol's
// shape: a length-prefixed packet whose actual_tcp_pose block (6 big-endian
// doubles, at the fixed offset used by URRealtimeReader) carries the pose in
// meters/radians.
//
// Two modes:
//   * start()            -> one packet, then close.
//   * startStreaming(ms) -> keep pushing a packet with an incrementing x every
//                           `ms` and never close, which is what the controller
//                           actually does.
//
// The streaming mode is the point: the controller pushes whether or not the
// client asks, so a reader that consumes exactly one packet per readPose()
// call answers with the *oldest* queued packet -- a pose frozen at connect
// time -- and leaves the rest queued in memory. The single-shot mock could
// never show that (stage-10 field report, 2026-10-10).
class MockURServer {
public:
    ~MockURServer() { stop(); }

    bool start() { return startCommon(0, -1); }

    // One packet whose pose field is six exact zeros: the wrong-offset bug's
    // signature. The reader must call that an error, not a pose.
    bool startZeroPose() { m_zeroPose = true; return startCommon(0, -1); }

    // Send one exact packet, byte for byte, then close. Used for packets
    // captured from a real controller, where the bytes -- not this file's idea
    // of the layout -- are the specification.
    bool startSendingPacket(const QByteArray& packet)
    {
        m_rawPacket = packet;
        return startCommon(0, -1);
    }

    // intervalMs <= 0 means "one packet and close".
    bool startStreaming(int intervalMs = 2) { return startCommon(intervalMs, -1); }

    // Push `packets` packets, then hold the connection open without sending
    // anything else: the controller is gone but TCP has not noticed yet.
    bool startStreamingThenSilence(int intervalMs, int packets)
    {
        return startCommon(intervalMs, packets);
    }

    // Packets handed to the socket so far (streaming mode: the next x is
    // 0.1 m * sentCount()).
    int sentCount() const { return m_sent.load(); }

private:
    bool startCommon(int intervalMs, int maxPackets)
    {
        m_intervalMs = intervalMs;
        m_maxPackets = maxPackets;
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
        if (bind(m_listen, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == SOCKET_ERROR)
            return false;
        if (listen(m_listen, 4) == SOCKET_ERROR)
            return false;
        sockaddr_in bound{};
        int len = sizeof(bound);
        if (getsockname(m_listen, reinterpret_cast<sockaddr*>(&bound), &len) == SOCKET_ERROR)
            return false;
        m_port = ntohs(bound.sin_port);
        m_thread = std::thread([this]() { serve(); });
        return true;
    }

public:
    quint16 port() const { return m_port; }

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
    static void pushBE(QByteArray& out, double v)
    {
        quint64 raw = 0;
        std::memcpy(&raw, &v, sizeof(raw));
        for (int shift = 56; shift >= 0; shift -= 8)
            out.push_back(static_cast<char>((raw >> shift) & 0xFF));
    }

    // One length-prefixed packet with the given actual_tcp_pose (meters) and
    // the body layout URRealtimeReader reads.
    static QByteArray buildPacket(double x, double y, double z, double rx)
    {
        // Body layout must match URRealtimeReader::kPoseOffset (8 + 48*9 =
        // 440), UR's classic realtime field order:
        //   timestamp, q_target, qd_target, qdd_target, I_target, M_target,
        //   q_actual, qd_actual, I_actual, M_actual, actual_TCP_pose, ...
        //
        // Every field EXCEPT the pose carries a distinctive value (0.50 .. on
        // through 4.5x) instead of zeros, on purpose. Both wrong offsets of
        // 2026-10-10 (200, then 152) sat one and three fields short of the
        // pose, and the mock of that day could not tell them apart: it built
        // its packet from the same wrong constant, and it zero-filled the
        // neighbours, so a misaligned read returned six zeros and the test
        // agreed. The sentinels are all >= 0.5 m, so a misread is at least
        // 500 mm and can never be confused with the expected 100/200/300 mm.
        // qd_target/qdd_target/actual_TCP_speed stay zero because that is what
        // a real controller reports for them at a standstill (measured).
        QByteArray body;
        pushBE(body, 12345.6789);                        // timestamp
        for (int field = 0; field < 9; ++field) {        // q_target .. M_actual
            for (int j = 0; j < 6; ++j)
                pushBE(body, 0.5 * (field + 1) + 0.01 * j);
        }
        // actual_TCP_pose: x,y,z in meters + rx,ry,rz axis-angle radians
        pushBE(body, x);
        pushBE(body, y);
        pushBE(body, z);
        pushBE(body, rx);
        pushBE(body, 0.0);
        pushBE(body, 0.0);
        // actual_TCP_speed (488): zero at rest, as measured on a controller.
        for (int i = 0; i < 6; ++i) pushBE(body, 0.0);
        // actual_TCP_force (536): sentinel.
        for (int i = 0; i < 6; ++i) pushBE(body, 1.21 + 0.01 * i);
        // target_TCP_pose (584): the same pose 1 mm further along, like a
        // controller chasing its target. A reader one field further than 440
        // must not answer with this and call it the pose.
        pushBE(body, x + 0.001);
        pushBE(body, y);
        pushBE(body, z);
        pushBE(body, rx);
        pushBE(body, 0.0);
        pushBE(body, 0.0);

        QByteArray packet;
        const quint32 msgLen = static_cast<quint32>(body.size() + 4);
        for (int shift = 24; shift >= 0; shift -= 8)
            packet.push_back(static_cast<char>((msgLen >> shift) & 0xFF));
        packet.append(body);
        return packet;
    }

    void serve()
    {
        SOCKET c = accept(m_listen, nullptr, nullptr);
        if (c == INVALID_SOCKET)
            return;

        // Never block the (single-threaded) mock forever on a send: if the
        // client stops reading we must still be able to shut down.
        DWORD sndTimeout = 500;
        setsockopt(c, SOL_SOCKET, SO_SNDTIMEO,
                   reinterpret_cast<const char*>(&sndTimeout), sizeof(sndTimeout));

        if (m_intervalMs <= 0) {
            const QByteArray packet = !m_rawPacket.isEmpty()
                ? m_rawPacket
                : (m_zeroPose
                       ? buildPacket(0.0, 0.0, 0.0, 0.0)
                       : buildPacket(0.1, 0.2, 0.3, 1.5707963267948966)); // pi/2
            const int sent =
                ::send(c, packet.constData(), static_cast<int>(packet.size()), 0);
            if (sent > 0)
                m_sent.store(1);
            closesocket(c);
            return;
        }

        // Streaming mode: the controller keeps pushing whether or not anyone
        // reads, and never closes on its own.
        int i = 0;
        while (m_running.load()) {
            if (m_maxPackets >= 0 && i >= m_maxPackets) {
                // Hold the connection open but stop pushing (startStreaming-
                // ThenSilence): the controller is gone, TCP has not noticed.
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
                continue;
            }
            const QByteArray packet =
                buildPacket(0.1 * (i + 1), 0.2, 0.3, 1.5707963267948966);
            if (::send(c, packet.constData(), static_cast<int>(packet.size()), 0)
                == SOCKET_ERROR)
                break;
            m_sent.store(++i);
            std::this_thread::sleep_for(
                std::chrono::milliseconds(m_intervalMs));
        }
        closesocket(c);
    }

    SOCKET m_listen = INVALID_SOCKET;
    quint16 m_port = 0;
    int m_intervalMs = 0;
    int m_maxPackets = -1;
    bool m_zeroPose = false;
    QByteArray m_rawPacket;
    bool m_wsaUp = false;
    std::atomic<bool> m_running{false};
    std::atomic<int> m_sent{0};
    std::thread m_thread;
};

} // namespace

void TestRobotPose::modbusFloat32()
{
    MockModbusServer server;
    QVERIFY(server.start(RegisterFormat::Float32));
    ModbusTcpReader reader;
    ModbusConfig cfg;
    cfg.format = RegisterFormat::Float32;
    cfg.timeoutMs = 2000;
    reader.setConfig(cfg);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Ok);
    QCOMPARE(pose.xyz[0], 100.0);
    QCOMPARE(pose.xyz[1], 200.0);
    QCOMPARE(pose.xyz[2], 300.0);
    QCOMPARE(pose.rpy[0], 10.0);
    QCOMPARE(pose.rpy[2], 30.0);
    server.stop();
}

void TestRobotPose::modbusInt32Scaled()
{
    MockModbusServer server;
    QVERIFY(server.start(RegisterFormat::Int32Scaled));
    ModbusTcpReader reader;
    ModbusConfig cfg;
    cfg.format = RegisterFormat::Int32Scaled;
    cfg.scale = 0.001;      // device stores mm*1000
    cfg.timeoutMs = 2000;
    reader.setConfig(cfg);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Ok);
    QCOMPARE(pose.xyz[0], 100.0);   // 100000 * 0.001
    QCOMPARE(pose.rpy[1], 20.0);
    server.stop();
}

void TestRobotPose::modbusInt16Scaled()
{
    MockModbusServer server;
    QVERIFY(server.start(RegisterFormat::Int16Scaled));
    ModbusTcpReader reader;
    ModbusConfig cfg;
    cfg.format = RegisterFormat::Int16Scaled;
    cfg.scale = 0.1;
    cfg.timeoutMs = 2000;
    reader.setConfig(cfg);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Ok);
    QCOMPARE(pose.xyz[0], 100.0);
    QCOMPARE(pose.xyz[2], 300.0);
    server.stop();
}

// 全 0 的寄存器块不是位姿：以前这里返回 Ok，把 (0,0,0,0,0,0) 静默写进卡片，
// 标定结果会整体偏掉 —— 与 UR 侧那条"读取成功但结果是错的"是同一类问题。
void TestRobotPose::modbusAllZeroPoseIsAnError()
{
    MockModbusServer server;
    QVERIFY(server.startZeroPose());
    ModbusTcpReader reader;
    ModbusConfig cfg;
    cfg.startAddress = 100;
    cfg.timeoutMs = 2000;
    reader.setConfig(cfg);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::ProtocolError);
    QVERIFY2(reader.lastError().contains(QStringLiteral("全为 0")),
             qPrintable(reader.lastError()));
    // 报错时不能写出半个位姿（Pose 依旧是调用方给的全 0 初值）。
    QCOMPARE(pose.xyz[0], 0.0);
    server.stop();
}

// NaN 同理：解析"成功"（IEEE 位模式完整）但不是数。
void TestRobotPose::modbusNotANumberIsAnError()
{
    MockModbusServer server;
    QVERIFY(server.startNotANumber());
    ModbusTcpReader reader;
    ModbusConfig cfg;
    cfg.timeoutMs = 2000;
    reader.setConfig(cfg);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::ProtocolError);
    QVERIFY2(reader.lastError().contains(QStringLiteral("非有限值")),
             qPrintable(reader.lastError()));
    server.stop();
}

// 判据本身（三个 reader 共用一处，见 RobotPose.h checkPoseSanity）。
void TestRobotPose::poseSanityPredicate()
{
    using RobotPose::PoseSanity;
    const std::array<double, 6> ok { 1.0, 0.0, 0.0, 0.0, 0.0, 0.0 };
    QCOMPARE(RobotPose::checkPoseSanity(ok), PoseSanity::Ok);
    const std::array<double, 6> zero { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };
    QCOMPARE(RobotPose::checkPoseSanity(zero), PoseSanity::AllZero);
    const std::array<double, 6> nan {
        std::numeric_limits<double>::quiet_NaN(), 1.0, 2.0, 3.0, 4.0, 5.0 };
    QCOMPARE(RobotPose::checkPoseSanity(nan), PoseSanity::NotFinite);
    const std::array<double, 6> inf {
        1.0, 2.0, 3.0, std::numeric_limits<double>::infinity(), 0.0, 0.0 };
    QCOMPARE(RobotPose::checkPoseSanity(inf), PoseSanity::NotFinite);
    QVERIFY(RobotPose::poseSanityText(PoseSanity::AllZero).contains(QStringLiteral("全为 0")));
    QVERIFY(RobotPose::poseSanityText(PoseSanity::NotFinite).contains(QStringLiteral("非有限值")));
    QVERIFY(RobotPose::poseSanityText(PoseSanity::Ok).isEmpty());
}

void TestRobotPose::modbusTimeout()
{
    MockModbusServer server;
    QVERIFY(server.startSilent());
    ModbusTcpReader reader;
    ModbusConfig cfg;
    cfg.timeoutMs = 200;
    reader.setConfig(cfg);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Timeout);
    server.stop();
}

void TestRobotPose::notConnected()
{
    ModbusTcpReader reader;
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::NotConnected);
    QVERIFY(!reader.isConnected());
}

void TestRobotPose::statusTextMapped()
{
    QVERIFY(statusText(Status::Ok).contains(QStringLiteral("成功")));
    QVERIFY(statusText(Status::Timeout).contains(QStringLiteral("超时")));
    QVERIFY(statusText(Status::NotConnected).contains(QStringLiteral("未连接")));
}

void TestRobotPose::urRealtimePose()
{
    MockURServer server;
    QVERIFY(server.start());
    URRealtimeReader reader;
    reader.setTimeoutMs(2000);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Ok);
    // meters -> millimeters
    QCOMPARE(pose.xyz[0], 100.0);
    QCOMPARE(pose.xyz[1], 200.0);
    QCOMPARE(pose.xyz[2], 300.0);
    // axis-angle radians, passed through unchanged (NOT converted to degrees)
    QVERIFY(qAbs(pose.rpy[0] - 1.5707963267948966) < 1e-9);
    QCOMPARE(pose.rpy[1], 0.0);
    QCOMPARE(pose.rpy[2], 0.0);
    reader.disconnect();
    server.stop();
}

// A real 30003 packet, captured byte for byte from a live UR controller on
// 2026-10-10 with the arm standing still and the pendant, feature set to base,
// showing x=-208.71 mm y=-232.90 mm z=880.18 mm, rx=0.799 ry=1.697 rz=-1.697
// rad.
//
// This is the fixture the two earlier attempts were missing. The mock packet
// was built from the same offset constant as the reader, so it could only ever
// confirm the mistake; real controller bytes cannot agree with a mistake. Body
// 440 carries exactly the pendant's pose, while the blocks the earlier
// constants pointed at -- 152 (I_target) and 200 (M_target) -- carry values no
// pose can have, and 488 (actual_TCP_speed) is exactly zero because the arm is
// standing still.
static const char kCapturedUrRealtimePacket[] =
    "AAAExECZHj987ZFovdt7AAAAAAC/5MiV43478L/0+Vyz6IJwv++ZIafyizA98mVMJYbPbj/l8jPjqrz/AAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPIrph3n3NPvACKN3+l9Y/T/uE/tYIShgv7ihbLP3MQQ/sJcGF6oorwAA"
    "AAAAAAAAPMC0CfEAAADAPpWOmkifq0Aiqw1ruAnVv+ftrjx8lO8/4B31AvYXOgAAAAAAAAAAvdt7AAAAAAC/5MiV"
    "43478L/0+Vyz6IJwv++ZIafyizA98mVMJYbPbj/l8jPjqrz/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAPIrph3n3NPvACKN3+l9Y/T/uE/tYIShgv7ihbLP3MQQ/sJcGF6oorwAAAAAAAAAA"
    "PIrph3n3NPvACKN3+l9Y/T/uE/tYIShgv7ihbLP3MQQ/sJcGF6oorwAAAAAAAAAAv8q3JSlIING/zc+qzdi5qD/s"
    "Kmo319NnP+mPLLAmawY/+yjitycj5L/7KOK3DEwpAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAv8q3JSlI"
    "ING/zc+qzdi5qD/sKmo319NnP+mPLLAmawY/+yjitycj5L/7KOK3DEwpAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAOYAAAAAAAEA5AAAAAAAAQDiAAAAAAABAOAAAAAAAAEA3"
    "gAAAAAAAQDcAAAAAAAA/vQkX1rZam0AAAAAAAAAAQBwAAAAAAABAb6AAAAAAAEBvoAAAAAAAQG+gAAAAAABAb6AA"
    "AAAAAEBvoAAAAAAAQG+gAAAAAAA/8AAAAAAAAEAPfhA4utR+QBVmD3rdeZxAGBiXviMhdT/5qAenrx13P/mhcS4Q"
    "QWA/9JY8EG/BXcAeQ76H5ARWwBkKFSY9w2W+GefCmb8jbAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQEgAAAAAAABASAAAAAAAAD/u"
    "2bBbBbBbAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/8AAA"
    "AAAAAL/VqXU77KwQv7fO2Rab7To/2tmU402iAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/wAAAAAAAAQEiAAAAA"
    "AABAQYAAAAAAAAAAAAAAAAAAQADMzMzMzM0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/dbaAWi1zAD91toBaLXMA"
    "P3W2gFotcwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";

// The parser against real controller bytes: this is the regression that pins
// kPoseOffset to a machine instead of to a document.
void TestRobotPose::urRealtimeReadsCapturedPacket()
{
    const QByteArray packet =
        QByteArray::fromBase64(QByteArray(kCapturedUrRealtimePacket));
    QCOMPARE(packet.size(), 1220);

    MockURServer server;
    QVERIFY(server.startSendingPacket(packet));
    URRealtimeReader reader;
    reader.setTimeoutMs(2000);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));

    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Ok);
    // The pendant's numbers: meters -> millimeters.
    QVERIFY(qAbs(pose.xyz[0] - (-208.71414676390157)) < 1e-6);
    QVERIFY(qAbs(pose.xyz[1] - (-232.90000010588341)) < 1e-6);
    QVERIFY(qAbs(pose.xyz[2] - 880.177601879592) < 1e-6);
    // And the rotation vector in radians, passed through unchanged.
    QVERIFY(qAbs(pose.rpy[0] - 0.79872736362753538) < 1e-9);
    QVERIFY(qAbs(pose.rpy[1] - 1.6974818376931973) < 1e-9);
    QVERIFY(qAbs(pose.rpy[2] - (-1.6974818373025846)) < 1e-9);

    reader.disconnect();
    server.stop();
}

// The controller pushes a packet every control cycle whether or not the client
// asks. A reader that consumes exactly one packet per readPose() call answers
// with the pose from right after connect and leaves the rest queued -- the
// "the value only changes after reconnecting" field report (2026-10-10).
void TestRobotPose::urRealtimeStreamsNewestPose()
{
    MockURServer server;
    QVERIFY(server.startStreaming(2));   // 0.1 m, 0.2 m, 0.3 m, ... every 2 ms
    URRealtimeReader reader;
    reader.setTimeoutMs(2000);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));

    Pose first;
    QCOMPARE(reader.readPose(first), Status::Ok);
    QVERIFY(first.xyz[0] >= 100.0);      // a real pose (packet 1 is 0.1 m)

    // The robot keeps moving while the user does not touch the tool.
    QTRY_VERIFY(server.sentCount() >= 12);

    Pose second;
    QCOMPARE(reader.readPose(second), Status::Ok);
    QVERIFY(second.xyz[0] > first.xyz[0]);   // it must follow the robot, not stick
    QVERIFY2(second.xyz[0] >= 1100.0,
             qPrintable(QStringLiteral(
                 "readPose returned x=%1 mm (%2 packets behind) -- the realtime "
                 "backlog was left queued instead of reporting the newest pose")
                 .arg(second.xyz[0])
                 .arg(server.sentCount() - second.xyz[0] / 100.0)));

    // Reading twice in a row must both answer with the current pose.
    Pose third;
    QCOMPARE(reader.readPose(third), Status::Ok);
    QVERIFY(third.xyz[0] >= second.xyz[0]);

    // Consuming the stream must not depend on someone asking for a pose: while
    // the tool sits idle it is the socket buffer that would otherwise grow
    // (~9 MB/min at 125 Hz -- the field report's "memory keeps climbing").
    const quint64 idleStart = reader.packetsConsumed();
    QTest::qWait(100);
    QVERIFY2(reader.packetsConsumed() > idleStart + 5,
             qPrintable(QStringLiteral(
                 "consumed %1 -> %2 packets during 100 ms of streaming: the "
                 "realtime port is not drained while the tool is idle")
                 .arg(idleStart).arg(reader.packetsConsumed())));

    reader.disconnect();
    server.stop();
}

// The offset bug's signature: a packet that parses cleanly but whose pose field
// is six exact zeros. That is not a pose (a UR TCP cannot sit at the base
// origin) -- and reporting it as one is exactly how the wrong offset stayed
// invisible: it went into the cards as a "successful" read of (0,0,0,0,0,0)
// while the pendant disagreed (2026-10-10).
void TestRobotPose::urRealtimeZeroPoseIsAnError()
{
    MockURServer server;
    QVERIFY(server.startZeroPose());
    URRealtimeReader reader;
    reader.setTimeoutMs(500);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));

    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::ProtocolError);
    QVERIFY2(reader.lastError().contains(QStringLiteral("全为 0")),
             qPrintable(reader.lastError()));

    reader.disconnect();
    server.stop();
}

// A stream that stops (controller lost, TCP not yet aware) must not be answered
// with the last pose as if it were current -- on a calibration tool a silently
// stale pose is worse than an error, it gets recorded into the cards.
void TestRobotPose::urRealtimeStaleStreamTimesOut()
{
    MockURServer server;
    QVERIFY(server.startStreamingThenSilence(2, 3));   // 3 packets, then quiet
    URRealtimeReader reader;
    reader.setTimeoutMs(300);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));

    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Ok);       // the live stream answers

    QTest::qWait(600);                                  // ... then it goes quiet
    QCOMPARE(reader.readPose(pose), Status::Timeout);

    reader.disconnect();
    server.stop();
}

// The console keeps the UR pose in axis-angle DEGREES (convenient for the jog
// pads), but the calibration card and every record written from it use
// axis-angle RADIANS (the communication tool's historical convention, and what
// HandEyeSDK expects before the user picks a unit).  These are the exact
// helpers UrMotionBackend::cardPose() uses -- a regression here silently
// multiplies a calibration pose by 57.3.
void TestRobotPose::cardPoseFromState()
{
    const std::array<double, 6> cart{400.5, -120.25, 310.75, 30.0, -45.5, 90.0};

    const RobotPose::Pose pose = RobotPose::fromStateCart(cart);
    QCOMPARE(pose.xyz[0], cart[0]);
    QCOMPARE(pose.xyz[1], cart[1]);
    QCOMPARE(pose.xyz[2], cart[2]);
    QCOMPARE(pose.rpy[0], cart[3]);
    QCOMPARE(pose.rpy[1], cart[4]);
    QCOMPARE(pose.rpy[2], cart[5]);

    const RobotPose::Pose rad = RobotPose::axisAngleDegToRad(pose);
    // Translation must not be scaled; only the axis-angle part converts.
    QCOMPARE(rad.xyz[0], cart[0]);
    QCOMPARE(rad.xyz[2], cart[2]);
    QVERIFY(std::abs(rad.rpy[2] - 3.14159265358979323846 / 2.0) < 1e-12);
    QVERIFY(std::abs(rad.rpy[1] + 45.5 * 3.14159265358979323846 / 180.0) < 1e-12);

    // The card is a space separated field list, always 6 entries, 3 decimals.
    const QStringList fields = RobotPose::formatFields(rad);
    QCOMPARE(fields.size(), 6);
    QCOMPARE(fields[0], QStringLiteral("400.500"));
    QCOMPARE(fields[2], QStringLiteral("310.750"));
    QCOMPARE(fields[5], QStringLiteral("1.571"));
    // UrMotionBackend::cardPose() is `fromStateCart` -> `axisAngleDegToRad`;
    // there is no second conversion anywhere on the write-card path.
}

// Which connection supplies the photo-node pose.  The photo node used to check
// only the communication tool, so a console-only connection failed; after the
// merge the console is the only connection, and the rule must stay fail-closed
// for simulated / stale / moving consoles.
void TestRobotPose::poseSourceChoice()
{
    using namespace RobotPoseSource;

    Inputs consoleOnly;
    consoleOnly.consoleConnected = true;
    consoleOnly.consoleSimulated = false;
    consoleOnly.consolePoseFresh = true;
    QCOMPARE(choose(consoleOnly), Source::Console);

    // Console connected but simulated: plausible numbers that must never reach
    // a calibration record.
    Inputs simulated = consoleOnly;
    simulated.consoleSimulated = true;
    QCOMPARE(choose(simulated), Source::None);

    // Stream stopped for longer than the freshness window.
    Inputs stale = consoleOnly;
    stale.consolePoseFresh = false;
    QCOMPARE(choose(stale), Source::None);

    // Motion in flight: the image would be paired with a pose the robot no
    // longer has.
    Inputs moving = consoleOnly;
    moving.consoleMoving = true;
    QCOMPARE(choose(moving), Source::None);

    // Console disconnected: no source at all.
    Inputs off = consoleOnly;
    off.consoleConnected = false;
    QCOMPARE(choose(off), Source::None);

    QCOMPARE(label(Source::Console), QStringLiteral("机器人控制"));
    QCOMPARE(label(Source::None), QStringLiteral("无"));
}
