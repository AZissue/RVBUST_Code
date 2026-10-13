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
    // 解析出 6 个数 ≠ 读到真实位姿（第 13 回合，见 RobotPose.h 的
    // checkPoseSanity）：全 0 / 非有限值必须报错，且不改调用方的 out。
    void zeroPoseIsRejected();
    void nonFinitePoseIsRejected();

    // Failure paths: readable error, no crash, state stays usable.
    void timeoutIsRetryable();
    void badCrcIsProtocolError();
    void shortOrMissingFieldIsReadableError();
    void invalidJsonIsReadableError();
    void notConnectedWithoutConnect();
    void connectRefusedIsReported();
};
