#include "test_robot_pose.h"

#include <QtTest>
#include <QThread>
#include <cstring>
#include <thread>
#include <winsock2.h>

#include "logic/RobotPose.h"

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

    bool start(RegisterFormat fmt)
    {
        return startCommon(fmt, false);
    }

    // Accept connections but never reply -> the client must time out.
    bool startSilent()
    {
        return startCommon(RegisterFormat::Float32, true);
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
    bool startCommon(RegisterFormat fmt, bool silent)
    {
        m_format = fmt;
        m_silent = silent;
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
            const float vals[6] = { 100.0f, 200.0f, 300.0f, 10.0f, 20.0f, 30.0f };
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
    bool m_silent = false;
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
