#include "test_capture_lifecycle.h"

#include "logic/CaptureLifecycle.h"

#include <QTest>

using namespace CaptureLifecycle;

void TestCaptureLifecycle::submitOnlyWhenIdleAndOpen()
{
    State s;
    QVERIFY(canSubmit(s));

    onSubmit(s);
    QVERIFY(hasWorkerRunning(s));
    QVERIFY(!canSubmit(s));   // one task at a time

    const auto fin = onFinished(s);
    QVERIFY(fin.apply);
    QVERIFY(!hasWorkerRunning(s));
    QVERIFY(canSubmit(s));    // idle again
}

void TestCaptureLifecycle::timeoutKeepsWorkerRunning()
{
    State s;
    onSubmit(s);

    const auto t = onTimeout(s);
    QVERIFY(t.report);
    QVERIFY(!canSubmit(s));   // UI gave up, the SDK thread did not
    QVERIFY(hasWorkerRunning(s));

    // A second watchdog tick must not report the timeout twice.
    QVERIFY(!onTimeout(s).report);
}

void TestCaptureLifecycle::lateFinishAfterTimeoutIsDropped()
{
    State s;
    onSubmit(s);
    onTimeout(s);

    const auto fin = onFinished(s);
    QVERIFY(!fin.apply);          // late result ignored
    QVERIFY(fin.wasTimedOut);
    QVERIFY(!hasWorkerRunning(s));
    QVERIFY(canSubmit(s));        // worker really exited -> new capture allowed
}

void TestCaptureLifecycle::normalFinishAppliesResult()
{
    State s;
    onSubmit(s);

    const auto fin = onFinished(s);
    QVERIFY(fin.apply);
    QVERIFY(!fin.wasTimedOut);
}

void TestCaptureLifecycle::shutdownDropsResultAndBlocksSubmit()
{
    State s;
    onSubmit(s);
    onShutdown(s);

    QVERIFY(!canSubmit(s));
    const auto fin = onFinished(s);
    QVERIFY(!fin.apply);          // even a healthy result must not reach a closing app
    QVERIFY(hasWorkerRunning(s) == false);
    QVERIFY(!canSubmit(s));       // shutdown is terminal
}

void TestCaptureLifecycle::releaseReopensSubmitButNotWhileWorkerRuns()
{
    // Release finished with no capture in flight -> the manager is usable again.
    State idle;
    onShutdown(idle);
    onReleased(idle);
    QVERIFY(canSubmit(idle));

    // Release finished while the old capture worker is still inside the SDK:
    // shutdown is cleared, but a new capture must stay blocked until it exits.
    State s;
    onSubmit(s);
    onShutdown(s);
    onReleased(s);
    QVERIFY(!canSubmit(s));
    QVERIFY(hasWorkerRunning(s));

    const auto fin = onFinished(s);
    QVERIFY(!fin.apply);       // result belongs to the released session
    QVERIFY(canSubmit(s));     // worker really left -> capture allowed again
}

void TestCaptureLifecycle::timeoutAfterFinishIsIgnored()
{
    State s;
    onSubmit(s);
    onFinished(s);

    const auto t = onTimeout(s);
    QVERIFY(!t.report);           // watchdog fired late: no user-facing error
    QVERIFY(!hasWorkerRunning(s));
}
