#include "test_camera_recovery.h"

#include <QtTest>

#include "logic/CameraRelease.h"
#include "logic/CrashInject.h"

using namespace CameraRelease;

namespace {

// Applies a plan to a state, the way shutdown() mutates its own flags, so the
// "call it twice" claim can be tested without a camera.
void apply(const Actions& a, State& s)
{
    if (a.noop)
        return;
    if (a.closeDevice)
        s.deviceOpen = false;
    if (a.systemShutdown)
        s.systemInited = false;
    s.released = true;
}

} // namespace

void TestCameraRecovery::idleStateIsNoop()
{
    // Never connected, never initialised: closeDevice/systemShutdown are false,
    // so shutdown() enters no SDK branch.
    const Actions a = plan(State{});
    QVERIFY(!a.closeDevice);
    QVERIFY(!a.systemShutdown);
}

void TestCameraRecovery::repeatTeardownIsNoop()
{
    State s;
    s.deviceOpen = true;
    s.systemInited = true;

    const Actions first = plan(s);
    QVERIFY(!first.noop);
    QVERIFY(first.closeDevice);
    QVERIFY(first.systemShutdown);
    QVERIFY(first.emitDisconnected);
    apply(first, s);

    // Second call — the state of a finished teardown.
    const Actions second = plan(s);
    QVERIFY(second.noop);              // ← repeated Close/Destroy is impossible
    QVERIFY(!second.closeDevice);
    QVERIFY(!second.systemShutdown);
    QVERIFY(!second.emitDisconnected); // ← no second "相机已断开"
    apply(second, s);
    QVERIFY(plan(s).noop);             // stays settled no matter how often
}

void TestCameraRecovery::teardownAfterConnectClosesAndAnnounces()
{
    // A live connection: released is false because connect() clears it.
    State s;
    s.deviceOpen = true;
    s.systemInited = true;
    s.released = false;

    const Actions a = plan(s);
    QVERIFY(!a.noop);
    QVERIFY(a.emitDisconnected);
}

void TestCameraRecovery::systemOnlyTeardownShutsDownSystem()
{
    State s;
    s.deviceOpen = false;      // e.g. Open() failed after SystemInit() succeeded
    s.systemInited = true;

    const Actions a = plan(s);
    QVERIFY(!a.noop);
    QVERIFY(!a.closeDevice);
    QVERIFY(a.systemShutdown);
}

void TestCameraRecovery::retryScheduleIsOneTwoThreeSeconds()
{
    const std::vector<int> d = connectRetryDelaysMs(3);
    QCOMPARE(d.size(), std::size_t(3));
    QCOMPARE(d[0], 1000);   // 1 s before the 1st retry
    QCOMPARE(d[1], 2000);
    QCOMPARE(d[2], 3000);
    // The whole schedule is bounded, so a failed connect cannot hang the UI.
    int total = 0;
    for (int ms : d) total += ms;
    QCOMPARE(total, 6000);
}

void TestCameraRecovery::retryDisabledWhenCountIsZero()
{
    QVERIFY(connectRetryDelaysMs(0).empty());
    QVERIFY(connectRetryDelaysMs(-1).empty());
    QCOMPARE(connectRetryDelaysMs(1).size(), std::size_t(1));
}

void TestCameraRecovery::classifiesBusyFromTheDeviceFlag()
{
    // The GigE "In Use" flag is hard evidence, and it wins over the text.
    QCOMPARE(classify(QString(), /*deviceFound=*/true, /*deviceInUse=*/true),
             ConnectFailure::DeviceBusy);
}

