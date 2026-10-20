#pragma once

#include <QObject>

class QTimer;

// 相机生命周期监督：健康扫描 + 有界自动重连的**节奏与预算**。
//
// 原来这两件事是 CameraManager 里的两个 QTimer、一个尝试计数和几条交织在
// 采集/预览判断之间的分支。这里只搬走「什么时候再试、还能试几次」这一层：
//
//   - CameraManager 仍然决定**是否允许**重连（已连接？正在关闭？预览/采集在跑？）
//     并真正执行 initWithDeviceSerial()；
//   - 本类只回答 planReconnect() 的结果（Scheduled / Ignored / Exhausted），
//     负责单次定时器和 3 次尝试预算，重连成功时 noteConnected() 清零。
//
// 因此设备锁顺序、worker token、预览仲裁都留在原处，行为不变。
class CameraHealthMonitor : public QObject {
    Q_OBJECT
public:
    // 三态而不是 bool：调用方要把"已排程"（发提示、停预览、记住预览状态）和
    // "预算用尽"（发失败提示、保持现状）区分开。两者都不能继续重连。
    enum class ReconnectPlan { Ignored, Scheduled, Exhausted };

    static constexpr int MAX_ATTEMPTS = 3;
    static constexpr int RECONNECT_INTERVAL_MS = 3000;
    // 任务 3.4: was 5 s, which took the device lock (SystemFindDevice) 12x per
    // minute and wrote a "[DEV] health-scan acquired device" line each time.
    // 30 s is plenty for hot-plug detection; AppConfig can tune it.
    static constexpr int HEALTH_INTERVAL_MS = 30000;

    explicit CameraHealthMonitor(QObject* parent = nullptr);

    // Hot-plug scans.  Start is queued by CameraManager after a successful
    // connect (timers must be touched from their owning thread).
    void setHealthInterval(int ms);
    int healthInterval() const;
    void startHealthChecks();
    // Stops both timers and drops the attempt budget (teardown path).
    void stop();

    // One reconnect slot: Ignored while a retry is already pending, Scheduled
    // (attempt counted, timer armed) otherwise, Exhausted once the budget is
    // spent — the budget is reset so a later manual recovery starts fresh.
    ReconnectPlan planReconnect();
    int attempts() const { return m_attempts; }
    // Successful (re)connect: the next incident gets a full budget again.
    void noteConnected();

    // Retry spacing is a policy knob (defaults to RECONNECT_INTERVAL_MS);
    // exposed so the unit tests do not have to wait three seconds.
    void setReconnectInterval(int ms);

signals:
    void healthCheckDue();
    void reconnectDue();

private:
    QTimer* m_healthTimer = nullptr;
    QTimer* m_reconnectTimer = nullptr;
    int m_reconnectIntervalMs = RECONNECT_INTERVAL_MS;
    int m_attempts = 0;
};
