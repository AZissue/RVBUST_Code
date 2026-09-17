#include "test_nrc_json_reader.h"

#include <QtTest>
#include <mutex>
#include <thread>
#include <vector>
#include <winsock2.h>

#include "logic/NrcJsonReader.h"

using namespace RobotPose;

namespace {

// The four frames captured from the vendor SDK (pose_probe.exe -> mock server)
// as raw hex.  These are the ground truth for the request side of the
// protocol; every assertion on outgoing bytes compares against them.
const char* const kCapturedConnect     = "4e66000c20027b22726f626f74223a317d0afac1f6a0";
const char* const kCapturedGetPosition = "4e6600162f077b22636f6f7264223a302c22726f626f74223a317d0ae33618e0";
const char* const kCapturedGetCoord    = "4e66000c22027b22726f626f74223a317d0a1baf320d";
const char* const kCapturedGetExtra    = "4e66001670127b22636f6f7264223a302c22726f626f74223a317d0ac3c95baa";

// A pose no other value in these tests shares, so a mix-up is visible.
const char* const kPoseJson =
    "{\"posValue\":[11.5,-22.25,33.75,4.5,-5.25,6.125]}";

// Minimal 博纳斯/纳博特 controller mock on a worker thread (raw Winsock,
// blocking IO).  It reads framed requests, records them verbatim and answers
// the pose command; a separate thread is required because the Qt client waits
// synchronously and cannot pump the server's event loop itself.
class MockNrcServer {
public:
    enum class Mode {
        ReplyAll,       // answers 0x2002 and 0x2F07 (realistic controller)
        ReplyPoseOnly,  // ignores the handshake, answers the pose read
        Silent,         // accepts but never answers -> client must time out
        BadCrc          // answers the pose with a corrupted CRC
    };

    ~MockNrcServer() { stop(); }

    bool start(Mode mode)
    {
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

    void setResponseJson(const QByteArray& json)
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_responseJson = json;
    }

    quint16 port() const { return m_port; }

    std::vector<QByteArray> frames() const
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        return m_frames;
    }

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

    // Reads one complete frame (header + payload + CRC) off the connection.
    static bool recvFrame(SOCKET c, QByteArray& frame)
    {
        char header[6];
        if (!recvAll(c, header, sizeof(header)))
            return false;
        const int len = (static_cast<unsigned char>(header[2]) << 8)
            | static_cast<unsigned char>(header[3]);
        frame = QByteArray(header, sizeof(header));
        if (len <= 0 || len > 8192)
            return false;
        QByteArray rest(len + 4, '\0');
        if (!recvAll(c, rest.data(), rest.size()))
            return false;
        frame += rest;
        return true;
    }

    static quint16 frameCmd(const QByteArray& frame)
    {
        return static_cast<quint16>((static_cast<unsigned char>(frame[4]) << 8)
                                    | static_cast<unsigned char>(frame[5]));
    }

    void sendFrame(SOCKET c, const QByteArray& frame, bool corruptCrc)
    {
        QByteArray out = frame;
        if (corruptCrc && out.size() >= 4)
            out[out.size() - 1] = static_cast<char>(out[out.size() - 1] ^ 0x5A);
        ::send(c, out.constData(), static_cast<int>(out.size()), 0);
    }

    void serve()
    {
        while (m_listen != INVALID_SOCKET) {
            SOCKET c = accept(m_listen, nullptr, nullptr);
            if (c == INVALID_SOCKET)
                break;
            QByteArray frame;
            while (recvFrame(c, frame)) {
                {
                    std::lock_guard<std::mutex> lk(m_mutex);
                    m_frames.push_back(frame);
                }
                const quint16 cmd = frameCmd(frame);
                if (m_mode == Mode::Silent)
                    continue;
                if (cmd == kNrcCmdConnect) {
                    if (m_mode == Mode::ReplyAll) {
                        // The handshake reply's real schema is unknown; the
                        // client must skip it by command id, not parse it.
                        sendFrame(c, NrcJsonReader::buildFrame(cmd, "{\"robot\":1}\n"), false);
                    }
                    continue;
                }
                if (cmd == kNrcCmdGetCurrentPosition) {
                    QByteArray json;
                    {
                        std::lock_guard<std::mutex> lk(m_mutex);
                        json = m_responseJson;
                    }
                    sendFrame(c, NrcJsonReader::buildFrame(cmd, json),
                              m_mode == Mode::BadCrc);
                }
            }
            closesocket(c);
        }
    }

    SOCKET m_listen = INVALID_SOCKET;
    quint16 m_port = 0;
    Mode m_mode = Mode::ReplyAll;
    QByteArray m_responseJson = QByteArray(kPoseJson);
    mutable std::mutex m_mutex;
    std::vector<QByteArray> m_frames;
    std::thread m_thread;
};

struct MockRun {
    RobotPose::Status status = RobotPose::Status::NotConnected;
    RobotPose::Pose pose;
    QString error;
    QByteArray lastResponse;      // JSON body the adapter ended up parsing
    std::vector<QByteArray> frames;
    bool connected = false;
};

