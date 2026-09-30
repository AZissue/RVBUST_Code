#pragma once

#include <QObject>

class TestCalibrationService : public QObject {
    Q_OBJECT
private slots:
    void normalizePoseLineAcceptsSpacesAndCommas();
    void normalizePoseLineRejectsBadInput();
    void errorTextMapping();
    // T-008：SDK 内部异常（桥接层拦截到的 SEH/异常）不能再被说成"参数无效"。
    void sdkInternalErrorIsDistinctFromBadParameters();
};
