#include "app/CalibrationController.h"

#include <QtConcurrent>

CalibrationController::CalibrationController(QObject* parent) : QObject(parent)
{
    m_watcher = new QFutureWatcher<CalibrationService::Result>(this);
    connect(m_watcher, &QFutureWatcher<CalibrationService::Result>::finished,
            this, &CalibrationController::onWatcherFinished);
}

bool CalibrationController::isRunning() const
{
    return m_watcher->isRunning();
}

bool CalibrationController::start(const QString& folder,
                                  const std::vector<CaptureRecord>& records,
                                  const CalibrationService::Params& params)
{
    if (m_watcher->isRunning())
        return false;

    // Build the columns before handing off: the worker only sees value copies,
    // and the index-alignment rule lives in one tested place.
    const CalibrationService::Columns columns =
        CalibrationService::columnsFromRecords(records);

    // A new run must not let a caller read the previous run's result.
    m_result = CalibrationService::Result{};

    m_watcher->setFuture(QtConcurrent::run(
        [folder, columns, params]() {
            return CalibrationService::calibrate(
                folder, columns.camera, columns.pose, columns.tcp, params);
        }));
    return true;
}

void CalibrationController::onWatcherFinished()
{
    m_result = m_watcher->result();
    emit finished();
}
