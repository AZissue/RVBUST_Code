#pragma once

#include <QObject>

// 博纳斯/纳博特 (Inexbot) JSON-over-TCP adapter — framed against the four
// frames captured on a real controller (see logic/NrcJsonReader.h).
class TestNrcJsonReader : public QObject {
    Q_OBJECT
private slots:
    // Wire format: the bytes the adapter puts on the socket must equal the
    // capture, byte for byte (magic, length, cmd, '\n', CRC).
    void connectAndPoseFramesMatchCapturedBytes();
    void allCapturedCommandFramesAreByteExact();
    // A late 0x2002 reply must be skipped, not parsed as a pose.
    void handshakeReplyIsSkipped();
    // ... and a robot that never answers the handshake must still work.
    void worksWhenHandshakeIsIgnored();

    // Response schema is unconfirmed: every candidate key must parse.
    void parsesPosValue();
    void parsesCurrentPos();
    void parsesRealPosMcs();
    void parsesNestedData();
    void parsesPoseInsideTopLevelArray();

    // Failure paths: readable error, no crash, state stays usable.
    void timeoutIsRetryable();
    void badCrcIsProtocolError();
    void shortOrMissingFieldIsReadableError();
    void invalidJsonIsReadableError();
    void notConnectedWithoutConnect();
    void connectRefusedIsReported();
};
