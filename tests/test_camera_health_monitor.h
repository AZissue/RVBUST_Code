#pragma once

#include <QObject>

// 架构收敛第 3 批：健康扫描 / 自动重连的节奏与尝试预算。
// 这些规则原来散在 CameraManager 的两个 QTimer + 一个计数器里，没有相机
// 也能验证；真正的设备重连仍由 CameraManager 执行（这里不碰 SDK）。
class TestCameraHealthMonitor : public QObject {
    Q_OBJECT
private slots:
    void defaultsMatchTheHistoricalPolicy();
    void healthIntervalFallsBackWhenNonPositive();
    void healthChecksKeepTickingUntilStopped();
    void planCountsAttemptsAndExhaustsTheBudget();
    void aPendingRetryIsNotDoubleScheduled();
    void noteConnectedRestoresTheBudget();
    void stopDropsTimersAndBudget();
};
