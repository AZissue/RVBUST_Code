#pragma once

// ── 采集任务生命周期（纯策略）──────────────────────────────────────────
//
// 采集/扫描跑在线程池里，SDK 调用本身无法取消（真卡死时线程会一直停在
// Capture() 里）。界面「不再等结果」和「worker 已经退出」必须分开记：
//   * timedOut      —— 超时定时器已触发，界面恢复，迟到结果要丢弃；
//   * workerRunning —— 线程池任务真的还在跑，这期间不能再提交新任务
//                      （否则 setFuture() 会覆盖旧 future，旧任务失控）。
// 关窗时也只能按 workerRunning 判断是否安全销毁对象；超时不能当作已退出。
//
// 这里不放任何 SDK/Qt 代码，状态与判定都能单测。
namespace CaptureLifecycle {

struct State {
    bool workerRunning = false;   // 线程池任务确实在跑
    bool timedOut = false;        // 界面已放弃等待，结果迟到时丢弃
    bool shuttingDown = false;    // 已进入关闭/释放流程
};

// 超时后定时器完成：结果是否应用、是否需向界面报超时。
struct Timeout {
    bool report = false;   // 需要向界面报一次超时（只报一次）
};

// 任务真正结束时：结果是否应用（超时/关闭后的迟到结果一律丢弃）。
struct Finish {
    bool apply = false;
    bool wasTimedOut = false;
};

inline bool canSubmit(const State& s)
{
    return !s.workerRunning && !s.shuttingDown;
}

inline void onSubmit(State& s)
{
    s.workerRunning = true;
    s.timedOut = false;
}

// 看门狗触发。worker 已退出后才到的超时是无意义的，不报。
inline Timeout onTimeout(State& s)
{
    Timeout t;
    if (s.workerRunning && !s.timedOut) {
        s.timedOut = true;
        t.report = true;
    }
    return t;
}

inline Finish onFinished(State& s)
{
    Finish f;
    f.wasTimedOut = s.timedOut;
    f.apply = s.workerRunning && !s.timedOut && !s.shuttingDown;
    s.workerRunning = false;
    s.timedOut = false;
    return f;
}

// 关闭流程开始：在跑的任务结果不再应用；workerRunning 保持真实值，
// 由调用方用 hasWorkerRunning() 决定能否安全销毁对象。
inline void onShutdown(State& s)
{
    s.shuttingDown = true;
    if (s.workerRunning)
        s.timedOut = true;
}

inline bool hasWorkerRunning(const State& s)
{
    return s.workerRunning;
}

// 释放流程结束（设备已关闭，管理器可再次连接）。shuttingDown 是可逆的，
// workerRunning 保留真实值：若旧 worker 还卡在 SDK 里，新采集继续被拒绝，
// 直到 onFinished() 真正收到它退出。
inline void onReleased(State& s)
{
    s.shuttingDown = false;
}

} // namespace CaptureLifecycle
