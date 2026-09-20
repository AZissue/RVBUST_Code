#pragma once

#include <QObject>

// 第 5 回合 任务 3: the pure release / recovery rules behind the camera
// lifetime work — idempotent teardown, the bounded connect retry, the failure
// classification and the operator-facing hints.
class TestCameraRecovery : public QObject {
    Q_OBJECT
private slots:
    // Nothing was ever opened: the plan must touch no SDK object.
    void idleStateIsNoop();
    // The 3.1 requirement in one test: a repeat teardown is a real no-op — no
    // second Close/Destroy, no second SystemShutdown, no second signal.
    void repeatTeardownIsNoop();
    void teardownAfterConnectClosesAndAnnounces();
    // A device whose system was initialised but never opened still needs the
    // SDK-wide shutdown.
    void systemOnlyTeardownShutsDownSystem();
    void retryScheduleIsOneTwoThreeSeconds();
    void retryDisabledWhenCountIsZero();
    void classifiesBusyFromTheDeviceFlag();
    void classifiesBusyFromTheErrorText();
    void classifiesMissingDevice();
    void retriesOnlyWhenItCanHelp();
    void busyHintTellsTheOperatorWhatToDo();
    void everyFailureHasAHint();
    void crashInjectMatchesOnlyItsOwnValue();
};
