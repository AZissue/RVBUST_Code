#pragma once

// 执行引擎：按拓扑序同步执行流程，收集每个模块的成功/失败与日志。

#include <functional>
#include <string>
#include <vector>

#include "Process.h"

namespace rvc {

struct ModuleRunRecord {
    int                     nodeId = -1;
    std::string             name;
    bool                    success = false;
    double                  elapsedMs = 0.0;  // 本模块 execute 耗时
    std::vector<std::string> logs;
};

struct RunResult {
    bool ok = false;
    std::string error;  // 流程级错误（如检测到环）
    std::vector<ModuleRunRecord> records;
};

class Engine {
public:
    // 每个模块执行完成后的回调（可选，用于 UI 进度推送）。
    // 回调在调用 runOnce 的同一线程内触发；core 保持 Qt-free。
    using ProgressCallback = std::function<void(const ModuleRunRecord&)>;

    // 同步按拓扑序执行整个流程；任一模块失败不中断后续独立分支，
    // 但其下游模块会因输入缺失而失败。
    static RunResult runOnce(Process& process, ProgressCallback onModule = nullptr);
};

} // namespace rvc
