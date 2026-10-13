#pragma once

#include <QObject>

class TestRobotPose : public QObject {
    Q_OBJECT
private slots:
    void modbusFloat32();
    void modbusInt32Scaled();
    void modbusInt16Scaled();
    void modbusAllZeroPoseIsAnError();
    void modbusNotANumberIsAnError();
    void poseSanityPredicate();
    void modbusTimeout();
    void notConnected();
    void statusTextMapped();
    void urRealtimePose();
    void urRealtimeReadsCapturedPacket();
    void urRealtimeStreamsNewestPose();
    void urRealtimeZeroPoseIsAnError();
    void urRealtimeStaleStreamTimesOut();
    void urRtdeStreamsNewestPose();
    void urRtdeUnavailablePoseIsRejected();
};
