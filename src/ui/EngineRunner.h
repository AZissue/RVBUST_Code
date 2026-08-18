#pragma once

// 执行引擎的 UI 异步封装：把 core::Engine::runOnce（同步、Qt-free）
// 放到 QThread worker 执行，进度经 Qt 信号 QueuedConnection 回 GUI 线程。
//
// 线程模型：
//  - start() 只能由 GUI 线程调用；同一时间只允许一个运行实例（防并发）
//  - worker 线程内每模块完成 emit moduleFinished，结束 emit runFinished
//  - Process 对象生命周期由调用方保证（运行期间不得修改图）

#include <QObject>
#include <QThread>

#include <atomic>

#include "core/Engine.h"

namespace rvc {

class EngineRunner : public QObject {
    Q_OBJECT
public:
    explicit EngineRunner(QObject* parent = nullptr);
    ~EngineRunner() override;

    // 启动一次运行；已在运行则返回 false
    bool start(Process& process);

    bool isRunning() const { return running_.load(); }

    // runFinished 到达后由 GUI 线程复位 running 标志
    void reset() { running_.store(false); }

Q_SIGNALS:
    void moduleFinished(rvc::ModuleRunRecord record);
    void runFinished(rvc::RunResult result, double totalMs);

private:
    std::atomic<bool> running_{false};
};

} // namespace rvc
