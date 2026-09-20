#pragma once

#include <QObject>

// 第 5 回合 任务 1: which capture parameters a connect ends up using — the ones
// the camera holds (default) or the ones saved in AppConfig.
class TestCameraParamPolicy : public QObject {
    Q_OBJECT
private slots:
    // The core promise of use_camera_params=1: nothing is pushed to the device.
    void cameraInternalPushesNothing();
    // A device that reported no parameters must still not be written to.
    void cameraInternalEmptyReadPushesNothing();
    void savedConfigIsApplied();
    // No saved values + use_camera_params=0: nothing to push, and no write-back.
    void savedConfigEmptyPushesNothing();
    // An explicit edit always wins, so a change can never be silently ignored.
    void operatorEditBeatsTheCheckbox();
    // Degenerate but reachable: edited with nothing stored → no key pushed.
    void operatorEditWithEmptySavedPushesNothing();
    // The settings dialog shows where the displayed numbers came from.
    void sourceAnnotationIsExplicit();
};
