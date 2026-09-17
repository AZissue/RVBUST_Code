#pragma once

#include "logic/RobotPose.h"

#include <QByteArray>
#include <QString>

class QTcpSocket;

// 博纳斯 / 纳博特 (Inexbot) 上位机 JSON-over-TCP reader (stage 9).
//
// The vendor SDK (nrc_host.dll) is itself a socket *client*: it frames a JSON
// body with a small binary header.  We re-implement the client side on
// QTcpSocket so the green package ships no additional DLL.
//
// Frame layout — captured on a real controller by driving the official
// nrc_host.lib (pose_probe.exe) against a mock server.  The four samples below
// are asserted byte-for-byte in tests/test_nrc_json_reader.cpp:
//
//   'N' 'f'      2 bytes magic (0x4E 0x66)
//   uint16 BE    payload length = number of JSON bytes, INCLUDING the '\n'
//   uint16 BE    command id
//   N bytes      JSON payload, terminated by '\n'
//   uint32 BE    CRC32 (zlib/IEEE) over [length field .. last JSON byte],
//                i.e. frame[2, 6 + length) — magic and the CRC itself excluded
//
//   0x2002 connect_robot(ip, port)      4e66 000c 2002 {"robot":1}\n        fac1f6a0
//   0x2F07 get_current_position(coord=0) 4e66 0016 2f07 {"coord":0,"robot":1}\n e33618e0
//   0x2202 get_current_coord()          4e66 000c 2202 {"robot":1}\n        1baf320d
//   0x7012 get_current_extra_position() 4e66 0016 7012 {"coord":0,"robot":1}\n c3c95baa
//
// The *response* schema is unconfirmed (the vendor SDK returned
// RECEIVE_FAILED(-1) for every candidate field name tried against the real
// controller), so parsing is deliberately tolerant: candidate key names first,
// then one level down into nested objects — see parsePoseJson().  Every
// response is dumped (hex + text) into the runtime log so a field session can
// pin the real field names down from the log alone.
namespace RobotPose {

enum NrcCommand : quint16 {
    kNrcCmdConnect             = 0x2002,   // connect_robot
    kNrcCmdGetCoord            = 0x2202,   // get_current_coord
    kNrcCmdGetCurrentPosition  = 0x2F07,   // get_current_position (coord=0: TCP)
    kNrcCmdGetExtraPosition    = 0x7012    // get_current_extra_position
};

class NrcJsonReader : public Reader {
public:
    NrcJsonReader() = default;
    ~NrcJsonReader() override;

    bool connect(const QString& host, quint16 port) override;
    void disconnect() override;
    Status readPose(Pose& out) override;
    QString lastError() const override;

    void setTimeoutMs(int ms);
    int timeoutMs() const { return m_timeoutMs; }
    bool isConnected() const;

    // JSON payload of the most recent 0x2F07 response (empty until one arrives).
    QByteArray lastResponse() const { return m_lastResponse; }

    // ── Protocol primitives ────────────────────────────────────────────
    // Pure helpers, public so the unit tests can assert the wire bytes
    // without a socket in the way.
    static quint32 crc32(const QByteArray& data);
    static QByteArray buildFrame(quint16 cmd, const QByteArray& json);
    static QByteArray connectRequestJson(int robot = 1);
    static QByteArray poseRequestJson(int coord = 0, int robot = 1);

    // Tolerant response parser.  On failure `error` (when given) receives a
    // readable reason; `out` is only written on Status::Ok.
    static Status parsePoseJson(const QByteArray& json, Pose& out, QString* error);

private:
    // Sends one command and returns the payload of the matching reply.
    Status transact(quint16 cmd, const QByteArray& json, QByteArray& payload);
    // Reads one complete frame; `payload` receives the JSON body, `cmd` the
    // command id.  Uses at most `budgetMs` for the whole frame.
    Status readFrame(QByteArray& payload, quint16& cmd, int budgetMs);
    // Drops everything buffered on the socket so the next read starts at a
    // frame boundary (called after a timeout / desynchronized stream).
    void dropPendingInput();

    QTcpSocket* m_socket = nullptr;
    int m_timeoutMs = 1500;
    QString m_error;
    QByteArray m_lastResponse;
};

} // namespace RobotPose
