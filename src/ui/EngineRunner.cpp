#include "EngineRunner.h"

#include <chrono>

namespace rvc {

EngineRunner::EngineRunner(QObject* parent) : QObject(parent)
{
    // 跨线程信号投递需要注册自定义类型
    qRegisterMetaType<rvc::ModuleRunRecord>("rvc::ModuleRunRecord");
    qRegisterMetaType<rvc::RunResult>("rvc::RunResult");
}

EngineRunner::~EngineRunner() = default;

bool EngineRunner::start(Process& process)
{
    if (running_.exchange(true))
        return false;

    // 一次性 worker 线程：跑完自毁
    QThread* worker = QThread::create([this, &process] {
        const auto t0 = std::chrono::steady_clock::now();
        RunResult result = Engine::runOnce(process, [this](const ModuleRunRecord& rec) {
            Q_EMIT moduleFinished(rec);  // QueuedConnection 投递到 GUI 线程
        });
        const double totalMs = std::chrono::duration<double, std::milli>(
                                   std::chrono::steady_clock::now() - t0)
                                   .count();
        Q_EMIT runFinished(result, totalMs);
    });
    connect(worker, &QThread::finished, worker, &QObject::deleteLater);
    worker->start();
    return true;
}

} // namespace rvc