// Brings up a mock, connects, performs exactly one readPose() and reports both
// the outcome and the frames the controller actually received.
MockRun runMock(MockNrcServer::Mode mode,
                const QByteArray& responseJson = QByteArray(kPoseJson),
                int timeoutMs = 800)
{
    MockRun run;
    MockNrcServer server;
    if (!server.start(mode))
        return run;
    server.setResponseJson(responseJson);

    NrcJsonReader reader;
    reader.setTimeoutMs(timeoutMs);
    run.connected = reader.connect(QStringLiteral("127.0.0.1"), server.port());
    if (run.connected) {
        run.status = reader.readPose(run.pose);
        run.error = reader.lastError();
        run.lastResponse = reader.lastResponse();
        reader.disconnect();
    } else {
        run.error = reader.lastError();
    }
    run.frames = server.frames();
    server.stop();
    return run;
}

void verifyPose(const Pose& pose)
{
    QCOMPARE(pose.xyz[0], 11.5);
    QCOMPARE(pose.xyz[1], -22.25);
    QCOMPARE(pose.xyz[2], 33.75);
    QCOMPARE(pose.rpy[0], 4.5);
    QCOMPARE(pose.rpy[1], -5.25);
    QCOMPARE(pose.rpy[2], 6.125);
}

} // namespace

void TestNrcJsonReader::connectAndPoseFramesMatchCapturedBytes()
{
    const MockRun run = runMock(MockNrcServer::Mode::ReplyAll);
    QVERIFY(run.connected);
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);

    // Frame 0 is the connect_robot handshake sent by connect(), frame 1 the
    // get_current_position request sent by readPose().
    QCOMPARE(static_cast<int>(run.frames.size()), 2);
    QCOMPARE(run.frames[0], QByteArray::fromHex(kCapturedConnect));
    QCOMPARE(run.frames[1], QByteArray::fromHex(kCapturedGetPosition));
}

void TestNrcJsonReader::allCapturedCommandFramesAreByteExact()
{
    // The remaining two captured frames are builders, so they are asserted
    // directly (the other two also go over a real socket in the test above).
    QCOMPARE(NrcJsonReader::buildFrame(kNrcCmdConnect, NrcJsonReader::connectRequestJson(1)),
             QByteArray::fromHex(kCapturedConnect));
    QCOMPARE(NrcJsonReader::buildFrame(kNrcCmdGetCoord, NrcJsonReader::connectRequestJson(1)),
             QByteArray::fromHex(kCapturedGetCoord));
    QCOMPARE(NrcJsonReader::buildFrame(kNrcCmdGetCurrentPosition,
                                       NrcJsonReader::poseRequestJson(0, 1)),
             QByteArray::fromHex(kCapturedGetPosition));
    QCOMPARE(NrcJsonReader::buildFrame(kNrcCmdGetExtraPosition,
                                       NrcJsonReader::poseRequestJson(0, 1)),
             QByteArray::fromHex(kCapturedGetExtra));
}

void TestNrcJsonReader::handshakeReplyIsSkipped()
{
    // ReplyAll answers the handshake first, so the response that readPose()
    // sees first carries cmd 0x2002 — parsing it as a pose would fail.  The
    // payload that ended up parsed must be the pose reply, not the handshake.
    const MockRun run = runMock(MockNrcServer::Mode::ReplyAll);
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);
    QCOMPARE(run.lastResponse, QByteArray(kPoseJson));
    QVERIFY(run.error.isEmpty());
}

void TestNrcJsonReader::worksWhenHandshakeIsIgnored()
{
    const MockRun run = runMock(MockNrcServer::Mode::ReplyPoseOnly);
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);
}

void TestNrcJsonReader::parsesPosValue()
{
    const MockRun run = runMock(MockNrcServer::Mode::ReplyPoseOnly, QByteArray(kPoseJson));
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);
}

void TestNrcJsonReader::parsesCurrentPos()
{
    const MockRun run = runMock(MockNrcServer::Mode::ReplyPoseOnly,
                                "{\"currentPos\":[11.5,-22.25,33.75,4.5,-5.25,6.125]}");
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);
}

void TestNrcJsonReader::parsesRealPosMcs()
{
    const MockRun run = runMock(MockNrcServer::Mode::ReplyPoseOnly,
                                "{\"realPosMCS\":[11.5,-22.25,33.75,4.5,-5.25,6.125],"
                                "\"robot\":1,\"err\":0}");
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);
}

void TestNrcJsonReader::parsesNestedData()
{
    // Candidate name nested one level down, plus the array under a name that
    // is not on the candidate list at all — both must still be found.
    const MockRun nested = runMock(MockNrcServer::Mode::ReplyPoseOnly,
                                   "{\"err\":0,\"data\":{\"currentPos\":"
                                   "[11.5,-22.25,33.75,4.5,-5.25,6.125]}}");
    QCOMPARE(nested.status, Status::Ok);
    verifyPose(nested.pose);

    const MockRun unknownName = runMock(MockNrcServer::Mode::ReplyPoseOnly,
                                        "{\"err\":0,\"data\":{\"someUnknownField\":"
                                        "[11.5,-22.25,33.75,4.5,-5.25,6.125]}}");
    QCOMPARE(unknownName.status, Status::Ok);
    verifyPose(unknownName.pose);
}

