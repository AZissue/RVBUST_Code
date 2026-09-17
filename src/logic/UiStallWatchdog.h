#pragma once

#include <string>

// UI-thread stall watchdog.
//
// A low-overhead heart-beat: the UI thread owns a QTimer (100 ms by default)
// and feeds the current monotonic time into tick().  When the gap between two
// consecutive ticks exceeds the threshold (500 ms by default, configurable) the
// UI thread was blocked for that long, which is exactly the symptom the field
// reports as "卡死".  Each stall episode is reported once, together with a
// snapshot of what the pipeline was doing at the time, so a runtime log tail
// shows which stage is responsible.
//
// Pure logic (no Qt, no threads, no allocation on the hot path) so the
// edge-trigger behaviour and the formatting are unit-testable.
namespace UiStallWatchdog {

// Heart-beat interval and the stall threshold (both configurable at run time).
inline constexpr double kDefaultThresholdMs = 500.0;   // 500 ms
inline constexpr double kDefaultIntervalMs  = 100.0;   // 100 ms

// What the UI thread was busy with when the stall was detected.  Plain data, so
// formatting never touches a live object from the logging path.
struct Context {
    bool previewing = false;    // 2D preview stream running
    bool capturing = false;     // capture / detect pipeline running
    bool uploading3d = false;   // Vis point-cloud upload in progress
    long long pointCount = 0;   // points currently in the 3D scene
};

struct Tick {
    bool stalled = false;       // first tick of a stall episode
    bool recovered = false;     // first healthy tick after a stall
    double stallMs = 0.0;       // measured gap for this tick
    double maxStallMs = 0.0;    // worst gap seen since reset()
};

class Watchdog {
public:
    explicit Watchdog(double thresholdMs = kDefaultThresholdMs,
                      double intervalMs = kDefaultIntervalMs);

    void setThresholdMs(double ms);
    double thresholdMs() const { return m_thresholdMs; }
    void setIntervalMs(double ms);
    double intervalMs() const { return m_intervalMs; }

    // Re-baseline the heart-beat to the current instant (call after an
    // intentional blocking operation, e.g. a modal dialog, so that wait is not
    // reported as a stall).  Everything that blocks *after* the reset is still
    // measured — the baseline is "now", never "no sample".
    void reset();

    // `nowMs` must come from a monotonic clock — use nowMs() below.
    Tick tick(double nowMs, const Context& ctx);

    long long stallCount() const { return m_stallCount; }
    double maxStallMs() const { return m_maxStallMs; }

    // Total number of tick() calls — the CPU cost is one subtraction and one
    // comparison per call, published so the field log proves the overhead.
    long long tickCount() const { return m_tickCount; }

private:
    double m_thresholdMs;
    double m_intervalMs;
    double m_lastMs = -1.0;
    bool m_inStall = false;
    long long m_stallCount = 0;
    long long m_tickCount = 0;
    double m_maxStallMs = 0.0;
};

// "[WATCHDOG] UI stall 734 ms (预览=是 拍照=否 3D上传=是 点数=682k)"
std::string formatStall(double stallMs, const Context& ctx);

// Compact count used by formatStall: 682k / 1.5M.
std::string formatCount(long long n);

// Monotonic millisecond clock (std::chrono::steady_clock based).
double nowMs();

} // namespace UiStallWatchdog
