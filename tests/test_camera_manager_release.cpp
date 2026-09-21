#include "test_camera_manager_release.h"

#include <QtTest>

#include "logic/CameraManager.h"

// Every test here stays on a *never connected* CameraManager: no Open, no
// SystemInit, no capture — the camera on the bench is not touched, so the suite
// cannot disturb a running session or leave the device occupied.

void TestCameraManagerRelease::shutdownTwiceOnAConnectedlessManager()
{
    CameraManager cam;
    QSignalSpy disconnected(&cam, &CameraManager::cameraDisconnected);

    cam.shutdown(1000);
    QCOMPARE(disconnected.count(), 1);
    QVERIFY(!cam.isConnected());

    // 任务 3.1: the repeat call (closeEvent → aboutToQuit, or 断开 → 关机) must
    // be a no-op.  Before the state-driven plan this re-entered Close/Destroy
    // and emitted a second "相机已断开".
    cam.shutdown(1000);
    QCOMPARE(disconnected.count(), 1);

    cam.shutdown(0);              // even a zero-wait repeat is harmless
    QCOMPARE(disconnected.count(), 1);
}

void TestCameraManagerRelease::releaseReportSurvivesARepeatCall()
{
    CameraManager cam;
    cam.shutdown(1000);
    const auto first = cam.lastRelease();
    QVERIFY(first.attempted);
    QVERIFY(first.released);
    QVERIFY(first.detail.isEmpty());

    // The no-op path returns before the report is reset, so what the UI/log
    // reads afterwards still describes the release that really happened.
    cam.shutdown(1000);
    const auto second = cam.lastRelease();
    QCOMPARE(second.attempted, first.attempted);
    QCOMPARE(second.released, first.released);
    QCOMPARE(second.detail, first.detail);
}

void TestCameraManagerRelease::captureSummaryEmptyBeforeConnect()
{
    CameraManager cam;
    // 第 12 回合 任务 1: the app no longer owns any capture parameter.  The
    // summary is a mirror of what the *camera* holds, so before a connect there
    // is nothing in it — and, just as important, it never gets filled from
    // anywhere but the device (loadCameraOptionsLocked is the only writer).
    QVERIFY(cam.cameraCaptureSummary().isEmpty());
}

void TestCameraManagerRelease::healthIntervalIsConfigurable()
{
    CameraManager cam;
    // 任务 3.4: 5 s (the old constant, which grabbed the device lock 12×/min)
    // is no longer the default.
    QCOMPARE(cam.healthCheckInterval(), 30000);
    cam.setHealthCheckInterval(60000);
    QCOMPARE(cam.healthCheckInterval(), 60000);
    // Non-positive input falls back to the default rather than a 0 ms timer,
    // which would fire continuously.
    cam.setHealthCheckInterval(0);
    QCOMPARE(cam.healthCheckInterval(), 30000);
    cam.setHealthCheckInterval(-5);
    QCOMPARE(cam.healthCheckInterval(), 30000);

    QCOMPARE(cam.connectRetryCount(), 3);
    cam.setConnectRetryCount(5);
    QCOMPARE(cam.connectRetryCount(), 5);
    cam.setConnectRetryCount(0);        // negative/zero disables retrying
    QCOMPARE(cam.connectRetryCount(), 0);
    cam.setConnectRetryCount(-2);
    QCOMPARE(cam.connectRetryCount(), 0);
}
