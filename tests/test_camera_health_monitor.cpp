#include "test_camera_health_monitor.h"

#include <QtTest>

#include "logic/CameraHealthMonitor.h"

namespace {
constexpr auto kScheduled = CameraHealthMonitor::ReconnectPlan::Scheduled;
constexpr auto kIgnored = CameraHealthMonitor::ReconnectPlan::Ignored;
constexpr auto kExhausted = CameraHealthMonitor::ReconnectPlan::Exhausted;
} // namespace

void TestCameraHealthMonitor::defaultsMatchTheHistoricalPolicy()
{
    CameraHealthMonitor m;
    // 30 s（不是 5 s）、3 次、无待定尝试 —— 与改造前 CameraManager 的常量一致。
    QCOMPARE(m.healthInterval(), CameraHealthMonitor::HEALTH_INTERVAL_MS);
    QCOMPARE(m.healthInterval(), 30000);
    QCOMPARE(CameraHealthMonitor::MAX_ATTEMPTS, 3);
    QCOMPARE(m.attempts(), 0);
}

void TestCameraHealthMonitor::healthIntervalFallsBackWhenNonPositive()
{
    CameraHealthMonitor m;
    m.setHealthInterval(5000);
    QCOMPARE(m.healthInterval(), 5000);
    m.setHealthInterval(0);
    QCOMPARE(m.healthInterval(), CameraHealthMonitor::HEALTH_INTERVAL_MS);
    m.setHealthInterval(-1);
    QCOMPARE(m.healthInterval(), CameraHealthMonitor::HEALTH_INTERVAL_MS);
}

void TestCameraHealthMonitor::healthChecksKeepTickingUntilStopped()
{
    CameraHealthMonitor m;
    m.setHealthInterval(5);
    QSignalSpy ticks(&m, &CameraHealthMonitor::healthCheckDue);

    m.startHealthChecks();
    QTRY_VERIFY(ticks.count() >= 2);

    m.stop();
    const int seen = ticks.count();
    QTest::qWait(30);
    QCOMPARE(ticks.count(), seen);
}

void TestCameraHealthMonitor::planCountsAttemptsAndExhaustsTheBudget()
{
    CameraHealthMonitor m;
    m.setReconnectInterval(1);
    QSignalSpy due(&m, &CameraHealthMonitor::reconnectDue);

    for (int i = 1; i <= CameraHealthMonitor::MAX_ATTEMPTS; ++i) {
        QCOMPARE(m.planReconnect(), kScheduled);
        QCOMPARE(m.attempts(), i);
        // 等这一次的定时器真正走完，下一次才允许排程。
        QTRY_COMPARE(due.count(), i);
    }

    // 预算用尽：不再排程，并发出一条"请手动重连"的判定；计数清零，
    // 让下一次手动恢复后的事件重新拥有完整预算。
    QCOMPARE(m.planReconnect(), kExhausted);
    QCOMPARE(m.attempts(), 0);
    QTest::qWait(20);
    QCOMPARE(due.count(), CameraHealthMonitor::MAX_ATTEMPTS);
}

void TestCameraHealthMonitor::aPendingRetryIsNotDoubleScheduled()
{
    CameraHealthMonitor m;
    m.setReconnectInterval(50);
    QSignalSpy due(&m, &CameraHealthMonitor::reconnectDue);

    QCOMPARE(m.planReconnect(), kScheduled);
    QCOMPARE(m.attempts(), 1);
    // 定时器还没走：再次请求必须被忽略，既不重复计数也不重置等待。
    QCOMPARE(m.planReconnect(), kIgnored);
    QCOMPARE(m.attempts(), 1);

    QVERIFY(due.wait(1000));
    QCOMPARE(due.count(), 1);
    // 走完之后又可以排下一次。
    QCOMPARE(m.planReconnect(), kScheduled);
    QCOMPARE(m.attempts(), 2);
}

void TestCameraHealthMonitor::noteConnectedRestoresTheBudget()
{
    CameraHealthMonitor m;
    m.setReconnectInterval(1);
    QSignalSpy due(&m, &CameraHealthMonitor::reconnectDue);

    QCOMPARE(m.planReconnect(), kScheduled);
    QTRY_COMPARE(due.count(), 1);
    QCOMPARE(m.planReconnect(), kScheduled);
    QTRY_COMPARE(due.count(), 2);
    QCOMPARE(m.attempts(), 2);

    // 重连成功：下一次故障从头计数（与 finishConnect 里原来的清零一致）。
    m.noteConnected();
    QCOMPARE(m.attempts(), 0);
    QCOMPARE(m.planReconnect(), kScheduled);
    QCOMPARE(m.attempts(), 1);
}

void TestCameraHealthMonitor::stopDropsTimersAndBudget()
{
    CameraHealthMonitor m;
    m.setHealthInterval(1);
    m.setReconnectInterval(1);
    QSignalSpy health(&m, &CameraHealthMonitor::healthCheckDue);
    QSignalSpy due(&m, &CameraHealthMonitor::reconnectDue);

    m.startHealthChecks();
    QCOMPARE(m.planReconnect(), kScheduled);
    m.stop();

    QTest::qWait(30);
    QCOMPARE(health.count(), 0);
    QCOMPARE(due.count(), 0);
    QCOMPARE(m.attempts(), 0);
}
