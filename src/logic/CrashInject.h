#pragma once

// ── Deliberate crash injection — TEST ONLY ──
//
// HEC_CRASH_INJECT=after-connect | after-capture makes the app take a
// deliberate null-pointer write at that point, so the hard-crash behaviour can
// be exercised on demand (the acceptance test for 第 5 回合 任务 3.3):
//   * no modal error box may block the process,
//   * the process must really exit (no zombie holding the camera),
//   * the camera must be connectable again immediately afterwards.
//
// It is read on every check and an unset variable means "one empty-string
// compare" — normal operation is never affected.  Used only by the two sites
// marked 崩溃注入 in CameraManager.cpp.

#include <QByteArray>
#include <QtGlobal>

namespace CrashInject {

enum class Point { AfterConnect, AfterCapture };

inline QByteArray envValue() { return qgetenv("HEC_CRASH_INJECT"); }

// Pure predicate (unit-tested): does this environment value select that point?
inline bool matches(const QByteArray& value, Point p)
{
    const char* want = (p == Point::AfterConnect) ? "after-connect" : "after-capture";
    return !value.isEmpty() && value == QByteArray(want);
}

inline bool enabled(Point p) { return matches(envValue(), p); }

// Performs the fault.  Call sites: end of a successful connect, and end of a
// successful capture (after the frame has reached the UI).
inline void hitIfEnabled(Point p)
{
    if (!enabled(p))
        return;
    // Intentional null write: `volatile` keeps the store in the generated code
    // so the access violation really happens instead of being optimised out.
    volatile int* dead = nullptr;
    *dead = 0x5EED;
}

} // namespace CrashInject
