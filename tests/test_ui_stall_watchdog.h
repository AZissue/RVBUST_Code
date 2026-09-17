#pragma once

#include <QObject>

class TestUiStallWatchdog : public QObject {
    Q_OBJECT
private slots:
    void firstTickIsNotAStall();
    void detectsStallOverThreshold();
    void reportsEachEpisodeOnce();
    void recoversAndDetectsAgain();
    void thresholdIsConfigurable();
    void tracksMaxStall();
    void contextFormatting();
    void countFormatting();
    void clockIsMonotonic();
    // A block that starts right after reset() must still be reported: the old
    // reset() cleared the baseline, so the camera connect that follows the
    // modal device-list dialog produced no watchdog line at all.
    void blockAfterResetIsStillReported();
    // Measured cost of the hot path, so "the watchdog is cheap" is a number in
    // the log rather than an assertion (D5 acceptance).
    void tickCostIsNegligible();
};