void TestCameraRecovery::classifiesBusyFromTheErrorText()
{
    QCOMPARE(classify(QStringLiteral("device is in use"), true, false),
             ConnectFailure::DeviceBusy);
    QCOMPARE(classify(QStringLiteral("设备被占用"), true, false),
             ConnectFailure::DeviceBusy);
    QCOMPARE(classify(QStringLiteral("Device BUSY"), true, false),
             ConnectFailure::DeviceBusy);
    QCOMPARE(classify(QStringLiteral("该模式不支持"), true, false),
             ConnectFailure::Unsupported);
    QCOMPARE(classify(QStringLiteral("open failed: -12"), true, false),
             ConnectFailure::SdkError);
    QCOMPARE(classify(QString(), true, false), ConnectFailure::Unknown);
}

void TestCameraRecovery::classifiesMissingDevice()
{
    // Not found wins over everything: no text and no in-use flag can help.
    QCOMPARE(classify(QString(), /*deviceFound=*/false, false),
             ConnectFailure::DeviceNotFound);
    QCOMPARE(classify(QStringLiteral("in use"), false, true),
             ConnectFailure::DeviceNotFound);
}

void TestCameraRecovery::retriesOnlyWhenItCanHelp()
{
    // Occupied / transient SDK errors are worth 1+2+3 s of waiting.
    QVERIFY(shouldRetry(ConnectFailure::DeviceBusy));
    QVERIFY(shouldRetry(ConnectFailure::SdkError));
    QVERIFY(shouldRetry(ConnectFailure::Unknown));
    // An unplugged camera or an unsupported model fails identically 3 s later,
    // so a retry would only delay the error the operator needs to read.
    QVERIFY(!shouldRetry(ConnectFailure::DeviceNotFound));
    QVERIFY(!shouldRetry(ConnectFailure::Unsupported));
}

void TestCameraRecovery::busyHintTellsTheOperatorWhatToDo()
{
    const QString h = operatorHint(ConnectFailure::DeviceBusy, 3, QString());
    QVERIFY(h.contains(QStringLiteral("被占用")));
    QVERIFY(h.contains(QStringLiteral("重试")));
    // The 3.3 requirement: readable recovery advice, not a bare SDK string.
    QVERIFY(h.contains(QStringLiteral("10 秒")));
    QVERIFY(h.contains(QStringLiteral("插拔")));
    QVERIFY(h.contains(QStringLiteral("电源")));
    QVERIFY(h.contains(QStringLiteral("3 次")));   // matches what actually ran
}

void TestCameraRecovery::everyFailureHasAHint()
{
    const ConnectFailure all[] = { ConnectFailure::DeviceBusy,
                                   ConnectFailure::DeviceNotFound,
                                   ConnectFailure::Unsupported,
                                   ConnectFailure::SdkError,
                                   ConnectFailure::Unknown };
    for (ConnectFailure f : all) {
        const QString h = operatorHint(f, 1, QStringLiteral("原始错误"));
        QVERIFY(!h.isEmpty());
    }
    // The raw SDK text is kept for the field, appended to the readable advice.
    QVERIFY(operatorHint(ConnectFailure::SdkError, 0, QStringLiteral("open failed: -12"))
                .contains(QStringLiteral("open failed: -12")));
}

void TestCameraRecovery::crashInjectMatchesOnlyItsOwnValue()
{
    using CrashInject::Point;
    // Exact match only: a typo must not crash an operator's normal session.
    QVERIFY(CrashInject::matches("after-connect", Point::AfterConnect));
    QVERIFY(CrashInject::matches("after-capture", Point::AfterCapture));
    QVERIFY(!CrashInject::matches("after-capture", Point::AfterConnect));
    QVERIFY(!CrashInject::matches("after-connect", Point::AfterCapture));
    // Unset / unrelated values are inert (the default for every user).
    QVERIFY(!CrashInject::matches(QByteArray(), Point::AfterConnect));
    QVERIFY(!CrashInject::matches(QByteArray(), Point::AfterCapture));
    QVERIFY(!CrashInject::matches("1", Point::AfterConnect));
    QVERIFY(!CrashInject::matches("after-connect ", Point::AfterConnect));
    QVERIFY(!CrashInject::matches("AFTER-CONNECT", Point::AfterConnect));
}
