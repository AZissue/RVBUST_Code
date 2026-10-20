#pragma once

#include <QObject>
#include <QFutureWatcher>
#include <vector>

#include "logic/CalibrationService.h"
#include "models/CaptureRecord.h"

// Runs one hand-eye calibration off the UI thread and owns its result.
//
// Before this class MainWindow held the QFutureWatcher, the busy flag and the
// "build the three text columns from the session records" loop.  Now the
// controller owns the watcher and the result; MainWindow only builds the mode /
// config parameters, shows the busy state and renders `result()` when
// `finished()` arrives.
//
// The job captures only copies of the columns and params (never `this`), so a
// calibration still running while the window closes is harmless.
class CalibrationController : public QObject {
    Q_OBJECT
public:
    explicit CalibrationController(QObject* parent = nullptr);

    bool isRunning() const;

    // Starts a calibration; returns false (and does nothing) when one is
    // already running.  `records` are turned into the three SDK columns here
    // with CalibrationService::columnsFromRecords (empty cells kept).
    bool start(const QString& folder,
               const std::vector<CaptureRecord>& records,
               const CalibrationService::Params& params);

    // Result of the last finished run.  Only meaningful after finished().
    const CalibrationService::Result& result() const { return m_result; }

signals:
    void finished();

private:
    void onWatcherFinished();

    QFutureWatcher<CalibrationService::Result>* m_watcher = nullptr;
    CalibrationService::Result m_result;
};
