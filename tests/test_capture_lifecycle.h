#pragma once

#include <QObject>

// 采集任务生命周期策略（src/logic/CaptureLifecycle.h，header-only）。
// 钉住两件事：超时不等于退出；超时/关闭后不得再提交、迟到结果不得应用。
class TestCaptureLifecycle : public QObject {
    Q_OBJECT
private slots:
    void submitOnlyWhenIdleAndOpen();
    void timeoutKeepsWorkerRunning();
    void lateFinishAfterTimeoutIsDropped();
    void normalFinishAppliesResult();
    void shutdownDropsResultAndBlocksSubmit();
    void releaseReopensSubmitButNotWhileWorkerRuns();
    void timeoutAfterFinishIsIgnored();
};
