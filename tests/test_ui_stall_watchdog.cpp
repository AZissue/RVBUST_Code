#include "test_ui_stall_watchdog.h"

#include <QtTest>

#include "logic/UiStallWatchdog.h"

using UiStallWatchdog::Context;
using UiStallWatchdog::Watchdog;

void TestUiStallWatchdog::firstTickIsNotAStall()
{
    Watchdog w;
    const auto t = w.tick(1000.0, Context{});
    QVERIFY(!t.stalled);      // no previous sample to compare against
    QVERIFY(!t.recovered);
    QCOMPARE(w.tickCount(), 1LL);
}

void TestUiStallWatchdog::detectsStallOverThreshold()
{
    Watchdog w(500.0, 100.0);
    w.tick(0.0, Context{});
    QVERIFY(!w.tick(100.0, Context{}).stalled);   // healthy 100 ms cadence
    QVERIFY(!w.tick(200.0, Context{}).stalled);

    const auto t = w.tick(2000.0, Context{});     // UI thread blocked for 1800 ms
    QVERIFY(t.stalled);
    QCOMPARE(t.stallMs, 1800.0);
    QCOMPARE(w.stallCount(), 1LL);
}

void TestUiStallWatchdog::reportsEachEpisodeOnce()
{
    Watchdog w(500.0, 100.0);
    w.tick(0.0, Context{});
    QVERIFY(w.tick(2000.0, Context{}).stalled);   // long block
    // While still blocked we keep getting late ticks; the episode must be
    // reported once, not once per late tick.
    QVERIFY(!w.tick(2900.0, Context{}).stalled);
    QVERIFY(!w.tick(3800.0, Context{}).stalled);
    QCOMPARE(w.stallCount(), 1LL);
}

void TestUiStallWatchdog::recoversAndDetectsAgain()
{
    Watchdog w(500.0, 100.0);
    w.tick(0.0, Context{});
    QVERIFY(w.tick(2000.0, Context{}).stalled);

    const auto r = w.tick(2100.0, Context{});
    QVERIFY(!r.stalled);
    QVERIFY(r.recovered);
    QVERIFY(!w.tick(2200.0, Context{}).recovered);   // recovery is edge-triggered

    QVERIFY(w.tick(3000.0, Context{}).stalled);      // second episode
    QCOMPARE(w.stallCount(), 2LL);
}

void TestUiStallWatchdog::thresholdIsConfigurable()
{
    Watchdog w;                       // default 500 ms
    QCOMPARE(w.thresholdMs(), UiStallWatchdog::kDefaultThresholdMs);
    QCOMPARE(w.intervalMs(), UiStallWatchdog::kDefaultIntervalMs);

    w.tick(0.0, Context{});
    QVERIFY(!w.tick(300.0, Context{}).stalled);   // 300 ms is under the 500 ms default

    w.reset();
    w.setThresholdMs(600.0);
    w.tick(0.0, Context{});
    QVERIFY(w.tick(700.0, Context{}).stalled);    // ... and 700 ms is a stall at 600 ms

    // A non-positive threshold is rejected rather than disabling the watchdog.
    w.setThresholdMs(0.0);
    QCOMPARE(w.thresholdMs(), 600.0);
}

void TestUiStallWatchdog::tracksMaxStall()
{
    Watchdog w(500.0, 100.0);
    w.tick(0.0, Context{});
    QVERIFY(w.tick(800.0, Context{}).stalled);       // 800 ms
    w.tick(900.0, Context{});
    QVERIFY(w.tick(2200.0, Context{}).stalled);      // 1300 ms
    QCOMPARE(w.maxStallMs(), 1300.0);
    QCOMPARE(w.tick(2300.0, Context{}).maxStallMs, 1300.0);
}

void TestUiStallWatchdog::contextFormatting()
{
    Context ctx;
    ctx.previewing = true;
    ctx.uploading3d = true;
    ctx.pointCount = 682000;

    const std::string line = UiStallWatchdog::formatStall(734.0, ctx);
    QVERIFY(line.find("UI stall 734 ms") != std::string::npos);
    QVERIFY(line.find("预览=是") != std::string::npos);
    QVERIFY(line.find("拍照=否") != std::string::npos);
    QVERIFY(line.find("3D上传=是") != std::string::npos);
    QVERIFY(line.find("点数=682k") != std::string::npos);
}

void TestUiStallWatchdog::countFormatting()
{
    QCOMPARE(UiStallWatchdog::formatCount(0), std::string("0"));
    QCOMPARE(UiStallWatchdog::formatCount(999), std::string("999"));
    QCOMPARE(UiStallWatchdog::formatCount(1000), std::string("1k"));
    QCOMPARE(UiStallWatchdog::formatCount(682000), std::string("682k"));
    QCOMPARE(UiStallWatchdog::formatCount(1500000), std::string("1.5M"));
}

void TestUiStallWatchdog::clockIsMonotonic()
{
    const double a = UiStallWatchdog::nowMs();
    const double b = UiStallWatchdog::nowMs();
    QVERIFY(b >= a);
}

void TestUiStallWatchdog::blockAfterResetIsStillReported()
{
    Watchdog w(500.0, 100.0);
    w.tick(0.0, Context{});
    w.tick(100.0, Context{});                        // healthy cadence
    QCOMPARE(w.stallCount(), 0LL);

    // A modal dialog is dismissed and reset() re-baselines the watchdog.
    w.reset();

    // The UI then blocks for 2.1 s (the real camera connect).  The very next
    // tick must report it — with the old reset() this tick was swallowed as the
    // "first sample" and the stall was never seen.
    const double now = UiStallWatchdog::nowMs();
    const auto t = w.tick(now + 2100.0, Context{});
    QVERIFY(t.stalled);
    QVERIFY2(t.stallMs >= 2100.0 && t.stallMs < 2200.0,
             qPrintable(QStringLiteral("stallMs=%1").arg(t.stallMs)));
    QCOMPARE(w.stallCount(), 1LL);
    QCOMPARE(w.maxStallMs(), t.stallMs);
}

void TestUiStallWatchdog::tickCostIsNegligible()
{
    // A healthy tick must stay far below the 100 ms heart-beat: the runtime
    // cost per tick is one subtraction, two comparisons and a struct copy.
    // The bound below is deliberately loose (2 us) so the test measures the
    // order of magnitude instead of flaking on a loaded machine.
    constexpr int kTicks = 200000;
    Watchdog w(500.0, 100.0);
    Context ctx;
    ctx.previewing = true;
    ctx.pointCount = 682000;

    const double t0 = UiStallWatchdog::nowMs();
    double t = 0.0;
    for (int i = 0; i < kTicks; ++i) {
        t += 100.0;                       // healthy 100 ms cadence
        w.tick(t, ctx);
    }
    const double elapsedMs = UiStallWatchdog::nowMs() - t0;
    const double perTickUs = elapsedMs * 1000.0 / kTicks;

    qInfo("watchdog tick cost: %.3f us/tick over %d ticks (%lld stalls)",
          perTickUs, kTicks, w.stallCount());
    QCOMPARE(w.tickCount(), static_cast<long long>(kTicks));
    QCOMPARE(w.stallCount(), 0LL);
    QVERIFY2(perTickUs < 2.0, "tick() is too expensive for a 100 ms heart-beat");
}