void TestNrcJsonReader::parsesPoseInsideTopLevelArray()
{
    Pose pose;
    QString error;
    QCOMPARE(NrcJsonReader::parsePoseJson("[11.5,-22.25,33.75,4.5,-5.25,6.125]", pose, &error),
             Status::Ok);
    verifyPose(pose);
    QVERIFY(error.isEmpty());
}

void TestNrcJsonReader::timeoutIsRetryable()
{
    MockNrcServer silent;
    QVERIFY(silent.start(MockNrcServer::Mode::Silent));
    NrcJsonReader reader;
    reader.setTimeoutMs(250);
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), silent.port()));

    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::Timeout);
    QVERIFY(!reader.lastError().isEmpty());
    // The socket must stay usable: a second read times out again instead of
    // failing with a protocol error from the first attempt's leftover bytes.
    QCOMPARE(reader.readPose(pose), Status::Timeout);
    QVERIFY(reader.isConnected());
    QVERIFY(!reader.lastError().isEmpty());
    reader.disconnect();
    silent.stop();

    // ... and a fresh reader against a controller that does answer still works.
    const MockRun run = runMock(MockNrcServer::Mode::ReplyPoseOnly);
    QCOMPARE(run.status, Status::Ok);
    verifyPose(run.pose);
}

void TestNrcJsonReader::badCrcIsProtocolError()
{
    const MockRun run = runMock(MockNrcServer::Mode::BadCrc);
    QCOMPARE(run.status, Status::ProtocolError);
    QVERIFY2(run.error.contains(QStringLiteral("CRC")),
             qPrintable(QStringLiteral("unexpected error: %1").arg(run.error)));
}

void TestNrcJsonReader::shortOrMissingFieldIsReadableError()
{
    Pose pose;
    QString error;

    // A candidate field that is present but too short names the field.
    QCOMPARE(NrcJsonReader::parsePoseJson("{\"posValue\":[1,2,3]}", pose, &error),
             Status::ProtocolError);
    QVERIFY2(error.contains(QStringLiteral("posValue")), qPrintable(error));
    QVERIFY2(error.contains(QStringLiteral("3")), qPrintable(error));

    // No usable field at all: the error lists the candidate names.
    error.clear();
    QCOMPARE(NrcJsonReader::parsePoseJson("{\"robot\":1,\"err\":0}", pose, &error),
             Status::ProtocolError);
    QVERIFY2(error.contains(QStringLiteral("posValue")), qPrintable(error));

    // Same through the socket: a readable failure, not a crash.
    const MockRun run = runMock(MockNrcServer::Mode::ReplyPoseOnly,
                                "{\"err\":0,\"data\":{\"nope\":\"x\"}}");
    QCOMPARE(run.status, Status::ProtocolError);
    QVERIFY(!run.error.isEmpty());
}

void TestNrcJsonReader::invalidJsonIsReadableError()
{
    Pose pose;
    QString error;
    QCOMPARE(NrcJsonReader::parsePoseJson("{not json at all", pose, &error),
             Status::ProtocolError);
    QVERIFY2(error.contains(QStringLiteral("JSON")), qPrintable(error));

    // A non-numeric element inside an otherwise long array is also rejected.
    error.clear();
    QCOMPARE(NrcJsonReader::parsePoseJson(
                 "{\"posValue\":[1,2,3,4,5,\"oops-not-a-number\"]}", pose, &error),
             Status::ProtocolError);
    QVERIFY(!error.isEmpty());
}

void TestNrcJsonReader::notConnectedWithoutConnect()
{
    NrcJsonReader reader;
    Pose pose;
    QCOMPARE(reader.readPose(pose), Status::NotConnected);
    QVERIFY(!reader.isConnected());

    MockNrcServer server;
    QVERIFY(server.start(MockNrcServer::Mode::ReplyPoseOnly));
    QVERIFY(reader.connect(QStringLiteral("127.0.0.1"), server.port()));
    reader.disconnect();
    QCOMPARE(reader.readPose(pose), Status::NotConnected);
    QVERIFY(!reader.isConnected());
    server.stop();
}

void TestNrcJsonReader::connectRefusedIsReported()
{
    // A closed port on loopback refuses immediately; the adapter must report a
    // readable error instead of blocking or crashing.
    MockNrcServer gone;
    QVERIFY(gone.start(MockNrcServer::Mode::ReplyPoseOnly));
    const quint16 deadPort = gone.port();
    gone.stop();        // the OS frees the port, nothing listens there now

    NrcJsonReader reader;
    reader.setTimeoutMs(400);
    QVERIFY(!reader.connect(QStringLiteral("127.0.0.1"), deadPort));
    QVERIFY(!reader.lastError().isEmpty());
    QVERIFY(!reader.isConnected());
}
