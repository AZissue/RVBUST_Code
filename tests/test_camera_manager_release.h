#pragma once

#include <QObject>

// 第 5 回合 任务 3.1/3.3 against the *real* CameraManager (not just the pure
// plan): the teardown is driven twice in a row on one object and must neither
// error nor announce the disconnect twice.  No camera is touched — the object
// is never connected, so no SDK call is reached (SystemInit stays false).
class TestCameraManagerRelease : public QObject {
    Q_OBJECT
private slots:
    void shutdownTwiceOnAConnectedlessManager();
    // The same claim through the public report: the second call must not
    // restart the release, so the first call's outcome is still what is shown.
    void releaseReportSurvivesARepeatCall();
    void useCameraParamsDefaultsToOn();
    void healthIntervalIsConfigurable();
};
