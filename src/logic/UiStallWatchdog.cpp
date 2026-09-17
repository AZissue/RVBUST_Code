#include "logic/UiStallWatchdog.h"

#include <chrono>
#include <cstdio>
#include <cmath>

namespace UiStallWatchdog {

Watchdog::Watchdog(double thresholdMs, double intervalMs)
    : m_thresholdMs(thresholdMs > 0.0 ? thresholdMs : kDefaultThresholdMs)
    , m_intervalMs(intervalMs > 0.0 ? intervalMs : kDefaultIntervalMs)
{
}

void Watchdog::setThresholdMs(double ms)
{
    if (ms > 0.0)
        m_thresholdMs = ms;
}

void Watchdog::setIntervalMs(double ms)
{
    if (ms > 0.0)
        m_intervalMs = ms;
}

void Watchdog::reset()
{
    // Re-baseline to *now*, not to "no sample".
    //
    // reset() is called right after an intentional blocking operation (a modal
    // dialog) so that think-time is not reported as a stall.  With the baseline
    // cleared to -1 the next tick had nothing to compare against and was
    // swallowed as the first sample — so a block that began right after reset()
    // was never measured at all: the 2.1 s camera connect that follows the
    // device-list dialog produced no watchdog line.  Anchoring the baseline at
    // the reset instant keeps the dialog out of the report while still
    // measuring everything that blocks from here on.
    m_lastMs = nowMs();
    m_inStall = false;
}

Tick Watchdog::tick(double nowMs, const Context& ctx)
{
    Tick out;
    ++m_tickCount;

    if (m_lastMs < 0.0) {
        // First sample: nothing to compare against yet.
        m_lastMs = nowMs;
        return out;
    }

    const double gapMs = nowMs - m_lastMs;
    m_lastMs = nowMs;
    out.stallMs = gapMs;

    if (gapMs > m_thresholdMs) {
        if (gapMs > m_maxStallMs)
            m_maxStallMs = gapMs;
        if (!m_inStall) {
            // Edge trigger: report the episode once, not on every late tick.
            m_inStall = true;
            ++m_stallCount;
            out.stalled = true;
        }
    } else if (m_inStall) {
        m_inStall = false;
        out.recovered = true;
    }

    // Always publish the running maximum.  Reporting it only on a late tick
    // made a healthy tick return 0, so a caller could not read the worst stall
    // after the UI had recovered (and the value contradicted the header).
    out.maxStallMs = m_maxStallMs;
    return out;
}

std::string formatCount(long long n)
{
    char buf[32];
    const double v = static_cast<double>(n);
    if (n >= 1000000)
        std::snprintf(buf, sizeof(buf), "%.1fM", v / 1000000.0);
    else if (n >= 1000)
        std::snprintf(buf, sizeof(buf), "%.0fk", v / 1000.0);
    else
        std::snprintf(buf, sizeof(buf), "%lld", n);
    return std::string(buf);
}

std::string formatStall(double stallMs, const Context& ctx)
{
    char buf[256];
    std::snprintf(buf, sizeof(buf),
                  "UI stall %.0f ms (预览=%s 拍照=%s 3D上传=%s 点数=%s)",
                  stallMs,
                  ctx.previewing ? "是" : "否",
                  ctx.capturing ? "是" : "否",
                  ctx.uploading3d ? "是" : "否",
                  formatCount(ctx.pointCount).c_str());
    return std::string(buf);
}

double nowMs()
{
    using namespace std::chrono;
    return static_cast<double>(
        duration_cast<microseconds>(steady_clock::now().time_since_epoch()).count())
        / 1000.0;
}

} // namespace UiStallWatchdog
